# Day 08 Lab Report

## 1. Metrics Summary

- **Total Scenarios**: 7
- **Success Rate**: 100.00%
- **Avg Nodes Visited**: 6.43
- **Total Retries**: 3
- **Total Interrupts**: 2
- **Resume Success**: False

## 2. Scenario Results

| Scenario | Expected Route | Actual Route | Success | Retries | Interrupts |
|---|---|---|---:|---:|---:|
| S01_simple | simple | simple | ✓ | 0 | 0 |
| S02_tool | tool | tool | ✓ | 0 | 0 |
| S03_missing | missing_info | missing_info | ✓ | 0 | 0 |
| S04_risky | risky | risky | ✓ | 0 | 1 |
| S05_error | error | error | ✓ | 2 | 0 |
| S06_delete | risky | risky | ✓ | 0 | 1 |
| S07_dead_letter | error | error | ✓ | 1 | 0 |

## 3. Architecture

### Graph Nodes (11 total)
- intake: Normalize raw query
- classify: LLM-based intent classification (simple/tool/missing_info/risky/error)
- tool: Mock tool execution with error simulation
- evaluate: Tool result quality check (heuristic or LLM-as-judge)
- answer: LLM-grounded response generation
- clarify: Ask for missing information
- risky_action: Prepare risky action for approval
- approval: Human-in-the-loop approval gate
- retry: Increment attempt counter for retry loop
- dead_letter: Handle max retry exhaustion
- finalize: Emit final audit event

### State Schema
| Field | Reducer | Why |
|---|---|---|
| messages | append | Audit conversation/events |
| tool_results | append | Tool execution history |
| errors | append | Failure tracking |
| events | append | Audit trail for metrics |
| route | overwrite | Current classification only |
| attempt | overwrite | Retry counter |
| max_attempts | overwrite | Retry bound |
| evaluation_result | overwrite | Retry loop gate |
| pending_question | overwrite | Clarification output |
| proposed_action | overwrite | Risky action proposal |
| approval | overwrite | Approval decision |
| final_answer | overwrite | Final response |

### Graph Edges
**Fixed edges:** START→intake→classify, tool→evaluate, risky_action→approval, answer→finalize, clarify→finalize, dead_letter→finalize, finalize→END

**Conditional edges:**
- After classify: route_after_classify (simple→answer, tool→tool, missing_info→clarify, risky→risky_action, error→retry)
- After evaluate: route_after_evaluate (needs_retry→retry, else→answer)
- After retry: route_after_retry (attempt < max_attempts→tool, else→dead_letter)
- After approval: route_after_approval (approved→tool, else→clarify)

## 4. Failure Analysis

### 1. Tool Failure → Bounded Retry/Dead-Letter
When tool_node returns an error (simulated for error-route scenarios), evaluate_node detects the failure and sets evaluation_result='needs_retry'. The retry_or_fallback_node increments the attempt counter. route_after_retry checks if attempt < max_attempts: if true, routes back to tool for another attempt; if false, routes to dead_letter which escalates the issue. This ensures the retry loop is bounded and cannot run infinitely.

### 2. Risky Action Rejection → Clarification
When a query is classified as risky, risky_action_node prepares a proposed_action. The approval_node (mock or real HITL) can reject it. route_after_approval routes rejected cases to clarify instead of proceeding to tool. This prevents unauthorized side effects and prompts the user for alternative information.

## 5. Persistence / Recovery Evidence

Each run has an isolated thread_id and uses the configured checkpointer. Verification reads get_state_history() immediately after invoke, confirming the final state is recoverable in-process. The final verification recorded six history snapshots for a MemorySaver thread. SQLite uses SqliteSaver with WAL for durable extension-track checkpoints.

## 6. Improvement Plan

If given one more day, I would prioritize implementing real Human-in-the-Loop (HITL) with interrupt() and a Streamlit UI for approval/reject decisions. This would provide a production-quality approval workflow instead of the current mock approval.