# Contributing

This guide covers development setup, testing, and project structure for contributing to Codebase Cortex.

## Development Setup

### Prerequisites

- Python 3.11+ (developed on 3.14)
- [uv](https://docs.astral.sh/uv/) package manager
- Git

### Clone and install

```bash
git clone https://github.com/sarupurisailalith/codebase-cortex.git
cd codebase-cortex
uv sync
```

This installs all dependencies including dev tools (pytest, pytest-asyncio).

### Install as editable CLI

```bash
uv tool install -e .
```

The `-e` flag installs in editable mode — code changes take effect immediately without reinstalling.

This registers both `cortex` and `codebase-cortex` as CLI commands.

## Project Structure

```
codebase-cortex/
├── src/codebase_cortex/           # Main package
│   ├── __init__.py
│   ├── cli.py                     # Click CLI commands
│   ├── config.py                  # Settings dataclass, get_llm() factory
│   ├── state.py                   # CortexState TypedDict definitions
│   ├── graph.py                   # LangGraph StateGraph
│   ├── mcp_client.py              # Notion MCP connection
│   ├── agents/                    # Pipeline agents
│   │   ├── base.py                # BaseAgent ABC
│   │   ├── code_analyzer.py       # Git diff / full scan analysis
│   │   ├── semantic_finder.py     # FAISS similarity search
│   │   ├── doc_writer.py          # Section-level Notion updates
│   │   ├── task_creator.py        # Task page creation
│   │   └── sprint_reporter.py     # Sprint summary generation
│   ├── auth/                      # OAuth 2.0 + PKCE
│   │   ├── oauth.py               # PKCE flow, token exchange
│   │   ├── callback_server.py     # Local HTTP server
│   │   └── token_store.py         # Token persistence
│   ├── embeddings/                # Vector search
│   │   ├── indexer.py             # Code chunking + embedding
│   │   ├── store.py               # FAISS index management
│   │   └── clustering.py          # HDBSCAN topic clustering
│   ├── git/                       # Git integration
│   │   ├── diff_parser.py         # Diff parsing
│   │   └── github_client.py       # GitHub API (optional)
│   ├── notion/                    # Notion helpers
│   │   ├── bootstrap.py           # Starter page creation
│   │   └── page_cache.py          # Page metadata cache
│   └── utils/                     # Shared utilities
│       ├── json_parsing.py        # Robust JSON extraction
│       ├── logging.py             # Rich-based logging
│       ├── rate_limiter.py        # Async token bucket
│       └── section_parser.py      # Markdown section parser
├── tests/                         # Test suite
│   ├── conftest.py                # Shared fixtures
│   ├── test_agents.py             # Agent unit tests
│   ├── test_bootstrap.py          # Notion bootstrap tests
│   ├── test_config.py             # Config/settings tests
│   ├── test_diff_parser.py        # Git diff parsing tests
│   ├── test_embeddings.py         # FAISS + clustering tests
│   ├── test_graph.py              # Graph routing tests
│   ├── test_page_cache.py         # Page cache tests
│   ├── test_section_parser.py     # Section parser tests
│   └── test_state.py              # State TypedDict tests
├── docs/                          # Documentation
├── pyproject.toml                 # Project metadata and dependencies
├── CLAUDE.md                      # Claude Code instructions
└── LICENSE                        # MIT
```

## Running Tests

```bash
# Run all tests
uv run pytest

# Run with verbose output
uv run pytest -v

# Run a specific test file
uv run pytest tests/test_section_parser.py -v

# Run a specific test
uv run pytest tests/test_section_parser.py::test_merge_case_insensitive_heading_match -v
```

### Test categories

| Test File | Tests | What it covers |
|-----------|-------|---------------|
| `test_agents.py` | Agent instantiation and base methods |
| `test_bootstrap.py` | Notion page bootstrap logic |
| `test_config.py` | Settings loading, LLM factory |
| `test_diff_parser.py` | Git diff parsing |
| `test_embeddings.py` | FAISS index, search, HDBSCAN clustering |
| `test_graph.py` | Graph compilation, conditional routing |
| `test_page_cache.py` | Page cache, fuzzy title matching |
| `test_section_parser.py` | Section parsing, merging, heading normalization |
| `test_state.py` | State TypedDict creation |

### Writing tests

- Tests use pytest with fixtures in `conftest.py`
- Async tests use `pytest-asyncio` with `asyncio_mode = "auto"`
- Mock external services (LLM, Notion MCP) — tests should run without API keys
- Test files mirror the source structure: `src/codebase_cortex/utils/section_parser.py` → `tests/test_section_parser.py`

## Architecture Patterns

### Agent pattern

All agents follow this structure:

```python
class MyAgent(BaseAgent):
    async def run(self, state: CortexState) -> dict:
        # 1. Read inputs from state
        analysis = state.get("analysis", "")

        # 2. Do work (LLM calls, MCP calls, etc.)
        result = await self._invoke_llm(messages)

        # 3. Return state updates
        return {"my_output": result}
```

Key conventions:
- Agents are stateless — all state flows through `CortexState`
- Use `_invoke_llm()` for LLM calls (handles logging + structured content blocks)
- Use `_append_error()` for error collection
- Return a dict of state updates (not the full state)

### MCP session pattern

```python
from codebase_cortex.mcp_client import notion_mcp_session, rate_limiter

async with notion_mcp_session(settings) as session:
    await rate_limiter.acquire()
    result = await session.call_tool("notion-fetch", arguments={"id": page_id})
```

- Always use the `notion_mcp_session` context manager
- Always call `rate_limiter.acquire()` before each MCP call
- Check `result.isError` before using results

### Settings pattern

```python
from codebase_cortex.config import Settings

settings = Settings.from_env()  # Loads from cwd/.cortex/.env
# or
settings = Settings.from_env(Path("/path/to/repo"))
```

## Adding a New Agent

1. Create `src/codebase_cortex/agents/my_agent.py`:

```python
from codebase_cortex.agents.base import BaseAgent
from codebase_cortex.state import CortexState

SYSTEM_PROMPT = """Your system prompt here."""

class MyAgent(BaseAgent):
    async def run(self, state: CortexState) -> dict:
        # Implementation
        return {"my_output": result}
```

2. Add state fields to `src/codebase_cortex/state.py`

3. Add a node function in `src/codebase_cortex/graph.py`:

```python
async def my_agent_node(state: CortexState) -> dict:
    agent = MyAgent(get_llm(settings))
    return await agent.run(state)
```

4. Wire into the graph in `build_graph()`

5. Add tests in `tests/test_agents.py`

## Code Style

- Type hints on all public functions
- Async for MCP and LLM interactions
- `src/` layout with hatchling build backend
- No docstrings needed on private methods unless logic is non-obvious
- Use `from __future__ import annotations` for forward references

## Dependencies

### Runtime

| Package | Purpose |
|---------|---------|
| langgraph | Multi-agent orchestration |
| langchain-core | Base LLM abstractions |
| langchain-google-genai | Google Gemini integration |
| langchain-anthropic | Anthropic integration |
| langchain-openai | OpenRouter integration |
| langchain-mcp-adapters | MCP tool compatibility |
| mcp | Model Context Protocol client |
| httpx | Async HTTP |
| sentence-transformers | Code embeddings |
| faiss-cpu | Vector similarity search |
| hdbscan | Topic clustering |
| gitpython | Git diff parsing |
| PyGithub | GitHub API (optional) |
| click | CLI framework |
| rich | Styled terminal output |
| python-dotenv | Environment loading |

### Dev

| Package | Purpose |
|---------|---------|
| pytest | Test framework |
| pytest-asyncio | Async test support |
