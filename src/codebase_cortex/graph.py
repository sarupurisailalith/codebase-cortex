"""LangGraph StateGraph definition for the Cortex pipeline."""

from __future__ import annotations

from langgraph.graph import StateGraph, START, END

from codebase_cortex.state import CortexState


async def code_analyzer_node(state: CortexState) -> dict:
    """Analyze git diffs and identify changes."""
    from codebase_cortex.agents.code_analyzer import CodeAnalyzerAgent
    from codebase_cortex.config import get_llm

    agent = CodeAnalyzerAgent(get_llm())
    return await agent.run(state)


async def semantic_finder_node(state: CortexState) -> dict:
    """Find semantically related documentation."""
    # Placeholder — implemented in Week 2
    return {"related_docs": []}


async def doc_writer_node(state: CortexState) -> dict:
    """Write or update Notion documentation pages."""
    # Placeholder — implemented in Week 2
    return {"doc_updates": []}


async def task_creator_node(state: CortexState) -> dict:
    """Create tasks for undocumented areas."""
    # Placeholder — implemented in Week 2
    return {"tasks_created": []}


async def sprint_reporter_node(state: CortexState) -> dict:
    """Generate sprint summary report."""
    # Placeholder — implemented in Week 2
    return {"sprint_summary": ""}


def should_run_docs(state: CortexState) -> str:
    """Route based on whether we have analysis results to act on."""
    if state.get("analysis"):
        return "semantic_finder"
    return "end"


def should_run_sprint(state: CortexState) -> str:
    """Route to sprint reporter only on schedule triggers."""
    if state.get("trigger") == "schedule":
        return "sprint_reporter"
    return "end"


def build_graph() -> StateGraph:
    """Build and compile the Cortex pipeline graph.

    Pipeline flow:
        code_analyzer -> semantic_finder -> doc_writer -> task_creator -> [sprint_reporter] -> END
    """
    graph = StateGraph(CortexState)

    # Add nodes
    graph.add_node("code_analyzer", code_analyzer_node)
    graph.add_node("semantic_finder", semantic_finder_node)
    graph.add_node("doc_writer", doc_writer_node)
    graph.add_node("task_creator", task_creator_node)
    graph.add_node("sprint_reporter", sprint_reporter_node)

    # Entry point
    graph.add_edge(START, "code_analyzer")

    # Conditional: only proceed if analysis produced results
    graph.add_conditional_edges(
        "code_analyzer",
        should_run_docs,
        {"semantic_finder": "semantic_finder", "end": END},
    )

    # Linear flow through doc pipeline
    graph.add_edge("semantic_finder", "doc_writer")
    graph.add_edge("doc_writer", "task_creator")

    # Conditional: sprint reporter only on schedule
    graph.add_conditional_edges(
        "task_creator",
        should_run_sprint,
        {"sprint_reporter": "sprint_reporter", "end": END},
    )
    graph.add_edge("sprint_reporter", END)

    return graph


def compile_graph():
    """Build and compile the graph, ready for invocation."""
    return build_graph().compile()
