"""CLI commands for Codebase Cortex."""

from __future__ import annotations

import asyncio
import secrets
import time
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel

from codebase_cortex.config import Settings, PROJECT_ROOT

console = Console()


@click.group()
@click.version_option(package_name="codebase-cortex")
def cli() -> None:
    """Codebase Cortex - Keep engineering docs in sync with code."""
    pass


@cli.command()
def init() -> None:
    """Interactive setup wizard. Connects to Notion via OAuth and configures the project."""
    console.print(Panel("Codebase Cortex Setup", style="bold blue"))

    # Step 1: LLM provider
    provider = click.prompt(
        "LLM provider",
        type=click.Choice(["google", "anthropic"]),
        default="google",
    )

    api_key = ""
    if provider == "google":
        api_key = click.prompt("Google API key (GOOGLE_API_KEY)")
        key_name = "GOOGLE_API_KEY"
    else:
        api_key = click.prompt("Anthropic API key (ANTHROPIC_API_KEY)")
        key_name = "ANTHROPIC_API_KEY"

    # Step 2: Repository path
    repo_path = click.prompt(
        "Repository path (local path or GitHub URL)",
        default=".",
    )

    # Step 3: GitHub token (only if remote URL)
    github_token = ""
    if repo_path.startswith("https://github.com") or repo_path.startswith("git@"):
        # Try gh CLI first
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
            github_token = click.prompt("GitHub Personal Access Token")

    # Step 4: Write .env
    env_path = PROJECT_ROOT / ".env"
    env_lines = [
        f"LLM_PROVIDER={provider}",
        f"{key_name}={api_key}",
        f"REPO_PATH={repo_path}",
    ]
    if github_token:
        env_lines.append(f"GITHUB_TOKEN={github_token}")

    env_path.write_text("\n".join(env_lines) + "\n")
    console.print(f"[green]Wrote {env_path}[/green]")

    # Step 5: OAuth with Notion
    console.print("\n[bold]Connecting to Notion...[/bold]")
    console.print("A browser window will open for Notion authorization.")

    try:
        asyncio.run(_run_oauth())
        console.print("[green]Notion connected successfully![/green]")
    except Exception as e:
        console.print(f"[yellow]Notion OAuth skipped: {e}[/yellow]")
        console.print("You can retry later with: cortex init")

    # Step 6: Bootstrap Notion pages
    console.print("\n[bold]Setup complete![/bold]")
    console.print("Run [cyan]cortex status[/cyan] to verify the connection.")
    console.print("Run [cyan]cortex run --once[/cyan] to analyze your repo.")


async def _run_oauth() -> None:
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

    settings = Settings.from_env()
    port = settings.oauth_callback_port
    redirect_uri = f"http://localhost:{port}/callback"

    # Fetch server metadata
    metadata = await fetch_oauth_metadata()
    auth_endpoint = metadata.get("authorization_endpoint")
    token_endpoint = metadata.get("token_endpoint")

    # Dynamic client registration
    client_info = await register_client(redirect_uri)
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


@cli.command()
@click.option("--once", is_flag=True, help="Run once and exit (no watch mode).")
@click.option("--watch", is_flag=True, help="Watch for changes and run continuously.")
@click.option("--dry-run", is_flag=True, help="Analyze without writing to Notion.")
def run(once: bool, watch: bool, dry_run: bool) -> None:
    """Run the Cortex pipeline."""
    from codebase_cortex.graph import compile_graph
    from codebase_cortex.utils.logging import get_logger

    logger = get_logger()
    settings = Settings.from_env()

    if not once and not watch:
        once = True  # Default to single run

    graph = compile_graph()

    initial_state = {
        "trigger": "manual",
        "repo_path": str(Path(settings.repo_path).resolve()),
        "dry_run": dry_run,
        "errors": [],
    }

    if dry_run:
        console.print("[yellow]Dry run mode — no Notion writes[/yellow]")

    async def _run_once():
        result = await graph.ainvoke(initial_state)
        if result.get("errors"):
            for err in result["errors"]:
                logger.error(err)
        if result.get("analysis"):
            console.print(Panel(result["analysis"], title="Analysis", border_style="green"))
        else:
            console.print("[yellow]No analysis produced. Check if there are recent changes.[/yellow]")

    if once:
        asyncio.run(_run_once())
    elif watch:
        console.print("[cyan]Watch mode not yet implemented. Use --once.[/cyan]")


@cli.command()
def status() -> None:
    """Show connection status and workspace info."""
    settings = Settings.from_env()

    console.print(Panel("Codebase Cortex Status", style="bold blue"))

    # Check .env
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        console.print(f"[green]Config:[/green] {env_path}")
    else:
        console.print("[red]Config:[/red] .env not found. Run 'cortex init'.")
        return

    # Check LLM
    console.print(f"[green]LLM Provider:[/green] {settings.llm_provider}")
    console.print(f"[green]Repo Path:[/green] {settings.repo_path}")

    # Check Notion tokens
    token_path = settings.notion_token_path
    if token_path.exists():
        from codebase_cortex.auth.token_store import load_tokens

        token_data = load_tokens(token_path)
        if token_data and not token_data.is_expired:
            console.print("[green]Notion:[/green] Connected (token valid)")
        elif token_data:
            console.print("[yellow]Notion:[/yellow] Token expired (will auto-refresh)")
        else:
            console.print("[red]Notion:[/red] Token file corrupt")
    else:
        console.print("[red]Notion:[/red] Not connected. Run 'cortex init'.")

    # Test MCP connection
    if token_path.exists():
        console.print("\nTesting Notion MCP connection...")
        try:
            asyncio.run(_test_mcp(settings))
            console.print("[green]MCP:[/green] Connected to mcp.notion.com")
        except Exception as e:
            console.print(f"[red]MCP:[/red] {e}")


async def _test_mcp(settings: Settings) -> None:
    """Test the MCP connection by listing available tools."""
    from codebase_cortex.mcp_client import notion_mcp_session

    async with notion_mcp_session(settings) as session:
        result = await session.list_tools()
        console.print(f"  Available tools: {len(result.tools)}")


@cli.command()
@click.argument("path", default=".", type=click.Path(exists=True))
def analyze(path: str) -> None:
    """One-shot diff analysis without Notion writes."""
    from codebase_cortex.git.diff_parser import get_recent_diff
    from codebase_cortex.agents.code_analyzer import CodeAnalyzerAgent
    from codebase_cortex.config import get_llm

    settings = Settings.from_env()
    repo_path = Path(path).resolve()

    diff_text = get_recent_diff(str(repo_path))
    if not diff_text:
        console.print("[yellow]No recent changes found.[/yellow]")
        return

    agent = CodeAnalyzerAgent(get_llm(settings))
    state = {
        "trigger": "manual",
        "repo_path": str(repo_path),
        "diff_text": diff_text,
        "dry_run": True,
        "errors": [],
    }

    result = asyncio.run(agent.run(state))
    if result.get("analysis"):
        console.print(Panel(result["analysis"], title="Analysis", border_style="green"))


@cli.command()
def embed() -> None:
    """Rebuild the embedding index."""
    console.print("[cyan]Embedding pipeline not yet implemented (Week 2).[/cyan]")
