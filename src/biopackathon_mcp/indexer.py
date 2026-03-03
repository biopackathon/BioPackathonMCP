"""Hybrid search index: FAISS (dense) + BM25 (sparse)."""

from __future__ import annotations

import json
import pickle
import re
from pathlib import Path
from typing import Any

import faiss
import numpy as np
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer

DEFAULT_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
INDEX_DIR = Path("data/index")

_CJK_RANGES = r"\u3000-\u9fff\uf900-\ufaff\uff00-\uffef"
_TOKEN_RE = re.compile(rf"[a-z0-9]+|[{_CJK_RANGES}]+")


def _is_cjk(seg: str) -> bool:
    return any("\u3000" <= c <= "\u9fff" or "\uf900" <= c <= "\ufaff"
               or "\uff00" <= c <= "\uffef" for c in seg)


def _tokenize(text: str) -> list[str]:
    """Tokenize for BM25: whole words for Latin/digits, character bigrams for CJK."""
    tokens: list[str] = []
    for seg in _TOKEN_RE.findall(text.lower()):
        tokens.append(seg)
        if _is_cjk(seg):
            for i in range(len(seg) - 1):
                tokens.append(seg[i : i + 2])
    return tokens


class Chunk:
    """A single subtitle chunk with metadata."""

    __slots__ = (
        "video_id", "title", "text", "t_start", "t_end",
        "date", "speaker", "tags",
    )

    def __init__(
        self,
        video_id: str,
        title: str,
        text: str,
        t_start: float,
        t_end: float,
        date: str | None = None,
        speaker: str | None = None,
        tags: list[str] | None = None,
    ) -> None:
        self.video_id = video_id
        self.title = title
        self.text = text
        self.t_start = t_start
        self.t_end = t_end
        self.date = date
        self.speaker = speaker
        self.tags = tags or []

    def url(self) -> str:
        t = int(self.t_start)
        return f"https://www.youtube.com/watch?v={self.video_id}&t={t}s"

    def to_dict(self) -> dict[str, Any]:
        return {
            "video_id": self.video_id,
            "title": self.title,
            "text": self.text,
            "t_start": self.t_start,
            "t_end": self.t_end,
            "date": self.date,
            "speaker": self.speaker,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Chunk:
        return cls(**d)


class HybridIndex:
    """FAISS + BM25 hybrid search over subtitle chunks."""

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self.model_name = model_name
        self._model: SentenceTransformer | None = None
        self.chunks: list[Chunk] = []
        self.faiss_index: faiss.IndexFlatIP | None = None
        self.bm25: BM25Okapi | None = None

    @property
    def model(self) -> SentenceTransformer:
        if self._model is None:
            self._model = SentenceTransformer(self.model_name)
        return self._model

    def build(self, chunks: list[Chunk]) -> None:
        """Build both FAISS and BM25 indices from chunks."""
        self.chunks = chunks
        if not chunks:
            return

        # Combine title and text for richer search signal
        search_texts = [f"{c.title} {c.text}" for c in chunks]

        # Dense index
        embeddings = self.model.encode(search_texts, show_progress_bar=True, normalize_embeddings=True)
        embeddings = np.array(embeddings, dtype=np.float32)
        dim = embeddings.shape[1]
        self.faiss_index = faiss.IndexFlatIP(dim)
        self.faiss_index.add(embeddings)

        # Sparse index
        tokenized = [_tokenize(t) for t in search_texts]
        self.bm25 = BM25Okapi(tokenized)

    def search(
        self,
        query: str,
        top_k: int = 10,
        bm25_weight: float = 0.4,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Hybrid search: normalised BM25 + cosine similarity scores."""
        if not self.chunks or self.faiss_index is None or self.bm25 is None:
            return []

        n = len(self.chunks)

        # Dense scores — retrieve all when filters are applied
        q_emb = self.model.encode([query], normalize_embeddings=True).astype(np.float32)
        k_dense = n if filters else min(n, top_k * 3)
        dense_scores_raw, dense_indices = self.faiss_index.search(q_emb, k_dense)
        dense_scores_map: dict[int, float] = {}
        for idx, score in zip(dense_indices[0], dense_scores_raw[0]):
            if idx >= 0:
                dense_scores_map[int(idx)] = float(score)

        # Sparse scores
        sparse_scores_raw = self.bm25.get_scores(_tokenize(query))

        # Normalise scores to [0, 1]
        dense_arr = np.array([dense_scores_map.get(i, 0.0) for i in range(n)])
        d_max = dense_arr.max() if dense_arr.max() > 0 else 1.0
        dense_norm = dense_arr / d_max

        s_max = sparse_scores_raw.max() if sparse_scores_raw.max() > 0 else 1.0
        sparse_norm = sparse_scores_raw / s_max

        combined = (1 - bm25_weight) * dense_norm + bm25_weight * sparse_norm

        # Apply filters
        if filters:
            for i, chunk in enumerate(self.chunks):
                if "date" in filters and (chunk.date or "") < filters["date"]:
                    combined[i] = -1
                if "speaker" in filters and chunk.speaker != filters["speaker"]:
                    combined[i] = -1
                if "tags" in filters:
                    if not set(filters["tags"]) & set(chunk.tags):
                        combined[i] = -1

        ranked = np.argsort(-combined)[:top_k]
        results: list[dict[str, Any]] = []
        for idx in ranked:
            if combined[idx] <= 0:
                continue
            c = self.chunks[idx]
            results.append({
                "video_id": c.video_id,
                "title": c.title,
                "url": c.url(),
                "t_start": c.t_start,
                "t_end": c.t_end,
                "score": round(float(combined[idx]), 4),
                "snippet": c.text[:300],
                "date": c.date,
                "speaker": c.speaker,
                "tags": c.tags,
            })
        return results

    def save(self, directory: str | Path | None = None) -> None:
        d = Path(directory) if directory else INDEX_DIR
        d.mkdir(parents=True, exist_ok=True)
        # Save chunks
        with open(d / "chunks.json", "w", encoding="utf-8") as f:
            json.dump([c.to_dict() for c in self.chunks], f, ensure_ascii=False)
        # Save FAISS
        if self.faiss_index is not None:
            faiss.write_index(self.faiss_index, str(d / "faiss.index"))
        # Save BM25
        if self.bm25 is not None:
            with open(d / "bm25.pkl", "wb") as f:
                pickle.dump(self.bm25, f)
        # Save metadata
        with open(d / "meta.json", "w", encoding="utf-8") as f:
            json.dump({"model_name": self.model_name}, f)

    def load(self, directory: str | Path | None = None) -> None:
        d = Path(directory) if directory else INDEX_DIR
        # Load metadata (if present) before loading model
        meta_path = d / "meta.json"
        if meta_path.exists():
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
            self.model_name = meta.get("model_name", DEFAULT_MODEL)
        with open(d / "chunks.json", encoding="utf-8") as f:
            self.chunks = [Chunk.from_dict(c) for c in json.load(f)]
        self.faiss_index = faiss.read_index(str(d / "faiss.index"))
        with open(d / "bm25.pkl", "rb") as f:
            self.bm25 = pickle.load(f)
