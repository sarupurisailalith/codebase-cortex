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

    # Load project configuration and indexes at startup
    settings = Settings.from_env()
    store = FAISSStore(settings.faiss_index_dir)
    store.load()
    docs_dir = settings.repo_path / "docs"
    meta = MetaIndex(docs_dir)
    meta.load()

    # ── Tool 1: Semantic search ────────────────────────────────────────
    @mcp.tool()
    def cortex_search_related_docs(query: str, k: int = 5) -> dict:
        """Find documentation sections related to a code change or query.
        Uses FAISS semantic search. Pass a natural language query, code snippet, or function name.
        """
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

    return mcp
