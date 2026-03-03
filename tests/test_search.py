"""Tests for ingest, indexing, and search functionality."""

from __future__ import annotations

import tempfile
from pathlib import Path

from biopackathon_mcp.indexer import Chunk, HybridIndex
from biopackathon_mcp.ingest_youtube import chunk_subtitles
from biopackathon_mcp.tools import answer_question, list_tags, recommend_videos, search_segments


def _build_test_index(sample_subtitles: list[dict]) -> HybridIndex:
    """Helper: build index from sample subtitles."""
    chunks = chunk_subtitles(
        sample_subtitles,
        video_id="TEST_VIDEO_001",
        title="BioPackathon Test Video",
        date="2024-06-01",
    )
    index = HybridIndex()
    index.build(chunks)
    return index


class TestChunking:
    def test_chunk_count(self, sample_subtitles: list[dict]) -> None:
        chunks = chunk_subtitles(
            sample_subtitles,
            video_id="v1",
            title="test",
        )
        assert len(chunks) >= 1
        for c in chunks:
            assert c.video_id == "v1"
            assert c.t_start >= 0
            assert c.t_end > c.t_start

    def test_chunk_duration_bounds(self, sample_subtitles: list[dict]) -> None:
        chunks = chunk_subtitles(
            sample_subtitles,
            video_id="v1",
            title="test",
        )
        # Each chunk should be roughly within bounds (last chunk may be shorter)
        for c in chunks[:-1]:
            duration = c.t_end - c.t_start
            assert duration <= 95, f"Chunk too long: {duration}s"

    def test_tags_extracted(self, sample_subtitles: list[dict]) -> None:
        chunks = chunk_subtitles(
            sample_subtitles,
            video_id="v1",
            title="test",
        )
        all_tags = set()
        for c in chunks:
            all_tags.update(c.tags)
        # The sample subtitles mention Docker, Snakemake, RNA, etc.
        assert len(all_tags) > 0


class TestHybridSearch:
    def test_search_returns_results(self, sample_subtitles: list[dict]) -> None:
        index = _build_test_index(sample_subtitles)
        results = search_segments(index, "Docker reproducibility", top_k=3)
        assert len(results) > 0
        assert "video_id" in results[0]
        assert "url" in results[0]
        assert "score" in results[0]

    def test_search_relevance(self, sample_subtitles: list[dict]) -> None:
        index = _build_test_index(sample_subtitles)
        results = search_segments(index, "RNA-seq single-cell", top_k=5)
        assert len(results) > 0
        # At least one of the top results should contain RNA-related content
        all_snippets = " ".join(r["snippet"].lower() for r in results)
        assert any(kw in all_snippets for kw in ["rna", "single-cell", "bioconductor"])

    def test_search_empty_query(self, sample_subtitles: list[dict]) -> None:
        index = _build_test_index(sample_subtitles)
        results = search_segments(index, "", top_k=3)
        # Should not crash, may return results
        assert isinstance(results, list)

    def test_search_with_filter(self, sample_subtitles: list[dict]) -> None:
        index = _build_test_index(sample_subtitles)
        # date filter means "on or after" the given date
        results = search_segments(
            index, "Docker", top_k=5,
            filters={"date": "2024-06-01"},
        )
        assert len(results) > 0
        # Future date should return nothing
        results_empty = search_segments(
            index, "Docker", top_k=5,
            filters={"date": "9999-01-01"},
        )
        assert len(results_empty) == 0


class TestIndexPersistence:
    def test_save_and_load(self, sample_subtitles: list[dict]) -> None:
        index = _build_test_index(sample_subtitles)
        with tempfile.TemporaryDirectory() as tmpdir:
            index.save(tmpdir)
            loaded = HybridIndex()
            loaded.load(tmpdir)
            assert len(loaded.chunks) == len(index.chunks)
            results = loaded.search("Docker", top_k=2)
            assert len(results) > 0


class TestAnswerQuestion:
    def test_answer_has_citations(self, sample_subtitles: list[dict]) -> None:
        index = _build_test_index(sample_subtitles)
        result = answer_question(index, "Tell me about Docker reproducibility")
        assert "answer" in result
        assert "citations" in result
        assert len(result["citations"]) > 0
        assert "url" in result["citations"][0]


class TestListTags:
    def test_list_tags_returns_counts(self, sample_subtitles: list[dict]) -> None:
        index = _build_test_index(sample_subtitles)
        results = list_tags(index)
        assert isinstance(results, list)
        assert len(results) > 0
        assert "tag" in results[0]
        assert "count" in results[0]

    def test_list_tags_sorted_descending(self, sample_subtitles: list[dict]) -> None:
        index = _build_test_index(sample_subtitles)
        results = list_tags(index)
        counts = [r["count"] for r in results]
        assert counts == sorted(counts, reverse=True)

    def test_list_tags_empty_index(self) -> None:
        index = HybridIndex()
        results = list_tags(index)
        assert results == []


class TestRecommendVideos:
    def test_recommend_returns_videos(self, sample_subtitles: list[dict]) -> None:
        index = _build_test_index(sample_subtitles)
        results = recommend_videos(index, "introduction to bioinformatics")
        assert len(results) > 0
        assert "video_id" in results[0]
        assert "key_timestamps" in results[0]


class TestJapaneseTokenization:
    def test_cjk_bigrams(self) -> None:
        from biopackathon_mcp.indexer import _tokenize
        tokens = _tokenize("シングルセルRNA解析")
        assert "rna" in tokens
        assert "シン" in tokens
        assert "ング" in tokens
        assert "グル" in tokens
        assert len(tokens) > 3

    def test_latin_words_preserved(self) -> None:
        from biopackathon_mcp.indexer import _tokenize
        tokens = _tokenize("Docker reproducibility")
        assert "docker" in tokens
        assert "reproducibility" in tokens

    def test_mixed_text(self) -> None:
        from biopackathon_mcp.indexer import _tokenize
        tokens = _tokenize("Snakemakeでワークフローを書く")
        assert "snakemake" in tokens
        assert "ワー" in tokens
        assert "ーク" in tokens


class TestJapaneseTagExtraction:
    def test_katakana_snakemake(self) -> None:
        from biopackathon_mcp.ingest_youtube import _extract_tags
        tags = _extract_tags("スネークメイクでワークフローを書く", title="入門")
        assert "Snakemake" in tags
        assert "workflow" in tags

    def test_katakana_snakemake_variant(self) -> None:
        from biopackathon_mcp.ingest_youtube import _extract_tags
        tags = _extract_tags("スネイクメイク入門")
        assert "Snakemake" in tags

    def test_r_tag_no_false_positive(self) -> None:
        from biopackathon_mcp.ingest_youtube import _extract_tags
        tags = _extract_tags("Docker reproducibility RNA-seq RENGE")
        assert "R" not in tags
        assert "RNA" in tags
        assert "Docker" in tags

    def test_r_tag_true_positive(self) -> None:
        from biopackathon_mcp.ingest_youtube import _extract_tags
        tags = _extract_tags("R言語でパッケージを開発する")
        assert "R" in tags
        assert "package" in tags

    def test_reproducibility_japanese(self) -> None:
        from biopackathon_mcp.ingest_youtube import _extract_tags
        tags = _extract_tags("再現性のある環境を構築する")
        assert "reproducibility" in tags

    def test_title_used_for_tags(self) -> None:
        from biopackathon_mcp.ingest_youtube import _extract_tags
        tags = _extract_tags("はい、今日の話です", title="Snakemakeの入門")
        assert "Snakemake" in tags


class TestTitleInSearch:
    def test_title_boosts_search(self) -> None:
        chunks = [
            Chunk(video_id="v1", title="Snakemake入門", text="はい、ワークフローの話です",
                  t_start=0, t_end=30, tags=["Snakemake"]),
            Chunk(video_id="v2", title="RNA解析", text="はい、別の話です",
                  t_start=0, t_end=30, tags=["RNA"]),
        ]
        index = HybridIndex()
        index.build(chunks)
        results = index.search("Snakemake", top_k=2)
        assert results[0]["video_id"] == "v1"
