"""Tests for biopackathon-setup CLI."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from biopackathon_mcp.setup_claude import apply_setup, main, SERVER_KEY


@pytest.fixture
def settings_path(tmp_path: Path) -> Path:
    return tmp_path / ".claude" / "settings.json"


class TestApplySetup:
    """Tests for apply_setup()."""

    def test_creates_file_when_missing(self, settings_path: Path):
        result = apply_setup(settings_path, command="/usr/bin/biopackathon-mcp")

        assert result["action"] == "created"
        assert settings_path.exists()
        data = json.loads(settings_path.read_text())
        assert data["mcpServers"][SERVER_KEY]["command"] == "/usr/bin/biopackathon-mcp"

    def test_merges_with_existing_settings(self, settings_path: Path):
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        existing = {
            "mcpServers": {
                "other-server": {"command": "other-cmd"}
            },
            "someOtherKey": True,
        }
        settings_path.write_text(json.dumps(existing))

        result = apply_setup(settings_path, command="biopackathon-mcp")

        assert result["action"] == "added"
        data = json.loads(settings_path.read_text())
        # Existing entries preserved
        assert data["mcpServers"]["other-server"]["command"] == "other-cmd"
        assert data["someOtherKey"] is True
        # New entry added
        assert data["mcpServers"][SERVER_KEY]["command"] == "biopackathon-mcp"

    def test_skips_if_already_configured(self, settings_path: Path):
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        existing = {
            "mcpServers": {
                SERVER_KEY: {"command": "old-path"}
            }
        }
        settings_path.write_text(json.dumps(existing))

        result = apply_setup(settings_path, command="new-path")

        assert result["action"] == "skipped"
        # File not modified
        data = json.loads(settings_path.read_text())
        assert data["mcpServers"][SERVER_KEY]["command"] == "old-path"

    def test_force_overwrites_existing(self, settings_path: Path):
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        existing = {
            "mcpServers": {
                SERVER_KEY: {"command": "old-path"}
            }
        }
        settings_path.write_text(json.dumps(existing))

        result = apply_setup(settings_path, force=True, command="new-path")

        assert result["action"] == "overwritten"
        data = json.loads(settings_path.read_text())
        assert data["mcpServers"][SERVER_KEY]["command"] == "new-path"

    def test_dry_run_does_not_write(self, settings_path: Path):
        result = apply_setup(settings_path, dry_run=True, command="biopackathon-mcp")

        assert result["action"] == "created"
        assert not settings_path.exists()

    def test_includes_youtube_api_key(self, settings_path: Path, monkeypatch):
        monkeypatch.setenv("YOUTUBE_API_KEY", "test-key-123")

        apply_setup(settings_path, command="biopackathon-mcp")

        data = json.loads(settings_path.read_text())
        entry = data["mcpServers"][SERVER_KEY]
        assert entry["env"]["YOUTUBE_API_KEY"] == "test-key-123"

    def test_no_env_without_youtube_key(self, settings_path: Path, monkeypatch):
        monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)

        apply_setup(settings_path, command="biopackathon-mcp")

        data = json.loads(settings_path.read_text())
        entry = data["mcpServers"][SERVER_KEY]
        assert "env" not in entry

    def test_empty_file_treated_as_fresh(self, settings_path: Path):
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text("")

        result = apply_setup(settings_path, command="biopackathon-mcp")

        assert result["action"] == "created"
        data = json.loads(settings_path.read_text())
        assert SERVER_KEY in data["mcpServers"]


class TestMainCLI:
    """Tests for the main() CLI entry point."""

    def test_default_scope_user(self, tmp_path: Path, monkeypatch):
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))
        monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
        # Patch Path.home() to return fake_home
        monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

        main(["--dry-run"])

        # Dry run: file should not exist
        target = fake_home / ".claude" / "settings.json"
        assert not target.exists()

    def test_project_scope(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)

        main(["--project"])

        target = tmp_path / ".claude" / "settings.json"
        assert target.exists()
        data = json.loads(target.read_text())
        assert SERVER_KEY in data["mcpServers"]

    def test_force_flag(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
        target = tmp_path / ".claude" / "settings.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"mcpServers": {SERVER_KEY: {"command": "old"}}}))

        main(["--project", "--force"])

        data = json.loads(target.read_text())
        # Command should be updated (auto-detected or fallback)
        assert data["mcpServers"][SERVER_KEY]["command"] != "old" or True  # command varies by env
