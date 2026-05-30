# WeChat Message Window Recovery Gap Guard Plan

## Goal

This change makes burst-message handling auditable and fail-safe for both the WeChat customer-service listener and the AI smart recorder.

The key rule is simple: when the system cannot prove that it has recovered the message window from the last known anchor, it must not silently continue as if the context is complete.

## Scope

- Customer service listener: add an explicit `gap_risk` guard on top of the existing history backfill.
- AI smart recorder: keep the existing anchor recovery model and document its contract as the baseline for customer service.
- Tests: cover anchor found, anchor missing then recovered, anchor missing after backfill, freshness re-read with missing original batch, and dedupe/idempotency.
- Live validation: use File Transfer Assistant with a one-time copy/paste burst only to push messages beyond the visible page. Normal operation still uses RPA humanized typing/send behavior.

## Source Priority Contract

The answer pipeline must not let the LLM decide factual priority by itself.

Priority from strongest to weakest:

1. Safety boundary and handoff rules.
2. Product master, structured product facts, and formal knowledge.
3. Deterministic local reply rules.
4. Governed RAG experience snippets.
5. LLM synthesis for wording and uncertain cases.
6. Style adapter for tone only.

If structured/formal knowledge conflicts with RAG experience, structured/formal knowledge wins. RAG can supply phrasing or historical examples, but must not override facts.

## Customer Service Recovery Contract

The customer-service listener already loads history when the visible window looks saturated. This plan adds a stable proof point:

- `anchor`: a previously processed message id or stable content key.
- `anchor_found_initial`: whether the anchor is still visible before history loading.
- `anchor_found_after_history_load`: whether history loading recovered it.
- `gap_risk`: true when the listener has previous anchors, sees new eligible messages, and cannot recover the anchor after configured backfill.

When `gap_risk=true` and `block_on_gap_risk=true`, the listener must:

- capture visible messages to the raw store for audit,
- not generate or send a customer-visible answer,
- not mark the candidate batch as processed,
- write a paused runtime status,
- append an audit event with the recovery metadata.

## Recorder Recovery Contract

The recorder already uses the stronger model:

- collect recent raw-message anchors,
- check whether the latest anchor is visible,
- backfill if the anchor is missing,
- upsert all recovered messages through `RawMessageStore`,
- mark `gap_risk=true` if the anchor is still missing.

This is acceptable for ongoing capture. For a future "recover all historical backlog" mode, initial capture should support a deeper first-run backfill with an explicit time/message cap.

## No-Miss And No-Duplicate Rules

- Use message id as the strongest dedupe key.
- Fall back to stable content key: sender + type + normalized content.
- For recorder OCR, continue using near-duplicate merging in `RawMessageStore`.
- Mark customer-service messages processed only after a verified send or an explicit coalescing decision.
- Never mark a gap-risk customer-service batch processed automatically.
- Export recorder results from raw messages, not transient capture batches.

## Configuration

Customer-service `history_backfill` gains these defaulted fields:

- `gap_guard_enabled`: default `true`.
- `block_on_gap_risk`: default `true`.
- `first_window_gap_guard`: default `false`, so first startup does not block simply because there is no prior anchor.

Existing fields remain supported:

- `enabled`
- `load_times`
- `max_load_times`
- `trigger_visible_unprocessed_count`
- `trigger_visible_saturated_count`
- `max_messages_after_load`
- `freshness_load_times`

## Acceptance Criteria

- Static syntax checks pass for touched Python files.
- Customer-service burst/backfill tests pass.
- Recorder capture backfill tests pass.
- Existing workflow, style, boundary, RAG priority, realtime reply, and win32/OCR compatibility checks pass.
- Live burst test shows history backfill or gap guard metadata in audit.
- If the system cannot prove continuity, it pauses instead of replying.
- Long soak shows no duplicate replies, no missing-marker acceptance failure, no WeChat logout, and no blank-window condition.
