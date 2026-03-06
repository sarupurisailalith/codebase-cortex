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
    from codebase_cortex.config import RECOMMENDED_MODELS, DEFAULT_MODELS

    provider = click.prompt(
        "LLM provider",
        type=click.Choice(["google", "anthropic", "openrouter"]),
        default="google",
    )

    api_key = ""
    if provider == "google":
        api_key = click.prompt("Google API key (GOOGLE_API_KEY)")
        key_name = "GOOGLE_API_KEY"
    elif provider == "anthropic":
        api_key = click.prompt("Anthropic API key (ANTHROPIC_API_KEY)")
        key_name = "ANTHROPIC_API_KEY"
    else:
        api_key = click.prompt("OpenRouter API key (OPENROUTER_API_KEY)")
        key_name = "OPENROUTER_API_KEY"

    # Step 1b: Model selection
    recommended = RECOMMENDED_MODELS.get(provider, [])
    default_model = DEFAULT_MODELS.get(provider, "")

    if recommended:
        console.print("\n[bold]Recommended models:[/bold]")
        for i, m in enumerate(recommended, 1):
            marker = " (default)" if m == default_model else ""
            console.print(f"  {i}. {m}{marker}")
        console.print(f"  {len(recommended) + 1}. Custom model name")

        model_choice = click.prompt(
            "Choose model",
            type=click.IntRange(1, len(recommended) + 1),
            default=1,
        )

        if model_choice <= len(recommended):
            llm_model = recommended[model_choice - 1]
        else:
            llm_model = click.prompt("Model name")
    else:
        llm_model = click.prompt("Model name")

    console.print(f"[green]Model:[/green] {llm_model}")

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
        f"LLM_MODEL={llm_model}",
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

    # Step 4: Git hook
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

    # Step 5: OAuth with Notion
    console.print("\n[bold]Connecting to Notion...[/bold]")
    console.print("A browser window will open for Notion authorization.")

    notion_connected = False
    try:
        asyncio.run(_run_oauth(cwd))
        console.print("[green]Notion connected successfully![/green]")
        notion_connected = True
    except Exception as e:
        console.print(f"[yellow]Notion OAuth skipped: {e}[/yellow]")
        console.print("You can retry later with: cortex init")

    # Step 6: Bootstrap Notion pages
    if notion_connected:
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

    console.print("\n[bold]Setup complete![/bold]")
    console.print("Run [cyan]cortex status[/cyan] to verify the connection.")
    console.print("Run [cyan]cortex run --once[/cyan] to analyze your repo.")


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
@click.option("--dry-run", is_flag=True, help="Analyze without writing to Notion.")
@click.option("--full", is_flag=True, help="Analyze entire codebase (not just recent diff).")
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging (LLM calls, MCP calls).")
def run(once: bool, watch: bool, dry_run: bool, full: bool, verbose: bool) -> None:
    """Run the Cortex pipeline on the current repo."""
    from codebase_cortex.graph import compile_graph
    from codebase_cortex.notion.page_cache import PageCache
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

    # Auto-detect: if doc pages have no real content yet, do a full scan
    if not full:
        cache = PageCache(cache_path=settings.page_cache_path)
        arch_page = cache.find_by_title("Architecture Overview")
        if arch_page and arch_page.content_hash == "":
            # Pages exist but were never written with real content
            # Check if this looks like a first run after init
            doc_pages = cache.find_all_doc_pages()
            all_empty = all(p.content_hash == "" for p in doc_pages)
            if all_empty:
                console.print("[cyan]First run detected — doing full codebase scan[/cyan]")
                full = True

    graph = compile_graph()

    initial_state = {
        "trigger": "manual",
        "repo_path": str(settings.repo_path),
        "dry_run": dry_run,
        "full_scan": full,
        "errors": [],
    }

    if full:
        console.print("[cyan]Full codebase analysis mode[/cyan]")
    if dry_run:
        console.print("[yellow]Dry run mode — no Notion writes[/yellow]")

    async def _run_once():
        # Discover any new child pages under the parent (e.g. user-moved pages)
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
    from codebase_cortex.agents.doc_writer import strip_notion_metadata
    from codebase_cortex.config import get_llm
    from codebase_cortex.mcp_client import notion_mcp_session, rate_limiter
    from codebase_cortex.notion.page_cache import PageCache
    from codebase_cortex.utils.json_parsing import parse_json_array
    from codebase_cortex.utils.section_parser import merge_sections, parse_sections

    cache = PageCache(cache_path=settings.page_cache_path)
    doc_pages = cache.find_all_doc_pages()

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
        if isinstance(raw, list):
            raw = "\n".join(str(block) for block in raw)
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
