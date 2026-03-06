# Codebase Cortex - Claude Code Instructions

## Project Overview
LangGraph multi-agent system that syncs engineering docs with code via Notion MCP.

## Tech Stack
- Python 3.14, uv package manager
- LangGraph for multi-agent orchestration
- Notion MCP (remote hosted, OAuth + Streamable HTTP)
- Google Gemini as primary LLM (langchain-google-genai)
- sentence-transformers + FAISS for embeddings
- Click for CLI, Rich for logging

## Project Structure
- `src/codebase_cortex/` - Main package
- `src/codebase_cortex/agents/` - LangGraph agent nodes
- `src/codebase_cortex/auth/` - OAuth 2.0 + PKCE for Notion
- `src/codebase_cortex/embeddings/` - FAISS index + HDBSCAN clustering
- `src/codebase_cortex/git/` - Git diff parsing, GitHub client
- `src/codebase_cortex/notion/` - Notion page bootstrap and caching
- `tests/` - pytest tests

## Commands
- `uv sync` - Install dependencies
- `uv run cortex --help` - CLI help
- `uv run pytest` - Run tests
- `uv run pytest tests/test_config.py -v` - Run specific test

## Per-Repo Usage Pattern
- Cortex is a global CLI tool that runs inside target repos
- `cortex init` creates `.cortex/` in the target repo (gitignored)
- Config, tokens, FAISS index all live in `.cortex/`
- `Settings.from_env()` reads from `cwd/.cortex/.env`
- No more PROJECT_ROOT or global DATA_DIR

## Conventions
- Use `src/` layout with hatchling build backend
- Type hints on all public functions
- Async where interacting with MCP or LLM
- Tests use pytest with fixtures in conftest.py
