# MCP Server Mode

Codebase Cortex can run as an MCP (Model Context Protocol) server, giving your coding agent direct access to documentation tools — semantic search, section editing, freshness checking, and more.

No LLM API key required. The agent's own LLM does the reasoning; Cortex provides the documentation infrastructure.

## Quick Start

### 1. Initialize Cortex

```bash
pip install codebase-cortex
cd your-project
cortex init
```

Select "Coding agent tool" when prompted. Cortex will:
- Build a FAISS semantic search index of your codebase
- Generate the MCP config for your agent
- Optionally add documentation guidelines to CLAUDE.md

### 2. Restart Your Agent

Restart Claude Code, Cursor, or Windsurf. Cortex tools will appear automatically.

### 3. Use the Tools

Your agent now has access to 11 documentation tools. Ask it to:
- "Search for docs related to the auth module"
- "Update the API documentation to reflect these changes"
- "Check which docs are stale"

## Available Tools

### Core Tools

| Tool | Description |
|------|-------------|
| `cortex_search_related_docs` | Find docs related to code changes using semantic search |
| `cortex_read_section` | Read a doc section with metadata (draft, human-edited, timestamps) |
| `cortex_write_section` | Update a doc section with human-edit protection |
| `cortex_list_docs` | List all doc pages and their section structure |
| `cortex_check_freshness` | Find docs that may be stale based on recent commits |
| `cortex_get_doc_status` | Get overall documentation health metrics |

### Utility Tools

| Tool | Description |
|------|-------------|
| `cortex_rebuild_index` | Rebuild the semantic search index (incremental by default) |
| `cortex_accept_drafts` | Accept draft docs by removing draft banners |
| `cortex_create_page` | Create a new doc page with initial structure |
| `cortex_knowledge_map` | See code-to-documentation relationships |
| `cortex_sync` | Sync local docs to Notion or other platforms |

## Agent Configuration

### Claude Code

Cortex adds to `.mcp.json` in your project root:

```json
{
  "mcpServers": {
    "cortex": {
      "command": "cortex",
      "args": ["mcp", "serve"]
    }
  }
}
```

### Cursor

Config goes in `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "cortex": {
      "command": "cortex",
      "args": ["mcp", "serve"]
    }
  }
}
```

### Windsurf

Config goes in `.windsurf/mcp.json` (same format as above).

### Manual Configuration

For other agents, start the server with:

```bash
cortex mcp serve
```

The server communicates over stdio using the MCP protocol.

## Hybrid Mode

MCP server mode coexists with standalone features. You can have:

- **MCP tools** for your coding agent (no LLM needed)
- **Git hooks** for automatic doc updates on every commit (needs LLM)
- **CI/CD integration** for pipeline doc checks (needs LLM)

To enable standalone features alongside MCP:

```bash
cortex config set LLM_MODEL gemini/gemini-2.5-flash-lite
cortex config set LLM_API_KEY your-key
```

## Human-Edit Protection

When you manually edit a doc section, Cortex tracks the change. If the agent tries to overwrite a human-edited section via `cortex_write_section`, it returns `skipped_human_edited` instead of overwriting.

The agent can acknowledge this and force-write by appending ` [force]` to the heading.

## Troubleshooting

### "Cortex is not initialized"
Run `cortex init` in your project directory.

### Tools not appearing in agent
1. Verify `.mcp.json` exists with the cortex entry
2. Restart your agent
3. Check that `cortex` is on your PATH: `which cortex`

### Search returns no results
The FAISS index may need building:
- Ask the agent to use `cortex_rebuild_index`
- Or run `cortex embed` from the terminal

### Stale search results
The server auto-reloads the FAISS index when it detects changes on disk. If results seem stale, use `cortex_rebuild_index` to force a refresh.
