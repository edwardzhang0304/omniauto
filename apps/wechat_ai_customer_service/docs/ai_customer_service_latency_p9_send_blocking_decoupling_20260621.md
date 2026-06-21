# P9 Send Blocking Decoupling

## Purpose

P9 targets the remaining short-message latency that comes from scheduler blocking during real WeChat RPA send.

The latest three-session live run passed functionally, but timing showed:

- three sessions / one round took about 219s;
- prompt simulation cost about 65s and is not production customer-service latency;
- reply-phase capture cost about 31s;
- actual assistant RPA sends cost about 49.6s across five visible sends;
- `send_post_seconds` occupied about 75.8s across scheduler ticks.

Brain and final polish are no longer the first optimization target.  The next useful work is to prevent one slow foreground send from blocking collection of already-completed Brain/polish results for other sessions.

## Non-Negotiable Boundaries

- Do not rename existing variables, public functions, CLI routes, JSON fields, artifact scopes, constants, or file paths.
- Do not change `add-friend-entry-click-plan` or any worker-facing command contract.
- Do not shorten timeouts to make a test appear faster.
- Do not bypass `customer_service_brain`, final visible polish, semantic review, freshness checks, session-envelope checks, active-target confirmation, or WeChat send guards.
- Do not add local customer-visible templates or fallback wording.
- Do not make account-specific, product-specific, or customer-specific speed branches.
- Do not allow concurrent foreground WeChat RPA actions.

## Current Blocking Shape

The scheduler already runs Brain/final-polish work through executor pools, but `tick()` still calls `_consume_send_queue()` synchronously.  `_consume_send_queue()` performs freshness validation and the real `send_fn()` call inline.

Current shape:

```text
collect polish A
send A with foreground RPA, blocking the scheduler tick
collect polish B/C only after send A returns
```

This is safe, but slow.  During a real send, the scheduler cannot quickly turn completed Brain/polish futures into ready replies.

## Target Shape

Keep WeChat foreground RPA serial, but move the slow send operation into one internal send worker.

Target shape:

```text
collect polish A
dispatch ready reply A to one send worker
scheduler tick returns and can collect polish B/C
send worker owns foreground RPA lock and completes A safely
```

Important distinction:

- Allowed while a send is in flight: collect completed planner/polish futures, update state, enqueue ready replies.
- Not allowed while a send is in flight: start a new foreground capture, open chat, search, type, click, or run another send.

## Chapter Plan

### P9.1 Single Send Worker Dispatch

Add internal runtime support for one in-flight send:

- reuse existing `select_ready_replies()`, `mark_reply_sending()`, freshness, `send_fn()`, `mark_reply_sent()`, and failure/stale paths;
- do not change public state field names;
- add only additive event/timing fields if needed;
- preserve `send_max_replies_per_round` as the upper bound for synchronous behavior, but dispatch at most one worker send at a time in this chapter.

Expected gain:

- other completed Brain/polish futures can be collected while foreground send is still running;
- `send_post_seconds` in scheduler ticks should drop because the slow RPA action is no longer inline.

### P9.2 RPA Foreground Exclusion During Send In-Flight

While the worker is sending:

- skip `_capture_pending()` for that tick;
- skip dispatching any second send;
- keep collecting completed planner/polish futures.

This keeps foreground WeChat actions serial and avoids high-risk overlap.

### P9.3 Queue-Wait Observability

Add additive timing only:

- `send_dispatched_at`;
- `send_worker_started_at`;
- `send_worker_finished_at`;
- derived `ready_to_dispatch_seconds` / `dispatch_to_finished_seconds` in event breakdown where practical.

These fields must be optional and must not replace existing JSON fields.

### P9.4 Focused Regression And Live Decision

Required before live:

```powershell
python -B -m py_compile apps\wechat_ai_customer_service\admin_backend\services\customer_service_scheduler.py apps\wechat_ai_customer_service\admin_backend\services\customer_service_scheduler_state.py apps\wechat_ai_customer_service\tests\run_customer_service_multi_session_scheduler_checks.py
python -B apps\wechat_ai_customer_service\tests\run_customer_service_multi_session_scheduler_checks.py
python -B workflows\verification\wechat_customer_service\two_visible_session_customer_service_live.py --self-check
```

Live testing should remain low-volume and guarded.  If there is any blank render, wrong target, red exclamation, safety prompt, or login prompt, stop and diagnose before continuing.

Live harness note:

- After P9, test-only `status(interactive=False)` probes must be deferred while scheduler summary reports `reply_sending > 0`.
- This does not weaken the production send guard; it prevents the acceptance harness from adding an extra foreground OCR/status operation while the send worker owns the WeChat foreground RPA path.
- A final/postflight status probe should still run after `reply_sending` clears.

## Acceptance

- Scheduler can collect completed Brain/polish results while one reply is sending.
- No foreground capture/search/open/send occurs concurrently with a send in-flight.
- Existing Brain First ownership and final polish requirements remain intact.
- Existing ready reply session binding, stale checks, and target confirmation remain intact.
- Existing public contracts and names remain unchanged.
- Focused scheduler regression passes.
- Static compile passes.

## Stop Rules

Stop and document instead of changing runtime behavior if:

- a proposed change requires parallel WeChat foreground operations;
- a proposed change bypasses freshness or target/session confirmation;
- a proposed change skips final polish or semantic review;
- a proposed change renames existing public contracts;
- a live run shows WeChat blank render, security prompt, red exclamation, or target mismatch.
