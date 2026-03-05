"""SemanticFinder agent — finds related docs via FAISS embedding similarity."""

from __future__ import annotations

from pathlib import Path

from codebase_cortex.agents.base import BaseAgent
from codebase_cortex.config import Settings
from codebase_cortex.embeddings.indexer import EmbeddingIndexer
from codebase_cortex.embeddings.store import FAISSStore
from codebase_cortex.state import CortexState, RelatedDoc


class SemanticFinderAgent(BaseAgent):
    """Finds semantically related code chunks using FAISS embeddings.

    Embeds the analysis text from CodeAnalyzer, queries the FAISS index
    for similar code chunks, and returns them as RelatedDoc entries.
    """

    async def run(self, state: CortexState) -> dict:
        analysis = state.get("analysis", "")
        if not analysis:
            return {"related_docs": []}

        repo_path = Path(state.get("repo_path", "."))
        settings = Settings.from_env(repo_path)
        index_dir = settings.faiss_index_dir

        try:
            # Always rebuild the index to capture new/changed files
            indexer = EmbeddingIndexer(repo_path=repo_path)
            chunks = indexer.collect_chunks()
            if not chunks:
                return {"related_docs": []}

            store = FAISSStore(index_dir=index_dir)
            embeddings = indexer.embed_chunks(chunks)
            store.build(embeddings, chunks)
            store.save()
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
                ))

            return {"related_docs": related_docs}

        except Exception as e:
            return {
                "related_docs": [],
                "errors": self._append_error(state, f"Semantic search failed: {e}"),
            }
