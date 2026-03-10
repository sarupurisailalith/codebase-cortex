"""LangGraph StateGraph definition for the Cortex pipeline."""

from __future__ import annotations

from langgraph.graph import StateGraph, START, END

from codebase_cortex.config import Settings
from codebase_cortex.state import CortexState


# ---------------------------------------------------------------------------
# Node wrapper functions
# ---------------------------------------------------------------------------


async def code_analyzer_node(state: CortexState) -> dict:
    """Analyze git diffs and identify changes."""
    from codebase_cortex.agents.code_analyzer import CodeAnalyzerAgent

    agent = CodeAnalyzerAgent(Settings.from_env())
    return await agent.run(state)


async def semantic_finder_node(state: CortexState) -> dict:
    """Find semantically related documentation."""
    from codebase_cortex.agents.semantic_finder import SemanticFinderAgent

    agent = SemanticFinderAgent(Settings.from_env())
    return await agent.run(state)


async def section_router_node(state: CortexState) -> dict:
    """Triage: identify which doc sections need updating."""
    from codebase_cortex.agents.section_router import SectionRouterAgent

    agent = SectionRouterAgent(Settings.from_env())
    return await agent.run(state)


async def doc_writer_node(state: CortexState) -> dict:
    """Write or update documentation pages."""
    from codebase_cortex.agents.doc_writer import DocWriterAgent
    from codebase_cortex.backends import get_backend

    settings = Settings.from_env()
    agent = DocWriterAgent(settings, backend=get_backend(settings))
    return await agent.run(state)


async def doc_validator_node(state: CortexState) -> dict:
    """Validate documentation accuracy against source code."""
    from codebase_cortex.agents.doc_validator import DocValidatorAgent

    agent = DocValidatorAgent(Settings.from_env())
    return await agent.run(state)


async def toc_generator_node(state: CortexState) -> dict:
    """Update TOC markers, meta index, and INDEX.md."""
    from codebase_cortex.agents.toc_generator import TOCGeneratorAgent

    agent = TOCGeneratorAgent(Settings.from_env())
    return await agent.run(state)


async def task_creator_node(state: CortexState) -> dict:
    """Create tasks for undocumented areas."""
    from codebase_cortex.agents.task_creator import TaskCreatorAgent
    from codebase_cortex.backends import get_backend

    settings = Settings.from_env()
    agent = TaskCreatorAgent(settings, backend=get_backend(settings))
    return await agent.run(state)


async def sprint_reporter_node(state: CortexState) -> dict:
    """Generate sprint summary report."""
    from codebase_cortex.agents.sprint_reporter import SprintReporterAgent
    from codebase_cortex.backends import get_backend

    settings = Settings.from_env()
    agent = SprintReporterAgent(settings, backend=get_backend(settings))
    return await agent.run(state)


async def output_router_node(state: CortexState) -> dict:
    """Route output based on mode (apply/propose/dry-run)."""
    from codebase_cortex.agents.output_router import OutputRouterAgent

    agent = OutputRouterAgent(Settings.from_env())
    return await agent.run(state)


# ---------------------------------------------------------------------------
# Conditional routing functions
# ---------------------------------------------------------------------------


def should_run_section_router(state: CortexState) -> str:
    """After code_analyzer: route to semantic_finder if analysis exists."""
    return "semantic_finder" if state.get("analysis") else "end"


def should_run_doc_writer(state: CortexState) -> str:
    """After section_router: route to doc_writer if sections identified."""
    return "doc_writer" if state.get("targeted_sections") else "end"


def should_run_validator(state: CortexState) -> str:
    """After doc_writer: skip validator at 'standard' detail level."""
    if state.get("detail_level", "standard") == "standard":
        return "toc_generator"
    return "doc_validator"


def should_run_sprint(state: CortexState) -> str:
    """After task_creator: route to sprint_reporter if outputs exist."""
    has_output = state.get("validated_updates") or state.get("doc_updates") or state.get("tasks_created")
    return "sprint_reporter" if has_output else "end"


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------


def build_graph() -> StateGraph:
    """Build and compile the Cortex pipeline graph.

    Pipeline flow (v0.2):
        code_analyzer -> semantic_finder -> section_router -> doc_writer
        -> doc_validator -> toc_generator -> task_creator -> sprint_reporter
        -> output_router -> END

    Conditional exits:
        - After code_analyzer: END if no analysis
        - After section_router: END if no targeted sections
        - After doc_writer: skip doc_validator at "standard" detail level
        - After task_creator: END if no updates or tasks
    """
    graph = StateGraph(CortexState)

    # Add all nodes
    graph.add_node("code_analyzer", code_analyzer_node)
    graph.add_node("semantic_finder", semantic_finder_node)
    graph.add_node("section_router", section_router_node)
    graph.add_node("doc_writer", doc_writer_node)
    graph.add_node("doc_validator", doc_validator_node)
    graph.add_node("toc_generator", toc_generator_node)
    graph.add_node("task_creator", task_creator_node)
    graph.add_node("sprint_reporter", sprint_reporter_node)
    graph.add_node("output_router", output_router_node)

    # Entry point
    graph.add_edge(START, "code_analyzer")

    # Conditional: only proceed if analysis produced results
    graph.add_conditional_edges(
        "code_analyzer",
        should_run_section_router,
        {"semantic_finder": "semantic_finder", "end": END},
    )

    # semantic_finder -> section_router
    graph.add_edge("semantic_finder", "section_router")

    # Conditional: only proceed if sections need updating
    graph.add_conditional_edges(
        "section_router",
        should_run_doc_writer,
        {"doc_writer": "doc_writer", "end": END},
    )

    # Conditional: skip validator at standard detail level
    graph.add_conditional_edges(
        "doc_writer",
        should_run_validator,
        {"doc_validator": "doc_validator", "toc_generator": "toc_generator"},
    )

    # doc_validator -> toc_generator
    graph.add_edge("doc_validator", "toc_generator")

    # toc_generator -> task_creator
    graph.add_edge("toc_generator", "task_creator")

    # Conditional: sprint reporter only if there are outputs
    graph.add_conditional_edges(
        "task_creator",
        should_run_sprint,
        {"sprint_reporter": "sprint_reporter", "end": END},
    )

    # sprint_reporter -> output_router -> END
    graph.add_edge("sprint_reporter", "output_router")
    graph.add_edge("output_router", END)

    return graph


def compile_graph():
    """Build and compile the graph, ready for invocation."""
    return build_graph().compile()
