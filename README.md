# Codebase Cortex

LangGraph multi-agent system that keeps engineering documentation in sync with code via Notion MCP.

## Quick Start

```bash
# Install dependencies
uv sync

# Interactive setup (connects to Notion via OAuth)
uv run cortex init

# Run the pipeline
uv run cortex run --once
```

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
| `cortex init` | Interactive setup wizard |
| `cortex run` | Run the full pipeline |
| `cortex status` | Show connection status |
| `cortex analyze` | One-shot diff analysis |
| `cortex embed` | Rebuild embedding index |

## Configuration

Copy `.env.example` to `.env` and fill in your API keys:

```bash
cp .env.example .env
```

Notion OAuth tokens are managed automatically by `cortex init`.

## License

MIT
