# Architecture

Codebase Cortex is a multi-agent pipeline built on [LangGraph](https://langchain-ai.github.io/langgraph/) that connects a git repository to a Notion workspace via the [Notion MCP](https://developers.notion.com/docs/mcp) protocol.

## System Overview

```mermaid
graph TB
    subgraph Input
        GIT[Git Repository]
        USER[User CLI]
    end

    subgraph "Cortex Pipeline (LangGraph)"
        CA[CodeAnalyzer Agent]
        SF[SemanticFinder Agent]
        DW[DocWriter Agent]
        TC[TaskCreator Agent]
        SR[SprintReporter Agent]
    end

    subgraph Infrastructure
        FAISS[(FAISS Index)]
        LLM[LLM Provider]
        CACHE[Page Cache]
    end

    subgraph Output
        NOTION[Notion Workspace]
    end

    GIT -->|diffs| CA
    USER -->|prompt| DW
    CA -->|analysis| SF
    SF -->|related docs| DW
    SF <-->|embeddings| FAISS
    DW -->|doc updates| TC
    TC -->|tasks| SR
    CA <-->|invoke| LLM
    DW <-->|invoke| LLM
    TC <-->|invoke| LLM
    SR <-->|invoke| LLM
    DW <-->|read/write| NOTION
    TC <-->|create pages| NOTION
    SR <-->|append| NOTION
    DW <--> CACHE
    TC <--> CACHE
```

## Agent Pipeline

The pipeline is orchestrated by a LangGraph `StateGraph`. All agents share a single `CortexState` TypedDict that flows through the graph:

```mermaid
stateDiagram-v2
    [*] --> CodeAnalyzer
    CodeAnalyzer --> SemanticFinder: analysis exists
    CodeAnalyzer --> [*]: no changes
    SemanticFinder --> DocWriter
    DocWriter --> TaskCreator
    TaskCreator --> SprintReporter: has updates
    TaskCreator --> [*]: nothing to report
    SprintReporter --> [*]
```

### Conditional routing

The graph includes two conditional edges:

1. **After CodeAnalyzer**: If no `analysis` was produced (no code changes detected), the pipeline ends early.
2. **After TaskCreator**: If neither `doc_updates` nor `tasks_created` have content, the pipeline skips SprintReporter.

## Shared State

All agents read from and write to a shared `CortexState` TypedDict:

```mermaid
graph LR
    subgraph CortexState
        direction TB
        T[trigger, repo_path, dry_run, full_scan]
        G[diff_text, changed_files]
        A[analysis]
        R[related_docs]
        D[doc_updates]
        K[tasks_created]
        S[sprint_summary]
        E[errors]
    end

    CA[CodeAnalyzer] -->|writes| G
    CA -->|writes| A
    SF[SemanticFinder] -->|writes| R
    DW[DocWriter] -->|writes| D
    TC[TaskCreator] -->|writes| K
    SR[SprintReporter] -->|writes| S
```

| Field | Type | Set By |
|-------|------|--------|
| `trigger` | `str` | CLI (commit/pr/schedule/manual) |
| `repo_path` | `str` | CLI |
| `dry_run` | `bool` | CLI |
| `full_scan` | `bool` | CLI |
| `diff_text` | `str` | CodeAnalyzer |
| `changed_files` | `list[FileChange]` | CodeAnalyzer |
| `analysis` | `str` | CodeAnalyzer |
| `related_docs` | `list[RelatedDoc]` | SemanticFinder |
| `doc_updates` | `list[DocUpdate]` | DocWriter |
| `tasks_created` | `list[TaskItem]` | TaskCreator |
| `sprint_summary` | `str` | SprintReporter |
| `errors` | `list[str]` | Any agent |

## Section-Level Document Updates

DocWriter uses a deterministic merge strategy to update only changed sections of a page, rather than rewriting entire documents:

```mermaid
sequenceDiagram
    participant N as Notion
    participant DW as DocWriter
    participant LLM as LLM
    participant SP as SectionParser

    DW->>N: Fetch current page (notion-fetch)
    N-->>DW: Raw page content
    DW->>DW: strip_notion_metadata()
    DW->>LLM: Analysis + current content
    LLM-->>DW: section_updates JSON
    DW->>SP: parse_sections(existing)
    DW->>SP: merge_sections(existing, updates)
    SP-->>DW: Merged content
    DW->>N: replace_content (notion-update-page)
```

1. **Fetch** — Current page content retrieved from Notion via MCP
2. **Analyze** — LLM receives the analysis and current page content, returns only changed sections
3. **Parse** — Existing content is parsed into sections by markdown headings
4. **Merge** — Changed sections replace their corresponding headings; new sections are appended
5. **Write** — Merged content is written back as a full page replacement

This ensures unchanged sections are preserved exactly, and the LLM only generates content for sections that need updating.

## Data Flow: Full Pipeline Run

```mermaid
sequenceDiagram
    participant User
    participant CLI
    participant CA as CodeAnalyzer
    participant SF as SemanticFinder
    participant DW as DocWriter
    participant TC as TaskCreator
    participant SR as SprintReporter
    participant Notion

    User->>CLI: cortex run --once
    CLI->>CA: State{repo_path}
    CA->>CA: Parse git diff
    CA->>CA: LLM analysis
    CA-->>CLI: State{analysis, changed_files}

    CLI->>SF: State{analysis, repo_path}
    SF->>SF: Rebuild FAISS index
    SF->>SF: Embed analysis
    SF->>SF: Search top-10 similar chunks
    SF-->>CLI: State{related_docs}

    CLI->>DW: State{analysis, related_docs}
    DW->>Notion: Fetch all doc pages
    DW->>DW: LLM generates section updates
    DW->>DW: Merge sections locally
    DW->>Notion: Write updated pages
    DW-->>CLI: State{doc_updates}

    CLI->>TC: State{analysis, doc_updates}
    TC->>TC: LLM identifies gaps
    TC->>Notion: Create task pages
    TC-->>CLI: State{tasks_created}

    CLI->>SR: State{analysis, doc_updates, tasks_created}
    SR->>SR: LLM generates sprint summary
    SR->>Notion: Append to Sprint Log
    SR-->>CLI: State{sprint_summary}
```

## MCP Connection

Cortex connects to Notion through the Model Context Protocol (MCP) using OAuth 2.0 with PKCE:

```mermaid
graph LR
    CORTEX[Cortex] -->|Streamable HTTP| MCP[mcp.notion.com/mcp]
    MCP -->|API| NOTION[Notion API]

    subgraph Auth
        TOKEN[Token Store] -->|Bearer token| CORTEX
        TOKEN -->|Auto-refresh| MCP
    end
```

- **Transport**: Streamable HTTP to `https://mcp.notion.com/mcp`
- **Authentication**: OAuth 2.0 + PKCE with dynamic client registration
- **Rate Limiting**: Dual token bucket (180 req/min general, 30 req/min search)
- **Tools Used**: `notion-fetch`, `notion-update-page`, `notion-create-pages`, `notion-search`

## Project Structure

```
codebase-cortex/
├── src/codebase_cortex/
│   ├── cli.py                    # Click CLI (init, run, status, prompt, etc.)
│   ├── config.py                 # Settings, get_llm() factory
│   ├── state.py                  # CortexState TypedDict
│   ├── graph.py                  # LangGraph StateGraph definition
│   ├── mcp_client.py             # Notion MCP connection
│   ├── agents/
│   │   ├── base.py               # BaseAgent ABC
│   │   ├── code_analyzer.py      # Git diff analysis
│   │   ├── semantic_finder.py    # FAISS similarity search
│   │   ├── doc_writer.py         # Section-level Notion updates
│   │   ├── task_creator.py       # Task page creation
│   │   └── sprint_reporter.py    # Sprint summary generation
│   ├── auth/
│   │   ├── oauth.py              # OAuth 2.0 + PKCE flow
│   │   ├── callback_server.py    # Local HTTP server for OAuth
│   │   └── token_store.py        # Token persistence and refresh
│   ├── embeddings/
│   │   ├── indexer.py            # Code chunking and embedding
│   │   ├── store.py              # FAISS index management
│   │   └── clustering.py         # HDBSCAN topic clustering
│   ├── git/
│   │   ├── diff_parser.py        # Git diff parsing
│   │   └── github_client.py      # GitHub API (optional)
│   ├── notion/
│   │   ├── bootstrap.py          # Starter page creation
│   │   └── page_cache.py         # Page metadata cache
│   └── utils/
│       ├── json_parsing.py       # Robust JSON extraction
│       ├── logging.py            # Rich-based logging
│       ├── rate_limiter.py       # Async token bucket
│       └── section_parser.py     # Markdown section parser
├── tests/                        # pytest test suite
├── docs/                         # Documentation
├── pyproject.toml
└── CLAUDE.md                     # Claude Code instructions
```

## Technology Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Orchestration | LangGraph | Multi-agent pipeline with conditional routing |
| LLM | Google Gemini / Anthropic / OpenRouter | Code analysis, doc generation |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2) | 384-dim code chunk embeddings |
| Vector Search | FAISS (IndexFlatL2) | Similarity search over code chunks |
| Clustering | HDBSCAN | Topic discovery from embeddings |
| Notion | MCP (Streamable HTTP) | Read/write documentation pages |
| Auth | OAuth 2.0 + PKCE | Notion authorization |
| CLI | Click + Rich | Command-line interface |
| Git | GitPython | Diff parsing, commit history |
| HTTP | httpx | Async HTTP for OAuth and MCP |
