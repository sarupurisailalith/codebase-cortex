"""Sentence-transformers embedding pipeline for code chunks."""

from __future__ import annotations

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
    ".mypy_cache", ".ruff_cache",
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
        """Walk the repo and extract code chunks from all indexable files."""
        self.chunks = []
        for file_path in self._iter_files():
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                if not content.strip():
                    continue
                rel_path = str(file_path.relative_to(self.repo_path))
                chunks = self._chunk_file(rel_path, content)
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
        """Yield indexable files from the repo."""
        for path in self.repo_path.rglob("*"):
            if any(skip in path.parts for skip in SKIP_DIRS):
                continue
            if not path.is_file():
                continue
            if path.suffix not in CODE_EXTENSIONS:
                continue
            if path.stat().st_size > MAX_FILE_SIZE:
                continue
            yield path

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
