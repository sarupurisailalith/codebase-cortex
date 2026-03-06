# Configuration

Codebase Cortex stores all per-repo configuration in a `.cortex/` directory inside your project repository. This directory is automatically gitignored.

## Setup

Run `cortex init` inside your project repository to create the configuration:

```bash
cd /path/to/your-project
cortex init
```

The interactive wizard guides you through provider selection, API key entry, and Notion authorization.

## Directory Structure

```
your-project/
└── .cortex/                        # Created by cortex init
    ├── .env                        # Configuration and API keys
    ├── .gitignore                  # Ignores everything in .cortex/
    ├── notion_tokens.json          # OAuth tokens (auto-refreshed)
    ├── page_cache.json             # Tracked Notion page metadata
    ├── debug.log                   # Debug log (when --verbose is used)
    ├── hook.log                    # Git hook output log
    └── faiss_index/                # Vector embeddings
        ├── index.faiss             # FAISS binary index
        └── chunks.json             # Chunk metadata
```

## Environment Variables

All configuration is stored in `.cortex/.env`. The `cortex init` wizard creates this file.

### Required

| Variable | Description | Example |
|----------|-------------|---------|
| `LLM_PROVIDER` | LLM provider to use | `google`, `anthropic`, `openrouter` |
| `LLM_MODEL` | Model name | `gemini-2.5-flash-lite` |

### Provider-specific (one required)

| Variable | Provider | Description |
|----------|----------|-------------|
| `GOOGLE_API_KEY` | Google | Google AI / Gemini API key |
| `ANTHROPIC_API_KEY` | Anthropic | Anthropic API key |
| `OPENROUTER_API_KEY` | OpenRouter | OpenRouter API key |

### Optional

| Variable | Description | Default |
|----------|-------------|---------|
| `GITHUB_TOKEN` | GitHub PAT (only for private remote repos) | — |

## LLM Providers

### Google Gemini (default)

```env
LLM_PROVIDER=google
LLM_MODEL=gemini-2.5-flash-lite
GOOGLE_API_KEY=your-key-here
```

**Recommended models:**

| Model | Speed | Quality | Cost |
|-------|-------|---------|------|
| `gemini-2.5-flash-lite` | Fast | Good | Low |
| `gemini-3-flash-preview` | Fast | Better | Low |
| `gemini-2.5-pro` | Slower | Best | Higher |

### Anthropic

```env
LLM_PROVIDER=anthropic
LLM_MODEL=claude-sonnet-4-20250514
ANTHROPIC_API_KEY=your-key-here
```

**Recommended models:**

| Model | Speed | Quality | Cost |
|-------|-------|---------|------|
| `claude-sonnet-4-20250514` | Medium | High | Medium |
| `claude-haiku-4-5-20251001` | Fast | Good | Low |

### OpenRouter

```env
LLM_PROVIDER=openrouter
LLM_MODEL=anthropic/claude-sonnet-4
OPENROUTER_API_KEY=your-key-here
```

OpenRouter provides access to many models from a single API key. Any model available on OpenRouter can be used — just provide the full model ID.

## Notion OAuth Tokens

OAuth tokens are stored in `.cortex/notion_tokens.json`:

```json
{
  "access_token": "...",
  "refresh_token": "...",
  "expires_at": 1741234567.89,
  "client_id": "...",
  "client_secret": "...",
  "token_endpoint": "https://mcp.notion.com/token"
}
```

- **Access tokens** expire after 1 hour
- **Refresh tokens** are rotated automatically (Notion allows max 2 valid refresh tokens)
- Token refresh is handled transparently — you don't need to re-authorize

To re-authorize, run `cortex init` again.

## Page Cache

The page cache (`.cortex/page_cache.json`) tracks Notion pages that Cortex manages:

```json
{
  "page-uuid-1": {
    "page_id": "page-uuid-1",
    "title": "Architecture Overview",
    "last_synced": 1741234567.89,
    "content_hash": "a1b2c3d4"
  }
}
```

- **`content_hash`** — MD5 hash of the last content written (used for first-run detection)
- **`last_synced`** — Unix timestamp of last sync

The cache is automatically populated during `cortex init` (starter pages) and updated whenever pages are written.

### Adding pages to the cache

```bash
# Discover pages via search
cortex scan

# Link a specific page by ID
cortex scan --link "page-uuid"
```

## FAISS Index

The FAISS index is stored in `.cortex/faiss_index/`:

- **`index.faiss`** — Binary FAISS IndexFlatL2 (L2 distance metric)
- **`chunks.json`** — Metadata for each indexed chunk

The index is rebuilt on each `cortex run` to capture code changes. You can manually rebuild with:

```bash
cortex embed
```

## Git Hook

If you opted in during `cortex init`, a post-commit hook is installed at `.git/hooks/post-commit`:

```bash
# --- codebase-cortex post-commit hook ---
if command -v cortex >/dev/null 2>&1; then
    cortex run --once --verbose >> .cortex/hook.log 2>&1 &
fi
```

The hook:
- Runs in the background (doesn't block git)
- Logs output to `.cortex/hook.log`
- Checks if `cortex` is available before running
- Can be set to `full` or `dry-run` mode during setup

To remove the hook, delete the hook marker section from `.git/hooks/post-commit`.

## Verbose / Debug Mode

Pass `-v` or `--verbose` to any command to enable debug logging:

```bash
cortex run --once -v
cortex prompt "..." -v
```

This logs:
- LLM call details (message count, character count, response preview)
- MCP tool calls (tool name, arguments, response preview)
- All output is also written to `.cortex/debug.log`
