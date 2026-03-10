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

    Uses IndexIDMap wrapping IndexFlatL2 to support ID-based operations
    needed for incremental rebuilds.
    """

    index_dir: Path
    index: faiss.IndexIDMap | faiss.IndexFlatL2 | None = field(default=None, repr=False)
    chunks: list[CodeChunk] = field(default_factory=list)
    _dimension: int = 384  # all-MiniLM-L6-v2 output dimension
    _id_counter: int = 0
    _id_to_idx: dict[int, int] = field(default_factory=dict)  # FAISS ID -> chunks list index

    def build(self, embeddings: np.ndarray, chunks: list[CodeChunk]) -> None:
        """Build a new index from embeddings and chunks.

        Args:
            embeddings: Array of shape (n, dimension).
            chunks: Corresponding code chunks (must match embeddings length).
        """
        if len(embeddings) == 0:
            base = faiss.IndexFlatL2(self._dimension)
            self.index = faiss.IndexIDMap(base)
            self.chunks = []
            self._id_counter = 0
            self._id_to_idx = {}
            return

        self._dimension = embeddings.shape[1]
        base = faiss.IndexFlatL2(self._dimension)
        self.index = faiss.IndexIDMap(base)

        ids = np.arange(len(chunks), dtype=np.int64)
        self.index.add_with_ids(embeddings.astype(np.float32), ids)
        self.chunks = list(chunks)
        self._id_counter = len(chunks)
        self._id_to_idx = {i: i for i in range(len(chunks))}

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
            if idx < 0:
                continue
            # Map FAISS ID to chunk index
            chunk_idx = self._id_to_idx.get(int(idx))
            if chunk_idx is None or chunk_idx >= len(self.chunks):
                continue
            results.append(SearchResult(
                chunk=self.chunks[chunk_idx],
                distance=float(dist),
                score=1.0 / (1.0 + float(dist)),
            ))
        return results

    def get_chunk_ids_for_files(self, file_paths: list[str]) -> list[int]:
        """Return FAISS IDs for all chunks belonging to given files."""
        file_set = set(file_paths)
        ids = []
        for faiss_id, chunk_idx in self._id_to_idx.items():
            if chunk_idx < len(self.chunks) and self.chunks[chunk_idx].file_path in file_set:
                ids.append(faiss_id)
        return ids

    def remove_ids(self, ids: list[int]) -> None:
        """Remove vectors by FAISS ID."""
        if not ids or self.index is None:
            return

        ids_array = np.array(ids, dtype=np.int64)
        self.index.remove_ids(ids_array)

        # Remove from id_to_idx mapping and mark chunks as removed
        removed_chunk_idxs = set()
        for fid in ids:
            chunk_idx = self._id_to_idx.pop(fid, None)
            if chunk_idx is not None:
                removed_chunk_idxs.add(chunk_idx)

        # Rebuild chunks list (remove gaps)
        if removed_chunk_idxs:
            new_chunks = [c for i, c in enumerate(self.chunks) if i not in removed_chunk_idxs]
            self.chunks = new_chunks
            # Rebuild id_to_idx mapping
            self._rebuild_id_mapping()

    def add(self, chunks: list[CodeChunk], embeddings: np.ndarray) -> None:
        """Add new chunks and embeddings to the existing index."""
        if not chunks or len(embeddings) == 0:
            return

        if self.index is None:
            self.build(embeddings, chunks)
            return

        # Assign new IDs
        new_ids = np.arange(
            self._id_counter,
            self._id_counter + len(chunks),
            dtype=np.int64,
        )
        self.index.add_with_ids(embeddings.astype(np.float32), new_ids)

        base_idx = len(self.chunks)
        for i, chunk in enumerate(chunks):
            self._id_to_idx[int(new_ids[i])] = base_idx + i
        self.chunks.extend(chunks)
        self._id_counter += len(chunks)

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
                "content": c.content[:2000],  # Truncate for storage
                "start_line": c.start_line,
                "end_line": c.end_line,
            }
            for c in self.chunks
        ]
        (self.index_dir / "chunks.json").write_text(json.dumps(metadata, indent=2))

        # Save ID mapping
        id_map = {
            "id_counter": self._id_counter,
            "id_to_idx": {str(k): v for k, v in self._id_to_idx.items()},
        }
        (self.index_dir / "id_map.json").write_text(json.dumps(id_map))

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

        # Load ID mapping if available
        id_map_path = self.index_dir / "id_map.json"
        if id_map_path.exists():
            id_map = json.loads(id_map_path.read_text())
            self._id_counter = id_map.get("id_counter", len(self.chunks))
            self._id_to_idx = {int(k): v for k, v in id_map.get("id_to_idx", {}).items()}
        else:
            # Legacy index without ID map — reconstruct
            self._id_counter = len(self.chunks)
            self._id_to_idx = {i: i for i in range(len(self.chunks))}

        return True

    @property
    def size(self) -> int:
        """Number of vectors in the index."""
        if self.index is None:
            return 0
        return self.index.ntotal

    def _rebuild_id_mapping(self) -> None:
        """Rebuild _id_to_idx after chunk list mutation."""
        # Create a reverse mapping: old chunk_idx -> new chunk_idx
        # After removal, chunks are compacted, so rebuild from scratch
        new_id_to_idx = {}
        idx = 0
        for fid, old_idx in sorted(self._id_to_idx.items()):
            new_id_to_idx[fid] = idx
            idx += 1
        self._id_to_idx = new_id_to_idx
