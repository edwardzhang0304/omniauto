# P8 Capture/Brain Overlap Latency Optimization

## Scope

This phase continues the short-message latency work after P7.  The goal is to reduce avoidable scheduler wait time without changing framework boundaries, variable names, CLI routes, JSON contracts, or public APIs.

Hard limits:

- Do not rename existing variables, paths, CLI commands, artifact scopes, JSON fields, or public function names.
- Do not shorten timeouts as a substitute for getting a valid result.
- Do not bypass `customer_service_brain`, final visible polish, freshness checks, RPA target checks, or send guards.
- Do not add customer-visible local templates or fallback wording.
- Do not add account-specific or product-specific rules.

## Evidence

P6/P7 artifacts show three different remaining latency classes:

- Short greetings still spend about 9-12s in capture, 4-19s in final polish future time, and 12-19s in RPA send.
- Short business live replies can spend about 37-38s in RPA send when the reply is split into multiple visible segments.
- Boundary dry runs after P7 no longer reproduce the 30s evidence-pack rebuild, but semantic reviewer and final polish future time still vary.

One concrete scheduler wait is now visible:

- In `p6_diag_short_greeting_live_20260620`, the first captured session waited about 12s from `capture_finished_at` to `brain_started_at`.
- That wait was caused by the scheduler capturing all pending sessions first, then submitting Brain tasks after the whole capture phase.
- Brain planning is designed not to call RPA.  Therefore it can safely run while the scheduler continues foreground capture for another session.

## Change Plan

### P8.1 Inline Planner Submission After Each Capture

After one session is captured and `enqueue_llm_task()` creates the planner task, immediately call the existing private `_submit_llm_tasks()` helper from inside the capture loop.

This is intentionally narrow:

- The same `enqueue_llm_task()` and `_submit_llm_tasks()` paths are used.
- Existing planner concurrency limits still apply.
- Existing events and latency trace fields are preserved.
- Capture remains foreground and serial.
- Brain runs only in the existing planner executor and must not call RPA.
- Final polish, freshness, send target confirmation, and RPA guards remain unchanged.

Expected gain:

- In two-session live short-message cases, the first session can start Brain roughly one capture duration earlier.
- On the P6 short-greeting shape, this can recover up to about 10-12s for the first ready reply when planner capacity is available.

### P8.2 Hold Reviewer/Polish/RPA Changes Until Ranked

Do not change semantic reviewer behavior, final polish behavior, or same-target multi-segment RPA send behavior in this chapter.

Reason:

- Reviewer variance exists, but the current artifacts do not prove a safe universal shortcut.
- Final polish external wait appears partly provider/future scheduling related; skipping polish would violate Brain First baseline.
- Multi-segment send reuse touches RPA safety and should be designed separately after more live evidence.

## Acceptance

- A focused scheduler test proves Brain can start while a later session capture is still running.
- Existing multi-session scheduler regression still passes.
- Harness self-check still passes.
- No public contract, CLI, route, JSON field, or variable rename is introduced.
- Long-run state records the result and next bottleneck ranking.
