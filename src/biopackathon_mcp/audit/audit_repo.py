"""Reproducibility audit for a local repository."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


_RULES_PATH = Path(__file__).parent / "rules.yml"

Severity = str  # "info" | "warn" | "error"


def _load_rules() -> dict[str, Any]:
    with open(_RULES_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _find_files(repo: Path, patterns: list[str]) -> list[Path]:
    """Glob for files matching any of the patterns."""
    found: list[Path] = []
    for pat in patterns:
        found.extend(repo.rglob(pat))
    return sorted(set(found))


def _grep_file(path: Path, pattern: str) -> list[dict[str, Any]]:
    """Search a file for regex pattern. Returns list of {line, excerpt}."""
    hits: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except (OSError, UnicodeDecodeError):
        return hits
    regex = re.compile(pattern, re.IGNORECASE)
    for i, line in enumerate(lines, 1):
        if regex.search(line):
            hits.append({"line": i, "excerpt": line.strip()[:200]})
    return hits


def _check_container(repo: Path, rule: dict[str, Any]) -> dict[str, Any]:
    files = _find_files(repo, rule["glob_patterns"])
    if files:
        return {
            "severity": "info",
            "item": rule["id"],
            "reason": "Container definition file found.",
            "evidence": [{"path": str(f.relative_to(repo)), "line": 0, "excerpt": ""} for f in files],
        }
    return {
        "severity": rule["severity"],
        "item": rule["id"],
        "reason": "No Dockerfile / Containerfile found. Consider containerizing your project.",
        "evidence": [],
    }


def _check_lockfile(repo: Path, rule: dict[str, Any]) -> dict[str, Any]:
    files = _find_files(repo, rule["glob_patterns"])
    if files:
        return {
            "severity": "info",
            "item": rule["id"],
            "reason": "Dependency version lock file found.",
            "evidence": [{"path": str(f.relative_to(repo)), "line": 0, "excerpt": ""} for f in files],
        }
    return {
        "severity": rule["severity"],
        "item": rule["id"],
        "reason": "No lock file found. Consider pinning dependency versions.",
        "evidence": [],
    }


def _check_workflow(repo: Path, rule: dict[str, Any]) -> dict[str, Any]:
    files = _find_files(repo, rule["glob_patterns"])
    if files:
        return {
            "severity": "info",
            "item": rule["id"],
            "reason": "Workflow definition file found.",
            "evidence": [{"path": str(f.relative_to(repo)), "line": 0, "excerpt": ""} for f in files],
        }
    return {
        "severity": rule["severity"],
        "item": rule["id"],
        "reason": "No workflow engine definition found (Snakemake/Nextflow/CWL/WDL/Makefile).",
        "evidence": [],
    }


def _check_seed(repo: Path, rule: dict[str, Any]) -> dict[str, Any]:
    lang_patterns: dict[str, list[str]] = rule["patterns"]
    extensions_map = {
        "python": ["*.py"],
        "r": ["*.R", "*.r", "*.Rmd"],
        "julia": ["*.jl"],
    }
    all_evidence: list[dict[str, Any]] = []

    for lang, patterns in lang_patterns.items():
        exts = extensions_map.get(lang, [])
        source_files = _find_files(repo, exts)
        for sf in source_files:
            for pat in patterns:
                hits = _grep_file(sf, pat)
                for h in hits:
                    all_evidence.append({
                        "path": str(sf.relative_to(repo)),
                        "line": h["line"],
                        "excerpt": h["excerpt"],
                    })

    if all_evidence:
        return {
            "severity": "info",
            "item": rule["id"],
            "reason": "Random seed pinning detected.",
            "evidence": all_evidence,
        }
    return {
        "severity": rule["severity"],
        "item": rule["id"],
        "reason": "No random seed pinning found. Consider fixing seeds for reproducibility.",
        "evidence": [],
    }


def _check_readme_repro(repo: Path, rule: dict[str, Any]) -> dict[str, Any]:
    readme_candidates = ["README.md", "README.rst", "README.txt", "README"]
    readme_path: Path | None = None
    for name in readme_candidates:
        p = repo / name
        if p.exists():
            readme_path = p
            break

    if readme_path is None:
        return {
            "severity": "error",
            "item": rule["id"],
            "reason": "No README file found.",
            "evidence": [],
        }

    content = readme_path.read_text(encoding="utf-8", errors="replace")
    has_code_block = bool(re.search(r"```", content))
    has_repro_keyword = bool(re.search(
        r"(install|setup|run|usage|getting.started|how.to|quickstart|reproduce)",
        content, re.IGNORECASE,
    ))

    if has_code_block and has_repro_keyword:
        return {
            "severity": "info",
            "item": rule["id"],
            "reason": "README contains reproduction steps (code block + relevant keywords).",
            "evidence": [{"path": str(readme_path.relative_to(repo)), "line": 0, "excerpt": ""}],
        }

    reasons: list[str] = []
    if not has_code_block:
        reasons.append("no code block (```) found")
    if not has_repro_keyword:
        reasons.append("no reproduction-related keywords (install/setup/run, etc.) found")

    return {
        "severity": rule["severity"],
        "item": rule["id"],
        "reason": f"README reproduction steps are insufficient: {'; '.join(reasons)}.",
        "evidence": [{"path": str(readme_path.relative_to(repo)), "line": 0, "excerpt": ""}],
    }


def _check_download_urls(repo: Path, rule: dict[str, Any]) -> dict[str, Any]:
    url_pattern = rule["url_pattern"]
    checksum_patterns = rule["checksum_patterns"]

    code_exts = ["*.py", "*.R", "*.r", "*.Rmd", "*.jl", "*.sh", "*.bash", "*.nf", "*.smk", "*.wdl", "*.cwl"]
    source_files = _find_files(repo, code_exts)

    url_evidence: list[dict[str, Any]] = []
    has_checksum = False

    for sf in source_files:
        hits = _grep_file(sf, url_pattern)
        for h in hits:
            url_evidence.append({
                "path": str(sf.relative_to(repo)),
                "line": h["line"],
                "excerpt": h["excerpt"],
            })

    # Check for checksum mentions anywhere
    all_files = _find_files(repo, ["*"])
    for f in all_files:
        if f.is_file() and f.stat().st_size < 500_000:
            for cp in checksum_patterns:
                if _grep_file(f, cp):
                    has_checksum = True
                    break
        if has_checksum:
            break

    if not url_evidence:
        return {
            "severity": "info",
            "item": rule["id"],
            "reason": "No hardcoded download URLs detected.",
            "evidence": [],
        }

    sev = rule["severity"]
    if len(url_evidence) > 5 and not has_checksum:
        sev = "warn"

    reason = f"Download URLs detected in {len(url_evidence)} location(s)."
    if not has_checksum:
        reason += " No checksums found."
    else:
        reason += " Checksum references found."

    return {
        "severity": sev,
        "item": rule["id"],
        "reason": reason,
        "evidence": url_evidence[:20],  # cap evidence size
    }


_CHECKERS = {
    "container": _check_container,
    "lockfile": _check_lockfile,
    "workflow": _check_workflow,
    "seed": _check_seed,
    "readme_repro": _check_readme_repro,
    "download_urls": _check_download_urls,
}


def audit_repo(repo_path: str) -> dict[str, Any]:
    """Run reproducibility audit on a local repository.

    Returns:
        {
            "score": 0-100,
            "findings": [{severity, item, reason, evidence: [{path, line, excerpt}]}]
        }
    """
    repo = Path(repo_path).resolve()
    if not repo.is_dir():
        return {
            "score": 0,
            "findings": [{
                "severity": "error",
                "item": "repo_path",
                "reason": f"The specified path does not exist or is not a directory: {repo_path}",
                "evidence": [],
            }],
        }

    rules_data = _load_rules()
    rules = {r["id"]: r for r in rules_data["rules"]}
    findings: list[dict[str, Any]] = []

    for rule_id, rule in rules.items():
        checker = _CHECKERS.get(rule_id)
        if checker:
            finding = checker(repo, rule)
            findings.append(finding)

    # Score calculation: each rule contributes equally
    # "info" = pass (full points), "warn" = partial (half), "error" = fail (0)
    total_rules = len(findings)
    if total_rules == 0:
        return {"score": 0, "findings": findings}

    points = 0
    for f in findings:
        if f["severity"] == "info":
            points += 1.0
        elif f["severity"] == "warn":
            points += 0.5
    score = int(round(100 * points / total_rules))

    return {"score": score, "findings": findings}
