"""Shared fixtures for tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_subtitles() -> list[dict]:
    with open(FIXTURES_DIR / "sample_subtitles.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def pseudo_repo_path() -> Path:
    return FIXTURES_DIR / "pseudo_repo"


@pytest.fixture
def pseudo_repo_minimal_path() -> Path:
    return FIXTURES_DIR / "pseudo_repo_minimal"
