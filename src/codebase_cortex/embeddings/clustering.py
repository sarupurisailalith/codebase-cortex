"""HDBSCAN topic clustering for Knowledge Map generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from collections import defaultdict

import hdbscan
import numpy as np

from codebase_cortex.embeddings.indexer import CodeChunk


@dataclass
class TopicCluster:
    """A cluster of related code chunks representing a topic."""

    cluster_id: int
    label: str
    chunks: list[CodeChunk] = field(default_factory=list)
    centroid: np.ndarray | None = field(default=None, repr=False)

    @property
    def file_paths(self) -> list[str]:
        """Unique file paths in this cluster."""
        return sorted(set(c.file_path for c in self.chunks))

    @property
    def size(self) -> int:
        return len(self.chunks)


@dataclass
class TopicClusterer:
    """Clusters code embeddings into topics using HDBSCAN.

    HDBSCAN is density-based — it automatically determines the number
    of clusters and marks sparse points as noise (cluster_id = -1).
    """

    min_cluster_size: int = 3
    min_samples: int = 2

    def cluster(
        self,
        embeddings: np.ndarray,
        chunks: list[CodeChunk],
    ) -> list[TopicCluster]:
        """Cluster embeddings and return topic groups.

        Args:
            embeddings: Array of shape (n, dimension).
            chunks: Corresponding code chunks.

        Returns:
            List of TopicCluster, excluding noise cluster.
        """
        if len(embeddings) < self.min_cluster_size:
            # Too few chunks to cluster meaningfully
            return [TopicCluster(
                cluster_id=0,
                label=self._generate_label(chunks),
                chunks=list(chunks),
            )] if chunks else []

        clusterer = hdbscan.HDBSCAN(
            min_cluster_size=self.min_cluster_size,
            min_samples=self.min_samples,
            metric="euclidean",
        )
        labels = clusterer.fit_predict(embeddings.astype(np.float64))

        # Group chunks by cluster
        cluster_map: dict[int, list[tuple[CodeChunk, np.ndarray]]] = defaultdict(list)
        for label, chunk, emb in zip(labels, chunks, embeddings):
            cluster_map[int(label)].append((chunk, emb))

        topics = []
        for cluster_id, items in sorted(cluster_map.items()):
            if cluster_id == -1:
                continue  # Skip noise

            cluster_chunks = [item[0] for item in items]
            cluster_embeddings = np.array([item[1] for item in items])
            centroid = cluster_embeddings.mean(axis=0)

            topics.append(TopicCluster(
                cluster_id=cluster_id,
                label=self._generate_label(cluster_chunks),
                chunks=cluster_chunks,
                centroid=centroid,
            ))

        return topics

    @staticmethod
    def _generate_label(chunks: list[CodeChunk]) -> str:
        """Generate a descriptive label from chunk metadata.

        Uses the most common directory and chunk names to create
        a human-readable topic label.
        """
        if not chunks:
            return "Unknown"

        # Find most common directory
        dirs = defaultdict(int)
        names = defaultdict(int)
        for c in chunks:
            parts = c.file_path.split("/")
            if len(parts) > 1:
                dirs[parts[0]] += 1
            names[c.name] += 1

        top_dir = max(dirs, key=dirs.get) if dirs else ""
        # Pick top 2 most common names
        top_names = sorted(names, key=names.get, reverse=True)[:2]

        if top_dir:
            return f"{top_dir}: {', '.join(top_names)}"
        return ", ".join(top_names)

    def to_markdown(self, topics: list[TopicCluster]) -> str:
        """Render topic clusters as a Markdown Knowledge Map."""
        if not topics:
            return "No topics identified yet.\n"

        lines = ["# Knowledge Map\n"]
        lines.append(f"*{sum(t.size for t in topics)} code chunks across {len(topics)} topics*\n")

        for topic in sorted(topics, key=lambda t: t.size, reverse=True):
            lines.append(f"## {topic.label}")
            lines.append(f"*{topic.size} chunks across {len(topic.file_paths)} files*\n")
            for fp in topic.file_paths[:10]:
                lines.append(f"- `{fp}`")
            if len(topic.file_paths) > 10:
                lines.append(f"- ... and {len(topic.file_paths) - 10} more files")
            lines.append("")

        return "\n".join(lines)
