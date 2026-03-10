"""Tests for Phase 3 pipeline nodes: SectionRouter, DocValidator, TOCGenerator, OutputRouter."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from codebase_cortex.state import CortexState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(tmp_path: Path):
    from codebase_cortex.config import Settings

    cortex_dir = tmp_path / ".cortex"
    cortex_dir.mkdir(exist_ok=True)
    return Settings(repo_path=tmp_path, cortex_dir=cortex_dir, doc_output="local")


def _patch_litellm(response_text: str):
    """Patch litellm.acompletion to return a mock response."""
    mock_response = AsyncMock()
    mock_response.choices = [AsyncMock()]
    mock_response.choices[0].message.content = response_text
    mock_response.usage = AsyncMock()
    mock_response.usage.prompt_tokens = 100
    mock_response.usage.completion_tokens = 50
    return patch("litellm.acompletion", return_value=mock_response)


# ---------------------------------------------------------------------------
# SectionRouter
# ---------------------------------------------------------------------------


class TestSectionRouter:
    @pytest.mark.asyncio
    async def test_returns_targeted_sections(self, tmp_path: Path):
        from codebase_cortex.agents.section_router import SectionRouterAgent

        settings = _make_settings(tmp_path)
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "arch.md").write_text("# Architecture\n\n## Overview\n\nContent.\n")

        # Initialize meta so fetch_page_list returns pages
        from codebase_cortex.backends.local_markdown import LocalMarkdownBackend
        backend = LocalMarkdownBackend(settings)
        await backend.write_page("arch.md", "Architecture", "# Architecture\n\n## Overview\n\nContent.", "create")

        llm_response = json.dumps([
            {"page": "arch.md", "section": "## Overview", "reason": "API changed", "priority": "high"}
        ])

        with _patch_litellm(llm_response):
            agent = SectionRouterAgent(settings)
            result = await agent.run(CortexState(analysis="Changed the auth module"))

        assert len(result["targeted_sections"]) == 1
        assert result["targeted_sections"][0]["page"] == "arch.md"

    @pytest.mark.asyncio
    async def test_empty_analysis_returns_empty(self, tmp_path: Path):
        from codebase_cortex.agents.section_router import SectionRouterAgent

        settings = _make_settings(tmp_path)
        agent = SectionRouterAgent(settings)
        result = await agent.run(CortexState(analysis=""))
        assert result["targeted_sections"] == []

    @pytest.mark.asyncio
    async def test_no_pages_returns_empty(self, tmp_path: Path):
        """First run with no docs — SectionRouter returns empty, lets DocWriter handle."""
        from codebase_cortex.agents.section_router import SectionRouterAgent

        settings = _make_settings(tmp_path)
        (tmp_path / "docs").mkdir(exist_ok=True)
        agent = SectionRouterAgent(settings)
        result = await agent.run(CortexState(analysis="Some analysis"))
        assert result["targeted_sections"] == []


# ---------------------------------------------------------------------------
# DocValidator
# ---------------------------------------------------------------------------


class TestDocValidator:
    @pytest.mark.asyncio
    async def test_skips_at_standard_level(self, tmp_path: Path):
        from codebase_cortex.agents.doc_validator import DocValidatorAgent

        settings = _make_settings(tmp_path)
        agent = DocValidatorAgent(settings)

        updates = [{"title": "Arch", "content": "# Arch\n\nContent.", "action": "update"}]
        result = await agent.run(CortexState(
            doc_updates=updates,
            detail_level="standard",
        ))

        assert len(result["validated_updates"]) == 1
        assert result["validated_updates"][0]["confidence"] == "high"
        assert result["validation_issues"] == []

    @pytest.mark.asyncio
    async def test_validates_at_detailed_level(self, tmp_path: Path):
        from codebase_cortex.agents.doc_validator import DocValidatorAgent

        settings = _make_settings(tmp_path)

        llm_response = json.dumps([{"confidence": "medium", "issues": ["Minor type discrepancy"]}])

        updates = [{"title": "API", "content": "# API\n\nEndpoints.", "action": "update"}]
        with _patch_litellm(llm_response):
            agent = DocValidatorAgent(settings)
            result = await agent.run(CortexState(
                doc_updates=updates,
                detail_level="detailed",
                analysis="Changed API endpoints",
            ))

        assert len(result["validated_updates"]) == 1
        assert result["validated_updates"][0]["confidence"] == "medium"
        assert len(result["validation_issues"]) == 1

    @pytest.mark.asyncio
    async def test_excludes_fundamentally_wrong(self, tmp_path: Path):
        from codebase_cortex.agents.doc_validator import DocValidatorAgent

        settings = _make_settings(tmp_path)

        llm_response = json.dumps([{
            "confidence": "low",
            "issues": ["References nonexistent function FooBar()"]
        }])

        updates = [{"title": "Bad", "content": "# Bad\n\nWrong stuff.", "action": "update"}]
        with _patch_litellm(llm_response):
            agent = DocValidatorAgent(settings)
            result = await agent.run(CortexState(
                doc_updates=updates,
                detail_level="detailed",
                analysis="Refactored auth",
            ))

        # Should be excluded from validated_updates
        assert len(result["validated_updates"]) == 0
        assert len(result["validation_issues"]) == 1
        assert result["validation_issues"][0]["action"] == "excluded"

    @pytest.mark.asyncio
    async def test_low_confidence_adds_marker(self, tmp_path: Path):
        from codebase_cortex.agents.doc_validator import DocValidatorAgent, LOW_CONFIDENCE_MARKER

        settings = _make_settings(tmp_path)

        llm_response = json.dumps([{
            "confidence": "low",
            "issues": ["Wrong return type described"]
        }])

        updates = [{"title": "API", "content": "Returns string.", "action": "update"}]
        with _patch_litellm(llm_response):
            agent = DocValidatorAgent(settings)
            result = await agent.run(CortexState(
                doc_updates=updates,
                detail_level="comprehensive",
                analysis="Changed return types",
            ))

        assert len(result["validated_updates"]) == 1
        assert LOW_CONFIDENCE_MARKER in result["validated_updates"][0]["content"]

    @pytest.mark.asyncio
    async def test_no_updates_returns_empty(self, tmp_path: Path):
        from codebase_cortex.agents.doc_validator import DocValidatorAgent

        settings = _make_settings(tmp_path)
        agent = DocValidatorAgent(settings)
        result = await agent.run(CortexState(doc_updates=[]))
        assert result["validated_updates"] == []


# ---------------------------------------------------------------------------
# TOCGenerator
# ---------------------------------------------------------------------------


class TestTOCGenerator:
    @pytest.mark.asyncio
    async def test_inserts_toc_markers(self, tmp_path: Path):
        from codebase_cortex.agents.toc_generator import TOCGeneratorAgent

        settings = _make_settings(tmp_path)
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "arch.md").write_text(
            "# Architecture\n\n## Overview\n\nText.\n\n## Components\n\nMore text.\n"
        )

        # Initialize meta
        from codebase_cortex.backends.local_markdown import LocalMarkdownBackend
        backend = LocalMarkdownBackend(settings)
        await backend.write_page(
            "arch.md", "Architecture",
            "# Architecture\n\n## Overview\n\nText.\n\n## Components\n\nMore text.",
            "create",
        )

        agent = TOCGeneratorAgent(settings)
        await agent.run(CortexState(detail_level="standard"))

        content = (docs_dir / "arch.md").read_text()
        assert "<!-- cortex:toc -->" in content
        assert "<!-- cortex:toc:end -->" in content
        assert "Overview" in content
        assert "Components" in content

    @pytest.mark.asyncio
    async def test_generates_index_md(self, tmp_path: Path):
        from codebase_cortex.agents.toc_generator import TOCGeneratorAgent

        settings = _make_settings(tmp_path)
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()

        from codebase_cortex.backends.local_markdown import LocalMarkdownBackend
        backend = LocalMarkdownBackend(settings)
        await backend.write_page("arch.md", "Architecture", "# Architecture\n\nText.", "create")

        agent = TOCGeneratorAgent(settings)
        await agent.run(CortexState(detail_level="standard"))

        index = docs_dir / "INDEX.md"
        assert index.exists()
        content = index.read_text()
        assert "Documentation Index" in content
        assert "Architecture" in content

    @pytest.mark.asyncio
    async def test_updates_toc_replaces_existing(self, tmp_path: Path):
        from codebase_cortex.agents.toc_generator import TOCGeneratorAgent, TOC_START, TOC_END

        settings = _make_settings(tmp_path)
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()

        # File with existing TOC
        existing = (
            "# Doc\n\n"
            f"{TOC_START}\n- old toc\n{TOC_END}\n\n"
            "## Section A\n\nContent A.\n\n## Section B\n\nContent B.\n"
        )
        (docs_dir / "doc.md").write_text(existing)

        from codebase_cortex.backends.local_markdown import LocalMarkdownBackend
        backend = LocalMarkdownBackend(settings)
        await backend.write_page("doc.md", "Doc", existing, "create")

        agent = TOCGeneratorAgent(settings)
        await agent.run(CortexState())

        content = (docs_dir / "doc.md").read_text()
        assert "old toc" not in content
        assert "Section A" in content
        assert "Section B" in content

    @pytest.mark.asyncio
    async def test_writes_run_metrics(self, tmp_path: Path):
        from codebase_cortex.agents.toc_generator import TOCGeneratorAgent

        settings = _make_settings(tmp_path)
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()

        from codebase_cortex.backends.local_markdown import LocalMarkdownBackend
        backend = LocalMarkdownBackend(settings)
        await backend.write_page("a.md", "A", "# A\n\nText.", "create")

        agent = TOCGeneratorAgent(settings)
        await agent.run(CortexState(run_metrics={"total_input_tokens": 500, "cost": 0.01}))

        import json
        meta = json.loads((docs_dir / ".cortex-meta.json").read_text())
        assert meta["last_run"]["total_input_tokens"] == 500


# ---------------------------------------------------------------------------
# OutputRouter
# ---------------------------------------------------------------------------


class TestOutputRouter:
    @pytest.mark.asyncio
    async def test_apply_mode(self, tmp_path: Path):
        from codebase_cortex.agents.output_router import OutputRouterAgent
        from codebase_cortex.config import Settings

        settings = Settings(doc_strategy="branch-aware", repo_path=tmp_path)
        agent = OutputRouterAgent(settings=settings)
        result = await agent.run(CortexState(
            output_mode="apply",
            validated_updates=[{"title": "Arch", "action": "update", "confidence": "high"}],
        ))
        assert "apply mode" in result["output_summary"]
        assert "Arch" in result["output_summary"]

    @pytest.mark.asyncio
    async def test_dry_run_mode(self, tmp_path: Path):
        from codebase_cortex.agents.output_router import OutputRouterAgent
        from codebase_cortex.config import Settings

        settings = Settings(doc_strategy="branch-aware", repo_path=tmp_path)
        agent = OutputRouterAgent(settings=settings)
        result = await agent.run(CortexState(
            output_mode="dry-run",
            validated_updates=[{"title": "API", "action": "update"}],
            tasks_created=[{"title": "Doc auth", "priority": "high"}],
        ))
        assert "dry-run" in result["output_summary"]
        assert "No changes were written" in result["output_summary"]
        assert "API" in result["output_summary"]
        assert "Doc auth" in result["output_summary"]

    @pytest.mark.asyncio
    async def test_propose_mode(self, tmp_path: Path):
        from codebase_cortex.agents.output_router import OutputRouterAgent

        settings = _make_settings(tmp_path)
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "arch.md").write_text("# Arch\n\nContent.")

        agent = OutputRouterAgent(settings)
        result = await agent.run(CortexState(
            output_mode="propose",
            validated_updates=[{"title": "Arch", "page_path": "arch.md", "action": "update"}],
        ))
        assert "staged" in result["output_summary"]

        # Check proposed directory was created
        proposed = tmp_path / ".cortex" / "proposed"
        assert proposed.exists()


# ---------------------------------------------------------------------------
# Graph routing
# ---------------------------------------------------------------------------


class TestGraphRouting:
    def test_should_run_section_router(self):
        from codebase_cortex.graph import should_run_section_router

        assert should_run_section_router({"analysis": "stuff"}) == "semantic_finder"
        assert should_run_section_router({"analysis": ""}) == "end"
        assert should_run_section_router({}) == "end"

    def test_should_run_doc_writer(self):
        from codebase_cortex.graph import should_run_doc_writer

        assert should_run_doc_writer({"targeted_sections": [{"page": "a.md"}]}) == "doc_writer"
        assert should_run_doc_writer({"targeted_sections": []}) == "end"
        assert should_run_doc_writer({}) == "end"

    def test_should_run_validator(self):
        from codebase_cortex.graph import should_run_validator

        assert should_run_validator({"detail_level": "standard"}) == "toc_generator"
        assert should_run_validator({"detail_level": "detailed"}) == "doc_validator"
        assert should_run_validator({"detail_level": "comprehensive"}) == "doc_validator"
        assert should_run_validator({}) == "toc_generator"  # default is standard

    def test_should_run_sprint(self):
        from codebase_cortex.graph import should_run_sprint

        assert should_run_sprint({"validated_updates": [{}]}) == "sprint_reporter"
        assert should_run_sprint({"tasks_created": [{}]}) == "sprint_reporter"
        assert should_run_sprint({"doc_updates": [{}]}) == "sprint_reporter"
        assert should_run_sprint({}) == "end"

    def test_build_graph_compiles(self):
        from codebase_cortex.graph import build_graph

        graph = build_graph()
        compiled = graph.compile()
        assert compiled is not None
