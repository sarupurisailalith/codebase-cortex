"""Sentence-transformers embedding pipeline for code chunks."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import re
from pathlib import Path
from dataclasses import dataclass, field

import numpy as np

# Lazy-loaded to avoid slow import at startup
_model = None
MODEL_NAME = "all-MiniLM-L6-v2"

# File extensions to index
CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs",
    ".rb", ".php", ".c", ".cpp", ".h", ".hpp", ".cs", ".swift",
    ".kt", ".scala", ".sh", ".bash", ".yml", ".yaml", ".toml",
    ".json", ".md", ".rst", ".txt",
}

# Directories to skip
SKIP_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__",
    ".pytest_cache", "dist", "build", ".eggs", ".tox",
    ".mypy_cache", ".ruff_cache", ".cortex", "docs",
}

# Max file size to index (100KB)
MAX_FILE_SIZE = 100_000


def _get_model():
    """Lazy-load the sentence-transformers model."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(MODEL_NAME)
    return _model


@dataclass
class CodeChunk:
    """A chunk of code with metadata for embedding."""

    file_path: str
    chunk_type: str  # "function" | "class" | "module" | "section"
    name: str
    content: str
    start_line: int
    end_line: int


@dataclass
class EmbeddingIndexer:
    """Indexes code chunks using sentence-transformers.

    Walks a repository, extracts meaningful code chunks,
    and generates embeddings for similarity search.
    """

    repo_path: Path
    chunks: list[CodeChunk] = field(default_factory=list)

    def collect_chunks(self) -> list[CodeChunk]:
        """Walk the repo and extract code chunks from all indexable files.

        Uses TreeSitterChunker for language-aware AST parsing, consistent
        with the incremental indexing path.
        """
        from codebase_cortex.embeddings.chunker import TreeSitterChunker

        chunker = TreeSitterChunker()
        self.chunks = []
        for file_path in self._iter_files():
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                if not content.strip():
                    continue
                rel_path = str(file_path.relative_to(self.repo_path))
                chunks = chunker.chunk_file(Path(rel_path), content)
                self.chunks.extend(chunks)
            except (OSError, UnicodeDecodeError):
                continue
        return self.chunks

    def embed_chunks(self, chunks: list[CodeChunk] | None = None) -> np.ndarray:
        """Generate embeddings for code chunks.

        Args:
            chunks: Chunks to embed. Uses self.chunks if not provided.

        Returns:
            numpy array of shape (n_chunks, embedding_dim).
        """
        chunks = chunks or self.chunks
        if not chunks:
            return np.array([])

        model = _get_model()
        texts = [self._chunk_to_text(c) for c in chunks]
        embeddings = model.encode(texts, show_progress_bar=False, convert_to_numpy=True)
        return embeddings

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        """Embed arbitrary text strings (for query embedding)."""
        if not texts:
            return np.array([])
        model = _get_model()
        return model.encode(texts, show_progress_bar=False, convert_to_numpy=True)

    def _iter_files(self):
        """Yield indexable files from the repo.

        Respects SKIP_DIRS and user-defined patterns in .cortex/.cortexignore.
        """
        ignore_patterns = self._load_ignore_patterns()
        for path in self.repo_path.rglob("*"):
            if any(skip in path.parts for skip in SKIP_DIRS):
                continue
            if not path.is_file():
                continue
            if path.suffix not in CODE_EXTENSIONS:
                continue
            if path.stat().st_size > MAX_FILE_SIZE:
                continue
            if ignore_patterns and self._is_ignored(path, ignore_patterns):
                continue
            yield path

    def _load_ignore_patterns(self) -> list[str]:
        """Load patterns from .cortex/.cortexignore (gitignore-style).

        Supports:
          - Directory names: ``docs/`` skips any path containing that directory
          - Glob patterns: ``*.generated.ts`` matches file names
          - Path patterns: ``frontend/dist/`` matches relative paths
          - Comments (lines starting with #) and blank lines are ignored
        """
        ignore_path = self.repo_path / ".cortex" / ".cortexignore"
        if not ignore_path.exists():
            return []
        patterns: list[str] = []
        for line in ignore_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            patterns.append(line)
        return patterns

    def _is_ignored(self, path: Path, patterns: list[str]) -> bool:
        """Check if a file path matches any ignore pattern."""
        rel = str(path.relative_to(self.repo_path))
        for pattern in patterns:
            # Directory pattern (e.g. "docs/" or "vendor/")
            if pattern.endswith("/"):
                dir_name = pattern.rstrip("/")
                if dir_name in path.parts:
                    return True
                if rel.startswith(dir_name + "/"):
                    return True
            # Glob against filename and relative path
            elif fnmatch.fnmatch(path.name, pattern) or fnmatch.fnmatch(rel, pattern):
                return True
        return False

    def _chunk_file(self, rel_path: str, content: str) -> list[CodeChunk]:
        """Split a file into meaningful chunks."""
        if rel_path.endswith(".py"):
            return self._chunk_python(rel_path, content)
        # For non-Python files, chunk by sections or as whole module
        return self._chunk_by_sections(rel_path, content)

    def _chunk_python(self, rel_path: str, content: str) -> list[CodeChunk]:
        """Extract Python functions and classes as chunks."""
        chunks = []
        lines = content.split("\n")

        # Regex patterns for top-level definitions
        func_pattern = re.compile(r"^(async\s+)?def\s+(\w+)")
        class_pattern = re.compile(r"^class\s+(\w+)")

        current_def = None
        current_start = 0
        current_name = ""
        current_type = ""

        for i, line in enumerate(lines):
            func_match = func_pattern.match(line)
            class_match = class_pattern.match(line)

            if func_match or class_match:
                # Save previous definition
                if current_def is not None:
                    chunk_content = "\n".join(lines[current_start:i])
                    if chunk_content.strip():
                        chunks.append(CodeChunk(
                            file_path=rel_path,
                            chunk_type=current_type,
                            name=current_name,
                            content=chunk_content,
                            start_line=current_start + 1,
                            end_line=i,
                        ))

                if func_match:
                    current_type = "function"
                    current_name = func_match.group(2)
                else:
                    current_type = "class"
                    current_name = class_match.group(1)
                current_def = True
                current_start = i

        # Save last definition
        if current_def is not None:
            chunk_content = "\n".join(lines[current_start:])
            if chunk_content.strip():
                chunks.append(CodeChunk(
                    file_path=rel_path,
                    chunk_type=current_type,
                    name=current_name,
                    content=chunk_content,
                    start_line=current_start + 1,
                    end_line=len(lines),
                ))

        # If no definitions found, treat whole file as module chunk
        if not chunks and content.strip():
            chunks.append(CodeChunk(
                file_path=rel_path,
                chunk_type="module",
                name=rel_path,
                content=content[:3000],
                start_line=1,
                end_line=len(lines),
            ))

        return chunks

    def _chunk_by_sections(self, rel_path: str, content: str) -> list[CodeChunk]:
        """Chunk non-Python files as whole modules (truncated if large)."""
        lines = content.split("\n")
        return [CodeChunk(
            file_path=rel_path,
            chunk_type="module",
            name=rel_path,
            content=content[:3000],
            start_line=1,
            end_line=len(lines),
        )]

    @staticmethod
    def _chunk_to_text(chunk: CodeChunk) -> str:
        """Convert a chunk to a text string suitable for embedding."""
        return f"{chunk.file_path} ({chunk.chunk_type}: {chunk.name})\n{chunk.content[:2000]}"

    # --- Incremental indexing ---

    def index_codebase_incremental(self, store: "FAISSStore") -> "IncrementalResult":
        """Only re-embed changed files. Returns stats.

        Compares file content hashes against a stored manifest to identify
        added, modified, and removed files.
        """
        from codebase_cortex.embeddings.chunker import TreeSitterChunker

        chunker = TreeSitterChunker()
        current_hashes = self._compute_file_hashes()
        previous_hashes = self._load_hash_manifest()

        added = [p for p in current_hashes if p not in previous_hashes]
        modified = [p for p in current_hashes if p in previous_hashes and current_hashes[p] != previous_hashes[p]]
        removed = [p for p in previous_hashes if p not in current_hashes]

        # Remove old chunks for modified + removed files
        files_to_remove = modified + removed
        if files_to_remove:
            ids = store.get_chunk_ids_for_files(files_to_remove)
            store.remove_ids(ids)

        # Re-chunk and re-embed added + modified files
        new_chunks: list[CodeChunk] = []
        for rel_path in added + modified:
            full_path = self.repo_path / rel_path
            try:
                content = full_path.read_text(encoding="utf-8", errors="ignore")
                new_chunks.extend(chunker.chunk_file(Path(rel_path), content))
            except (OSError, UnicodeDecodeError):
                continue

        if new_chunks:
            embeddings = self.embed_chunks(new_chunks)
            store.add(new_chunks, embeddings)

        # Save updated manifest
        self._save_hash_manifest(current_hashes)

        return IncrementalResult(
            files_added=len(added),
            files_modified=len(modified),
            files_removed=len(removed),
            chunks_re_embedded=len(new_chunks),
        )

    def _compute_file_hashes(self) -> dict[str, str]:
        """Compute MD5 hashes for all indexable files."""
        hashes: dict[str, str] = {}
        for file_path in self._iter_files():
            try:
                content = file_path.read_bytes()
                rel_path = str(file_path.relative_to(self.repo_path))
                hashes[rel_path] = hashlib.md5(content).hexdigest()
            except OSError:
                continue
        return hashes

    def _load_hash_manifest(self) -> dict[str, str]:
        """Load file hashes from the manifest."""
        manifest_path = self.repo_path / ".cortex" / "faiss_index" / "file_hashes.json"
        if manifest_path.exists():
            return json.loads(manifest_path.read_text())
        return {}

    def _save_hash_manifest(self, hashes: dict[str, str]) -> None:
        """Save file hashes to the manifest."""
        manifest_dir = self.repo_path / ".cortex" / "faiss_index"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        (manifest_dir / "file_hashes.json").write_text(json.dumps(hashes, indent=2))


@dataclass
class IncrementalResult:
    """Result of an incremental index rebuild."""

    files_added: int = 0
    files_modified: int = 0
    files_removed: int = 0
    chunks_re_embedded: int = 0
