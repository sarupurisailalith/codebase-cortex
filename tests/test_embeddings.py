"""Tests for embedding pipeline."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

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
