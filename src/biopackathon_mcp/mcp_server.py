"""MCP server exposing Bio'Pack'athon tools."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from .audit.audit_repo import audit_repo
from .indexer import HybridIndex
from .tools import answer_question, list_tags, recommend_videos, search_segments

INDEX_DIR = Path("data/index")

mcp = FastMCP(
    "biopackathon",
    instructions=(
        "Bio'Pack'athon YouTube playlist search, Q&A, recommendations, "
        "and reproducibility audit for bioinformatics packages."
    ),
)

_index: HybridIndex | None = None


def _get_index() -> HybridIndex:
    global _index
    if _index is not None:
        return _index
    idx = HybridIndex()
    if (INDEX_DIR / "chunks.json").exists():
        idx.load(INDEX_DIR)
    _index = idx
    return _index


def _parse_filters(filters: str | dict | None) -> dict[str, Any] | None:
    if filters is None:
        return None
    if isinstance(filters, str):
        try:
            return json.loads(filters)
        except json.JSONDecodeError:
            return None
    return filters


@mcp.tool()
def search_segments_tool(
    query: str,
    top_k: int = 10,
    filters: str | dict | None = None,
) -> list[dict[str, Any]]:
    """Search subtitle segments using hybrid search (BM25 + vector).

    Args:
        query: Search query
        top_k: Maximum number of results to return
        filters: JSON string in the format {"date":"2024-01-01","speaker":"name","tags":["RNA"]}. "date" filters segments on or after the given date.

    Returns:
        [{video_id, title, url, t_start, t_end, score, snippet}]
    """
    index = _get_index()
    if not index.chunks:
        return [{"error": "Index is empty. Please run biopackathon-ingest first."}]
    return search_segments(index, query, top_k=top_k, filters=_parse_filters(filters))


@mcp.tool()
def answer_question_tool(
    question: str,
    top_k: int = 8,
    filters: str | dict | None = None,
) -> dict[str, Any]:
    """Answer a question with evidence from YouTube subtitles. Returns a summary with timestamped URLs.

    Args:
        question: Question text
        top_k: Number of reference segments
        filters: JSON string for filter conditions

    Returns:
        {answer: str, citations: [{url, t_start, t_end, why}]}
    """
    index = _get_index()
    if not index.chunks:
        return {"answer": "Index is empty. Please run biopackathon-ingest first.", "citations": []}
    return answer_question(index, question, top_k=top_k, filters=_parse_filters(filters))


@mcp.tool()
def recommend_videos_tool(
    goal: str,
    top_k: int = 5,
    filters: str | dict | None = None,
) -> list[dict[str, Any]]:
    """Suggest recommended videos based on a learning goal.

    Args:
        goal: Learning goal or topic
        top_k: Number of videos to recommend
        filters: JSON string for filter conditions

    Returns:
        [{video_id, title, url, why, key_timestamps: [{t, label}]}]
    """
    index = _get_index()
    if not index.chunks:
        return [{"error": "Index is empty. Please run biopackathon-ingest first."}]
    return recommend_videos(index, goal, top_k=top_k, filters=_parse_filters(filters))


@mcp.tool()
def list_tags_tool() -> list[dict[str, Any]]:
    """List all available tags with their occurrence counts.

    Use this to discover valid tag values for the ``filters`` parameter
    of search_segments, answer_question, and recommend_videos.

    Returns:
        [{tag, count}] sorted by frequency (descending)
    """
    index = _get_index()
    if not index.chunks:
        return [{"error": "Index is empty. Please run biopackathon-ingest first."}]
    return list_tags(index)


@mcp.tool()
def audit_reproducibility_tool(repo_path: str) -> dict[str, Any]:
    """Audit the reproducibility of a GitHub repository.

    Inspects Dockerfile, lock files, workflow definitions, seed pinning, README instructions, download URLs, etc.

    Args:
        repo_path: Path to a local repository

    Returns:
        {score: 0-100, findings: [{severity, item, reason, evidence: [{path, line, excerpt}]}]}
    """
    return audit_repo(repo_path)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
