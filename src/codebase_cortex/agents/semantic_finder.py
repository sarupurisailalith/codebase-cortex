"""SemanticFinder agent — finds related docs via FAISS embedding similarity."""

from __future__ import annotations

import logging
from pathlib import Path

from codebase_cortex.agents.base import BaseAgent
from codebase_cortex.config import Settings
from codebase_cortex.embeddings.indexer import EmbeddingIndexer
from codebase_cortex.embeddings.store import FAISSStore
from codebase_cortex.state import CortexState, RelatedDoc

logger = logging.getLogger("cortex")


class SemanticFinderAgent(BaseAgent):
    """Finds semantically related code chunks using FAISS embeddings.

    Uses incremental indexing by default: only re-embeds files that changed
    since the last run. Falls back to a full rebuild when no existing index
    is found or when ``full_scan`` is requested.
    """

    async def run(self, state: CortexState) -> dict:
        analysis = state.get("analysis", "")
        if not analysis:
            return {"related_docs": []}

        repo_path = Path(state.get("repo_path", "."))
        settings = Settings.from_env(repo_path)
        index_dir = settings.faiss_index_dir
        full_scan = state.get("full_scan", False) or state.get("trigger") == "full_scan"

        try:
            indexer = EmbeddingIndexer(repo_path=repo_path)
            store = FAISSStore(index_dir=index_dir)

            # Try incremental rebuild unless full_scan requested
            if not full_scan and store.load():
                result = indexer.index_codebase_incremental(store)
                logger.info(
                    "Incremental index: +%d modified=%d removed=%d re-embedded=%d chunks",
                    result.files_added, result.files_modified,
                    result.files_removed, result.chunks_re_embedded,
                )
            else:
                # Full rebuild
                chunks = indexer.collect_chunks()
                if not chunks:
                    return {"related_docs": []}
                embeddings = indexer.embed_chunks(chunks)
                store.build(embeddings, chunks)

            store.save()

            if store.size == 0:
                return {"related_docs": []}

            query_emb = indexer.embed_texts([analysis])
            if query_emb.size == 0:
                return {"related_docs": []}

            # Search for related chunks
            results = store.search(query_emb[0], k=10)

            related_docs: list[RelatedDoc] = []
            for r in results:
                related_docs.append(RelatedDoc(
                    page_id=r.chunk.file_path,
                    title=f"{r.chunk.name} ({r.chunk.file_path})",
                    similarity=r.score,
                    content=r.chunk.content[:2000],
                ))

            return {"related_docs": related_docs}

        except Exception as e:
            return {
                "related_docs": [],
                "errors": self._append_error(state, f"Semantic search failed: {e}"),
            }

