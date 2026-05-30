# RPA Backend State Machine Optimization

## Scope

This document defines the current optimization pass for the WeChat customer-service RPA control layer.

The goal is not to rebuild the existing implementation. The goal is to unify already completed RPA stability work into one runtime contract and only fill activation or wiring gaps.

Business reply logic is out of scope:

- no knowledge-base priority changes
- no LLM prompt or synthesis policy changes
- no customer-visible reply policy changes
- no product, RAG, data-capture, or handoff business rule changes

## Target Runtime Contract

The preferred customer-service runtime is:

```text
passive session-list monitor
  -> backend scheduler state
  -> short serial RPA capture
  -> async reply planning with captured messages only
  -> ready reply queue
  -> serial RPA freshness check and send
  -> processed anchor update and audit
```

The WeChat foreground should only be touched by the capture and send stages. LLM/rule/RAG planning must run from captured snapshots and must not call RPA.

## Reuse Matrix

| Capability | Current status | Reuse decision |
|---|---|---|
| RPA-first transport with wxauto4 reserve | Implemented | Keep. wxauto4 remains technical reserve, not default runtime. |
| Global RPA lock | Implemented | Keep. RPA capture/send stay serial. |
| Operator guard, F8 control, floating indicator | Implemented | Keep. Guard starts before managed listener work. |
| Humanized send parameters | Implemented | Keep. Do not replace with clipboard-bulk sending. |
| Send target guard and post-send validation | Implemented | Keep. Scheduler send path uses existing connector verification. |
| Blank-render detection and tray redraw recovery | Implemented | Keep. Blank render blocks blind send. |
| Passive logout/blank/auxiliary-window probe | Implemented | Keep. Stop and hand off on unrecoverable states. |
| Low-disturbance passive session polling | Implemented | Keep. Idle loops should not activate/normalize WeChat. |
| Anchor-based history backfill | Implemented | Keep. Backfill only when continuity cannot be proven. |
| Multi-session scheduler runtime | Implemented | Keep. This is the backend state machine. |
| CapturedMessagesConnector planner boundary | Implemented | Keep. Planner cannot send through RPA. |
| Scheduler live activation | Partially wired | Fill gap. Live low-risk configs must prefer scheduler unless explicitly disabled. |
| Current documentation | Split across several files | Add this umbrella contract and test plan. |

## Existing Modules Mapped To The Contract

- `admin_backend/services/customer_service_scheduler.py`
  - Owns backend scheduling.
  - Keeps RPA behind `capture_fn`, `freshness_fn`, and `send_fn`.
  - Runs LLM planning asynchronously from captured snapshots.

- `admin_backend/services/customer_service_scheduler_state.py`
  - Persists sessions, captures, LLM tasks, ready replies, and event audit.
  - Provides context-version and stale-reply protection.

- `admin_backend/services/session_monitor.py`
  - Detects changed sessions from passive list polling.
  - Preserves pending sessions when round limits truncate active targets.

- `workflows/listen_and_reply.py`
  - Keeps existing reply planning, batch selection, history backfill, freshness checks, and processed-anchor updates.

- `adapters/wechat_connector.py`
  - Keeps the single RPA lock and guarded sidecar calls.

- `adapters/wechat_win32_ocr_sidecar.py`
  - Performs concrete Win32/OCR RPA actions and render/login/window guards.

- `scripts/run_customer_service_listener.py`
  - Starts operator guard, risk probes, scheduler bridge, cloud guard, and runtime status.

## Gap To Fix In This Pass

The scheduler exists, but some live configs do not explicitly set `concurrency_scheduler.enabled=true`. In that case the managed listener can still fall back to the older serial `listen_and_reply.py --once` loop.

That fallback is functionally valid, but it does not fully realize the backend state-machine contract:

- it couples capture, planning, and send inside one target loop
- a slow LLM plan can delay other sessions
- more work happens in the foreground loop than necessary

The fix is a minimal activation rule:

- explicit `concurrency_scheduler.enabled=true` enables scheduler
- explicit `concurrency_scheduler.enabled=false` remains a rollback switch
- if the config has `live_safety_guard.enabled=true`, `multi_target.enabled=true`, and low-risk RPA mode is not disabled, scheduler is enabled by default
- `live_safety_guard.backend_state_scheduler_enabled=false` can opt out

## Acceptance Criteria

- Existing business-reply tests still pass.
- Multi-session scheduler tests pass.
- Win32/OCR compatibility tests pass.
- Workflow logic tests pass.
- Runtime scheduler gate tests cover explicit enable, explicit disable, and live-safety inferred enable.
- A low-risk File Transfer Assistant live check confirms the current transport is Win32/OCR RPA and no wxauto4 default path is used.

## Operational Rollback

Set this in the listener config:

```json
{
  "concurrency_scheduler": {
    "enabled": false
  }
}
```

This keeps the old managed serial loop available for emergency rollback without changing business reply logic.
