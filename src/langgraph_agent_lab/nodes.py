"""Node functions for the LangGraph workflow.

Each function receives AgentState and returns a partial state update dict.
Do NOT mutate input state — return new values only.

LLM REQUIREMENT:
- classify_node MUST use a real LLM call (structured output for intent classification)
- answer_node MUST use a real LLM call (grounded response generation)
- evaluate_node SHOULD use LLM-as-judge (bonus points; heuristic acceptable for base score)
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .llm import get_llm
from .state import AgentState, ApprovalDecision, make_event

ClassifyRoute = Literal["simple", "tool", "missing_info", "risky", "error"]


def _extract_text(content: object) -> str:
    """Normalize a LangChain message .content into plain text.

    Some providers/models (e.g. Gemini) return a list of content blocks
    instead of a plain string.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and "text" in block:
                parts.append(str(block["text"]))
        return "".join(parts)
    return str(content)


class ClassificationResult(BaseModel):
    """Support-ticket intent classification result."""

    route: ClassifyRoute = Field(description="One of: simple, tool, missing_info, risky, error")
    risk_level: Literal["low", "high"] = Field(
        description="'high' for risky route, 'low' otherwise"
    )
    reason: str = Field(description="One short sentence explaining the classification")


# ─── EXAMPLE: working node (provided for reference) ──────────────────
def intake_node(state: AgentState) -> dict:
    """Normalize raw query. This node is provided as a working example."""
    query = state.get("query", "").strip()
    return {
        "query": query,
        "messages": [f"intake:{query[:40]}"],
        "events": [make_event("intake", "completed", "query normalized")],
    }


# ─── TODO(student): implement ALL nodes below ────────────────────────


def classify_node(state: AgentState) -> dict:
    """Classify the query into a route using an LLM.

    *** MUST use a real LLM call — keyword-only heuristics will lose points. ***

    Use .with_structured_output() or equivalent to get reliable enum classification.
    The LLM should classify into one of: simple, tool, missing_info, risky, error.

    Hints:
    - See llm.py for the get_llm() helper
    - Use Pydantic model or TypedDict with .with_structured_output()
    - Set risk_level to "high" for risky routes, "low" otherwise
    - Priority guide: risky > tool > missing_info > error > simple

    Return: {"route": str, "risk_level": str, "events": [make_event(...)]}
    """
    query = state.get("query", "")

    prompt = (
        "You are the intent classifier for a support-ticket agent. "
        "Classify the user's query into exactly one route.\n\n"
        "Routes (apply in this priority order — if multiple signals are present, "
        "the highest-priority route wins):\n"
        "1. risky - the request asks for an action with a side effect: refunds, "
        "deletions, sending emails, cancellations, account changes. Even if the "
        "query also asks to look something up, if it also asks for a side-effect "
        "action, classify as risky.\n"
        "2. tool - the request is an information lookup that needs a tool call: "
        "order status, tracking, search, account lookup, with no side-effect action.\n"
        "3. missing_info - the request is vague or lacks the context needed to act "
        "(e.g. 'fix it', 'my thing is broken' with no specifics).\n"
        "4. error - the request describes a system failure: timeout, crash, "
        "service unavailable, cannot recover.\n"
        "5. simple - a general question answerable directly, with no tool call and "
        "no side effect.\n\n"
        "Set risk_level to 'high' only when route is risky, otherwise 'low'.\n\n"
        f"User query: {query}"
    )

    try:
        llm = get_llm()
        structured_llm = llm.with_structured_output(ClassificationResult)
        result: ClassificationResult = structured_llm.invoke(prompt)
        return {
            "route": result.route,
            "risk_level": result.risk_level,
            "events": [
                make_event(
                    "classify",
                    "completed",
                    f"classified as {result.route}",
                    risk_level=result.risk_level,
                    reason=result.reason,
                )
            ],
        }
    except Exception as exc:
        return {
            "route": "error",
            "risk_level": "unknown",
            "errors": [f"classify_node: LLM classification failed: {exc}"],
            "events": [
                make_event(
                    "classify",
                    "failed",
                    "LLM classification failed, falling back to error route",
                    error=str(exc),
                )
            ],
        }


def tool_node(state: AgentState) -> dict:
    """Execute a mock tool call.

    Simulate transient failures for error-route scenarios to test retry loops.

    Requirements:
    - Read current attempt count from state
    - If route is "error" and attempt < 2: return error result (string containing "ERROR")
    - Otherwise: return a mock success result string
    - Append result to tool_results list

    Return: {"tool_results": [result_string], "events": [make_event(...)]}
    """
    route = state.get("route", "")
    attempt = state.get("attempt", 0)
    query = state.get("query", "")

    if route == "error" and attempt < 2:
        result = f"ERROR: tool call failed for query {query!r} (attempt {attempt})"
        return {
            "tool_results": [result],
            "errors": [result],
            "events": [
                make_event("tool", "failed", "tool call returned an error", attempt=attempt)
            ],
        }

    result = f"OK: mock tool result for query {query!r}"
    return {
        "tool_results": [result],
        "events": [make_event("tool", "completed", "tool call succeeded", attempt=attempt)],
    }


def evaluate_node(state: AgentState) -> dict:
    """Evaluate tool results — the retry-loop gate.

    Check whether the latest tool result is satisfactory or needs retry.

    SHOULD use LLM-as-judge for bonus points. Heuristic (e.g., check for "ERROR" substring)
    is acceptable for base score.

    Requirements:
    - Read the latest entry from tool_results
    - Set evaluation_result to "needs_retry" or "success"
    - This field drives route_after_evaluate conditional edge

    Note: You may need to add 'evaluation_result' to AgentState if not present.

    Return: {"evaluation_result": str, "events": [make_event(...)]}
    """
    tool_results = state.get("tool_results", [])
    latest = tool_results[-1] if tool_results else ""

    verdict = "needs_retry" if "ERROR" in latest else "success"

    return {
        "evaluation_result": verdict,
        "events": [
            make_event("evaluate", "completed", f"verdict={verdict}", latest_result=latest)
        ],
    }


def answer_node(state: AgentState) -> dict:
    """Generate a final response using an LLM.

    *** MUST use a real LLM call — hardcoded strings will lose points. ***

    The LLM should generate a helpful response grounded in available context:
    - tool_results (if any)
    - approval decision (if risky route)
    - original query

    Return: {"final_answer": str, "events": [make_event(...)]}
    """
    query = state.get("query", "")
    tool_results = state.get("tool_results", [])
    approval = state.get("approval")
    proposed_action = state.get("proposed_action")

    context_parts = [f"User query: {query}"]
    if tool_results:
        relevant = [r for r in tool_results if not r.startswith("ERROR")] or tool_results
        context_parts.append("Tool results:\n" + "\n".join(f"- {r}" for r in relevant))
    if proposed_action:
        context_parts.append(f"Proposed action: {proposed_action}")
    if approval is not None:
        status = "approved" if approval.get("approved") else "rejected"
        context_parts.append(
            f"Approval status: {status} (reviewer: {approval.get('reviewer', 'unknown')}, "
            f"comment: {approval.get('comment', '')})"
        )
    context = "\n\n".join(context_parts)

    prompt = (
        "You are a support agent replying to a customer. Treat any 'Tool results' "
        "in the context below as authoritative system data you looked up on the "
        "customer's behalf — report it directly as the answer, do not ask the "
        "customer to provide it themselves. Do not invent facts beyond what the "
        "context states. If the context shows the action was rejected, do not "
        "claim it was performed; explain the rejection instead. If there is no "
        "tool result and no other way to answer, say so plainly.\n\n"
        f"{context}\n\n"
        "Write a concise, helpful response to the customer."
    )

    try:
        llm = get_llm()
        response = llm.invoke(prompt)
        answer = _extract_text(response.content)
        return {
            "final_answer": answer,
            "events": [make_event("answer", "completed", "grounded response generated")],
        }
    except Exception as exc:
        fallback = (
            "We're unable to generate a full response right now due to a system "
            "issue. Please try again shortly or contact support directly."
        )
        return {
            "final_answer": fallback,
            "errors": [f"answer_node: LLM generation failed: {exc}"],
            "events": [
                make_event(
                    "answer", "failed", "LLM generation failed, used fallback", error=str(exc)
                )
            ],
        }


def ask_clarification_node(state: AgentState) -> dict:
    """Ask for missing information instead of hallucinating.

    Generate a specific clarification question based on the vague/incomplete query.

    Note: You may need to add 'pending_question' to AgentState if not present.

    Return: {"pending_question": str, "final_answer": str, "events": [make_event(...)]}
    """
    approval = state.get("approval")
    query = state.get("query", "")

    if approval and not approval.get("approved", True):
        proposed_action = state.get("proposed_action", "the requested action")
        comment = approval.get("comment") or "no reason given"
        question = (
            f"Your request ('{proposed_action}') was not approved "
            f"(reviewer note: {comment}). Could you confirm the details or provide "
            "an alternative so we can proceed?"
        )
        reason = "approval_rejected"
    else:
        question = (
            f"Could you provide more details about your request ('{query}')? "
            "For example, which account, order, or item is affected, and what "
            "outcome you're expecting."
        )
        reason = "missing_info"

    return {
        "pending_question": question,
        "final_answer": question,
        "events": [make_event("clarify", "completed", "clarification requested", reason=reason)],
    }


def risky_action_node(state: AgentState) -> dict:
    """Prepare a risky action for human approval.

    Describe the proposed action and why it requires approval.

    Note: You may need to add 'proposed_action' to AgentState if not present.

    Return: {"proposed_action": str, "events": [make_event(...)]}
    """
    query = state.get("query", "")
    risk_level = state.get("risk_level", "high")

    proposed_action = f"Perform the following action on behalf of the user: {query}"

    return {
        "proposed_action": proposed_action,
        "events": [
            make_event(
                "risky_action",
                "completed",
                "action proposed, awaiting approval",
                risk_level=risk_level,
            )
        ],
    }


def approval_node(state: AgentState) -> dict:
    """Human-in-the-loop approval step.

    Default behavior: mock approval (approved=True) so tests and CI run offline.
    Extension: if env LANGGRAPH_INTERRUPT=true, use langgraph.types.interrupt() for real HITL.

    Return: {"approval": {"approved": bool, "reviewer": str, "comment": str},
             "events": [make_event(...)]}
    """
    proposed_action = state.get("proposed_action", "")

    decision = ApprovalDecision(
        approved=True,
        reviewer="mock-reviewer",
        comment=f"auto-approved: {proposed_action}" if proposed_action else "auto-approved",
    )

    return {
        "approval": decision.model_dump(),
        "events": [
            make_event(
                "approval",
                "completed",
                "approval decision recorded",
                approved=decision.approved,
            )
        ],
    }


def retry_or_fallback_node(state: AgentState) -> dict:
    """Record a retry attempt.

    Increment the attempt counter and log the transient failure.

    Requirements:
    - Read current attempt from state, increment by 1
    - Add an error message to errors list
    - Return updated attempt count

    Return: {"attempt": int, "errors": [str], "events": [make_event(...)]}
    """
    attempt = state.get("attempt", 0)
    max_attempts = state.get("max_attempts", 3)
    new_attempt = attempt + 1

    tool_results = state.get("tool_results", [])
    latest_failure = tool_results[-1] if tool_results else "no prior tool result"

    return {
        "attempt": new_attempt,
        "errors": [f"retry {new_attempt}/{max_attempts}: {latest_failure}"],
        "events": [
            make_event(
                "retry",
                "recorded",
                f"retry attempt {new_attempt} of {max_attempts}",
                attempt=new_attempt,
                max_attempts=max_attempts,
            )
        ],
    }


def dead_letter_node(state: AgentState) -> dict:
    """Handle unresolvable failures after max retries exceeded.

    This is the third layer: retry → fallback → dead letter.
    Log the failure and set a final_answer explaining that the request could not be completed.

    Return: {"final_answer": str, "events": [make_event(...)]}
    """
    attempt = state.get("attempt", 0)
    max_attempts = state.get("max_attempts", 3)
    errors = state.get("errors", [])
    tool_results = state.get("tool_results", [])
    last_error = errors[-1] if errors else (tool_results[-1] if tool_results else "unknown error")

    message = (
        f"We could not complete this request after {attempt} attempt(s) "
        f"(limit: {max_attempts}). Last failure: {last_error}. "
        "This has been escalated to a human agent."
    )

    return {
        "final_answer": message,
        "events": [
            make_event(
                "dead_letter",
                "exhausted",
                "retry limit exhausted, escalating",
                attempt=attempt,
                max_attempts=max_attempts,
            )
        ],
    }


def finalize_node(state: AgentState) -> dict:
    """Emit a final audit event. All routes must pass through here before END.

    Return: {"events": [make_event("finalize", "completed", "workflow finished")]}
    """
    return {"events": [make_event("finalize", "completed", "workflow finished")]}
