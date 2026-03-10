# CI/CD Integration


<!-- cortex:toc -->
- [Overview](#overview)
- [The `cortex ci` Command](#the-cortex-ci-command)
  - [PR impact analysis](#pr-impact-analysis)
  - [Post-merge doc updates](#post-merge-doc-updates)
  - [JSON output format](#json-output-format)
- [GitHub Actions](#github-actions)
  - [Full workflow](#full-workflow)
  - [PR comment example](#pr-comment-example)
- [GitLab CI](#gitlab-ci)
- [Branch Strategies](#branch-strategies)
  - [main-only (default)](#main-only-default)
  - [branch-aware](#branch-aware)
- [Environment Setup](#environment-setup)
  - [Required secrets](#required-secrets)
  - [Using local models in CI](#using-local-models-in-ci)
- [Output Modes in CI](#output-modes-in-ci)
- [Monorepo Support](#monorepo-support)
- [Troubleshooting](#troubleshooting)
<!-- cortex:toc:end -->

## Overview

Cortex integrates with CI/CD pipelines to automate documentation updates. The `cortex ci` command is designed for unattended use — it outputs structured JSON that downstream pipeline steps can parse and act on.

Two primary workflows:

1. **On pull request** — Analyze the PR diff and report which docs would be affected (dry-run)
2. **On merge to main** — Generate and commit doc updates automatically

## The `cortex ci` Command

```bash
cortex ci [--on-pr] [--on-merge] [--auto-apply] [--dry-run]
```

The command auto-detects the CI provider from environment variables:
- **GitHub Actions**: Reads `GITHUB_ACTIONS`, `GITHUB_SHA`, `GITHUB_BASE_REF`, `GITHUB_EVENT_NAME`, `GITHUB_PR_NUMBER`, `GITHUB_REPOSITORY`
- **GitLab CI**: Reads `GITLAB_CI`, `CI_COMMIT_SHA`, `CI_MERGE_REQUEST_TARGET_BRANCH_NAME`, `CI_MERGE_REQUEST_IID`

### PR impact analysis

```bash
cortex ci --on-pr
```

Runs the full pipeline in **dry-run mode**. No files are written. The JSON output tells you which documentation pages would be created or updated by this PR. Use this to post informative comments on PRs so reviewers know the doc impact.

### Post-merge doc updates

```bash
# Stage changes for review (propose mode)
cortex ci --on-merge

# Write changes directly to docs/
cortex ci --on-merge --auto-apply
```

Runs after code is merged to the main branch. By default, changes are written to `.cortex/proposed/` (propose mode). With `--auto-apply`, changes go directly to `docs/`.

### JSON output format

All `cortex ci` invocations output structured JSON to stdout:

```json
{
  "analysis": "Added new WebhookManager class with delivery retry logic...",
  "doc_updates": [
    {
      "page": "architecture-overview.md",
      "action": "update",
      "sections": ["## Webhook System", "## API Layer"]
    },
    {
      "page": "api-reference.md",
      "action": "create"
    }
  ],
  "tasks_created": [
    {
      "title": "Document webhook retry configuration",
      "priority": "medium"
    }
  ],
  "errors": [],
  "ci_context": {
    "provider": "github",
    "sha": "abc123def456",
    "base_ref": "main",
    "event": "pull_request",
    "pr_number": "42",
    "repo": "owner/repo"
  }
}
```

Fields:
- **`analysis`** — Human-readable summary of what changed
- **`doc_updates`** — List of pages that were (or would be) created/updated
- **`tasks_created`** — Documentation tasks identified by the pipeline
- **`errors`** — Any errors encountered during the run
- **`ci_context`** — Detected CI provider and environment metadata

## GitHub Actions

### Full workflow

This workflow runs Cortex on PRs (impact analysis + comment) and on merge to main (auto-update docs):

```yaml
name: Cortex Doc Sync
on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

permissions:
  contents: write
  pull-requests: write

jobs:
  docs:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 2  # Need parent commit for diff

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install Cortex
        run: pip install codebase-cortex

      - name: Initialize Cortex
        env:
          GOOGLE_API_KEY: ${{ secrets.GOOGLE_API_KEY }}
        run: cortex init --quick

      - name: PR impact analysis
        if: github.event_name == 'pull_request'
        env:
          GOOGLE_API_KEY: ${{ secrets.GOOGLE_API_KEY }}
        run: cortex ci --on-pr > cortex-output.json

      - name: Comment on PR
        if: github.event_name == 'pull_request'
        uses: actions/github-script@v7
        with:
          script: |
            const fs = require('fs');
            const output = JSON.parse(fs.readFileSync('cortex-output.json', 'utf8'));
            if (output.doc_updates.length > 0) {
              const pages = output.doc_updates
                .map(u => `- **${u.page}**: ${u.action}`)
                .join('\n');
              await github.rest.issues.createComment({
                owner: context.repo.owner,
                repo: context.repo.repo,
                issue_number: context.issue.number,
                body: `## 📝 Documentation Impact\n\n${pages}\n\n<details>\n<summary>Full analysis</summary>\n\n${output.analysis}\n</details>`
              });
            }

      - name: Update docs on merge
        if: github.event_name == 'push'
        env:
          GOOGLE_API_KEY: ${{ secrets.GOOGLE_API_KEY }}
        run: cortex ci --on-merge --auto-apply

      - name: Commit doc updates
        if: github.event_name == 'push'
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add docs/
          git diff --cached --quiet || git commit -m "docs: auto-update from Cortex"
          git push
```

### PR comment example

When the workflow runs on a PR, it posts a comment like:

> ## Documentation Impact
>
> - **architecture-overview.md**: update
> - **api-reference.md**: create
>
> <details>
> <summary>Full analysis</summary>
>
> Added new WebhookManager class with delivery retry logic. The architecture overview needs updating to reflect the new webhook subsystem. A new API reference page should be created for the webhook endpoints.
> </details>

## GitLab CI

```yaml
stages:
  - docs

cortex-docs:
  stage: docs
  image: python:3.11
  before_script:
    - pip install codebase-cortex
    - cortex init --quick
  script:
    - |
      if [ -n "$CI_MERGE_REQUEST_IID" ]; then
        cortex ci --on-pr
      else
        cortex ci --on-merge --auto-apply
        git config user.name "GitLab CI"
        git config user.email "ci@gitlab.com"
        git add docs/
        git diff --cached --quiet || git commit -m "docs: auto-update from Cortex"
        git push "https://gitlab-ci-token:${CI_JOB_TOKEN}@${CI_SERVER_HOST}/${CI_PROJECT_PATH}.git" HEAD:${CI_COMMIT_REF_NAME}
      fi
  rules:
    - if: $CI_MERGE_REQUEST_IID
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
  variables:
    GOOGLE_API_KEY: $GOOGLE_API_KEY
```

For merge request comments in GitLab, parse the JSON output and use the GitLab API:

```yaml
  after_script:
    - |
      if [ -n "$CI_MERGE_REQUEST_IID" ] && [ -f cortex-output.json ]; then
        BODY=$(python3 -c "
      import json
      data = json.load(open('cortex-output.json'))
      if data['doc_updates']:
          pages = '\n'.join(f'- **{u[\"page\"]}**: {u[\"action\"]}' for u in data['doc_updates'])
          print(f'## Documentation Impact\n\n{pages}')
      ")
        if [ -n "$BODY" ]; then
          curl --request POST \
            --header "PRIVATE-TOKEN: ${GITLAB_API_TOKEN}" \
            "${CI_API_V4_URL}/projects/${CI_PROJECT_ID}/merge_requests/${CI_MERGE_REQUEST_IID}/notes" \
            --data-urlencode "body=$BODY"
        fi
      fi
```

## Branch Strategies

Configure in `.cortex/.env` via `DOC_STRATEGY`:

### main-only (default)

```env
DOC_STRATEGY=main-only
```

- Only processes commits on the main/default branch
- Non-main branches are skipped (no doc changes)
- Best for most teams — docs only update when code lands on main

### branch-aware

```env
DOC_STRATEGY=branch-aware
```

- Processes commits on all branches
- Useful for feature branches with their own documentation needs
- Branch name is included in CI context for conditional logic

## Environment Setup

### Required secrets

Add these to your CI provider's secret storage:

| Secret | When needed |
|--------|-------------|
| `GOOGLE_API_KEY` | Using Google Gemini models |
| `ANTHROPIC_API_KEY` | Using Anthropic models |
| `OPENROUTER_API_KEY` | Using OpenRouter |
| `OPENAI_API_KEY` | Using OpenAI models |
| `GITHUB_TOKEN` | Auto-provided by GitHub Actions (for PR comments) |

Only one LLM API key is needed, matching whatever model you configure.

### Using local models in CI

If you run a self-hosted LLM (vLLM, Ollama, etc.), point Cortex at it:

```yaml
env:
  LLM_MODEL: hosted_vllm/my-model
  LLM_API_BASE: http://your-gpu-server:8000
```

No API key is needed for local models. The CI runner must have network access to the model endpoint.

## Output Modes in CI

| Mode | Flag | Behavior |
|------|------|----------|
| Dry-run | `--on-pr` or `--dry-run` | Analyze only, write nothing |
| Propose | `--on-merge` | Write to `.cortex/proposed/` |
| Apply | `--on-merge --auto-apply` | Write directly to `docs/` |

For most teams, `--on-merge --auto-apply` with an auto-commit step is the simplest setup. If you want human review before doc changes land, use `--on-merge` (propose mode) and add a separate approval step.

## Monorepo Support

For monorepos, set `DOC_SCOPE` in `.cortex/.env` to limit analysis to a subdirectory:

```env
DOC_SCOPE=packages/api
```

Cortex will only analyze diffs within that scope. Each package can have its own `.cortex/` configuration and `docs/` output.

## Troubleshooting

**"Not initialized" error in CI:**
Add `cortex init --quick` before running `cortex ci`. The `--quick` flag auto-detects API keys from environment variables.

**Empty doc_updates in PR analysis:**
The PR may not touch any code that maps to existing documentation. Check that the base branch has been fetched (`fetch-depth: 2` in checkout).

**Large LLM costs in CI:**
Use a fast, inexpensive model for CI runs. Configure in `.cortex/.env`:
```env
LLM_MODEL=gemini/gemini-2.5-flash-lite
```
Or use a locally-deployed model to eliminate API costs entirely.

**Permission errors when committing:**
Ensure the workflow has `contents: write` permission (GitHub Actions) or the CI token has push access (GitLab).
