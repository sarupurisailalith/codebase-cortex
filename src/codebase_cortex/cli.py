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


@click.group()
@click.version_option(package_name="codebase-cortex")
def cli() -> None:
    """Codebase Cortex - Keep engineering docs in sync with code."""
    pass


@cli.command()
def init() -> None:
    """Interactive setup wizard. Run this inside your project repo."""
    cwd = Path.cwd()
    console.print(Panel(f"Codebase Cortex Setup — {cwd.name}", style="bold blue"))

    # Check if already initialized
    cortex_dir = cwd / CORTEX_DIR_NAME
    if cortex_dir.exists():
        if not click.confirm(f"{CORTEX_DIR_NAME}/ already exists. Re-initialize?", default=False):
            return

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

    # Step 2: GitHub token (optional)
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
            github_token = click.prompt("GitHub Personal Access Token")

    # Step 3: Create .cortex/ directory
    cortex_dir.mkdir(exist_ok=True)

    # Write .cortex/.env
    env_lines = [
        f"LLM_PROVIDER={provider}",
        f"{key_name}={api_key}",
    ]
    if github_token:
        env_lines.append(f"GITHUB_TOKEN={github_token}")

    env_path = cortex_dir / ".env"
    env_path.write_text("\n".join(env_lines) + "\n")

    # Write .cortex/.gitignore (ignore everything inside)
    (cortex_dir / ".gitignore").write_text("*\n")

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

    # Step 4: OAuth with Notion
    console.print("\n[bold]Connecting to Notion...[/bold]")
    console.print("A browser window will open for Notion authorization.")

    try:
        asyncio.run(_run_oauth(cwd))
        console.print("[green]Notion connected successfully![/green]")
    except Exception as e:
        console.print(f"[yellow]Notion OAuth skipped: {e}[/yellow]")
        console.print("You can retry later with: cortex init")

    console.print("\n[bold]Setup complete![/bold]")
    console.print("Run [cyan]cortex status[/cyan] to verify the connection.")
    console.print("Run [cyan]cortex run --once[/cyan] to analyze your repo.")


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
    """Run the Cortex pipeline on the current repo."""
    from codebase_cortex.graph import compile_graph
    from codebase_cortex.utils.logging import get_logger

    logger = get_logger()
    settings = Settings.from_env()

    if not settings.is_initialized:
        console.print("[red]Not initialized. Run 'cortex init' first.[/red]")
        return

    if not once and not watch:
        once = True  # Default to single run

    graph = compile_graph()

    initial_state = {
        "trigger": "manual",
        "repo_path": str(settings.repo_path),
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
    settings = Settings.from_env()

    console.print(Panel(f"Codebase Cortex Status — {settings.repo_path.name}", style="bold blue"))

    # Check initialization
    if not settings.is_initialized:
        console.print(f"[red]Not initialized.[/red] Run 'cortex init' in this directory.")
        return

    console.print(f"[green]Config:[/green] {settings.env_path}")
    console.print(f"[green]LLM Provider:[/green] {settings.llm_provider}")
    console.print(f"[green]Repo:[/green] {settings.repo_path}")

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

    # Check FAISS index
    if settings.faiss_index_dir.exists():
        console.print(f"[green]Index:[/green] {settings.faiss_index_dir}")
    else:
        console.print("[yellow]Index:[/yellow] Not built. Run 'cortex embed'.")

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

    agent = CodeAnalyzerAgent(get_llm(settings))
    state = {
        "trigger": "manual",
        "repo_path": str(settings.repo_path),
        "diff_text": diff_text,
        "dry_run": True,
        "errors": [],
    }

    result = asyncio.run(agent.run(state))
    if result.get("analysis"):
        console.print(Panel(result["analysis"], title="Analysis", border_style="green"))


@cli.command()
def embed() -> None:
    """Rebuild the embedding index for the current repo."""
    from codebase_cortex.embeddings.indexer import EmbeddingIndexer
    from codebase_cortex.embeddings.store import FAISSStore
    from codebase_cortex.embeddings.clustering import TopicClusterer

    settings = Settings.from_env()
    repo_path = settings.repo_path
    index_dir = settings.faiss_index_dir

    console.print(f"Indexing [cyan]{repo_path}[/cyan]...")

    indexer = EmbeddingIndexer(repo_path=repo_path)
    chunks = indexer.collect_chunks()
    console.print(f"Found [green]{len(chunks)}[/green] code chunks")

    if not chunks:
        console.print("[yellow]No indexable files found.[/yellow]")
        return

    console.print("Generating embeddings...")
    embeddings = indexer.embed_chunks(chunks)

    store = FAISSStore(index_dir=index_dir)
    store.build(embeddings, chunks)
    store.save()
    console.print(f"Saved FAISS index with [green]{store.size}[/green] vectors to {index_dir}")

    # Run clustering
    console.print("Clustering topics...")
    clusterer = TopicClusterer()
    topics = clusterer.cluster(embeddings, chunks)
    console.print(f"Found [green]{len(topics)}[/green] topic clusters")

    if topics:
        console.print(Panel(clusterer.to_markdown(topics), title="Knowledge Map", border_style="blue"))
