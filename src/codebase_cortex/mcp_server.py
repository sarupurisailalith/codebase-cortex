"""MCP server exposing Cortex documentation tools to coding agents.

All tools are deterministic — no LLM required. The coding agent's own LLM
does the reasoning; Cortex provides semantic search, section tracking,
metadata, and file management.

Start with: cortex mcp serve
"""

from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP

from codebase_cortex.config import Settings
from codebase_cortex.embeddings.store import FAISSStore
from codebase_cortex.backends.meta_index import MetaIndex

logger = logging.getLogger("cortex")


def create_server() -> FastMCP:
    """Create and configure the Cortex MCP server with all tools."""
    mcp = FastMCP("cortex", instructions="Documentation intelligence for your codebase")

    try:
        settings = Settings.from_env()
    except Exception:
        @mcp.tool()
        def cortex_status() -> dict:
            """Cortex is not initialized. Run 'cortex init' in your project first."""
            return {"error": "Cortex is not initialized in this project. Run 'cortex init' to set up."}
        return mcp

    # Load project configuration and indexes at startup
    store = FAISSStore(settings.faiss_index_dir)
    loaded = store.load()
    if not loaded:
        logger.warning("FAISS index not found or empty — semantic search will be unavailable until 'cortex index' is run.")
    docs_dir = settings.repo_path / "docs"
    meta = MetaIndex(docs_dir)
    meta.load()

    # Track FAISS index mtime for auto-reload on change
    _index_mtime: float = 0.0
    index_faiss_path = settings.faiss_index_dir / "index.faiss"
    if index_faiss_path.exists():
        _index_mtime = index_faiss_path.stat().st_mtime

    def _maybe_reload_index() -> None:
        """Reload FAISS index if it changed on disk."""
        nonlocal _index_mtime
        if not index_faiss_path.exists():
            return
        current_mtime = index_faiss_path.stat().st_mtime
        if current_mtime > _index_mtime:
            store.load()
            _index_mtime = current_mtime
            logger.info("FAISS index reloaded (updated on disk).")

    # ── Tool 1: Semantic search ────────────────────────────────────────
    @mcp.tool()
    def cortex_search_related_docs(query: str, k: int = 5) -> dict:
        """Find documentation sections related to a code change or query.
        Uses FAISS semantic search. Pass a natural language query, code snippet, or function name.
        """
        _maybe_reload_index()
        from codebase_cortex.embeddings.indexer import EmbeddingIndexer

        indexer = EmbeddingIndexer(settings.repo_path)
        query_embedding = indexer.embed_texts([query])
        if query_embedding.size == 0:
            return {"results": [], "error": "Failed to embed query"}
        results = store.search(query_embedding, k=k)
        return {
            "results": [
                {
                    "doc_file": r.chunk.file_path,
                    "section_heading": r.chunk.name,
                    "relevance_score": round(r.score, 3),
                    "snippet": r.chunk.content[:200],
                }
                for r in results
            ]
        }

    # ── Tool 2: Read a section ──────────────────────────────────────────
    @mcp.tool()
    def cortex_read_section(doc_file: str, heading: str = "") -> dict:
        """Read a specific section from a documentation page.
        Returns content with metadata (draft status, human-edited flag, timestamps).
        """
        from codebase_cortex.utils.section_parser import parse_sections, normalize_heading

        file_path = docs_dir / doc_file
        if not file_path.exists():
            return {"error": f"File not found: {doc_file}"}
        content = file_path.read_text()
        if not heading:
            page_meta = meta.get_page(doc_file)
            return {
                "content": content,
                "is_draft": page_meta.get("is_draft", False) if page_meta else False,
                "is_human_edited": False,
                "last_updated": page_meta.get("last_updated", "") if page_meta else "",
                "source_commit": page_meta.get("source_commit", "") if page_meta else "",
            }
        sections = parse_sections(content)
        target = normalize_heading(heading)
        for section in sections:
            if section.heading and normalize_heading(section.heading) == target:
                is_edited = meta.is_human_edited(doc_file, section.heading)
                section_meta = {}
                for s in meta.get_section_tree(doc_file):
                    if s.get("heading") == section.heading:
                        section_meta = s
                        break
                return {
                    "content": section.content,
                    "heading": section.heading,
                    "is_draft": "<!-- DRAFT -->" in section.content,
                    "is_human_edited": is_edited,
                    "last_updated": section_meta.get("last_updated", ""),
                    "source_commit": section_meta.get("source_commit", ""),
                }
        return {"error": f"Section '{heading}' not found in {doc_file}"}

    # ── Tool 3: Write / update a section ────────────────────────────────
    @mcp.tool()
    def cortex_write_section(doc_file: str, heading: str, content: str, mode: str = "update") -> dict:
        """Write or update a documentation section. Respects human-edit protection.
        Append ' [force]' to heading to overwrite human-edited sections.
        """
        import hashlib
        from codebase_cortex.utils.section_parser import parse_sections, merge_sections
        from codebase_cortex.utils.file_lock import cortex_lock

        force = heading.endswith(" [force]")
        if force:
            heading = heading.removesuffix(" [force]")
        file_path = docs_dir / doc_file
        lock_path = settings.cortex_dir / "meta.lock"

        with cortex_lock(lock_path) as acquired:
            if not acquired:
                return {"status": "error", "error": "Could not acquire lock."}
            if file_path.exists() and not force and mode == "update":
                if meta.is_human_edited(doc_file, heading):
                    return {
                        "status": "skipped_human_edited",
                        "doc_file": doc_file,
                        "message": f"Section '{heading}' was manually edited. Append ' [force]' to heading to overwrite.",
                    }
            if not file_path.exists():
                docs_dir.mkdir(exist_ok=True)
                full_content = f"{heading}\n{content}"
                file_path.write_text(full_content)
                meta.set_page(doc_file, heading.lstrip("# "))
                status = "created"
            else:
                existing = file_path.read_text()
                existing_sections = parse_sections(existing)
                action = "create" if mode == "create" else "update"
                merged = merge_sections(
                    existing_sections,
                    [{"heading": heading, "content": content, "action": action}],
                )
                file_path.write_text(merged)
                status = "updated"
            content_hash = hashlib.md5(content.strip().encode()).hexdigest()
            page_data = meta.get_page(doc_file)
            if not page_data:
                meta.set_page(doc_file, doc_file.removesuffix(".md").replace("-", " ").title())
            meta.update_section(
                page=doc_file,
                heading=heading,
                content_hash=content_hash,
                cortex_hash=content_hash,
                line_range=(0, 0),
            )
            meta.save()
        return {"status": status, "doc_file": doc_file}

    # ── Tool 4: List docs ───────────────────────────────────────────────
    @mcp.tool()
    def cortex_list_docs(include_sections: bool = True) -> dict:
        """List all documentation pages with their structure."""
        from codebase_cortex.utils.section_parser import parse_sections

        pages = []
        for md_file in sorted(docs_dir.glob("*.md")):
            if md_file.name.startswith("."):
                continue
            page_meta = meta.get_page(md_file.name) or {}
            page_info = {
                "doc_file": md_file.name,
                "title": page_meta.get("title", md_file.stem.replace("-", " ").title()),
                "is_draft": page_meta.get("is_draft", False),
                "last_updated": page_meta.get("last_updated", ""),
            }
            if include_sections:
                content = md_file.read_text()
                sections = parse_sections(content)
                page_info["sections"] = [
                    {"heading": s.heading, "level": s.level} for s in sections if s.heading
                ]
            pages.append(page_info)
        return {"pages": pages, "total": len(pages)}

    # ── Tool 5: Freshness check ─────────────────────────────────────────
    @mcp.tool()
    def cortex_check_freshness(max_commits_behind: int = 10) -> dict:
        """Check which documentation sections may be stale based on recent git commits."""
        import subprocess

        stale = []
        fresh_count = 0
        total_count = 0
        for page_name, page_data in meta.data.get("pages", {}).items():
            for section in page_data.get("sections", []):
                total_count += 1
                source_commit = section.get("source_commit", "")
                if not source_commit:
                    stale.append({
                        "doc_file": page_name,
                        "section_heading": section.get("heading", ""),
                        "commits_behind": -1,
                        "last_updated_commit": "",
                        "note": "No source commit tracked",
                    })
                    continue
                try:
                    result = subprocess.run(
                        ["git", "rev-list", "--count", f"{source_commit}..HEAD"],
                        capture_output=True,
                        text=True,
                        cwd=str(settings.repo_path),
                    )
                    if result.returncode == 0:
                        behind = int(result.stdout.strip())
                        if behind > max_commits_behind:
                            stale.append({
                                "doc_file": page_name,
                                "section_heading": section.get("heading", ""),
                                "commits_behind": behind,
                                "last_updated_commit": source_commit,
                            })
                        else:
                            fresh_count += 1
                    else:
                        fresh_count += 1
                except (subprocess.SubprocessError, ValueError):
                    fresh_count += 1
        return {"stale": stale, "fresh_count": fresh_count, "total_count": total_count}

    # ── Tool 6: Doc status overview ─────────────────────────────────────
    @mcp.tool()
    def cortex_get_doc_status() -> dict:
        """Get overall documentation health status."""
        total_pages = 0
        total_sections = 0
        draft_count = 0
        human_edited_count = 0
        for page_name, page_data in meta.data.get("pages", {}).items():
            total_pages += 1
            if page_data.get("is_draft"):
                draft_count += 1
            for section in page_data.get("sections", []):
                total_sections += 1
                if meta.is_human_edited(page_name, section.get("heading", "")):
                    human_edited_count += 1
        last_run = meta.data.get("last_run")
        sync_targets = [
            t.strip() for t in (settings.doc_sync_targets or "").split(",") if t.strip()
        ]
        return {
            "total_pages": total_pages,
            "total_sections": total_sections,
            "draft_count": draft_count,
            "human_edited_count": human_edited_count,
            "last_run": last_run.get("timestamp", "") if last_run else "",
            "last_run_commit": last_run.get("source_commit", "") if last_run else "",
            "index_size": store.size,
            "backend": settings.doc_output,
            "sync_targets": sync_targets,
        }

    # ── Tool 7: Rebuild FAISS index ──────────────────────────────────────
    @mcp.tool()
    def cortex_rebuild_index(incremental: bool = True) -> dict:
        """Rebuild the FAISS semantic search index.
        Re-indexes code files to update the semantic search database.
        Use after significant code changes or if search results seem stale.
        """
        import time
        from codebase_cortex.embeddings.indexer import EmbeddingIndexer
        from codebase_cortex.utils.file_lock import cortex_lock

        lock_path = settings.cortex_dir / "index.lock"
        with cortex_lock(lock_path) as acquired:
            if not acquired:
                return {"status": "error", "error": "Index is locked by another process."}
            start = time.time()
            indexer = EmbeddingIndexer(settings.repo_path)
            if incremental and store.size > 0:
                result = indexer.index_codebase_incremental(store)
                if result.files_added == 0 and result.files_modified == 0 and result.files_removed == 0:
                    return {"status": "up_to_date", "chunks_indexed": store.size, "files_scanned": 0, "duration_seconds": round(time.time() - start, 2)}
                store.save()
                return {"status": "rebuilt", "chunks_indexed": store.size, "files_scanned": result.files_added + result.files_modified, "duration_seconds": round(time.time() - start, 2)}
            else:
                chunks = indexer.collect_chunks()
                if chunks:
                    embeddings = indexer.embed_chunks(chunks)
                    store.build(embeddings, chunks)
                    store.save()
                return {"status": "rebuilt", "chunks_indexed": len(chunks), "files_scanned": len(set(c.file_path for c in chunks)), "duration_seconds": round(time.time() - start, 2)}

    # ── Tool 8: Accept drafts ──────────────────────────────────────────
    @mcp.tool()
    def cortex_accept_drafts(doc_file: str = "", heading: str = "") -> dict:
        """Accept draft documentation by removing draft banners.
        Strips '<!-- DRAFT -->' markers from documentation sections.
        """
        from codebase_cortex.utils.file_lock import cortex_lock

        lock_path = settings.cortex_dir / "meta.lock"
        accepted = []
        with cortex_lock(lock_path) as acquired:
            if not acquired:
                return {"error": "Could not acquire lock."}
            files = [docs_dir / doc_file] if doc_file else sorted(docs_dir.glob("*.md"))
            for file_path in files:
                if not file_path.exists() or file_path.name.startswith("."):
                    continue
                content = file_path.read_text()
                if "<!-- DRAFT -->" not in content:
                    continue
                new_content = content.replace("<!-- DRAFT -->\n", "").replace("<!-- DRAFT -->", "")
                if new_content != content:
                    file_path.write_text(new_content)
                    accepted.append({"doc_file": file_path.name})
                    page_data = meta.get_page(file_path.name)
                    if page_data:
                        page_data["is_draft"] = False
            if accepted:
                meta.save()
        return {"accepted": accepted, "count": len(accepted)}

    # ── Tool 9: Create page ────────────────────────────────────────────
    @mcp.tool()
    def cortex_create_page(title: str, sections: list[str] | None = None, content: str = "") -> dict:
        """Create a new documentation page with initial structure.
        Generates a markdown file in docs/ with the given title and optional sections.
        """
        import re
        from codebase_cortex.utils.file_lock import cortex_lock

        slug = re.sub(r"[^\w\s-]", "", title.lower().strip())
        slug = re.sub(r"[\s_]+", "-", slug).strip("-") or "untitled"
        doc_file = f"{slug}.md"
        file_path = docs_dir / doc_file
        if file_path.exists():
            return {"error": f"File already exists: {doc_file}"}
        parts = [f"# {title}"]
        if content:
            parts.append(content)
        if sections:
            for heading in sections:
                parts.append(f"## {heading}\n")
        full_content = "\n\n".join(parts) + "\n"
        lock_path = settings.cortex_dir / "meta.lock"
        with cortex_lock(lock_path) as acquired:
            if not acquired:
                return {"error": "Could not acquire lock."}
            docs_dir.mkdir(exist_ok=True)
            file_path.write_text(full_content)
            meta.set_page(doc_file, title)
            meta.save()
        return {"doc_file": doc_file, "sections": len(sections) if sections else 0}

    # ── Tool 10: Knowledge map ─────────────────────────────────────────
    @mcp.tool()
    def cortex_knowledge_map(format: str = "summary") -> dict:
        """Get the code-to-documentation relationship map.
        Shows which code files relate to which documentation pages.
        """
        _maybe_reload_index()
        if store.size == 0:
            return {"error": "No FAISS index. Run cortex_rebuild_index first."}

        code_files = set()
        doc_files = set()
        for chunk in store.chunks:
            if chunk.file_path.startswith("docs/") or chunk.file_path.endswith(".md"):
                doc_files.add(chunk.file_path)
            else:
                code_files.add(chunk.file_path)
        for md_file in docs_dir.glob("*.md"):
            if not md_file.name.startswith("."):
                doc_files.add(f"docs/{md_file.name}")

        from codebase_cortex.embeddings.indexer import EmbeddingIndexer
        clusters = []
        mapped_code = set()
        indexer = EmbeddingIndexer(settings.repo_path)
        for doc_file in sorted(doc_files):
            doc_name = doc_file.split("/")[-1].removesuffix(".md").replace("-", " ")
            query_embedding = indexer.embed_texts([doc_name])
            if query_embedding.size == 0:
                continue
            results = store.search(query_embedding, k=10)
            related_code = [r.chunk.file_path for r in results if not r.chunk.file_path.startswith("docs/") and r.score > 0.3]
            mapped_code.update(related_code)
            cluster = {
                "theme": doc_name.title(),
                "doc_files": [doc_file],
                "code_files": related_code[:5] if format == "summary" else related_code,
                "coverage": min(1.0, len(related_code) / 5),
            }
            clusters.append(cluster)
        unmapped = sorted(code_files - mapped_code)
        return {"clusters": clusters, "unmapped_code": unmapped[:20] if format == "summary" else unmapped, "unmapped_docs": []}

    # ── Tool 11: Sync to remote ────────────────────────────────────────
    @mcp.tool()
    async def cortex_sync(target: str = "notion") -> dict:
        """Sync local documentation to a configured remote target.
        Pushes local markdown docs to the specified platform (e.g. Notion).
        """
        if target == "notion":
            try:
                from codebase_cortex.cli import _run_sync_to_notion
                synced = await _run_sync_to_notion(settings)
                return {"synced_pages": synced, "target": target, "errors": []}
            except Exception as e:
                return {"synced_pages": 0, "target": target, "errors": [str(e)]}
        else:
            return {"synced_pages": 0, "target": target, "errors": [f"Unsupported sync target: {target}"]}

    return mcp
