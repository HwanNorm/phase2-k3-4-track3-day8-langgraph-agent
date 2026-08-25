"""Graph construction.

This module is intentionally import-safe. It imports LangGraph only inside the builder so unit tests
that check schema/metrics can run even if students are still debugging graph wiring.
"""

from __future__ import annotations

from typing import Any

from .state import AgentState


def build_graph(checkpointer: Any | None = None):
    """Build and compile the LangGraph workflow.

    TODO(student): Build the complete graph with this architecture:

    START → intake → classify → [conditional: route_after_classify]
      simple       → answer → finalize → END
      tool         → tool → evaluate → [conditional: route_after_evaluate]
                                          success → answer → finalize → END
                                          needs_retry → retry → [conditional: route_after_retry]
                                                                  tool (retry)
                                                                  dead_letter → finalize → END
      missing_info → clarify → finalize → END
      risky        → risky_action → approval → [conditional: route_after_approval]
                                                  approved → tool → evaluate → ...
                                                  rejected → clarify → finalize → END
      error        → retry → [conditional: route_after_retry] → ...

    Steps:
    1. Import StateGraph, START, END from langgraph.graph
    2. Create StateGraph(AgentState)
    3. Import and add all nodes from nodes.py (11 nodes total)
    4. Import and use routing functions from routing.py for conditional edges
    5. Add fixed edges (e.g., START→intake, intake→classify, tool→evaluate, etc.)
    6. Add conditional edges using add_conditional_edges()
    7. Compile with checkpointer: graph.compile(checkpointer=checkpointer)

    Reference: https://langchain-ai.github.io/langgraph/how-tos/create-react-agent/
    """
    from langgraph.graph import StateGraph, START, END

    from .nodes import (
        intake_node,
        classify_node,
        tool_node,
        evaluate_node,
        answer_node,
        ask_clarification_node,
        risky_action_node,
        approval_node,
        retry_or_fallback_node,
        dead_letter_node,
        finalize_node,
    )
    from .routing import (
        route_after_classify,
        route_after_evaluate,
        route_after_retry,
        route_after_approval,
    )

    builder = StateGraph(AgentState)

    # Register all 11 nodes
    builder.add_node("intake", intake_node)
    builder.add_node("classify", classify_node)
    builder.add_node("tool", tool_node)
    builder.add_node("evaluate", evaluate_node)
    builder.add_node("answer", answer_node)
    builder.add_node("clarify", ask_clarification_node)
    builder.add_node("risky_action", risky_action_node)
    builder.add_node("approval", approval_node)
    builder.add_node("retry", retry_or_fallback_node)
    builder.add_node("dead_letter", dead_letter_node)
    builder.add_node("finalize", finalize_node)

    # Fixed edges
    builder.add_edge(START, "intake")
    builder.add_edge("intake", "classify")
    builder.add_edge("tool", "evaluate")
    builder.add_edge("risky_action", "approval")
    builder.add_edge("answer", "finalize")
    builder.add_edge("clarify", "finalize")
    builder.add_edge("dead_letter", "finalize")
    builder.add_edge("finalize", END)

    # Conditional edges
    builder.add_conditional_edges("classify", route_after_classify)
    builder.add_conditional_edges("evaluate", route_after_evaluate)
    builder.add_conditional_edges("retry", route_after_retry)
    builder.add_conditional_edges("approval", route_after_approval)

    return builder.compile(checkpointer=checkpointer)
