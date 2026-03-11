"""CLI commands for Codebase Cortex."""

from __future__ import annotations

import asyncio
import secrets
import time
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel

from codebase_cortex.config import Settings, CORTEX_DIR_NAME

console = Console()


# ---------------------------------------------------------------------------
# Service connection helpers — standard pattern for OAuth-based integrations
# ---------------------------------------------------------------------------
# Each service (Notion, Confluence, etc.) follows the same pattern:
#   1. Check if tokens exist → if yes, already connected
#   2. If not, run interactive OAuth flow
#   3. Both `cortex init` and `cortex sync` use this helper
#
# To add a new service:
#   1. Add a _connect_<service>(settings) function
#   2. Add the service to SERVICE_CONNECTORS
#   3. Add it as a choice in `cortex sync --target`


def _set_env_value(env_path: Path, key: str, value: str) -> None:
    """Set a key=value in the .cortex/.env file."""
    key = key.upper()
    if env_path.exists():
        lines = env_path.read_text().splitlines()
    else:
        lines = []

    updated = False
    new_lines = []
    for line in lines:
        if line.strip().startswith(f"{key}="):
            new_lines.append(f"{key}={value}")
            updated = True
        else:
            new_lines.append(line)
    if not updated:
        new_lines.append(f"{key}={value}")

    env_path.write_text("\n".join(new_lines) + "\n")


def _connect_notion(settings: Settings) -> bool:
    """Connect to Notion via OAuth. Returns True if connected."""
    if settings.notion_token_path.exists():
        console.print("[green]Notion already connected.[/green]")
        return True

    console.print("[bold]Connecting to Notion...[/bold]")
    console.print("A browser window will open for Notion authorization.\n")
    try:
        asyncio.run(_run_oauth(settings.repo_path))
        console.print("[green]Notion connected![/green]")
        return True
    except Exception as e:
        console.print(f"[red]Notion OAuth failed: {e}[/red]")
        console.print("You can retry later with: [cyan]cortex sync --target notion[/cyan]")
        return False


SERVICE_CONNECTORS: dict[str, callable] = {
    "notion": _connect_notion,
    # Future: "confluence": _connect_confluence,
}


def _ensure_service_connected(settings: Settings, service: str) -> bool:
    """Ensure a service is connected, running OAuth if needed.

    This is the standard entry point for service auth. Both `init` and
    `sync` call this — so there's one path for each integration.
    """
    connector = SERVICE_CONNECTORS.get(service)
    if not connector:
        console.print(f"[red]Unknown service: {service}[/red]")
        return False
    return connector(settings)


@click.group()
@click.version_option(package_name="codebase-cortex")
def cli() -> None:
    """Codebase Cortex - Keep engineering docs in sync with code."""
    pass


@cli.command()
@click.option("--quick", is_flag=True, help="Fast-path setup: auto-detect LLM, skip wizard.")
def init(quick: bool) -> None:
    """Interactive setup wizard. Run this inside your project repo."""
    cwd = Path.cwd()

    if quick:
        _init_quick(cwd)
        return

    console.print(Panel(f"Codebase Cortex Setup — {cwd.name}", style="bold blue"))

    # Check if already initialized
    cortex_dir = cwd / CORTEX_DIR_NAME
    if cortex_dir.exists():
        if not click.confirm(f"{CORTEX_DIR_NAME}/ already exists. Re-initialize?", default=False):
            return

    # Step 1: LLM model (LiteLLM provider/model format)
    from codebase_cortex.config import RECOMMENDED_MODELS

    console.print("\n[bold]LLM Model (LiteLLM format: provider/model)[/bold]")
    console.print("  Examples: google/gemini-2.5-flash-lite, anthropic/claude-sonnet-4-20250514")
    console.print("  See: https://docs.litellm.ai/docs/providers")

    all_models = [m for models in RECOMMENDED_MODELS.values() for m in models]
    console.print("\n[bold]Recommended models:[/bold]")
    for i, m in enumerate(all_models, 1):
        console.print(f"  {i}. {m}")
    console.print(f"  {len(all_models) + 1}. Custom model name")

    model_choice = click.prompt(
        "Choose model",
        type=click.IntRange(1, len(all_models) + 1),
        default=1,
    )
    if model_choice <= len(all_models):
        llm_model = all_models[model_choice - 1]
    else:
        llm_model = click.prompt("Model name (provider/model)")

    console.print(f"[green]Model:[/green] {llm_model}")

    # Step 1b: API key (LiteLLM reads standard env vars, but we store as LLM_API_KEY too)
    api_key = click.prompt("API key", hide_input=True)

    # Step 2: Documentation config
    doc_output = click.prompt(
        "Documentation backend",
        type=click.Choice(["local", "notion"]),
        default="local",
    )

    detail_level = click.prompt(
        "Detail level",
        type=click.Choice(["standard", "detailed", "comprehensive"]),
        default="standard",
    )

    # Model quality recommendation
    _show_model_recommendation(llm_model, detail_level)

    branch_strategy = click.prompt(
        "Branch strategy",
        type=click.Choice(["main-only", "branch-aware"]),
        default="main-only",
    )

    # Step 3: GitHub token (optional)
    github_token = ""
    if click.confirm("Add a GitHub token? (only needed for private repos)", default=False):
        import subprocess

        try:
            result = subprocess.run(
                ["gh", "auth", "token"],
                capture_output=True,
                text=True,
                check=True,
            )
            github_token = result.stdout.strip()
            console.print("[green]GitHub token obtained from gh CLI[/green]")
        except (subprocess.CalledProcessError, FileNotFoundError):
            github_token = click.prompt("GitHub Personal Access Token", hide_input=True)

    # Step 4: Create .cortex/ directory and docs/
    cortex_dir.mkdir(exist_ok=True)

    # Write .cortex/.env — LiteLLM format
    # LiteLLM reads provider-specific env vars automatically (GOOGLE_API_KEY, etc.)
    # We also store as LLM_API_KEY for explicit passthrough
    provider = llm_model.split("/")[0] if "/" in llm_model else ""
    provider_key_map = {"gemini": "GEMINI_API_KEY", "google": "GOOGLE_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "openrouter": "OPENROUTER_API_KEY"}
    provider_key_name = provider_key_map.get(provider, "")

    env_lines = [
        f"LLM_MODEL={llm_model}",
        f"LLM_API_KEY={api_key}",
    ]
    if provider_key_name:
        env_lines.append(f"{provider_key_name}={api_key}")
    env_lines.extend([
        f"DOC_OUTPUT={doc_output}",
        f"DOC_DETAIL_LEVEL={detail_level}",
        f"DOC_STRATEGY={branch_strategy}",
        "DOC_OUTPUT_MODE=apply",
    ])
    if github_token:
        env_lines.append(f"GITHUB_TOKEN={github_token}")

    env_path = cortex_dir / ".env"
    env_path.write_text("\n".join(env_lines) + "\n")

    # Write .cortex/.gitignore (ignore everything inside)
    (cortex_dir / ".gitignore").write_text("*\n")

    # Create default .cortexignore
    _init_cortexignore(cortex_dir)

    # Create docs/ directory with initial files
    _init_docs_directory(cwd)

    # Add .cortex/ to repo's .gitignore if not already there
    repo_gitignore = cwd / ".gitignore"
    if repo_gitignore.exists():
        content = repo_gitignore.read_text()
        if CORTEX_DIR_NAME not in content:
            with open(repo_gitignore, "a") as f:
                f.write(f"\n# Codebase Cortex\n{CORTEX_DIR_NAME}/\n")
    else:
        repo_gitignore.write_text(f"# Codebase Cortex\n{CORTEX_DIR_NAME}/\n")

    console.print(f"[green]Created {cortex_dir}/ with config[/green]")

    # Step 5: Git hook
    git_dir = cwd / ".git"
    if git_dir.is_dir():
        if click.confirm("Auto-run Cortex after each git commit?", default=True):
            mode = click.prompt(
                "Hook mode",
                type=click.Choice(["full", "dry-run"]),
                default="full",
            )
            _install_git_hook(git_dir, mode)
    else:
        console.print("[yellow]Not a git repo — skipping git hook setup.[/yellow]")

    # Step 6: Remote sync (optional)
    settings = Settings.from_env(cwd)
    if doc_output == "notion" or click.confirm("Sync to Notion? (optional)", default=False):
        console.print()
        if _ensure_service_connected(settings, "notion"):
            console.print("\n[bold]Setting up Notion workspace...[/bold]")
            try:
                pages = asyncio.run(_bootstrap_pages(cwd))
                if pages:
                    console.print(f"[green]Created {len(pages)} pages in Notion[/green]")
                    for p in pages:
                        console.print(f"  - {p['title']}")
                else:
                    console.print("[yellow]No pages created (may already exist)[/yellow]")
            except Exception as e:
                console.print(f"[yellow]Page bootstrap skipped: {e}[/yellow]")

            # Ask about auto-sync
            if click.confirm("Auto-sync docs to Notion after every pipeline run?", default=True):
                _set_env_value(settings.env_path, "DOC_AUTO_SYNC", "true")
                _set_env_value(settings.env_path, "DOC_SYNC_TARGETS", "notion")
                console.print("[green]Auto-sync enabled.[/green]")

    console.print("\n[bold]Setup complete![/bold]")
    console.print("Run [cyan]cortex status[/cyan] to verify.")
    console.print("Run [cyan]cortex run --once[/cyan] to analyze your repo.")


def _init_quick(cwd: Path) -> None:
    """Fast-path init: auto-detect LLM, set defaults, create docs."""
    import os

    console.print(Panel(f"Codebase Cortex Quick Setup — {cwd.name}", style="bold blue"))
    cortex_dir = cwd / CORTEX_DIR_NAME
    cortex_dir.mkdir(exist_ok=True)

    env_lines = [
        "DOC_OUTPUT=local",
        "DOC_DETAIL_LEVEL=standard",
        "DOC_STRATEGY=main-only",
        "DOC_OUTPUT_MODE=apply",
    ]

    # Auto-detect API keys from environment
    if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        env_lines.append(f"LLM_API_KEY={api_key}")
        env_lines.append(f"GEMINI_API_KEY={api_key}")
        env_lines.append("LLM_MODEL=gemini/gemini-2.5-flash-lite")
        console.print("[green]Detected Google/Gemini API key[/green]")
    elif os.getenv("ANTHROPIC_API_KEY"):
        api_key = os.environ["ANTHROPIC_API_KEY"]
        env_lines.append(f"LLM_API_KEY={api_key}")
        env_lines.append(f"ANTHROPIC_API_KEY={api_key}")
        env_lines.append("LLM_MODEL=anthropic/claude-sonnet-4-20250514")
        console.print("[green]Detected ANTHROPIC_API_KEY[/green]")
    elif os.getenv("OPENROUTER_API_KEY"):
        api_key = os.environ["OPENROUTER_API_KEY"]
        env_lines.append(f"LLM_API_KEY={api_key}")
        env_lines.append(f"OPENROUTER_API_KEY={api_key}")
        env_lines.append("LLM_MODEL=openrouter/google/gemini-2.5-flash-lite")
        console.print("[green]Detected OPENROUTER_API_KEY[/green]")
    else:
        console.print("[yellow]No API key found in environment.[/yellow]")
        console.print("Set GOOGLE_API_KEY, ANTHROPIC_API_KEY, or OPENROUTER_API_KEY")
        console.print("Then run [cyan]cortex init --quick[/cyan] again.")
        return

    (cortex_dir / ".env").write_text("\n".join(env_lines) + "\n")
    (cortex_dir / ".gitignore").write_text("*\n")
    _init_cortexignore(cortex_dir)
    _init_docs_directory(cwd)

    # Add .cortex/ to .gitignore
    repo_gitignore = cwd / ".gitignore"
    if repo_gitignore.exists():
        content = repo_gitignore.read_text()
        if CORTEX_DIR_NAME not in content:
            with open(repo_gitignore, "a") as f:
                f.write(f"\n# Codebase Cortex\n{CORTEX_DIR_NAME}/\n")
    else:
        repo_gitignore.write_text(f"# Codebase Cortex\n{CORTEX_DIR_NAME}/\n")

    console.print(f"[green]Initialized {cortex_dir}/[/green]")
    console.print("[bold]Quick setup complete![/bold]")


DEFAULT_CORTEXIGNORE = """\
# .cortexignore — paths to exclude from FAISS indexing
# Works like .gitignore: one pattern per line, supports globs
# Directory patterns end with /

# Cortex-generated docs (avoid circular indexing)
docs/

# Common non-source directories
# vendor/
# generated/
# coverage/
"""


def _init_cortexignore(cortex_dir: Path) -> None:
    """Create a default .cortexignore if it doesn't exist."""
    ignore_path = cortex_dir / ".cortexignore"
    if not ignore_path.exists():
        ignore_path.write_text(DEFAULT_CORTEXIGNORE)


def _init_docs_directory(cwd: Path) -> None:
    """Create docs/ directory with initial INDEX.md and .cortex-meta.json."""
    import json

    docs_dir = cwd / "docs"
    docs_dir.mkdir(exist_ok=True)

    index_path = docs_dir / "INDEX.md"
    if not index_path.exists():
        index_path.write_text(
            f"# {cwd.name} Documentation\n\n"
            "<!-- cortex:toc -->\n"
            "*No pages yet. Run `cortex run --once --full` to generate docs.*\n"
            "<!-- /cortex:toc -->\n"
        )

    meta_path = docs_dir / ".cortex-meta.json"
    if not meta_path.exists():
        meta_path.write_text(json.dumps({"pages": {}, "run_metrics": {}}, indent=2))

    console.print(f"[green]Created docs/ with INDEX.md[/green]")


def _show_model_recommendation(llm_model: str, detail_level: str) -> None:
    """Show model quality recommendation for selected detail level."""
    model_lower = llm_model.lower()
    is_small_local = any(size in model_lower for size in ["7b", "8b", "3b", "1b"])

    if detail_level == "comprehensive" and is_small_local:
        console.print(
            f"\n[yellow]Note: Local small models may produce lower quality at "
            f"'{detail_level}' level. Consider using a larger model or 'detailed'.[/yellow]"
        )
    elif detail_level == "detailed" and is_small_local:
        console.print(
            f"\n[yellow]Note: '{detail_level}' works best with 30B+ or cloud models.[/yellow]"
        )


CORTEX_HOOK_MARKER = "# --- codebase-cortex post-commit hook ---"


def _install_git_hook(git_dir: Path, mode: str) -> None:
    """Install a post-commit git hook that runs Cortex automatically."""
    hooks_dir = git_dir / "hooks"
    hooks_dir.mkdir(exist_ok=True)
    hook_path = hooks_dir / "post-commit"

    dry_run_flag = " --dry-run" if mode == "dry-run" else ""
    hook_script = f"""{CORTEX_HOOK_MARKER}
# Runs Cortex in the background after each commit
if command -v cortex >/dev/null 2>&1; then
    cortex run --once --verbose{dry_run_flag} >> .cortex/hook.log 2>&1 &
fi
"""

    if hook_path.exists():
        existing = hook_path.read_text()
        if CORTEX_HOOK_MARKER in existing:
            console.print("[yellow]Git hook already installed — skipping.[/yellow]")
            return
        # Append to existing hook
        with open(hook_path, "a") as f:
            f.write("\n" + hook_script)
    else:
        hook_path.write_text("#!/bin/sh\n" + hook_script)

    hook_path.chmod(0o755)
    mode_label = "dry-run" if mode == "dry-run" else "full"
    console.print(f"[green]Installed post-commit hook ({mode_label} mode)[/green]")


async def _run_oauth(repo_path: Path) -> None:
    """Execute the OAuth flow: register client, open browser, wait for callback."""
    from codebase_cortex.auth.oauth import (
        generate_pkce_pair,
        fetch_oauth_metadata,
        register_client,
        build_authorization_url,
        exchange_code,
        open_browser,
    )
    from codebase_cortex.auth.callback_server import wait_for_callback
    from codebase_cortex.auth.token_store import TokenData, save_tokens

    settings = Settings.from_env(repo_path)
    port = settings.oauth_callback_port
    redirect_uri = f"http://localhost:{port}/callback"

    # Fetch server metadata
    metadata = await fetch_oauth_metadata()
    auth_endpoint = metadata.get("authorization_endpoint")
    token_endpoint = metadata.get("token_endpoint")
    registration_endpoint = metadata.get("registration_endpoint")

    # Dynamic client registration
    client_info = await register_client(redirect_uri, registration_endpoint=registration_endpoint)
    client_id = client_info["client_id"]
    client_secret = client_info["client_secret"]

    # PKCE
    verifier, challenge = generate_pkce_pair()
    state = secrets.token_urlsafe(32)

    # Open browser
    auth_url = build_authorization_url(
        client_id=client_id,
        redirect_uri=redirect_uri,
        code_challenge=challenge,
        state=state,
        authorization_endpoint=auth_endpoint,
    )
    open_browser(auth_url)

    # Wait for callback
    code, returned_state = await wait_for_callback(port=port)
    if returned_state != state:
        raise RuntimeError("OAuth state mismatch — possible CSRF attack")

    # Exchange code for tokens
    token_response = await exchange_code(
        code=code,
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        code_verifier=verifier,
        token_endpoint=token_endpoint,
    )

    # Save tokens
    token_data = TokenData(
        access_token=token_response["access_token"],
        refresh_token=token_response.get("refresh_token", ""),
        expires_at=time.time() + token_response.get("expires_in", 3600),
        client_id=client_id,
        client_secret=client_secret,
        token_endpoint=token_endpoint,
    )
    save_tokens(token_data, settings.notion_token_path)


async def _bootstrap_pages(repo_path: Path) -> list[dict]:
    """Create starter Notion pages for the repo."""
    from codebase_cortex.notion.bootstrap import bootstrap_notion_pages

    settings = Settings.from_env(repo_path)
    return await bootstrap_notion_pages(settings)


@cli.command()
@click.option("--once", is_flag=True, help="Run once and exit (no watch mode).")
@click.option("--watch", is_flag=True, help="Watch for changes and run continuously.")
@click.option("--dry-run", is_flag=True, help="Analyze without writing.")
@click.option("--full", is_flag=True, help="Analyze entire codebase (not just recent diff).")
@click.option("--detail", type=click.Choice(["standard", "detailed", "comprehensive"]), default=None, help="Override detail level for this run.")
@click.option("--propose", is_flag=True, help="Stage changes for review instead of applying.")
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging (LLM calls, MCP calls).")
def run(once: bool, watch: bool, dry_run: bool, full: bool, detail: str | None, propose: bool, verbose: bool) -> None:
    """Run the Cortex pipeline on the current repo."""
    from codebase_cortex.graph import compile_graph
    from codebase_cortex.utils.logging import setup_logging, get_logger

    if verbose:
        setup_logging(verbose=True)
    logger = get_logger()
    settings = Settings.from_env()

    if not settings.is_initialized:
        console.print("[red]Not initialized. Run 'cortex init' first.[/red]")
        return

    if not once and not watch:
        once = True  # Default to single run

    # Override settings per-run
    if detail:
        settings.doc_detail_level = detail
    if propose:
        settings.doc_output_mode = "propose"
    if dry_run:
        settings.doc_output_mode = "dry-run"

    # Auto-detect first run: check if docs/ is empty
    if not full:
        docs_dir = settings.repo_path / "docs"
        user_pages = [
            f for f in (docs_dir.glob("*.md") if docs_dir.exists() else [])
            if f.name not in ("INDEX.md",)
        ]
        if not docs_dir.exists() or not any(user_pages):
            console.print("[cyan]First run detected — doing full codebase scan[/cyan]")
            full = True

    graph = compile_graph()

    initial_state = {
        "trigger": "full_scan" if full else "manual",
        "repo_path": str(settings.repo_path),
        "dry_run": dry_run,
        "full_scan": full,
        "detail_level": settings.doc_detail_level,
        "output_mode": settings.doc_output_mode,
        "errors": [],
    }

    if full:
        console.print("[cyan]Full codebase analysis mode[/cyan]")
    if dry_run:
        console.print("[yellow]Dry run mode — no writes[/yellow]")
    if propose:
        console.print("[cyan]Propose mode — changes staged for review[/cyan]")

    async def _run_once():
        # Notion page discovery (only if using Notion backend)
        if settings.doc_output == "notion":
            from codebase_cortex.notion.bootstrap import discover_child_pages

            try:
                new_count = await discover_child_pages(settings)
                if new_count:
                    console.print(f"[green]Discovered {new_count} new page(s) in Notion[/green]")
            except Exception as e:
                logger.warning(f"Page discovery failed: {e}")

        result = await graph.ainvoke(initial_state)
        if result.get("errors"):
            for err in result["errors"]:
                logger.error(err)
        if result.get("analysis"):
            console.print(Panel(result["analysis"], title="Analysis", border_style="green"))
        else:
            console.print("[yellow]No analysis produced. Check if there are recent changes.[/yellow]")
            return

        if result.get("related_docs"):
            docs_text = "\n".join(
                f"- {d['title']} (similarity: {d['similarity']:.2f})"
                for d in result["related_docs"][:5]
            )
            console.print(Panel(docs_text, title="Related Docs", border_style="cyan"))

        if result.get("doc_updates"):
            updates_text = "\n".join(
                f"- {d['title']} ({d['action']})" for d in result["doc_updates"]
            )
            console.print(Panel(updates_text, title="Doc Updates", border_style="blue"))

        if result.get("tasks_created"):
            tasks_text = "\n".join(
                f"- [{t['priority']}] {t['title']}" for t in result["tasks_created"]
            )
            console.print(Panel(tasks_text, title="Tasks Created", border_style="yellow"))

        if result.get("sprint_summary"):
            console.print(Panel(result["sprint_summary"], title="Sprint Summary", border_style="magenta"))

    if once:
        asyncio.run(_run_once())
    elif watch:
        console.print("[cyan]Watch mode not yet implemented. Use --once.[/cyan]")


@cli.command()
def status() -> None:
    """Show connection status and workspace info."""
    import json

    settings = Settings.from_env()

    console.print(Panel(f"Codebase Cortex Status — {settings.repo_path.name}", style="bold blue"))

    if not settings.is_initialized:
        console.print(f"[red]Not initialized.[/red] Run 'cortex init' in this directory.")
        return

    # Configuration
    console.print(f"  [bold]Backend:[/bold]     {settings.doc_output}")
    console.print(f"  [bold]Detail:[/bold]      {settings.doc_detail_level}")
    console.print(f"  [bold]Strategy:[/bold]    {settings.doc_strategy}")
    console.print(f"  [bold]Output mode:[/bold] {settings.doc_output_mode}")
    console.print(f"  [bold]Model:[/bold]       {settings.llm_model}")

    # Local docs stats
    docs_dir = settings.repo_path / "docs"
    if docs_dir.is_dir():
        md_files = list(docs_dir.glob("*.md"))
        console.print(f"  [bold]Docs:[/bold]        {len(md_files)} pages in docs/")

        # Count sections from meta
        meta_path = docs_dir / ".cortex-meta.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text())
                total_sections = sum(
                    len(p.get("sections", []))
                    for p in meta.get("pages", {}).values()
                )
                human_edits = sum(
                    1 for p in meta.get("pages", {}).values()
                    for _heading, sec in p.get("sections", {}).items()
                    if sec.get("content_hash") and sec.get("cortex_hash")
                    and sec["content_hash"] != sec["cortex_hash"]
                )
                console.print(f"               {total_sections} sections tracked")
                if human_edits:
                    console.print(f"  [yellow]Human edits:[/yellow] {human_edits} sections modified since last Cortex run")

                # Run metrics
                metrics = meta.get("run_metrics", {})
                if metrics.get("last_run"):
                    console.print(f"  [bold]Last run:[/bold]    {metrics['last_run']}")
                if metrics.get("total_tokens"):
                    console.print(f"    Tokens:    {metrics['total_tokens']:,}")
            except (json.JSONDecodeError, KeyError):
                pass
    else:
        console.print("  [yellow]Docs:[/yellow]        Not created. Run 'cortex run --once --full'")

    # FAISS index
    if settings.faiss_index_dir.exists():
        console.print(f"  [green]Index:[/green]       {settings.faiss_index_dir}")
    else:
        console.print("  [yellow]Index:[/yellow]       Not built. Run 'cortex embed'")

    # Notion status
    token_path = settings.notion_token_path
    if token_path.exists():
        from codebase_cortex.auth.token_store import load_tokens

        token_data = load_tokens(token_path)
        if token_data and not token_data.is_expired:
            console.print("  [green]Notion:[/green]      Connected (token valid)")
        elif token_data:
            console.print("  [yellow]Notion:[/yellow]      Token expired (will auto-refresh)")
        else:
            console.print("  [red]Notion:[/red]      Token file corrupt")
    elif settings.doc_output == "notion":
        console.print("  [red]Notion:[/red]      Not connected. Run 'cortex init'")


async def _test_mcp(settings: Settings) -> None:
    """Test the MCP connection by listing available tools."""
    from codebase_cortex.mcp_client import notion_mcp_session

    async with notion_mcp_session(settings) as session:
        result = await session.list_tools()
        console.print(f"  Available tools: {len(result.tools)}")


@cli.command()
def analyze() -> None:
    """One-shot diff analysis without Notion writes."""
    from codebase_cortex.git.diff_parser import get_recent_diff
    from codebase_cortex.agents.code_analyzer import CodeAnalyzerAgent
    from codebase_cortex.config import get_llm

    settings = Settings.from_env()

    diff_text = get_recent_diff(str(settings.repo_path))
    if not diff_text:
        console.print("[yellow]No recent changes found.[/yellow]")
        return

    agent = CodeAnalyzerAgent(settings)
    state = {
        "trigger": "manual",
        "repo_path": str(settings.repo_path),
        "diff_text": diff_text,
        "detail_level": settings.doc_detail_level,
        "dry_run": True,
        "errors": [],
    }

    result = asyncio.run(agent.run(state))
    if result.get("analysis"):
        console.print(Panel(result["analysis"], title="Analysis", border_style="green"))


@cli.command()
@click.option("--incremental/--full", default=True, help="Incremental or full rebuild.")
def embed(incremental: bool) -> None:
    """Rebuild the embedding index for the current repo."""
    from codebase_cortex.embeddings.indexer import EmbeddingIndexer
    from codebase_cortex.embeddings.store import FAISSStore

    settings = Settings.from_env()
    repo_path = settings.repo_path
    index_dir = settings.faiss_index_dir

    indexer = EmbeddingIndexer(repo_path=repo_path)
    store = FAISSStore(index_dir=index_dir)

    if incremental and store.load():
        console.print(f"Incremental index update for [cyan]{repo_path}[/cyan]...")
        result = indexer.index_codebase_incremental(store)
        console.print(
            f"  +{result.files_added} added, "
            f"{result.files_modified} modified, "
            f"{result.files_removed} removed, "
            f"{result.chunks_re_embedded} chunks re-embedded"
        )
    else:
        console.print(f"Full index rebuild for [cyan]{repo_path}[/cyan]...")
        chunks = indexer.collect_chunks()
        console.print(f"Found [green]{len(chunks)}[/green] code chunks")

        if not chunks:
            console.print("[yellow]No indexable files found.[/yellow]")
            return

        console.print("Generating embeddings...")
        embeddings = indexer.embed_chunks(chunks)
        store.build(embeddings, chunks)

    store.save()
    console.print(f"Saved FAISS index with [green]{store.size}[/green] vectors to {index_dir}")


@cli.command()
@click.option("--query", default="", help="Search query to filter pages (default: scan all).")
@click.option("--link", multiple=True, help="Manually link a Notion page URL or ID to track.")
def scan(query: str, link: tuple[str, ...]) -> None:
    """Scan Notion workspace and link existing pages to Cortex.

    Use this when you have pre-existing documentation in Notion
    that you want Cortex to know about and update.

    Examples:
        cortex scan                         # Discover all pages
        cortex scan --query "API docs"      # Search for specific pages
        cortex scan --link <page-id>        # Link a specific page by ID
    """
    settings = Settings.from_env()

    if not settings.is_initialized:
        console.print("[red]Not initialized. Run 'cortex init' first.[/red]")
        return

    if link:
        asyncio.run(_link_pages(settings, list(link)))
    else:
        asyncio.run(_scan_workspace(settings, query))


async def _scan_workspace(settings: Settings, query: str) -> None:
    """Scan Notion workspace for existing pages and add them to cache."""
    from codebase_cortex.mcp_client import notion_mcp_session
    from codebase_cortex.notion.page_cache import PageCache
    from codebase_cortex.notion.bootstrap import extract_page_id
    import re

    cache = PageCache(cache_path=settings.page_cache_path)
    search_query = query or settings.repo_path.name

    console.print(f"Searching Notion for: [cyan]{search_query}[/cyan]")

    async with notion_mcp_session(settings) as session:
        result = await session.call_tool(
            "notion-search",
            arguments={"query": search_query},
        )

        if result.isError or not result.content:
            console.print("[yellow]No results found.[/yellow]")
            return

        response_text = result.content[0].text
        console.print(Panel(response_text[:2000], title="Search Results", border_style="cyan"))

        # Parse page IDs and titles from search results
        # Notion search returns markdown with page references
        uuid_pattern = r"[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}"
        found_ids = re.findall(uuid_pattern, response_text, re.IGNORECASE)

        if not found_ids:
            console.print("[yellow]No page IDs found in results.[/yellow]")
            return

        console.print(f"\nFound [green]{len(found_ids)}[/green] pages. Fetching details...")

        for page_id in found_ids[:20]:  # Limit to 20 pages
            try:
                fetch_result = await session.call_tool(
                    "notion-fetch",
                    arguments={"id": page_id},
                )
                if not fetch_result.isError and fetch_result.content:
                    page_text = fetch_result.content[0].text
                    # Extract title from first heading or first line
                    lines = page_text.strip().split("\n")
                    title = lines[0].lstrip("# ").strip() if lines else "Untitled"
                    # Clean up title
                    title = title.replace("**", "").strip()
                    if title:
                        cache.upsert(page_id, title)
                        console.print(f"  [green]Linked:[/green] {title} ({page_id[:8]}...)")
            except Exception as e:
                console.print(f"  [yellow]Failed to fetch {page_id[:8]}...: {e}[/yellow]")

    total = len(cache.pages)
    console.print(f"\n[bold]Cache now has {total} pages.[/bold]")
    console.print("Cortex will update these pages when relevant code changes are detected.")


@cli.command()
@click.argument("instruction")
@click.option("--page", "-p", multiple=True, help="Target page(s) to update. Repeatable. Auto-detects if omitted.")
@click.option("--dry-run", is_flag=True, help="Show planned changes without writing to Notion.")
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging.")
def prompt(instruction: str, page: tuple[str, ...], dry_run: bool, verbose: bool) -> None:
    """Send a natural language instruction to update Notion pages.

    Examples:
        cortex prompt "Make API docs more detailed with examples"
        cortex prompt "Add error handling section" --page "API Reference"
        cortex prompt "Update architecture diagram" -p "Architecture Overview" -p "API Reference"
    """
    from codebase_cortex.utils.logging import setup_logging

    if verbose:
        setup_logging(verbose=True)

    settings = Settings.from_env()
    if not settings.is_initialized:
        console.print("[red]Not initialized. Run 'cortex init' first.[/red]")
        return

    asyncio.run(_run_prompt(settings, instruction, list(page), dry_run))


async def _run_prompt(
    settings: Settings,
    instruction: str,
    page_filters: list[str],
    dry_run: bool,
) -> None:
    """Execute a user-directed prompt against specific Notion pages."""
    from codebase_cortex.backends.notion_backend import strip_notion_metadata
    from codebase_cortex.config import get_llm
    from codebase_cortex.mcp_client import notion_mcp_session, rate_limiter
    from codebase_cortex.notion.page_cache import PageCache
    from codebase_cortex.utils.json_parsing import parse_json_array
    from codebase_cortex.utils.section_parser import merge_sections, parse_sections

    cache = PageCache(cache_path=settings.page_cache_path)
    doc_pages = cache.find_all_doc_pages(parent_title=settings.repo_path.name)

    if not doc_pages:
        console.print("[red]No pages in cache. Run 'cortex run --once' first.[/red]")
        return

    # Resolve target pages
    if page_filters:
        targets = []
        for name in page_filters:
            found = cache.find_by_title(name)
            if found:
                targets.append(found)
            else:
                console.print(f"[yellow]Page not found: '{name}'[/yellow]")
                console.print("Available pages:")
                for p in doc_pages:
                    console.print(f"  - {p.title}")
                return
    else:
        targets = None  # LLM will auto-select

    # Fetch content of target pages (or all pages if auto-selecting)
    pages_to_fetch = targets if targets else doc_pages
    existing: dict[str, str] = {}

    console.print(f"Fetching {len(pages_to_fetch)} page(s) from Notion...")
    try:
        async with notion_mcp_session(settings) as session:
            for cp in pages_to_fetch:
                await rate_limiter.acquire()
                try:
                    result = await session.call_tool(
                        "notion-fetch",
                        arguments={"id": cp.page_id},
                    )
                    if not result.isError and result.content:
                        content = strip_notion_metadata(result.content[0].text)
                        existing[cp.title] = content
                except Exception as e:
                    console.print(f"[yellow]Could not fetch {cp.title}: {e}[/yellow]")
    except Exception as e:
        console.print(f"[red]Failed to connect to Notion: {e}[/red]")
        return

    if not existing:
        console.print("[red]No page content fetched.[/red]")
        return

    # Build LLM prompt
    page_contents = ""
    for title, content in existing.items():
        truncated = content[:4000] + ("..." if len(content) > 4000 else "")
        page_contents += f"\n### {title}\n```\n{truncated}\n```\n"

    page_list = "\n".join(f"- {t}" for t in existing.keys())

    if targets:
        scope_note = f"Update ONLY these pages: {', '.join(p.title for p in targets)}"
    else:
        scope_note = (
            "Choose which page(s) need updating based on the instruction. "
            "Only update pages that are relevant."
        )

    llm_prompt = f"""You are a technical documentation writer. A user wants to update their Notion documentation.

## User Instruction
{instruction}

## Scope
{scope_note}

## Current Page Contents
{page_contents}

## Available Pages
{page_list}

Generate updates as a JSON array. Each element has:
- "title": Exact page title (must match one of the available pages)
- "action": "update"
- "section_updates": Array of sections to change. Each has:
  - "heading": The exact markdown heading (e.g., "## API Endpoints")
  - "content": New content for that section
  - "action": "update" to replace existing section, or "create" to add new section

Only include sections that actually change. Unchanged sections are preserved automatically.
Respond with ONLY the JSON array."""

    # Call LLM
    from langchain_core.messages import HumanMessage, SystemMessage

    llm = get_llm(settings)
    console.print("Generating updates...")

    try:
        response = await llm.ainvoke([
            SystemMessage(content="You are a technical documentation writer. Output only valid JSON."),
            HumanMessage(content=llm_prompt),
        ])
        raw = response.content
        # Gemini 3 returns structured content blocks instead of plain strings
        if isinstance(raw, list):
            raw = "\n".join(
                part["text"] if isinstance(part, dict) else str(part)
                for part in raw
                if not isinstance(part, dict) or part.get("type") == "text"
            )
        updates_data = parse_json_array(raw)
    except Exception as e:
        console.print(f"[red]LLM call failed: {e}[/red]")
        return

    if not updates_data:
        console.print("[yellow]No updates suggested by LLM.[/yellow]")
        return

    # Build merged content and show summary
    planned: list[dict] = []
    for update in updates_data:
        title = update.get("title", "")
        if title not in existing:
            console.print(f"[yellow]Skipping unknown page: {title}[/yellow]")
            continue

        section_updates = update.get("section_updates", [])
        if not section_updates:
            continue

        existing_sections = parse_sections(existing[title])
        merged_content = merge_sections(existing_sections, section_updates)

        # Find page_id
        cached = cache.find_by_title(title)
        if not cached:
            continue

        planned.append({
            "page_id": cached.page_id,
            "title": title,
            "content": merged_content,
            "section_updates": section_updates,
        })

    if not planned:
        console.print("[yellow]No applicable updates.[/yellow]")
        return

    # Show summary
    console.print(Panel("[bold]Planned Changes[/bold]", border_style="blue"))
    for item in planned:
        sections_desc = ", ".join(
            f"{s.get('heading', '?')} ({s.get('action', 'update')})"
            for s in item["section_updates"]
        )
        console.print(f"  [cyan]{item['title']}[/cyan]: {sections_desc}")

    if dry_run:
        console.print("\n[yellow]Dry run — no changes written.[/yellow]")
        for item in planned:
            console.print(Panel(
                item["content"][:2000] + ("..." if len(item["content"]) > 2000 else ""),
                title=f"Preview: {item['title']}",
                border_style="dim",
            ))
        return

    # Confirmation
    if not click.confirm("\nApply these changes?", default=True):
        console.print("[yellow]Cancelled.[/yellow]")
        return

    # Write to Notion
    import hashlib

    try:
        async with notion_mcp_session(settings) as session:
            for item in planned:
                await rate_limiter.acquire()
                await session.call_tool(
                    "notion-update-page",
                    arguments={
                        "page_id": item["page_id"],
                        "command": "replace_content",
                        "new_str": item["content"],
                    },
                )
                content_hash = hashlib.md5(item["content"].encode()).hexdigest()[:8]
                cache.upsert(item["page_id"], item["title"], content_hash=content_hash)
                console.print(f"  [green]Updated:[/green] {item['title']}")
    except Exception as e:
        console.print(f"[red]Failed to write to Notion: {e}[/red]")
        return

    console.print(f"\n[bold green]Done! Updated {len(planned)} page(s).[/bold green]")


async def _link_pages(settings: Settings, page_ids: list[str]) -> None:
    """Manually link specific Notion pages by ID."""
    from codebase_cortex.mcp_client import notion_mcp_session
    from codebase_cortex.notion.page_cache import PageCache

    cache = PageCache(cache_path=settings.page_cache_path)

    async with notion_mcp_session(settings) as session:
        for page_id in page_ids:
            # Clean up the ID (remove URL prefix if pasted)
            clean_id = page_id.split("/")[-1].split("?")[0].split("-")[-1]
            if len(clean_id) == 32:
                # Add dashes to raw 32-char hex
                clean_id = f"{clean_id[:8]}-{clean_id[8:12]}-{clean_id[12:16]}-{clean_id[16:20]}-{clean_id[20:]}"

            try:
                result = await session.call_tool(
                    "notion-fetch",
                    arguments={"id": clean_id},
                )
                if not result.isError and result.content:
                    page_text = result.content[0].text
                    lines = page_text.strip().split("\n")
                    title = lines[0].lstrip("# ").strip() if lines else "Untitled"
                    title = title.replace("**", "").strip()
                    cache.upsert(clean_id, title)
                    console.print(f"[green]Linked:[/green] {title} ({clean_id[:8]}...)")
                else:
                    console.print(f"[red]Failed to fetch page {clean_id}[/red]")
            except Exception as e:
                console.print(f"[red]Error linking {clean_id}: {e}[/red]")


# --- New v0.2 commands ---


@cli.command()
@click.argument("action", type=click.Choice(["set", "show"]))
@click.argument("key", required=False)
@click.argument("value", required=False)
def config(action: str, key: str | None, value: str | None) -> None:
    """View or modify configuration.

    Examples:
        cortex config show
        cortex config set DOC_DETAIL_LEVEL comprehensive
        cortex config set LLM_MODEL anthropic/claude-sonnet-4-20250514
    """
    settings = Settings.from_env()

    if action == "show":
        if not settings.is_initialized:
            console.print("[red]Not initialized.[/red]")
            return
        content = settings.env_path.read_text()
        console.print(Panel(content, title=str(settings.env_path), border_style="cyan"))
        return

    # action == "set"
    if not key or value is None:
        console.print("[red]Usage: cortex config set KEY VALUE[/red]")
        return

    if not settings.is_initialized:
        console.print("[red]Not initialized. Run 'cortex init' first.[/red]")
        return

    _set_env_value(settings.env_path, key, value)
    console.print(f"[green]Set {key.upper()}={value}[/green]")


@cli.command()
def toc() -> None:
    """Rebuild TOC markers, INDEX.md, and .cortex-meta.json."""
    from codebase_cortex.agents.toc_generator import TOCGeneratorAgent

    settings = Settings.from_env()
    if not settings.is_initialized:
        console.print("[red]Not initialized. Run 'cortex init' first.[/red]")
        return

    agent = TOCGeneratorAgent(settings=settings)
    result = asyncio.run(agent.run({
        "repo_path": str(settings.repo_path),
        "doc_updates": [],
        "tasks_created": [],
        "errors": [],
    }))
    console.print("[green]TOC rebuilt.[/green]")
    if result.get("errors"):
        for err in result["errors"]:
            console.print(f"  [yellow]{err}[/yellow]")


@cli.command()
@click.option("--max-commits-behind", type=int, default=5, help="Staleness threshold.")
def check(max_commits_behind: int) -> None:
    """Check documentation freshness. Exit code 1 if stale (for CI)."""
    import json
    import subprocess
    import sys

    settings = Settings.from_env()
    if not settings.is_initialized:
        console.print("[red]Not initialized.[/red]")
        sys.exit(1)

    meta_path = settings.repo_path / "docs" / ".cortex-meta.json"
    if not meta_path.exists():
        console.print("[yellow]No .cortex-meta.json found. Run 'cortex run --once' first.[/yellow]")
        sys.exit(1)

    try:
        meta = json.loads(meta_path.read_text())
    except json.JSONDecodeError:
        console.print("[red]Corrupt .cortex-meta.json[/red]")
        sys.exit(1)

    source_commit = meta.get("last_run", {}).get("source_commit", "")
    if not source_commit:
        console.print("[yellow]No source_commit recorded. Docs may be stale.[/yellow]")
        sys.exit(1)

    # Count commits since source_commit
    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", f"{source_commit}..HEAD"],
            capture_output=True, text=True, check=True,
            cwd=str(settings.repo_path),
        )
        commits_behind = int(result.stdout.strip())
    except (subprocess.CalledProcessError, ValueError):
        console.print("[yellow]Could not determine commit distance.[/yellow]")
        sys.exit(1)

    if commits_behind > max_commits_behind:
        console.print(f"[red]Docs are {commits_behind} commits behind (threshold: {max_commits_behind})[/red]")
        sys.exit(1)
    elif commits_behind > 0:
        console.print(f"[yellow]Docs are {commits_behind} commits behind (within threshold)[/yellow]")
    else:
        console.print("[green]Docs are up to date.[/green]")


@cli.command()
def accept() -> None:
    """Remove draft banners from documentation pages."""
    import re

    settings = Settings.from_env()
    docs_dir = settings.repo_path / "docs"
    if not docs_dir.is_dir():
        console.print("[yellow]No docs/ directory found.[/yellow]")
        return

    draft_pattern = re.compile(
        r"> .+(?:Draft|DRAFT).+Codebase Cortex.+\n(?:> .+\n)*> .+cortex accept.+\n\n",
    )

    # Load meta index to update hashes after banner removal
    from codebase_cortex.backends.local_markdown import LocalMarkdownBackend

    backend = LocalMarkdownBackend(settings)

    count = 0
    for md_file in docs_dir.glob("*.md"):
        content = md_file.read_text()
        if "cortex accept" in content:
            cleaned = draft_pattern.sub("", content)
            if cleaned != content:
                md_file.write_text(cleaned)
                # Update meta hashes so sections aren't marked as human-edited
                backend._update_sections_meta(md_file.name, cleaned, cortex_written=True)
                count += 1
                console.print(f"  [green]Accepted:[/green] {md_file.name}")

    if count > 0:
        backend.meta.save()

    if count == 0:
        console.print("[green]No draft banners found.[/green]")
    else:
        console.print(f"\n[bold green]Accepted {count} page(s).[/bold green]")


@cli.command()
def diff() -> None:
    """Preview proposed changes (propose mode)."""
    import difflib

    settings = Settings.from_env()
    proposed_dir = settings.cortex_dir / "proposed"
    docs_dir = settings.repo_path / "docs"

    if not proposed_dir.is_dir() or not any(proposed_dir.iterdir()):
        console.print("[yellow]No proposed changes. Run 'cortex run --propose' first.[/yellow]")
        return

    for proposed_file in sorted(proposed_dir.glob("*.md")):
        current_file = docs_dir / proposed_file.name
        current_content = current_file.read_text().splitlines() if current_file.exists() else []
        proposed_content = proposed_file.read_text().splitlines()

        diff_lines = list(difflib.unified_diff(
            current_content, proposed_content,
            fromfile=f"docs/{proposed_file.name}",
            tofile=f"proposed/{proposed_file.name}",
            lineterm="",
        ))

        if diff_lines:
            colored = []
            for line in diff_lines:
                if line.startswith("+") and not line.startswith("+++"):
                    colored.append(f"[green]{line}[/green]")
                elif line.startswith("-") and not line.startswith("---"):
                    colored.append(f"[red]{line}[/red]")
                else:
                    colored.append(line)
            console.print(Panel("\n".join(colored), title=proposed_file.name, border_style="cyan"))
        else:
            console.print(f"  {proposed_file.name}: [dim]no changes[/dim]")


@cli.command()
def apply() -> None:
    """Apply proposed changes from propose mode."""
    import shutil

    settings = Settings.from_env()
    proposed_dir = settings.cortex_dir / "proposed"
    docs_dir = settings.repo_path / "docs"

    if not proposed_dir.is_dir() or not any(proposed_dir.iterdir()):
        console.print("[yellow]No proposed changes to apply.[/yellow]")
        return

    docs_dir.mkdir(exist_ok=True)

    from codebase_cortex.backends.local_markdown import LocalMarkdownBackend
    backend = LocalMarkdownBackend(settings)

    count = 0
    for proposed_file in sorted(proposed_dir.glob("*.md")):
        shutil.copy2(proposed_file, docs_dir / proposed_file.name)
        # Update meta hashes so sections aren't marked as human-edited
        content = (docs_dir / proposed_file.name).read_text()
        backend._update_sections_meta(proposed_file.name, content, cortex_written=True)
        count += 1
        console.print(f"  [green]Applied:[/green] {proposed_file.name}")

    if count > 0:
        backend.meta.save()

    # Clean up proposed/
    shutil.rmtree(proposed_dir)
    console.print(f"\n[bold green]Applied {count} file(s).[/bold green]")


@cli.command()
def discard() -> None:
    """Discard proposed changes without applying."""
    import shutil

    settings = Settings.from_env()
    proposed_dir = settings.cortex_dir / "proposed"

    if not proposed_dir.is_dir() or not any(proposed_dir.iterdir()):
        console.print("[yellow]No proposed changes to discard.[/yellow]")
        return

    count = len(list(proposed_dir.glob("*.md")))
    shutil.rmtree(proposed_dir)
    console.print(f"[green]Discarded {count} proposed file(s).[/green]")


@cli.command()
def map() -> None:
    """Generate a knowledge map from code embeddings."""
    from codebase_cortex.embeddings.store import FAISSStore
    from codebase_cortex.embeddings.clustering import TopicClusterer

    settings = Settings.from_env()
    store = FAISSStore(index_dir=settings.faiss_index_dir)

    if not store.load():
        console.print("[red]No FAISS index. Run 'cortex embed' first.[/red]")
        return

    if store.size == 0:
        console.print("[yellow]Index is empty.[/yellow]")
        return

    # Re-compute embeddings from stored chunks for clustering
    import numpy as np
    import faiss

    # Extract embeddings from the FAISS index
    if hasattr(store.index, "reconstruct_n"):
        embeddings = np.zeros((store.size, store.index.d), dtype=np.float32)
        for i in range(store.size):
            embeddings[i] = store.index.reconstruct(i)
    else:
        console.print("[yellow]Cannot extract embeddings from this index type.[/yellow]")
        return

    clusterer = TopicClusterer(min_cluster_size=3)
    topics = clusterer.cluster(embeddings, store.chunks)
    md = clusterer.to_markdown(topics)

    # Write knowledge map
    docs_dir = settings.repo_path / "docs"
    docs_dir.mkdir(exist_ok=True)
    map_path = docs_dir / "knowledge-map.md"
    map_path.write_text(md)
    console.print(f"[green]Knowledge map written to {map_path}[/green]")
    console.print(f"  {len(topics)} topic clusters found")


@cli.command()
def resolve() -> None:
    """Resolve git conflict markers in documentation files."""
    import re

    settings = Settings.from_env()
    docs_dir = settings.repo_path / "docs"

    if not docs_dir.is_dir():
        console.print("[yellow]No docs/ directory found.[/yellow]")
        return

    conflict_pattern = re.compile(
        r"<<<<<<<.*?\n(.*?)=======\n(.*?)>>>>>>>.*?\n",
        re.DOTALL,
    )

    count = 0
    for md_file in docs_dir.glob("*.md"):
        content = md_file.read_text()
        if "<<<<<<< " in content:
            # Keep the incoming (theirs) side of conflicts
            resolved = conflict_pattern.sub(r"\2", content)
            md_file.write_text(resolved)
            count += 1
            console.print(f"  [green]Resolved:[/green] {md_file.name}")

    if count == 0:
        console.print("[green]No conflict markers found.[/green]")
    else:
        console.print(f"\n[bold green]Resolved conflicts in {count} file(s).[/bold green]")
        console.print("Run [cyan]cortex run --once[/cyan] to regenerate affected sections.")


def _get_ci_context() -> dict:
    """Detect CI environment and extract context."""
    import os

    if os.environ.get("GITHUB_ACTIONS"):
        return {
            "provider": "github",
            "sha": os.environ.get("GITHUB_SHA", ""),
            "base_ref": os.environ.get("GITHUB_BASE_REF", "main"),
            "event": os.environ.get("GITHUB_EVENT_NAME", ""),
            "pr_number": os.environ.get("GITHUB_PR_NUMBER", ""),
            "repo": os.environ.get("GITHUB_REPOSITORY", ""),
        }
    if os.environ.get("GITLAB_CI"):
        return {
            "provider": "gitlab",
            "sha": os.environ.get("CI_COMMIT_SHA", ""),
            "base_ref": os.environ.get("CI_MERGE_REQUEST_TARGET_BRANCH_NAME", "main"),
            "event": "merge_request" if os.environ.get("CI_MERGE_REQUEST_IID") else "push",
        }
    return {"provider": "unknown", "sha": "", "base_ref": "main", "event": ""}


@cli.command()
@click.option("--on-pr", is_flag=True, help="Post doc impact comment on PR.")
@click.option("--on-merge", is_flag=True, help="Create doc update after merge.")
@click.option("--auto-apply", is_flag=True, help="Auto-apply instead of proposing.")
@click.option("--dry-run", is_flag=True, help="Preview only.")
def ci(on_pr: bool, on_merge: bool, auto_apply: bool, dry_run: bool) -> None:
    """CI/CD mode for automated documentation updates."""
    import json

    settings = Settings.from_env()
    if not settings.is_initialized:
        console.print("[red]Not initialized.[/red]")
        return

    ci_ctx = _get_ci_context()

    if on_pr:
        settings.doc_output_mode = "dry-run"
        console.print(f"[cyan]CI: PR impact analysis ({ci_ctx['provider']})[/cyan]")
    elif on_merge:
        if auto_apply:
            settings.doc_output_mode = "apply"
        else:
            settings.doc_output_mode = "propose"
        console.print(f"[cyan]CI: Post-merge doc update ({ci_ctx['provider']})[/cyan]")

    if dry_run:
        settings.doc_output_mode = "dry-run"

    from codebase_cortex.graph import compile_graph

    graph = compile_graph()
    initial_state = {
        "trigger": "ci",
        "repo_path": str(settings.repo_path),
        "dry_run": settings.doc_output_mode == "dry-run",
        "full_scan": False,
        "detail_level": settings.doc_detail_level,
        "output_mode": settings.doc_output_mode,
        "errors": [],
    }

    result = asyncio.run(graph.ainvoke(initial_state))

    # Output structured JSON for downstream CI steps
    output = {
        "analysis": result.get("analysis", ""),
        "doc_updates": result.get("doc_updates", []),
        "tasks_created": result.get("tasks_created", []),
        "errors": result.get("errors", []),
        "ci_context": ci_ctx,
    }
    console.print(json.dumps(output, indent=2))


@cli.command()
def migrate() -> None:
    """Migrate from Notion-only to local-first documentation.

    Fetches all existing Notion pages and converts them to local markdown files
    in docs/. Generates .cortex-meta.json and INDEX.md.
    """
    settings = Settings.from_env()

    if not settings.is_initialized:
        console.print("[red]Not initialized. Run 'cortex init' first.[/red]")
        return

    if not settings.notion_token_path.exists():
        console.print("[red]Notion not connected. Run 'cortex init' to connect.[/red]")
        return

    asyncio.run(_run_migration(settings))


async def _run_migration(settings: Settings) -> None:
    """Fetch Notion pages and create local docs."""
    import hashlib
    import json
    import re

    from codebase_cortex.backends.notion_backend import strip_notion_metadata
    from codebase_cortex.mcp_client import notion_mcp_session, rate_limiter
    from codebase_cortex.notion.page_cache import PageCache

    cache = PageCache(cache_path=settings.page_cache_path)
    doc_pages = cache.find_all_doc_pages(parent_title=settings.repo_path.name)

    if not doc_pages:
        console.print("[yellow]No pages in cache. Run 'cortex scan' first.[/yellow]")
        return

    docs_dir = settings.repo_path / "docs"
    docs_dir.mkdir(exist_ok=True)

    console.print(f"Migrating {len(doc_pages)} page(s) from Notion to docs/...")

    meta_pages: dict = {}

    try:
        async with notion_mcp_session(settings) as session:
            for cp in doc_pages:
                await rate_limiter.acquire()
                try:
                    result = await session.call_tool(
                        "notion-fetch",
                        arguments={"id": cp.page_id},
                    )
                    if result.isError or not result.content:
                        console.print(f"  [yellow]Skipped: {cp.title}[/yellow]")
                        continue

                    content = strip_notion_metadata(result.content[0].text)

                    # Slugify title for filename
                    slug = re.sub(r"[^\w\s-]", "", cp.title.lower())
                    slug = re.sub(r"[\s]+", "-", slug).strip("-")
                    filename = f"{slug}.md"

                    # Add TOC marker
                    if "<!-- cortex:toc -->" not in content:
                        content = content + "\n\n<!-- cortex:toc -->\n<!-- /cortex:toc -->\n"

                    (docs_dir / filename).write_text(content)
                    content_hash = hashlib.md5(content.encode()).hexdigest()

                    meta_pages[filename] = {
                        "title": cp.title,
                        "content_hash": content_hash,
                        "cortex_hash": content_hash,
                        "sections": {},
                    }

                    console.print(f"  [green]Migrated:[/green] {cp.title} → {filename}")
                except Exception as e:
                    console.print(f"  [yellow]Failed: {cp.title}: {e}[/yellow]")
    except Exception as e:
        console.print(f"[red]Notion connection failed: {e}[/red]")
        return

    # Write .cortex-meta.json
    meta = {"version": 2, "pages": meta_pages, "run_metrics": {}}
    (docs_dir / ".cortex-meta.json").write_text(json.dumps(meta, indent=2))

    # Generate INDEX.md
    index_lines = [f"# {settings.repo_path.name} Documentation", ""]
    index_lines.append("<!-- cortex:toc -->")
    index_lines.append("| Page | Description |")
    index_lines.append("|------|-------------|")
    for fname, info in sorted(meta_pages.items()):
        index_lines.append(f"| [{info['title']}]({fname}) | |")
    index_lines.append("<!-- /cortex:toc -->")
    (docs_dir / "INDEX.md").write_text("\n".join(index_lines) + "\n")

    console.print(f"\n[bold green]Migration complete! {len(meta_pages)} page(s) in docs/[/bold green]")

    if click.confirm("Keep syncing to Notion?", default=True):
        # Update .env with DOC_SYNC=notion
        env_path = settings.env_path
        content = env_path.read_text()
        if "DOC_SYNC=" not in content:
            env_path.write_text(content.rstrip() + "\nDOC_SYNC=notion\n")
        console.print("[green]Notion sync enabled.[/green]")

    console.print("[green]Set DOC_OUTPUT=local in .cortex/.env to use local docs.[/green]")


async def _run_sync_to_notion(settings: Settings) -> int:
    """Sync local docs/ to Notion. Returns number of pages synced.

    Extracted so it can be called from both `cortex sync` and auto-sync.
    """
    from codebase_cortex.mcp_client import notion_mcp_session
    from codebase_cortex.notion.bootstrap import (
        extract_page_id,
        search_page_by_title,
    )
    from codebase_cortex.notion.page_cache import PageCache
    from codebase_cortex.utils.rate_limiter import NotionRateLimiter

    docs_dir = settings.repo_path / "docs"
    md_files = [f for f in docs_dir.glob("*.md") if f.name not in ("INDEX.md",)]
    if not md_files:
        return 0

    rate_limiter = NotionRateLimiter()
    cache = PageCache(cache_path=settings.page_cache_path)
    repo_name = settings.repo_path.name

    async with notion_mcp_session(settings) as session:
        # Ensure parent page exists
        parent_id = None
        cached_parent = cache.find_by_title(repo_name)
        if cached_parent:
            parent_id = cached_parent.page_id
        else:
            parent_id = await search_page_by_title(session, repo_name)
            if parent_id:
                cache.upsert(parent_id, repo_name)
            else:
                await rate_limiter.acquire()
                result = await session.call_tool(
                    "notion-create-pages",
                    arguments={
                        "pages": [{
                            "properties": {"title": repo_name},
                            "content": (
                                f"# {repo_name}\n\n"
                                f"Documentation hub for **{repo_name}**.\n\n"
                                "Managed by [Codebase Cortex](https://github.com/sarupurisailalith/codebase-cortex)."
                            ),
                        }],
                    },
                )
                parent_id = extract_page_id(result)
                if parent_id:
                    cache.upsert(parent_id, repo_name)
                else:
                    return 0

        # Sync each doc as a child page
        synced = 0
        for md_file in md_files:
            title = None
            content = md_file.read_text()

            for line in content.split("\n"):
                if line.startswith("# "):
                    title = line[2:].strip()
                    break
            title = title or md_file.stem.replace("-", " ").title()

            existing = cache.find_by_title(title)
            try:
                await rate_limiter.acquire()
                if existing:
                    await session.call_tool(
                        "notion-update-page",
                        arguments={
                            "page_id": existing.page_id,
                            "command": "replace_content",
                            "new_str": content,
                        },
                    )
                else:
                    result = await session.call_tool(
                        "notion-create-pages",
                        arguments={
                            "parent": {"page_id": parent_id},
                            "pages": [{
                                "properties": {"title": title},
                                "content": content,
                            }],
                        },
                    )
                    page_id = extract_page_id(result)
                    if page_id:
                        cache.upsert(page_id, title)
                synced += 1
            except Exception:
                continue

        return synced


@cli.command()
@click.option("--target", type=click.Choice(["notion"]), required=True, help="Sync target.")
def sync(target: str) -> None:
    """Sync local docs to a remote platform."""
    settings = Settings.from_env()

    if target == "notion":
        if not _ensure_service_connected(settings, "notion"):
            return

        docs_dir = settings.repo_path / "docs"
        if not docs_dir.is_dir():
            console.print("[yellow]No docs/ directory to sync.[/yellow]")
            return

        md_files = [f for f in docs_dir.glob("*.md") if f.name not in ("INDEX.md",)]
        if not md_files:
            console.print("[yellow]No documentation pages to sync.[/yellow]")
            return

        console.print(f"Syncing {len(md_files)} page(s) to Notion...")

        try:
            synced = asyncio.run(_run_sync_to_notion(settings))
            console.print(f"\n[bold green]Synced {synced} page(s) to Notion.[/bold green]")

            # Offer to enable auto-sync if not already configured
            if not settings.doc_auto_sync:
                if click.confirm(
                    "Enable auto-sync after every pipeline run?", default=False
                ):
                    _set_env_value(settings.env_path, "DOC_AUTO_SYNC", "true")
                    _set_env_value(settings.env_path, "DOC_SYNC_TARGETS", target)
                    console.print(
                        "[green]Auto-sync enabled.[/green] "
                        "Run [cyan]cortex config set DOC_AUTO_SYNC false[/cyan] to disable."
                    )
        except Exception as e:
            console.print(f"[red]Sync failed: {e}[/red]")
