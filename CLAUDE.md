# Codebase Cortex - Claude Code Instructions

## Project Overview
LangGraph multi-agent system that syncs engineering docs with code. v0.3 adds MCP server mode — coding agents (Claude Code, Cursor, Windsurf) get 11 deterministic documentation tools, no LLM API key needed. Also a local-first, multi-backend documentation engine with incremental indexing and CI/CD support.

## Tech Stack
- Python 3.14, uv package manager
- LangGraph for multi-agent orchestration
- LiteLLM unified LLM interface (supports Google, Anthropic, OpenRouter, Ollama)
- Notion MCP (remote hosted, OAuth + Streamable HTTP)
- sentence-transformers + FAISS for embeddings
- Tree-sitter for language-aware code chunking (optional)
- Click for CLI, Rich for logging

## Project Structure
- `src/codebase_cortex/` - Main package
- `src/codebase_cortex/agents/` - LangGraph agent nodes (9 nodes in pipeline)
- `src/codebase_cortex/backends/` - DocBackend protocol, LocalMarkdownBackend, NotionBackend
- `src/codebase_cortex/auth/` - OAuth 2.0 + PKCE for Notion
- `src/codebase_cortex/embeddings/` - FAISS index, tree-sitter chunker, HDBSCAN clustering
- `src/codebase_cortex/git/` - Git diff parsing, GitHub client
- `src/codebase_cortex/notion/` - Notion page bootstrap and caching
- `src/codebase_cortex/mcp_server.py` - MCP server (11 tools, FastMCP, no LLM needed)
- `src/codebase_cortex/utils/` - Section parser, rate limiter, JSON parsing, file locking
- `tests/` - pytest tests
- `ref/` - Architecture docs and plans (local only)

## Commands
- `uv sync` - Install dependencies
- `uv run cortex --help` - CLI help (18 commands, including `cortex mcp serve`)
- `uv run pytest` - Run tests
- `uv run pytest tests/test_config.py -v` - Run specific test

## Per-Repo Usage Pattern
- Cortex is a global CLI tool that runs inside target repos
- `cortex init` creates `.cortex/` in the target repo (gitignored)
- `cortex init --quick` auto-detects LLM from env vars
- Config, tokens, FAISS index all live in `.cortex/`
- `Settings.from_env()` reads from `cwd/.cortex/.env`
- Documentation output to `docs/` (local) or Notion (remote)

## Conventions
- Use `src/` layout with hatchling build backend
- Type hints on all public functions
- Async where interacting with MCP or LLM
- Tests use pytest with fixtures in conftest.py
- New fields in CortexState and Settings must have defaults
