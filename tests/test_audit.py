"""Tests for reproducibility audit."""

from __future__ import annotations

from pathlib import Path

from biopackathon_mcp.audit.audit_repo import audit_repo


class TestAuditFullRepo:
    """Test against the well-configured pseudo_repo fixture."""

    def test_score_is_high(self, pseudo_repo_path: Path) -> None:
        result = audit_repo(str(pseudo_repo_path))
        assert result["score"] >= 50
        assert isinstance(result["findings"], list)

    def test_dockerfile_found(self, pseudo_repo_path: Path) -> None:
        result = audit_repo(str(pseudo_repo_path))
        container = [f for f in result["findings"] if f["item"] == "container"]
        assert len(container) == 1
        assert container[0]["severity"] == "info"  # found = info

    def test_lockfile_found(self, pseudo_repo_path: Path) -> None:
        result = audit_repo(str(pseudo_repo_path))
        lockfile = [f for f in result["findings"] if f["item"] == "lockfile"]
        assert len(lockfile) == 1
        assert lockfile[0]["severity"] == "info"

    def test_seed_found(self, pseudo_repo_path: Path) -> None:
        result = audit_repo(str(pseudo_repo_path))
        seed = [f for f in result["findings"] if f["item"] == "seed"]
        assert len(seed) == 1
        assert seed[0]["severity"] == "info"
        assert len(seed[0]["evidence"]) >= 2  # random.seed + np.random.seed

    def test_readme_repro_found(self, pseudo_repo_path: Path) -> None:
        result = audit_repo(str(pseudo_repo_path))
        readme = [f for f in result["findings"] if f["item"] == "readme_repro"]
        assert len(readme) == 1
        assert readme[0]["severity"] == "info"

    def test_download_urls_detected(self, pseudo_repo_path: Path) -> None:
        result = audit_repo(str(pseudo_repo_path))
        urls = [f for f in result["findings"] if f["item"] == "download_urls"]
        assert len(urls) == 1
        assert len(urls[0]["evidence"]) >= 1


class TestAuditMinimalRepo:
    """Test against the minimal pseudo_repo fixture (missing many items)."""

    def test_score_is_low(self, pseudo_repo_minimal_path: Path) -> None:
        result = audit_repo(str(pseudo_repo_minimal_path))
        # workflow and download_urls are "info" severity, so missing them still yields points
        assert result["score"] < 70

    def test_no_dockerfile(self, pseudo_repo_minimal_path: Path) -> None:
        result = audit_repo(str(pseudo_repo_minimal_path))
        container = [f for f in result["findings"] if f["item"] == "container"]
        assert len(container) == 1
        assert container[0]["severity"] == "warn"

    def test_no_lockfile(self, pseudo_repo_minimal_path: Path) -> None:
        result = audit_repo(str(pseudo_repo_minimal_path))
        lockfile = [f for f in result["findings"] if f["item"] == "lockfile"]
        assert len(lockfile) == 1
        assert lockfile[0]["severity"] == "warn"

    def test_no_seed(self, pseudo_repo_minimal_path: Path) -> None:
        result = audit_repo(str(pseudo_repo_minimal_path))
        seed = [f for f in result["findings"] if f["item"] == "seed"]
        assert len(seed) == 1
        assert seed[0]["severity"] == "warn"

    def test_readme_no_repro_steps(self, pseudo_repo_minimal_path: Path) -> None:
        result = audit_repo(str(pseudo_repo_minimal_path))
        readme = [f for f in result["findings"] if f["item"] == "readme_repro"]
        assert len(readme) == 1
        assert readme[0]["severity"] == "error"


class TestAuditInvalidPath:
    def test_nonexistent_path(self) -> None:
        result = audit_repo("/nonexistent/path/to/repo")
        assert result["score"] == 0
        assert result["findings"][0]["severity"] == "error"
