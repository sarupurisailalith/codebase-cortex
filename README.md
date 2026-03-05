# Codebase Cortex

LangGraph multi-agent system that keeps engineering documentation in sync with code via Notion MCP.

## Quick Start

```bash
# Install globally
pip install uv
git clone https://github.com/sarupurisailalith/codebase-cortex.git
cd codebase-cortex && uv sync

# Go to your project repo
cd /path/to/your-project

# Initialize Cortex (creates .cortex/ directory, connects to Notion)
cortex init

# Run the pipeline
cortex run --once
```

## How It Works

Run `cortex init` inside any git repo. Cortex creates a `.cortex/` directory (gitignored) that stores config, OAuth tokens, and FAISS indexes. Then `cortex run` analyzes your recent commits and syncs documentation to Notion.

## Architecture

Codebase Cortex uses a multi-agent pipeline powered by LangGraph:

1. **CodeAnalyzer** - Parses git diffs, identifies what changed and why
2. **SemanticFinder** - Finds related docs via FAISS embedding similarity
3. **DocWriter** - Updates/creates Notion pages to reflect code changes
4. **TaskCreator** - Creates Notion tasks for undocumented areas
5. **SprintReporter** - Generates weekly sprint summaries

## CLI Commands

| Command | Description |
|---------|-------------|
| `cortex init` | Interactive setup wizard (run inside your repo) |
| `cortex run` | Run the full pipeline |
| `cortex status` | Show connection status |
| `cortex analyze` | One-shot diff analysis |
| `cortex embed` | Rebuild embedding index |

## Per-Repo Config

`cortex init` creates a `.cortex/` directory in your repo:

```
your-project/
├── .cortex/           # Created by cortex init (gitignored)
│   ├── .env           # LLM provider, API keys
│   ├── .gitignore     # Ignores everything in .cortex/
│   ├── notion_tokens.json
│   ├── faiss_index/
│   └── page_cache.json
├── src/
└── ...
```

## License

MIT
