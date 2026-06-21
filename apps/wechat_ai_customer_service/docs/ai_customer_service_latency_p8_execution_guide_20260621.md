# P8 Execution Guide: Capture/Brain Overlap

## Purpose

P8 completes the original concurrency design at the scheduler execution level:

- WeChat RPA capture/send stays serial and guarded.
- Brain planning starts as soon as one captured session is ready.
- Brain/final-polish work uses existing executor pools and never touches foreground RPA.

This guide is for future developers who continue P8 or debug its artifacts.  It is an execution guide, not a new architecture proposal.

## Non-Negotiable Boundaries

- Do not rename existing variables, public functions, CLI routes, JSON fields, artifact names, constants, or file paths.
- Do not change `add-friend-entry-click-plan` or any worker-facing command contract.
- Do not shorten timeouts to make a test appear faster.
- Do not bypass `customer_service_brain`, final visible polish, freshness checks, session-envelope checks, RPA target confirmation, or send guards.
- Do not add local customer-visible fallback wording.
- Do not make account-specific or product-specific speed branches.
- Do not let planner/polish functions call RPA.

## Intended Execution Shape

Old shape:

```text
capture A -> capture B -> submit Brain A/B
```

P8 shape:

```text
capture A -> submit Brain A
capture B -> submit Brain B
```

The only intended overlap is:

```text
foreground RPA capture for session B
while Brain thinks for already-captured session A
```

This is safe because Brain planning consumes durable captured messages and does not operate WeChat.

## Implementation Rules

Use existing paths:

- `record_capture_result()`
- `enqueue_llm_task()`
- `CustomerServiceSchedulerRuntime._submit_llm_tasks()`
- existing planner executor and concurrency limits

Do not introduce a new queue, executor, public config, or API.

The scheduler may append more events, but existing event names and fields must remain compatible.

## Verification Steps

1. Static compile:

```powershell
python -B -m py_compile apps\wechat_ai_customer_service\admin_backend\services\customer_service_scheduler.py apps\wechat_ai_customer_service\tests\run_customer_service_multi_session_scheduler_checks.py workflows\verification\wechat_customer_service\two_visible_session_customer_service_live.py
```

2. Focused scheduler regression:

```powershell
python -B apps\wechat_ai_customer_service\tests\run_customer_service_multi_session_scheduler_checks.py
```

The suite must include a case proving the planner for the first capture can start before the second capture finishes.

3. Harness self-check:

```powershell
python -B workflows\verification\wechat_customer_service\two_visible_session_customer_service_live.py --self-check
```

4. Short greeting dry-run:

```powershell
python -B workflows\verification\wechat_customer_service\two_visible_session_customer_service_live.py --run-id <p8-run-id> --rounds 1 --scenario-set short_greeting --skip-prompt-send --synthetic-input-only --dry-reply-send --reply-timeout-seconds 240 --tick-interval-seconds 1
```

Acceptance:

- two replies verified,
- `target_match_ok` true,
- `session_key_match_ok` true,
- `capture_to_brain_start_seconds` is near zero for both sessions,
- no real danger signals in artifact scan.

5. Broader regression:

```powershell
python -B apps\wechat_ai_customer_service\tests\run_workflow_logic_checks.py
python -B apps\wechat_ai_customer_service\tests\run_brain_first_static_architecture_audit.py
```

## Reading P8 Artifacts

Primary success field:

- `latency_breakdown.capture_to_brain_start_seconds`

Expected P8 value:

- `0s` or near-zero for sessions whose planner capacity is available.

Fields that need careful interpretation:

- `planner_external_overhead_seconds`
- `polish_external_overhead_seconds`

In dry-run harnesses, these may include result-collection delay from test-loop status probes.  Do not treat them as production Brain/polish defects until production listener traces or low-volume live artifacts confirm the same shape.

## Dry-Run Harness Rule

When `--dry-reply-send` is enabled, per-tick interactive status probing is not needed for RPA send safety because no real WeChat send occurs.  A dry-run may still perform final postflight status.  This keeps dry timing closer to scheduler behavior and prevents test-only status OCR from being misread as Brain/final-polish latency.

Live runs must keep status/risk checks.

## Stop Rules

Stop and document instead of changing runtime behavior if:

- a suspected bottleneck appears only in dry-run artifacts and can be explained by harness probing,
- a proposed change would bypass final polish or semantic reviewer,
- a proposed change touches RPA send guard semantics,
- a proposed change requires renaming or public contract migration.

## Next Eligible Work After P8

- Verify production listener traces for planner/polish external overhead.
- Only if live traces confirm real runtime collection delay, design a small tick-followup optimization.
- Design multi-segment same-target RPA send optimization separately with a dedicated safety document.
- Keep semantic reviewer changes audit-only until a fresh artifact proves a universal safe shortcut.
