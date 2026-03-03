"""High-level tool functions exposed via MCP: search, answer, recommend."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

from .indexer import HybridIndex


def search_segments(
    index: HybridIndex,
    query: str,
    top_k: int = 10,
    filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Search subtitle segments. Returns ranked results with timestamps."""
    return index.search(query, top_k=top_k, filters=filters)


def answer_question(
    index: HybridIndex,
    question: str,
    top_k: int = 8,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Answer a question using retrieved segments as evidence.

    Returns a summary answer with timestamp-based citations.
    Does NOT copy transcript verbatim — summarises and points to source.
    """
    results = index.search(question, top_k=top_k, filters=filters)

    if not results:
        return {
            "answer": "No relevant subtitle segments found.",
            "citations": [],
        }

    # Build answer from top results
    citation_entries: list[dict[str, Any]] = []
    summary_parts: list[str] = []

    for r in results:
        snippet = r["snippet"]
        # Summarise: take first sentence or first 120 chars
        short = _first_sentence(snippet, max_len=120)
        summary_parts.append(f"- {short}")
        citation_entries.append({
            "url": r["url"],
            "t_start": r["t_start"],
            "t_end": r["t_end"],
            "why": f"[{r['title']}] {short}",
        })

    answer_text = (
        f"Found {len(results)} result(s) related to \"{question}\":\n\n"
        + "\n".join(summary_parts)
        + "\n\nSee the timestamped URLs for details."
    )

    return {
        "answer": answer_text,
        "citations": citation_entries,
    }


def recommend_videos(
    index: HybridIndex,
    goal: str,
    top_k: int = 5,
    filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Recommend videos relevant to a learning goal.

    Groups search results by video and picks the top videos.
    """
    # Search with more results to get good video coverage
    results = index.search(goal, top_k=top_k * 5, filters=filters)

    # Group by video_id
    video_map: dict[str, dict[str, Any]] = {}
    video_timestamps: dict[str, list[dict[str, Any]]] = defaultdict(list)
    video_scores: dict[str, float] = defaultdict(float)

    for r in results:
        vid = r["video_id"]
        if vid not in video_map:
            video_map[vid] = {
                "video_id": vid,
                "title": r["title"],
                "url": f"https://www.youtube.com/watch?v={vid}",
            }
        video_scores[vid] += r["score"]
        video_timestamps[vid].append({
            "t": r["t_start"],
            "label": _first_sentence(r["snippet"], max_len=60),
        })

    # Rank by aggregated score
    ranked_vids = sorted(video_scores, key=lambda v: video_scores[v], reverse=True)[:top_k]

    recommendations: list[dict[str, Any]] = []
    for vid in ranked_vids:
        info = video_map[vid]
        # Keep top 3 timestamps per video
        timestamps = sorted(video_timestamps[vid], key=lambda t: t["t"])[:3]
        recommendations.append({
            "video_id": info["video_id"],
            "title": info["title"],
            "url": info["url"],
            "why": f"Contains {len(video_timestamps[vid])} segment(s) related to the goal \"{goal}\".",
            "key_timestamps": timestamps,
        })

    return recommendations


def list_tags(index: HybridIndex) -> list[dict[str, Any]]:
    """List all available tags with occurrence counts, sorted by frequency."""
    counts: Counter[str] = Counter()
    for chunk in index.chunks:
        for tag in chunk.tags:
            counts[tag] += 1
    return [
        {"tag": tag, "count": count}
        for tag, count in counts.most_common()
    ]


def _first_sentence(text: str, max_len: int = 120) -> str:
    """Extract first sentence or truncate to max_len."""
    # Try to find sentence boundary
    match = re.search(r"[.!?\n]", text)
    if match and match.start() < max_len:
        return text[: match.start() + 1].strip()
    if len(text) <= max_len:
        return text.strip()
    return text[:max_len].strip() + "..."
