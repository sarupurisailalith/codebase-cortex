"""FAISS index management for code embeddings."""

from __future__ import annotations

import json
from pathlib import Path
from dataclasses import dataclass, field

import faiss
import numpy as np

from codebase_cortex.embeddings.indexer import CodeChunk


@dataclass
class SearchResult:
    """A single search result from the FAISS index."""

    chunk: CodeChunk
    distance: float
    score: float  # 1 / (1 + distance), higher = more similar


@dataclass
class FAISSStore:
    """Manages a FAISS vector index for code embeddings.

    Stores embeddings in a flat L2 index with chunk metadata
    persisted alongside in a JSON sidecar file.
    """

    index_dir: Path
    index: faiss.IndexFlatL2 | None = field(default=None, repr=False)
    chunks: list[CodeChunk] = field(default_factory=list)
    _dimension: int = 384  # all-MiniLM-L6-v2 output dimension

    def build(self, embeddings: np.ndarray, chunks: list[CodeChunk]) -> None:
        """Build a new index from embeddings and chunks.

        Args:
            embeddings: Array of shape (n, dimension).
            chunks: Corresponding code chunks (must match embeddings length).
        """
        if len(embeddings) == 0:
            self.index = faiss.IndexFlatL2(self._dimension)
            self.chunks = []
            return

        self._dimension = embeddings.shape[1]
        self.index = faiss.IndexFlatL2(self._dimension)
        self.index.add(embeddings.astype(np.float32))
        self.chunks = list(chunks)

    def search(self, query_embedding: np.ndarray, k: int = 5) -> list[SearchResult]:
        """Search the index for the k most similar chunks.

        Args:
            query_embedding: Array of shape (1, dimension) or (dimension,).
            k: Number of results to return.

        Returns:
            List of SearchResult sorted by similarity (highest first).
        """
        if self.index is None or self.index.ntotal == 0:
            return []

        query = query_embedding.reshape(1, -1).astype(np.float32)
        k = min(k, self.index.ntotal)
        distances, indices = self.index.search(query, k)

        results = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx < 0 or idx >= len(self.chunks):
                continue
            results.append(SearchResult(
                chunk=self.chunks[idx],
                distance=float(dist),
                score=1.0 / (1.0 + float(dist)),
            ))
        return results

    def save(self) -> None:
        """Persist the index and chunk metadata to disk."""
        self.index_dir.mkdir(parents=True, exist_ok=True)

        if self.index is not None:
            faiss.write_index(self.index, str(self.index_dir / "index.faiss"))

        metadata = [
            {
                "file_path": c.file_path,
                "chunk_type": c.chunk_type,
                "name": c.name,
                "content": c.content[:500],  # Truncate for storage
                "start_line": c.start_line,
                "end_line": c.end_line,
            }
            for c in self.chunks
        ]
        (self.index_dir / "chunks.json").write_text(json.dumps(metadata, indent=2))

    def load(self) -> bool:
        """Load an existing index from disk.

        Returns:
            True if loaded successfully, False if no index exists.
        """
        index_path = self.index_dir / "index.faiss"
        chunks_path = self.index_dir / "chunks.json"

        if not index_path.exists() or not chunks_path.exists():
            return False

        self.index = faiss.read_index(str(index_path))
        self._dimension = self.index.d

        metadata = json.loads(chunks_path.read_text())
        self.chunks = [CodeChunk(**m) for m in metadata]
        return True

    @property
    def size(self) -> int:
        """Number of vectors in the index."""
        if self.index is None:
            return 0
        return self.index.ntotal
