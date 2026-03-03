"""Ingest YouTube playlist: fetch video list, download subtitles, chunk, and build index."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from .indexer import Chunk, HybridIndex

DEFAULT_PLAYLIST = "PL0uaKHgcG00aJSa233gkhBA2HHe0-Ha-B"
CHUNK_MIN_SEC = 30
CHUNK_MAX_SEC = 90


def _get_api_key() -> str:
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        print("ERROR: YOUTUBE_API_KEY environment variable is not set.", file=sys.stderr)
        sys.exit(1)
    return key


def fetch_playlist_video_ids(playlist_id: str, api_key: str) -> list[dict[str, Any]]:
    """Return list of {video_id, title, date} from a YouTube playlist."""
    from googleapiclient.discovery import build

    youtube = build("youtube", "v3", developerKey=api_key)
    videos: list[dict[str, Any]] = []
    next_page: str | None = None

    while True:
        req = youtube.playlistItems().list(
            part="snippet",
            playlistId=playlist_id,
            maxResults=50,
            pageToken=next_page,
        )
        resp = req.execute()
        for item in resp.get("items", []):
            snippet = item["snippet"]
            videos.append({
                "video_id": snippet["resourceId"]["videoId"],
                "title": snippet["title"],
                "date": snippet.get("publishedAt", "")[:10],
            })
        next_page = resp.get("nextPageToken")
        if not next_page:
            break
    return videos


def fetch_subtitles(video_id: str) -> list[dict[str, Any]] | None:
    """Fetch YouTube auto/manual captions. Returns list of {text, start, duration} or None."""
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api._errors import (
        NoTranscriptFound,
        TranscriptsDisabled,
        VideoUnavailable,
    )

    try:
        api = YouTubeTranscriptApi()
        transcript = api.fetch(video_id, languages=["ja", "en"])
        return [
            {"text": s.text, "start": s.start, "duration": s.duration}
            for s in transcript.snippets
        ]
    except (NoTranscriptFound, TranscriptsDisabled, VideoUnavailable):
        return None
    except Exception:
        return None


# Use (?<![a-zA-Z]) / (?![a-zA-Z]) instead of \b for Latin keywords,
# because Python \b treats CJK chars as \w so "Dockerの" has no \b between r and の.
_TAG_PATTERNS: dict[str, list[str]] = {
    "RNA": [r"(?<![a-zA-Z])RNA(?![a-zA-Z])"],
    "DNA": [r"(?<![a-zA-Z])DNA(?![a-zA-Z])"],
    "genome": [r"(?<![a-zA-Z])[Gg]enome(?![a-zA-Z])", "ゲノム"],
    "sequencing": [r"(?<![a-zA-Z])[Ss]equencing(?![a-zA-Z])", "シーケンシング", "シークエンシング"],
    "alignment": [r"(?<![a-zA-Z])[Aa]lignment(?![a-zA-Z])", "アライメント"],
    "variant": [r"(?<![a-zA-Z])[Vv]ariant(?![a-zA-Z])", "バリアント"],
    "single-cell": [r"(?<![a-zA-Z])[Ss]ingle[- ]?[Cc]ell(?![a-zA-Z])", "シングルセル"],
    "scRNA": [r"(?<![a-zA-Z])scRNA(?![a-zA-Z])"],
    "bulk": [r"(?<![a-zA-Z])[Bb]ulk(?![a-zA-Z])", "バルク"],
    "proteomics": [r"(?<![a-zA-Z])[Pp]roteomics(?![a-zA-Z])", "プロテオミクス"],
    "metabolomics": [r"(?<![a-zA-Z])[Mm]etabolomics(?![a-zA-Z])", "メタボロミクス"],
    "Docker": [r"(?<![a-zA-Z])[Dd]ocker(?![a-zA-Z])", "ドッカー"],
    "Singularity": [r"(?<![a-zA-Z])[Ss]ingularity(?![a-zA-Z])", r"(?<![a-zA-Z])[Aa]pptainer(?![a-zA-Z])"],
    "Nextflow": [r"(?<![a-zA-Z])[Nn]extflow(?![a-zA-Z])"],
    "Snakemake": [r"(?<![a-zA-Z])[Ss]nakemake(?![a-zA-Z])", "スネークメイク", "スネイクメイク"],
    "conda": [r"(?<![a-zA-Z])conda(?![a-zA-Z])", "コンダ"],
    "Nix": [r"(?<![a-zA-Z])Nix(?![a-zA-Z])"],
    "R": [r"(?<![a-zA-Z])R(?![a-zA-Z])"],
    "Python": [r"(?<![a-zA-Z])[Pp]ython(?![a-zA-Z])", "パイソン"],
    "Julia": [r"(?<![a-zA-Z])[Jj]ulia(?![a-zA-Z])", "ジュリア"],
    "Bioconductor": [r"(?<![a-zA-Z])[Bb]ioconductor(?![a-zA-Z])"],
    "CRAN": [r"(?<![a-zA-Z])CRAN(?![a-zA-Z])"],
    "reproducibility": [r"(?<![a-zA-Z])[Rr]eproducibility(?![a-zA-Z])", "再現性"],
    "workflow": [r"(?<![a-zA-Z])[Ww]orkflow(?![a-zA-Z])", "ワークフロー"],
    "pipeline": [r"(?<![a-zA-Z])[Pp]ipeline(?![a-zA-Z])", "パイプライン"],
    "package": [r"(?<![a-zA-Z])[Pp]ackage(?![a-zA-Z])", "パッケージ"],
}


def _extract_tags(text: str, title: str = "") -> list[str]:
    """Extract tags using regex patterns with katakana variants."""
    combined = f"{title} {text}"
    found: list[str] = []
    for tag, patterns in _TAG_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, combined):
                found.append(tag)
                break
    return found


def chunk_subtitles(
    subs: list[dict[str, Any]],
    video_id: str,
    title: str,
    date: str | None = None,
) -> list[Chunk]:
    """Split subtitle entries into 30-90 second chunks."""
    if not subs:
        return []

    chunks: list[Chunk] = []
    buf_texts: list[str] = []
    buf_start: float = subs[0]["start"]
    buf_end: float = buf_start

    for entry in subs:
        start = entry["start"]
        duration = entry.get("duration", 0)
        end = start + duration
        span = end - buf_start

        if span > CHUNK_MAX_SEC and buf_texts:
            text = " ".join(buf_texts)
            chunks.append(Chunk(
                video_id=video_id,
                title=title,
                text=text,
                t_start=buf_start,
                t_end=buf_end,
                date=date,
                tags=_extract_tags(text, title=title),
            ))
            buf_texts = [entry["text"]]
            buf_start = start
            buf_end = end
        else:
            buf_texts.append(entry["text"])
            buf_end = end

    if buf_texts:
        text = " ".join(buf_texts)
        chunks.append(Chunk(
            video_id=video_id,
            title=title,
            text=text,
            t_start=buf_start,
            t_end=buf_end,
            date=date,
            tags=_extract_tags(text, title=title),
        ))

    return chunks


def load_existing_video_ids(index_dir: Path) -> set[str]:
    """Return set of video_ids already indexed."""
    chunks_file = index_dir / "chunks.json"
    if not chunks_file.exists():
        return set()
    with open(chunks_file, encoding="utf-8") as f:
        data = json.load(f)
    return {c["video_id"] for c in data}


def ingest(
    playlist_id: str = DEFAULT_PLAYLIST,
    index_dir: str = "data/index",
    api_key: str | None = None,
) -> int:
    """Run full ingest pipeline. Returns number of newly ingested videos."""
    if api_key is None:
        api_key = _get_api_key()

    idx_path = Path(index_dir)
    existing = load_existing_video_ids(idx_path)

    videos = fetch_playlist_video_ids(playlist_id, api_key)
    new_videos = [v for v in videos if v["video_id"] not in existing]

    if not new_videos:
        print("No new videos found.")
        return 0

    # Load existing chunks
    all_chunks: list[Chunk] = []
    if (idx_path / "chunks.json").exists():
        with open(idx_path / "chunks.json", encoding="utf-8") as f:
            all_chunks = [Chunk.from_dict(c) for c in json.load(f)]

    ingested = 0
    for i, v in enumerate(new_videos):
        vid = v["video_id"]
        print(f"  Fetching subtitles: {v['title']} ({vid}) ... ", end="", flush=True)
        subs = fetch_subtitles(vid)
        if subs is None:
            print("No subtitles available - skipped")
            continue
        chunks = chunk_subtitles(subs, vid, v["title"], v.get("date"))
        all_chunks.extend(chunks)
        ingested += 1
        print(f"OK ({len(chunks)} chunks)")
        if i < len(new_videos) - 1:
            time.sleep(3)

    # Rebuild index
    print("Rebuilding index ...")
    index = HybridIndex()
    index.build(all_chunks)
    index.save(idx_path)
    print(f"Done: added {ingested} video(s) ({len(all_chunks)} total chunks)")
    return ingested


def rebuild_index(index_dir: str = "data/index") -> HybridIndex:
    """Rebuild index from existing chunks.json with improved tokenization, embeddings, and tags."""
    idx_path = Path(index_dir)
    chunks_file = idx_path / "chunks.json"
    if not chunks_file.exists():
        print("ERROR: No chunks.json found. Run biopackathon-ingest first.", file=sys.stderr)
        sys.exit(1)

    with open(chunks_file, encoding="utf-8") as f:
        raw_chunks = json.load(f)

    # Re-extract tags with improved logic
    chunks: list[Chunk] = []
    for c in raw_chunks:
        tags = _extract_tags(c["text"], title=c.get("title", ""))
        chunks.append(Chunk(
            video_id=c["video_id"],
            title=c["title"],
            text=c["text"],
            t_start=c["t_start"],
            t_end=c["t_end"],
            date=c.get("date"),
            speaker=c.get("speaker"),
            tags=tags,
        ))

    print(f"Rebuilding index for {len(chunks)} chunks ...")
    index = HybridIndex()
    index.build(chunks)
    index.save(idx_path)
    print(f"Done. Index saved to {idx_path}")
    return index


def ingest_from_local(
    subtitles: list[dict[str, Any]],
    video_id: str,
    title: str,
    date: str | None = None,
    index_dir: str = "data/index",
) -> HybridIndex:
    """Build index from pre-loaded subtitle data (for testing)."""
    chunks = chunk_subtitles(subtitles, video_id, title, date)
    index = HybridIndex()
    index.build(chunks)
    index.save(index_dir)
    return index


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Bio'Pack'athon YouTube playlist ingest")
    parser.add_argument("--playlist", default=DEFAULT_PLAYLIST, help="YouTube playlist ID")
    parser.add_argument("--index-dir", default="data/index", help="Index output directory")
    parser.add_argument(
        "--rebuild", action="store_true",
        help="Rebuild index from existing chunks.json (re-extract tags, re-embed, re-tokenize)",
    )
    args = parser.parse_args()

    if args.rebuild:
        rebuild_index(index_dir=args.index_dir)
    else:
        ingest(playlist_id=args.playlist, index_dir=args.index_dir)


if __name__ == "__main__":
    main()
