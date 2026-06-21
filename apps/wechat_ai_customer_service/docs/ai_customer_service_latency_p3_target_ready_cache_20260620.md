# AI Customer Service Latency P3 Target Ready Cache

## Goal

Reduce repeated `target_ready` cost for short replies without changing public contracts or weakening WeChat send safety.

This slice only optimizes the internal Win32/OCR sidecar path. It must not rename CLI commands, JSON fields, public functions, variables used as integration contracts, or route names.

## Current Finding

P2 live timing showed `target_ready` still costs about 6-8 seconds. The expensive parts are:

- `open_chat`: sidebar/session activation and OCR candidate parsing.
- strong OCR title validation before send.

The existing fast path already skips `open_chat` when the active title is strongly confirmed. The remaining gap is that session-key cache misses can still cause repeated sidebar activation even when the same session was just confirmed.

## Safe Optimization

Add a short-lived internal confirmation cache inside `wechat_win32_ocr_sidecar.py`.

The first implementation may only reuse the strong title confirmation that `open_chat` just performed after a session-row click. It skips the immediately duplicated post-open OCR validation, while keeping the final pre-send strong target recheck before typing.

The verified implementation also skips the matching duplicate post-open settle pause when that same strict switch validation is reused. This still does not skip the final pre-send target guard in `send_payload`.

An observability-only follow-up adds internal `open_chat` timing breakdown into the existing optional `send_timing` payload. The added fields are diagnostic only and do not change action strategy, public CLI, function signatures, or existing JSON fields.

Later slices may consider skipping redundant `open_chat`, but only after live evidence proves the cached session row is still current.

Cache hit requirements:

- same `session_key`
- same target name
- same `exact` mode
- same window geometry
- recent successful strict title confirmation
- TTL not expired

On a cache hit:

- still run `validate_active_send_target`
- require `active_send_guard_is_strong`
- mark timing metadata for audit
- do not click the session row

For the first implementation, "cache hit" means the already completed target-switch validation is reused inside the same sidecar daemon call. The send payload still performs a strict target recheck before typing.

On any mismatch, expiry, weak confirmation, blank render, OCR failure, or target mismatch:

- fall back to the existing path
- keep hard-stop behavior for blank/login/auxiliary-window states

## Non-Goals

- No blind send.
- No removal of pre-send strong target guard.
- No bypass of session binding.
- No changes to Brain First reply ownership.
- No changes to add-friend CLI or worker JSON contracts.
- No account-specific or product-specific rules.

## Tests

Required before moving forward:

- source compile for touched files
- Win32/OCR compatibility checks
- send/action risk checks
- scheduler/workflow checks when runtime env or listener behavior changes

Live testing should be low-volume and only after static tests pass.

## 2026-06-20 Verification Notes

- Static and compatibility checks passed after P3.1/P3.2.
- Low-volume two-session live runs verified real sends and kept WeChat online.
- Final live timing showed `target_ready` around 4.9s and 4.5s after duplicate post-open validation/pause reuse.
- New `open_chat` breakdown shows remaining cost is mostly main screenshot/OCR plus activation confirmation OCR, not an obviously removable fixed wait.
- During live validation, a generic short-summon boundary defect was found and fixed: pure "在吗/人呢" turns must not continue prior self-history topics unless there is a real earlier unreplied customer message. This is a Brain/quality boundary fix, not an RPA speed shortcut.
