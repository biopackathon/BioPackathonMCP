"""CLI to register biopackathon-mcp in Claude Code / Claude Desktop settings."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys
from pathlib import Path


def _claude_desktop_config_path() -> Path:
    """Return the Claude Desktop config path for the current platform."""
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if system == "Windows":
        return Path(os.environ.get("APPDATA", "")) / "Claude" / "claude_desktop_config.json"
    # Linux / other
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def _resolve_target(scope: str) -> Path:
    """Return the settings file path for the given scope."""
    if scope == "user":
        return Path.home() / ".claude" / "settings.json"
    if scope == "project":
        return Path.cwd() / ".claude" / "settings.json"
    if scope == "desktop":
        return _claude_desktop_config_path()
    raise ValueError(f"Unknown scope: {scope}")


def _detect_command() -> str:
    """Detect the absolute path of the biopackathon-mcp command."""
    path = shutil.which("biopackathon-mcp")
    if path:
        return path
    return "biopackathon-mcp"


def _build_entry(command: str) -> dict:
    """Build the mcpServers entry dict."""
    entry: dict = {"command": command}
    api_key = os.environ.get("YOUTUBE_API_KEY")
    if api_key:
        entry["env"] = {"YOUTUBE_API_KEY": api_key}
    return entry


SERVER_KEY = "biopackathon-mcp"


def apply_setup(
    target: Path,
    *,
    force: bool = False,
    dry_run: bool = False,
    command: str | None = None,
) -> dict:
    """Apply the MCP server entry to the target settings file.

    Returns a dict with keys:
      action: "created" | "added" | "skipped" | "overwritten"
      path: str  — target file path
      entry: dict — the mcpServers entry that was (or would be) written
    """
    cmd = command or _detect_command()
    entry = _build_entry(cmd)

    # Load existing settings
    if target.exists():
        text = target.read_text(encoding="utf-8")
        settings = json.loads(text) if text.strip() else {}
    else:
        settings = {}

    servers = settings.setdefault("mcpServers", {})

    if SERVER_KEY in servers and not force:
        return {"action": "skipped", "path": str(target), "entry": servers[SERVER_KEY]}

    action = "overwritten" if SERVER_KEY in servers else ("added" if settings.get("mcpServers") else "created")
    servers[SERVER_KEY] = entry

    if not dry_run:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return {"action": action, "path": str(target), "entry": entry}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="biopackathon-setup",
        description="Register biopackathon-mcp in Claude Code or Claude Desktop settings.",
    )
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument(
        "--project",
        action="store_const",
        const="project",
        dest="scope",
        help="Write to .claude/settings.json in the current directory",
    )
    scope.add_argument(
        "--desktop",
        action="store_const",
        const="desktop",
        dest="scope",
        help="Write to the Claude Desktop configuration file",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing entry if present",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be written without making changes",
    )
    parser.set_defaults(scope="user")
    args = parser.parse_args(argv)

    target = _resolve_target(args.scope)
    result = apply_setup(target, force=args.force, dry_run=args.dry_run)

    action = result["action"]
    path = result["path"]
    entry_json = json.dumps(result["entry"], indent=2, ensure_ascii=False)

    if action == "skipped":
        print(f"Already configured in {path} (use --force to overwrite)")
        sys.exit(0)

    prefix = "[dry-run] " if args.dry_run else ""
    if action == "created":
        print(f"{prefix}Created {path}")
    elif action == "added":
        print(f"{prefix}Added biopackathon-mcp to {path}")
    else:
        print(f"{prefix}Overwrote biopackathon-mcp entry in {path}")

    print(f"\n  mcpServers.{SERVER_KEY}:")
    for line in entry_json.splitlines():
        print(f"    {line}")
    print()

    if os.environ.get("YOUTUBE_API_KEY"):
        print("YOUTUBE_API_KEY detected in environment and included.")
    else:
        print("Tip: set YOUTUBE_API_KEY env var before running to include it in the config.")


if __name__ == "__main__":
    main()
