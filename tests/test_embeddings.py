"""Tests for embedding pipeline."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from codebase_cortex.embeddings.chunker import TreeSitterChunker
from codebase_cortex.embeddings.indexer import (
    CodeChunk,
    EmbeddingIndexer,
    CODE_EXTENSIONS,
    SKIP_DIRS,
)
from codebase_cortex.embeddings.store import FAISSStore, SearchResult
from codebase_cortex.embeddings.clustering import TopicClusterer, TopicCluster


# --- EmbeddingIndexer tests ---


def test_code_chunk_creation():
    chunk = CodeChunk(
        file_path="src/main.py",
        chunk_type="function",
        name="main",
        content="def main(): pass",
        start_line=1,
        end_line=1,
    )
    assert chunk.file_path == "src/main.py"
    assert chunk.chunk_type == "function"


def test_indexer_collect_chunks(tmp_path: Path):
    # Create a simple Python file
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text("def hello():\n    return 'hi'\n\ndef goodbye():\n    return 'bye'\n")
    (src / "utils.py").write_text("class Helper:\n    pass\n")

    indexer = EmbeddingIndexer(repo_path=tmp_path)
    chunks = indexer.collect_chunks()

    assert len(chunks) >= 3  # 2 functions + 1 class
    names = [c.name for c in chunks]
    assert "hello" in names
    assert "goodbye" in names
    assert "Helper" in names


def test_indexer_skips_hidden_dirs(tmp_path: Path):
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "config.py").write_text("secret = True")

    venv = tmp_path / ".venv"
    venv.mkdir()
    (venv / "lib.py").write_text("x = 1")

    indexer = EmbeddingIndexer(repo_path=tmp_path)
    chunks = indexer.collect_chunks()
    assert len(chunks) == 0


def test_indexer_skips_large_files(tmp_path: Path):
    big_file = tmp_path / "big.py"
    big_file.write_text("x = 1\n" * 200_000)  # > 100KB

    indexer = EmbeddingIndexer(repo_path=tmp_path)
    chunks = indexer.collect_chunks()
    assert len(chunks) == 0


def test_indexer_chunk_python_module_fallback(tmp_path: Path):
    # File with no functions/classes should be treated as module
    (tmp_path / "config.py").write_text("DEBUG = True\nPORT = 8080\n")

    indexer = EmbeddingIndexer(repo_path=tmp_path)
    chunks = indexer.collect_chunks()
    assert len(chunks) == 1
    assert chunks[0].chunk_type == "module"


def test_indexer_non_python_file(tmp_path: Path):
    (tmp_path / "data.json").write_text('{"key": "value"}')

    indexer = EmbeddingIndexer(repo_path=tmp_path)
    chunks = indexer.collect_chunks()
    assert len(chunks) == 1
    assert chunks[0].chunk_type == "module"


# --- FAISSStore tests ---


def test_faiss_store_build_and_search(tmp_path: Path):
    chunks = [
        CodeChunk("a.py", "function", "foo", "def foo(): pass", 1, 1),
        CodeChunk("b.py", "function", "bar", "def bar(): return 1", 1, 1),
        CodeChunk("c.py", "class", "Baz", "class Baz: pass", 1, 1),
    ]
    # Use random embeddings (dim=8 for speed)
    embeddings = np.random.rand(3, 8).astype(np.float32)

    store = FAISSStore(index_dir=tmp_path / "index")
    store.build(embeddings, chunks)

    assert store.size == 3

    results = store.search(embeddings[0], k=2)
    assert len(results) == 2
    assert results[0].chunk.name == "foo"  # Most similar to itself
    assert results[0].score > 0


def test_faiss_store_save_and_load(tmp_path: Path):
    chunks = [
        CodeChunk("x.py", "function", "test", "def test(): pass", 1, 1),
    ]
    embeddings = np.random.rand(1, 8).astype(np.float32)

    store = FAISSStore(index_dir=tmp_path / "idx")
    store.build(embeddings, chunks)
    store.save()

    # Load into new store
    store2 = FAISSStore(index_dir=tmp_path / "idx")
    loaded = store2.load()
    assert loaded is True
    assert store2.size == 1
    assert store2.chunks[0].name == "test"


def test_faiss_store_empty_search(tmp_path: Path):
    store = FAISSStore(index_dir=tmp_path / "empty")
    results = store.search(np.zeros(8))
    assert results == []


def test_faiss_store_load_missing(tmp_path: Path):
    store = FAISSStore(index_dir=tmp_path / "nonexistent")
    assert store.load() is False


# --- TreeSitterChunker tests ---


class TestTreeSitterChunker:
    def test_python_regex_fallback(self):
        """Chunker uses regex fallback for Python when tree-sitter unavailable."""
        chunker = TreeSitterChunker()
        content = 'def hello():\n    return "hi"\n\ndef world():\n    return "world"\n'
        chunks = chunker.chunk_file(Path("example.py"), content)
        assert len(chunks) == 2
        assert chunks[0].name == "hello"
        assert chunks[0].chunk_type == "function"
        assert chunks[1].name == "world"

    def test_python_class_extraction(self):
        """Regex chunker extracts classes from Python files."""
        chunker = TreeSitterChunker()
        content = 'class Foo:\n    def bar(self):\n        pass\n\ndef standalone():\n    pass\n'
        chunks = chunker.chunk_file(Path("mod.py"), content)
        assert len(chunks) == 2
        assert chunks[0].chunk_type == "class"
        assert chunks[0].name == "Foo"
        assert chunks[1].chunk_type == "function"
        assert chunks[1].name == "standalone"

    def test_empty_content_returns_empty(self):
        chunker = TreeSitterChunker()
        assert chunker.chunk_file(Path("empty.py"), "") == []
        assert chunker.chunk_file(Path("blank.py"), "   \n  ") == []

    def test_unsupported_extension_fallback(self):
        """Unsupported file extensions produce a single module chunk."""
        chunker = TreeSitterChunker()
        content = "some content here\nline 2\n"
        chunks = chunker.chunk_file(Path("data.xyz"), content)
        assert len(chunks) == 1
        assert chunks[0].chunk_type == "module"
        assert chunks[0].name == "data.xyz"

    def test_python_no_definitions_becomes_module(self):
        """A Python file with no def/class becomes a module chunk."""
        chunker = TreeSitterChunker()
        content = "import os\nprint('hello')\n"
        chunks = chunker.chunk_file(Path("script.py"), content)
        assert len(chunks) == 1
        assert chunks[0].chunk_type == "module"

    def test_chunk_line_numbers(self):
        """Chunk start/end lines are correct."""
        chunker = TreeSitterChunker()
        content = "import os\n\ndef foo():\n    pass\n\ndef bar():\n    pass\n"
        chunks = chunker.chunk_file(Path("lines.py"), content)
        assert chunks[0].name == "foo"
        assert chunks[0].start_line == 3  # def foo() is line 3
        assert chunks[1].name == "bar"

    def test_large_file_truncation(self):
        """Fallback chunk content is truncated to 3000 chars."""
        chunker = TreeSitterChunker()
        content = "x" * 5000
        chunks = chunker.chunk_file(Path("big.txt"), content)
        assert len(chunks[0].content) == 3000


# --- FAISSStore ID operations tests ---


class TestFAISSStoreIDOperations:
    def _make_store(self, tmp_path: Path) -> tuple[FAISSStore, np.ndarray, list[CodeChunk]]:
        """Helper to create a store with sample data."""
        store = FAISSStore(index_dir=tmp_path / "index")
        chunks = [
            CodeChunk("a.py", "function", "func_a", "def func_a(): pass", 1, 1),
            CodeChunk("a.py", "function", "func_b", "def func_b(): pass", 2, 2),
            CodeChunk("b.py", "class", "ClassB", "class ClassB: pass", 1, 1),
            CodeChunk("c.py", "module", "c.py", "# module c", 1, 1),
        ]
        embeddings = np.random.rand(4, 384).astype(np.float32)
        store.build(embeddings, chunks)
        return store, embeddings, chunks

    def test_build_creates_id_map(self, tmp_path):
        store, _, chunks = self._make_store(tmp_path)
        assert store.size == 4
        assert len(store._id_to_idx) == 4
        assert store._id_counter == 4

    def test_get_chunk_ids_for_files(self, tmp_path):
        store, _, _ = self._make_store(tmp_path)
        ids = store.get_chunk_ids_for_files(["a.py"])
        assert len(ids) == 2  # func_a and func_b

    def test_get_chunk_ids_for_nonexistent_file(self, tmp_path):
        store, _, _ = self._make_store(tmp_path)
        ids = store.get_chunk_ids_for_files(["nonexistent.py"])
        assert ids == []

    def test_remove_ids(self, tmp_path):
        store, _, _ = self._make_store(tmp_path)
        ids = store.get_chunk_ids_for_files(["a.py"])
        store.remove_ids(ids)
        assert store.size == 2
        assert len(store.chunks) == 2
        # Remaining chunks are from b.py and c.py
        remaining_files = {c.file_path for c in store.chunks}
        assert remaining_files == {"b.py", "c.py"}

    def test_remove_empty_ids_noop(self, tmp_path):
        store, _, _ = self._make_store(tmp_path)
        store.remove_ids([])
        assert store.size == 4

    def test_add_to_existing_index(self, tmp_path):
        store, _, _ = self._make_store(tmp_path)
        new_chunks = [
            CodeChunk("d.py", "function", "func_d", "def func_d(): pass", 1, 1),
        ]
        new_embeddings = np.random.rand(1, 384).astype(np.float32)
        store.add(new_chunks, new_embeddings)
        assert store.size == 5
        assert len(store.chunks) == 5
        assert store._id_counter == 5

    def test_save_and_load_preserves_id_map(self, tmp_path):
        store, embeddings, chunks = self._make_store(tmp_path)
        store.save()

        loaded = FAISSStore(index_dir=tmp_path / "index")
        assert loaded.load() is True
        assert loaded.size == 4
        assert loaded._id_counter == 4
        assert len(loaded._id_to_idx) == 4
        assert len(loaded.chunks) == 4

    def test_search_after_remove_and_add(self, tmp_path):
        store, _, _ = self._make_store(tmp_path)
        # Remove a.py chunks
        ids = store.get_chunk_ids_for_files(["a.py"])
        store.remove_ids(ids)
        # Add new chunk
        new_chunks = [
            CodeChunk("e.py", "function", "func_e", "def func_e(): pass", 1, 1),
        ]
        new_embeddings = np.random.rand(1, 384).astype(np.float32)
        store.add(new_chunks, new_embeddings)
        # Search should work without errors
        query = np.random.rand(1, 384).astype(np.float32)
        results = store.search(query, k=5)
        assert len(results) <= 3  # 2 original + 1 new

    def test_build_empty(self, tmp_path):
        store = FAISSStore(index_dir=tmp_path / "index")
        store.build(np.array([]), [])
        assert store.size == 0
        assert store.search(np.random.rand(1, 384).astype(np.float32)) == []


# --- Incremental indexing tests ---


class TestIncrementalIndexing:
    def _create_repo(self, tmp_path: Path) -> Path:
        """Create a minimal repo structure for indexing."""
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "hello.py").write_text('def greet():\n    return "hello"\n')
        (repo / "utils.py").write_text('def add(a, b):\n    return a + b\n')
        return repo

    def test_compute_file_hashes(self, tmp_path):
        repo = self._create_repo(tmp_path)
        indexer = EmbeddingIndexer(repo_path=repo)
        hashes = indexer._compute_file_hashes()
        assert "hello.py" in hashes
        assert "utils.py" in hashes
        assert len(hashes["hello.py"]) == 32  # MD5 hex length

    def test_hash_manifest_save_and_load(self, tmp_path):
        repo = self._create_repo(tmp_path)
        indexer = EmbeddingIndexer(repo_path=repo)
        hashes = {"file.py": "abc123"}
        indexer._save_hash_manifest(hashes)
        loaded = indexer._load_hash_manifest()
        assert loaded == hashes

    def test_hash_manifest_empty_when_missing(self, tmp_path):
        repo = self._create_repo(tmp_path)
        indexer = EmbeddingIndexer(repo_path=repo)
        assert indexer._load_hash_manifest() == {}

    @staticmethod
    def _dynamic_embed(chunks):
        """Return random embeddings matching the number of chunks."""
        return np.random.rand(len(chunks), 384).astype(np.float32)

    @patch.object(EmbeddingIndexer, "embed_chunks")
    def test_incremental_detects_added_files(self, mock_embed, tmp_path):
        """First incremental run with no previous manifest treats all files as added."""
        repo = self._create_repo(tmp_path)
        indexer = EmbeddingIndexer(repo_path=repo)
        store = FAISSStore(index_dir=repo / ".cortex" / "faiss_index")

        mock_embed.side_effect = self._dynamic_embed

        result = indexer.index_codebase_incremental(store)
        assert result.files_added == 2
        assert result.files_modified == 0
        assert result.files_removed == 0
        assert result.chunks_re_embedded > 0

    @patch.object(EmbeddingIndexer, "embed_chunks")
    def test_incremental_detects_modified_files(self, mock_embed, tmp_path):
        """Modifying a file triggers re-embedding only that file's chunks."""
        repo = self._create_repo(tmp_path)
        indexer = EmbeddingIndexer(repo_path=repo)
        store = FAISSStore(index_dir=repo / ".cortex" / "faiss_index")

        mock_embed.side_effect = self._dynamic_embed
        indexer.index_codebase_incremental(store)

        # Modify a file
        (repo / "hello.py").write_text('def greet():\n    return "hi there"\n')

        result = indexer.index_codebase_incremental(store)
        assert result.files_added == 0
        assert result.files_modified == 1
        assert result.files_removed == 0

    @patch.object(EmbeddingIndexer, "embed_chunks")
    def test_incremental_detects_removed_files(self, mock_embed, tmp_path):
        """Deleting a file triggers removal of its chunks."""
        repo = self._create_repo(tmp_path)
        indexer = EmbeddingIndexer(repo_path=repo)
        store = FAISSStore(index_dir=repo / ".cortex" / "faiss_index")

        mock_embed.side_effect = self._dynamic_embed
        indexer.index_codebase_incremental(store)

        # Remove a file
        (repo / "utils.py").unlink()

        result = indexer.index_codebase_incremental(store)
        assert result.files_added == 0
        assert result.files_modified == 0
        assert result.files_removed == 1

    @patch.object(EmbeddingIndexer, "embed_chunks")
    def test_incremental_no_changes(self, mock_embed, tmp_path):
        """No changes means nothing is re-embedded."""
        repo = self._create_repo(tmp_path)
        indexer = EmbeddingIndexer(repo_path=repo)
        store = FAISSStore(index_dir=repo / ".cortex" / "faiss_index")

        mock_embed.side_effect = self._dynamic_embed
        indexer.index_codebase_incremental(store)

        # Second run, no changes
        result = indexer.index_codebase_incremental(store)
        assert result.files_added == 0
        assert result.files_modified == 0
        assert result.files_removed == 0
        assert result.chunks_re_embedded == 0


# --- TopicClusterer tests ---


def test_clusterer_too_few_chunks():
    chunks = [CodeChunk("a.py", "function", "foo", "x", 1, 1)]
    embeddings = np.random.rand(1, 8)

    clusterer = TopicClusterer(min_cluster_size=3)
    topics = clusterer.cluster(embeddings, chunks)

    # Should return single cluster with all chunks
    assert len(topics) == 1
    assert topics[0].size == 1


def test_clusterer_with_enough_data():
    # Create 3 tight clusters of 5 points each
    np.random.seed(42)
    cluster1 = np.random.rand(5, 8) + np.array([0, 0, 0, 0, 0, 0, 0, 0])
    cluster2 = np.random.rand(5, 8) + np.array([10, 10, 10, 10, 10, 10, 10, 10])
    cluster3 = np.random.rand(5, 8) + np.array([20, 20, 20, 20, 20, 20, 20, 20])
    embeddings = np.vstack([cluster1, cluster2, cluster3])

    chunks = [
        CodeChunk(f"dir{i // 5}/file{i}.py", "function", f"func{i}", "code", 1, 1)
        for i in range(15)
    ]

    clusterer = TopicClusterer(min_cluster_size=3, min_samples=2)
    topics = clusterer.cluster(embeddings, chunks)

    # Should find some clusters (exact number depends on HDBSCAN)
    assert len(topics) >= 1


def test_clusterer_to_markdown():
    topics = [
        TopicCluster(
            cluster_id=0,
            label="src: main, helper",
            chunks=[
                CodeChunk("src/main.py", "function", "main", "x", 1, 1),
                CodeChunk("src/helper.py", "function", "helper", "x", 1, 1),
            ],
        ),
    ]

    clusterer = TopicClusterer()
    md = clusterer.to_markdown(topics)
    assert "Knowledge Map" in md
    assert "src: main, helper" in md
    assert "2 chunks" in md


def test_clusterer_empty_markdown():
    clusterer = TopicClusterer()
    md = clusterer.to_markdown([])
    assert "No topics" in md
