"""TreeSitterChunker — language-aware code chunker using tree-sitter AST parsing.

Falls back to regex-based chunking if tree-sitter is not available.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from codebase_cortex.embeddings.indexer import CodeChunk

logger = logging.getLogger("cortex")

# Try to import tree-sitter; graceful fallback if unavailable
_tree_sitter_available = False
try:
    import tree_sitter_languages
    _tree_sitter_available = True
except ImportError:
    pass


LANGUAGE_MAP = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".rb": "ruby",
    ".php": "php",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
}

# AST node types to extract as chunks, per language
CHUNK_NODES: dict[str, list[str]] = {
    "python": ["function_definition", "class_definition"],
    "javascript": ["function_declaration", "class_declaration", "arrow_function", "method_definition"],
    "typescript": ["function_declaration", "class_declaration", "method_definition", "interface_declaration"],
    "go": ["function_declaration", "method_declaration", "type_declaration"],
    "rust": ["function_item", "impl_item", "struct_item", "enum_item"],
    "java": ["method_declaration", "class_declaration", "interface_declaration"],
    "ruby": ["method", "class", "module"],
    "php": ["function_definition", "class_declaration", "method_declaration"],
    "c": ["function_definition", "struct_specifier"],
    "cpp": ["function_definition", "class_specifier", "struct_specifier"],
}


class TreeSitterChunker:
    """Language-aware code chunker using tree-sitter AST parsing.

    Falls back to regex/whole-file chunking for unsupported languages
    or when tree-sitter is not installed.
    """

    def __init__(self) -> None:
        self._parsers: dict[str, object] = {}

    @property
    def is_available(self) -> bool:
        """Whether tree-sitter is available."""
        return _tree_sitter_available

    def chunk_file(self, file_path: Path, content: str) -> list[CodeChunk]:
        """Parse file and extract code chunks.

        Uses tree-sitter if available and language is supported,
        otherwise falls back to regex-based Python chunking or whole-file.
        """
        if not content.strip():
            return []

        lang = LANGUAGE_MAP.get(file_path.suffix)

        if lang and _tree_sitter_available:
            try:
                return self._chunk_with_tree_sitter(file_path, content, lang)
            except Exception as e:
                logger.debug(f"Tree-sitter chunking failed for {file_path}: {e}")

        # Fallback: regex for Python, whole-file for others
        if file_path.suffix == ".py":
            return self._chunk_python_regex(file_path, content)
        return self._fallback_chunk(file_path, content)

    def _chunk_with_tree_sitter(
        self, file_path: Path, content: str, lang: str
    ) -> list[CodeChunk]:
        """Chunk using tree-sitter AST parsing."""
        parser = self._get_parser(lang)
        tree = parser.parse(content.encode())

        target_types = set(CHUNK_NODES.get(lang, []))
        chunks: list[CodeChunk] = []

        for node in self._walk_for_chunks(tree.root_node, target_types):
            name = self._extract_name(node, content)
            chunk_type = self._classify_node(node.type)

            chunks.append(CodeChunk(
                file_path=str(file_path),
                chunk_type=chunk_type,
                name=name,
                content=content[node.start_byte:node.end_byte],
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
            ))

        if not chunks:
            return self._fallback_chunk(file_path, content)
        return chunks

    def _get_parser(self, lang: str):
        """Get or create a tree-sitter parser for the given language."""
        if lang not in self._parsers:
            self._parsers[lang] = tree_sitter_languages.get_parser(lang)
        return self._parsers[lang]

    def _walk_for_chunks(self, node, target_types: set[str]):
        """Walk the AST and yield nodes matching target types."""
        if node.type in target_types:
            yield node
            return  # Don't recurse into matched nodes

        for child in node.children:
            yield from self._walk_for_chunks(child, target_types)

    @staticmethod
    def _extract_name(node, content: str) -> str:
        """Extract the name of a definition node."""
        for child in node.children:
            if child.type in ("identifier", "name", "property_identifier"):
                return content[child.start_byte:child.end_byte]
        # Try first identifier in any child
        for child in node.children:
            for sub in child.children:
                if sub.type in ("identifier", "name"):
                    return content[sub.start_byte:sub.end_byte]
        return "anonymous"

    @staticmethod
    def _classify_node(node_type: str) -> str:
        """Map tree-sitter node type to CodeChunk chunk_type."""
        if "class" in node_type or "struct" in node_type or "enum" in node_type:
            return "class"
        if "function" in node_type or "method" in node_type:
            return "function"
        if "interface" in node_type:
            return "class"
        if "impl" in node_type:
            return "class"
        if "module" in node_type:
            return "module"
        return "function"

    def _chunk_python_regex(self, file_path: Path, content: str) -> list[CodeChunk]:
        """Regex-based Python chunking (fallback when tree-sitter unavailable)."""
        chunks: list[CodeChunk] = []
        lines = content.split("\n")
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
                if current_def is not None:
                    chunk_content = "\n".join(lines[current_start:i])
                    if chunk_content.strip():
                        chunks.append(CodeChunk(
                            file_path=str(file_path),
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

        if current_def is not None:
            chunk_content = "\n".join(lines[current_start:])
            if chunk_content.strip():
                chunks.append(CodeChunk(
                    file_path=str(file_path),
                    chunk_type=current_type,
                    name=current_name,
                    content=chunk_content,
                    start_line=current_start + 1,
                    end_line=len(lines),
                ))

        if not chunks and content.strip():
            return self._fallback_chunk(file_path, content)
        return chunks

    def _fallback_chunk(self, file_path: Path, content: str) -> list[CodeChunk]:
        """Whole-file chunk for unsupported languages (truncated)."""
        return [CodeChunk(
            file_path=str(file_path),
            chunk_type="module",
            name=file_path.name,
            content=content[:3000],
            start_line=1,
            end_line=content.count("\n") + 1,
        )]
