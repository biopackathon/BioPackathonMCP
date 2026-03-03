# BioPackathon MCP Server

An MCP server that searches and performs Q&A on subtitles from the Bio"Pack"athon YouTube playlist, recommends videos, and audits the reproducibility of GitHub repositories.

## Setup

### 1. Installation

```bash
pip install git+https://github.com/biopackathon/BioPackathonMCP.git
```

### 2. Environment Variables

```bash
export YOUTUBE_API_KEY="your-youtube-data-api-key"
```

<details>
<summary>Development installation</summary>

```bash
git clone https://github.com/biopackathon/BioPackathonMCP.git
cd BioPackathonMCP
pip install -e ".[dev]"
```

</details>

## Usage

### Step 1: Ingest YouTube Playlist

```bash
biopackathon-ingest
# Or specify a particular playlist
biopackathon-ingest --playlist PL0uaKHgcG00aJSa233gkhBA2HHe0-Ha-B --index-dir data/index
```

Ingests all videos with subtitles and builds a hybrid search index (FAISS + BM25).

### Step 2: Configure the MCP Server

MCP clients such as Claude Desktop and Claude Code **automatically start and manage** the server based on configuration files. You do not need to run `biopackathon-mcp` manually.

**Claude Desktop** — Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "biopackathon": {
      "command": "biopackathon-mcp",
      "env": {
        "YOUTUBE_API_KEY": "your-key"
      }
    }
  }
}
```

**Claude Code** — Add to `.claude/settings.json`:

```json
{
  "mcpServers": {
    "biopackathon": {
      "command": "biopackathon-mcp",
      "env": {
        "YOUTUBE_API_KEY": "your-key"
      }
    }
  }
}
```

After configuration, the client will automatically start the server at the beginning of each session.

<details>
<summary>Manual startup (for debugging)</summary>

```bash
biopackathon-mcp
```

The server starts as a long-running process waiting for requests from MCP clients. There will be no terminal output and it may appear frozen, but this is normal. Press `Ctrl+C` to stop.

Verify the server is running:

```bash
ps aux | grep biopackathon-mcp | grep -v grep
```

</details>

## MCP Tools

### `search_segments`

Search subtitle segments using hybrid search (BM25 + vector). Locate relevant sections of Bio"Pack"athon videos by keyword or topic, with timestamped URLs.

| Parameter | Type | Default | Description |
|---|---|---|---|
| query | str | (required) | Search query |
| top_k | int | 10 | Maximum number of results to return |
| filters | str \| None | None | JSON filter `{"date":"2024-01-01","speaker":"name","tags":["RNA"]}`. `date` returns segments on or after the given date |

**Examples:**

```
# Basic search
search_segments(query="R package development")

# Limit results
search_segments(query="reproducibility", top_k=3)

# Filter by date or tags
search_segments(query="single cell", filters='{"tags":["RNA"]}')
search_segments(query="LLM", filters='{"date":"2024-06-01"}')
```

**Example response:**

```json
[
  {
    "video_id": "JrwZUAnzZQM",
    "title": "LLM usage in R package development",
    "url": "https://www.youtube.com/watch?v=JrwZUAnzZQM&t=3591s",
    "t_start": 3591.6,
    "t_end": 3608.4,
    "score": 0.50,
    "snippet": "We could share how to use AI for maintenance...",
    "date": "2025-09-22",
    "speaker": null,
    "tags": []
  }
]
```

Use the timestamp in `url` (e.g. `&t=3591s`) to jump directly to the relevant section of the video.

---

### `answer_question`

Answer a question with evidence from YouTube subtitles. Returns a summary with timestamped citation URLs.

| Parameter | Type | Default | Description |
|---|---|---|---|
| question | str | (required) | Question text |
| top_k | int | 8 | Number of reference segments |
| filters | str \| None | None | Filter conditions |

**Examples:**

```
# Basic question
answer_question(question="What was discussed about Docker and reproducibility?")

# Increase references for broader search
answer_question(question="How to use Snakemake?", top_k=15)

# Filter by date range
answer_question(question="What are the LLM use cases?", filters='{"date":"2024-01-01"}')
```

**Example response:**

```json
{
  "answer": "Regarding reproducibility, Docker is recommended because...",
  "citations": [
    {
      "url": "https://www.youtube.com/watch?v=ySHaDZ9kqr0&t=2796s",
      "t_start": 2796.9,
      "t_end": 2843.8,
      "why": "[Virtual environment management tools for Python, R, Julia] Regarding reproducibility..."
    }
  ]
}
```

Each URL in `citations` links directly to the relevant section of the video.

---

### `recommend_videos`

Suggest recommended videos based on a learning goal, with key timestamps for quick navigation.

| Parameter | Type | Default | Description |
|---|---|---|---|
| goal | str | (required) | Learning goal or topic |
| top_k | int | 5 | Number of videos to recommend |
| filters | str \| None | None | Filter conditions |

**Examples:**

```
# Search by learning goal
recommend_videos(goal="Getting started with single-cell analysis")

# Limit number of results
recommend_videos(goal="How to create Python packages", top_k=3)

# Filter by tag
recommend_videos(goal="Learn workflow management", filters='{"tags":["Snakemake"]}')
```

**Example response:**

```json
[
  {
    "video_id": "6zbriRLKlWE",
    "title": "Workflow language: Introduction to Snakemake @ Bio\"Pack\"athon2025#6",
    "url": "https://www.youtube.com/watch?v=6zbriRLKlWE",
    "why": "Covers the basics of Snakemake usage",
    "key_timestamps": [
      {"t": 120, "label": "What is Snakemake"},
      {"t": 600, "label": "Basic rule syntax"}
    ]
  }
]
```

Use `key_timestamps` to jump directly to key points within the video.

---

### `list_tags`

List all available tags with their occurrence counts. Use this to discover valid tag values for the `filters` parameter of `search_segments`, `answer_question`, and `recommend_videos`.

| Parameter | Type | Default | Description |
|---|---|---|---|
| (none) | — | — | No parameters required |

**Examples:**

```
# List all available tags
list_tags()
```

**Example response:**

```json
[
  {"tag": "R", "count": 491},
  {"tag": "Python", "count": 79},
  {"tag": "package", "count": 34},
  {"tag": "RNA", "count": 33}
]
```

Results are sorted by frequency in descending order. Use the returned tag values in the `filters` parameter of other tools, e.g. `{"tags": ["R"]}`.

---

### `audit_reproducibility`

Audit the reproducibility of a local Git repository. Checks for Dockerfile, lock files, workflow definitions, random seed pinning, README instructions, download URLs, and more. Returns a score and actionable findings.

| Parameter | Type | Default | Description |
|---|---|---|---|
| repo_path | str | (required) | Path to a local repository |

**Examples:**

```
# Audit a repository
audit_reproducibility(repo_path="/home/user/my-project")

# Audit a specific repository
audit_reproducibility(repo_path="/home/user/dev/bioinfo-pipeline")
```

**Example response:**

```json
{
  "score": 65,
  "findings": [
    {
      "severity": "warning",
      "item": "No lock file found",
      "reason": "Dependency versions are not pinned",
      "evidence": [
        {
          "path": "requirements.txt",
          "line": 3,
          "excerpt": "pandas>=1.5"
        }
      ]
    },
    {
      "severity": "info",
      "item": "Dockerfile found",
      "reason": "Containerization ensures reproducibility",
      "evidence": [
        {
          "path": "Dockerfile",
          "line": 1,
          "excerpt": "FROM python:3.11-slim"
        }
      ]
    }
  ]
}
```

`score` ranges from 0 to 100, indicating the level of reproducibility. Each item in `findings` identifies a specific area for improvement.

## Testing

```bash
pytest -q
```

## Directory Structure

```
├── pyproject.toml
├── README.md
├── src/biopackathon_mcp/
│   ├── __init__.py
│   ├── ingest_youtube.py    # Playlist ingestion
│   ├── indexer.py           # FAISS + BM25 hybrid index
│   ├── tools.py             # search / answer / recommend logic
│   ├── mcp_server.py        # MCP server
│   └── audit/
│       ├── __init__.py
│       ├── audit_repo.py    # Reproducibility audit logic
│       └── rules.yml        # Audit rule definitions
└── tests/
    ├── conftest.py
    ├── test_search.py       # Search, Q&A, and recommendation tests
    ├── test_audit.py        # Audit tests
    └── fixtures/
        ├── sample_subtitles.json
        ├── pseudo_repo/          # Well-configured pseudo repository
        └── pseudo_repo_minimal/  # Minimally-configured pseudo repository
```
