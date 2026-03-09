# Codebase Cortex - Claude Code Instructions

## Project Overview
LangGraph multi-agent system that syncs engineering docs with code. Undergoing v0.2 redesign from Notion-coupled to local-first, multi-backend documentation engine.

## v0.2 Implementation (Active)

### Architecture & Plans
- **Architecture doc:** `ref/codebase-cortex-v02-architecture-revised.md` (source of truth, 1349 lines)
- **Plan docs:** `ref/plans/00-overview.md` through `ref/plans/08-migration-testing.md`
- **Branch:** `version2` (all v0.2 work happens here)

### Implementation Process
Phases are implemented **sequentially** (01 through 08). For each phase:
1. Read `ref/plans/00-overview.md` for context and dependency graph
2. Read the specific phase plan doc (e.g., `ref/plans/01-core-infrastructure.md`)
3. Read relevant sections of the architecture doc for full detail
4. Read existing source files before modifying them
5. Implement according to the plan's implementation order
6. Run verification checklist items from the plan
7. Run `uv run pytest` to confirm no regressions

### Phase Status
- [x] Phase 1: Core Infrastructure & LLM Layer (`ref/plans/01-core-infrastructure.md`)
- [x] Phase 2: DocBackend Protocol & Local Docs (`ref/plans/02-docbackend-local-docs.md`)
- [ ] Phase 3: New Pipeline Nodes & Graph (`ref/plans/03-pipeline-nodes.md`)
- [ ] Phase 4: Agent Refactoring (`ref/plans/04-agent-refactoring.md`)
- [ ] Phase 5: Embeddings Upgrades (`ref/plans/05-embeddings-upgrades.md`)
- [ ] Phase 6: CLI Overhaul (`ref/plans/06-cli-overhaul.md`)
- [ ] Phase 7: CI/CD & Advanced Features (`ref/plans/07-cicd-branch-advanced.md`)
- [ ] Phase 8: Migration & Testing (`ref/plans/08-migration-testing.md`)

## Tech Stack
- Python 3.14, uv package manager
- LangGraph for multi-agent orchestration
- Notion MCP (remote hosted, OAuth + Streamable HTTP)
- **v0.1.4:** Google Gemini via langchain-google-genai
- **v0.2 target:** LiteLLM unified interface (replaces all langchain LLM providers)
- sentence-transformers + FAISS for embeddings
- Click for CLI, Rich for logging

## Project Structure
- `src/codebase_cortex/` - Main package
- `src/codebase_cortex/agents/` - LangGraph agent nodes
- `src/codebase_cortex/backends/` - DocBackend protocol, LocalMarkdownBackend, NotionBackend
- `src/codebase_cortex/auth/` - OAuth 2.0 + PKCE for Notion
- `src/codebase_cortex/embeddings/` - FAISS index + HDBSCAN clustering
- `src/codebase_cortex/git/` - Git diff parsing, GitHub client
- `src/codebase_cortex/notion/` - Notion page bootstrap and caching
- `src/codebase_cortex/utils/` - Section parser, rate limiter, JSON parsing
- `tests/` - pytest tests
- `ref/` - Architecture docs and plans (gitignored, local only)

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

## Conventions
- Use `src/` layout with hatchling build backend
- Type hints on all public functions
- Async where interacting with MCP or LLM
- Tests use pytest with fixtures in conftest.py
- Keep backward compatibility with v0.1.4 (existing tests must pass)
- New fields in CortexState and Settings must have defaults
