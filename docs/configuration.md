# Configuration


<!-- cortex:toc -->
- [Setup](#setup)
- [Directory Structure](#directory-structure)
- [Environment Variables](#environment-variables)
  - [Required](#required)
  - [API Keys (one required)](#api-keys-one-required)
  - [Documentation Output](#documentation-output)
  - [Optional](#optional)
- [LLM Configuration](#llm-configuration)
  - [Model name format](#model-name-format)
  - [Google Gemini](#google-gemini)
  - [Anthropic](#anthropic)
  - [OpenRouter](#openrouter)
  - [Per-node model overrides](#per-node-model-overrides)
- [.cortexignore](#cortexignore)
- [Notion OAuth Tokens](#notion-oauth-tokens)
- [Page Cache](#page-cache)
  - [Adding pages to the cache](#adding-pages-to-the-cache)
- [FAISS Index](#faiss-index)
- [Git Hook](#git-hook)
- [Verbose / Debug Mode](#verbose--debug-mode)
<!-- cortex:toc:end -->

Codebase Cortex stores all per-repo configuration in a `.cortex/` directory inside your project repository. This directory is automatically gitignored.

## Setup

Run `cortex init` inside your project repository to create the configuration:

```bash
cd /path/to/your-project
cortex init
```

The interactive wizard guides you through model selection, API key entry, and documentation output configuration. Notion authorization is optional and only triggered if you choose `notion` as your documentation output target.

## Directory Structure

```
your-project/
├── .cortex/                        # Created by cortex init
│   ├── .env                        # Configuration and API keys
│   ├── .gitignore                  # Ignores everything in .cortex/
│   ├── .cortexignore               # User-defined FAISS indexing exclusions
│   ├── notion_tokens.json          # OAuth tokens (if using Notion backend)
│   ├── page_cache.json             # Tracked Notion page metadata
│   ├── debug.log                   # Debug log (when --verbose is used)
│   ├── hook.log                    # Git hook output log
│   ├── proposed/                   # Proposed doc changes (propose mode)
│   └── faiss_index/                # Vector embeddings
│       ├── index.faiss             # FAISS binary index
│       ├── chunks.json             # Chunk metadata
│       ├── id_map.json             # Chunk ID to index mapping
│       └── file_hashes.json        # File hash manifest for incremental rebuilds
├── docs/                           # Local documentation output (default)
│   ├── INDEX.md                    # Documentation index
│   └── .cortex-meta.json           # Documentation metadata
```

## Environment Variables

All configuration is stored in `.cortex/.env`. The `cortex init` wizard creates this file.

### Required

| Variable | Description | Example |
|----------|-------------|---------|
| `LLM_MODEL` | Model in provider/model format (LiteLLM) | `gemini/gemini-2.5-flash-lite` |

### API Keys

One API key is required for cloud providers. Local models (Ollama, vLLM, etc.) need no key.

| Variable | Provider | Description |
|----------|----------|-------------|
| `GOOGLE_API_KEY` | Google Gemini | Google AI / Gemini API key |
| `ANTHROPIC_API_KEY` | Anthropic | Anthropic API key |
| `OPENROUTER_API_KEY` | OpenRouter | OpenRouter API key |
| `OPENAI_API_KEY` | OpenAI | OpenAI API key |
| `LLM_API_KEY` | Any | Explicit key passthrough (overrides provider-specific vars) |
| `LLM_API_BASE` | Any | Custom API base URL (for local/self-hosted models) |

### Documentation Output

| Variable | Description | Default |
|----------|-------------|---------|
| `DOC_OUTPUT` | Documentation target | `local` |
| `DOC_DETAIL_LEVEL` | Level of detail in generated docs | `standard` |
| `DOC_STRATEGY` | Branching strategy | `main-only` |
| `DOC_OUTPUT_MODE` | How changes are applied | `apply` |
| `DOC_SCOPE` | Scope of documentation generation | — |

**`DOC_OUTPUT`** values:
- `local` — Write markdown files to the `docs/` directory (default)
- `notion` — Sync documentation to Notion via MCP

**`DOC_DETAIL_LEVEL`** values:
- `standard` — Concise documentation covering key points
- `detailed` — Expanded documentation with more context
- `comprehensive` — Full documentation with examples and edge cases

**`DOC_STRATEGY`** values:
- `main-only` — Only track changes on the main branch (default)
- `branch-aware` — Track changes across branches

**`DOC_OUTPUT_MODE`** values:
- `apply` — Write changes directly to the output target (default)
- `propose` — Write proposed changes to `.cortex/proposed/` for review
- `dry-run` — Show what would change without writing anything

### Optional

| Variable | Description | Default |
|----------|-------------|---------|
| `GITHUB_TOKEN` | GitHub PAT (only for private remote repos) | — |

## LLM Configuration

### Model name format

Cortex uses LiteLLM for model routing. Model names follow the `provider/model` format:

```
provider/model-name
```

There is no separate `LLM_PROVIDER` variable. The provider is parsed from the model name.

### Google Gemini

```env
LLM_MODEL=gemini/gemini-2.5-flash-lite
GOOGLE_API_KEY=your-key-here
```

**Recommended models:**

| Model | Speed | Quality | Cost |
|-------|-------|---------|------|
| `gemini/gemini-2.5-flash-lite` | Fast | Good | Low |
| `gemini/gemini-3-flash-preview` | Fast | Better | Low |
| `gemini/gemini-2.5-pro` | Slower | Best | Higher |

### Anthropic

```env
LLM_MODEL=anthropic/claude-sonnet-4-20250514
ANTHROPIC_API_KEY=your-key-here
```

**Recommended models:**

| Model | Speed | Quality | Cost |
|-------|-------|---------|------|
| `anthropic/claude-sonnet-4-20250514` | Medium | High | Medium |
| `anthropic/claude-haiku-4-5-20251001` | Fast | Good | Low |

### OpenRouter

```env
LLM_MODEL=openrouter/google/gemini-2.5-flash-lite
OPENROUTER_API_KEY=your-key-here
```

OpenRouter provides access to many models from a single API key. Any model available on OpenRouter can be used -- provide the full model path after `openrouter/`.

### Local Models (Ollama, vLLM, LM Studio)

Cortex works with locally-deployed models via LiteLLM. No API key is needed.

**Ollama:**
```env
LLM_MODEL=ollama/llama3
# Ollama runs on localhost:11434 by default
```

**vLLM:**
```env
LLM_MODEL=hosted_vllm/my-model
LLM_API_BASE=http://localhost:8000
```

**LM Studio:**
```env
LLM_MODEL=lm_studio/my-model
LLM_API_BASE=http://localhost:1234/v1
```

**Any OpenAI-compatible endpoint:**
```env
LLM_MODEL=openai/my-model
LLM_API_BASE=http://localhost:8080/v1
LLM_API_KEY=not-needed
```

See the [LiteLLM provider docs](https://docs.litellm.ai/docs/providers) for the full list of 100+ supported providers.

### Per-node model overrides

Individual pipeline nodes can use different models via `get_model_for_node()`. This allows cost optimization by using cheaper models for simpler tasks (e.g., TOC generation) and more capable models for complex tasks (e.g., doc writing). Node-specific model configuration is handled internally by the pipeline.

## .cortexignore

The `.cortexignore` file (located at `.cortex/.cortexignore`) controls which files are excluded from FAISS indexing. It uses gitignore-style patterns:

```
# Exclude generated documentation to prevent circular indexing
docs/

# Exclude vendored code
vendor/
third_party/

# Exclude specific file patterns
*.generated.*
*.min.js
```

When `cortex init` creates the `.cortexignore` file, it seeds it with `docs/` to prevent circular indexing of generated documentation.

Patterns in `.cortexignore` are applied in addition to the built-in exclusion list (`.git`, `node_modules`, `__pycache__`, etc.).

## Notion OAuth Tokens

OAuth tokens are stored in `.cortex/notion_tokens.json` (only present when using Notion as output target):

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
- Token refresh is handled transparently -- you don't need to re-authorize

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

- **`content_hash`** -- MD5 hash of the last content written (used for first-run detection)
- **`last_synced`** -- Unix timestamp of last sync

The cache is automatically populated during `cortex init` (when using Notion output) and updated whenever pages are written.

### Adding pages to the cache

```bash
# Discover pages via search
cortex scan

# Link a specific page by ID
cortex scan --link "page-uuid"
```

## FAISS Index

The FAISS index is stored in `.cortex/faiss_index/`:

- **`index.faiss`** -- Binary FAISS IndexIDMap(IndexFlatL2) for ID-based operations
- **`chunks.json`** -- Metadata for each indexed chunk
- **`id_map.json`** -- Chunk ID to FAISS index mapping
- **`file_hashes.json`** -- File hash manifest for incremental rebuilds

The index supports incremental updates -- only added or modified files are re-embedded, and chunks for deleted files are removed. You can manually rebuild with:

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
