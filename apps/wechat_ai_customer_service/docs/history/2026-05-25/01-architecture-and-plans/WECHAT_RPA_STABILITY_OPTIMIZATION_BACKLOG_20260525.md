# WeChat RPA Stability Optimization Backlog

## Goal

Keep the WeChat automation path stable, efficient, and low-risk after switching to pure RPA-first operation.

This backlog records follow-up work that is useful for validating and improving the RPA module. It is intentionally split into test-first items and optimization items so each future change has a clear acceptance path.

## Priority 1 Test Matrix

- Static compatibility: run focused py_compile and Win32/OCR compatibility checks after every RPA adapter change.
- RPA path proof: verify live status reports `adapter=win32_ocr`, `transport_priority=rpa_first`, and no wxauto4 reserve execution.
- Window geometry: test default fixed window, small window rejection, restored/minimized recovery, and current display bounds.
- History recovery: test visible-only read, shallow backfill, deep cumulative backfill, and gap guard metadata.
- Duplicate prevention: test OCR split fragments and repeated reads after messages have been processed.
- Safety states: test login window, QR/quick-login, blocked screen, blank render, and missing main window detection.
- No-send soak: periodically read status/messages without sending to detect white screen, logout, OCR instability, or adapter drift.

## Priority 2 Test Matrix

- Resolution and DPI matrix: 1366x768, 1920x1080, 2560x1440; 100%, 125%, 150% scaling.
- Window size matrix: fixed recommended size, maximized, narrow/small, partially offscreen, secondary monitor.
- Focus and obstruction: another app steals focus, partial overlap, IME candidate window, foreground lock delays.
- Mixed message types: text, long text, image/file rows, system timestamps, recall/system messages, multi-line bubbles.
- Customer service plus recorder concurrency: both modules active, shared RPA lock, floating indicator state, F8 pause/stop.

## Priority 3 Long Tests

- 30-minute no-send live soak.
- 2-hour mixed passive/active read soak.
- Half-day listener soak with synthetic low-frequency File Transfer Assistant traffic.
- Failure-recovery soak: deliberately minimize/restore WeChat, move the window, and verify recovery or safe pause.

## Optimization Backlog

- Adaptive backfill: start shallow, increase depth only when the anchor is missing or visible window is saturated.
- Anchor early stop: stop sidecar scrolling as soon as a target anchor or content fingerprint is recovered.
- OCR region crop: identify chat body, title, and input regions before OCR to reduce cost and false positives.
- Viewport fingerprint cache: skip OCR when screenshot hash/geometry indicates no meaningful change.
- Strong bottom confirmation: after deep history read, confirm the chat has returned to latest before sending.
- Operation telemetry: record open-chat, OCR, backfill, input, send, and verify durations for percentile tracking.
- Failure taxonomy: classify retryable, pause-required, human-takeover, suspected-risk, login, and blank-render states.
- Diagnostic package: persist screenshot, OCR text, window geometry, adapter metadata, and event JSON on every abnormal stop.
- Input strategy policy: keep clipboard disabled by default; allow test-only clipboard with explicit flags and audit marks.
- Dynamic send throttling: slow down after repeated sends, repeated OCR failures, or ambiguous target confirmation.

## Current First Test Batch

Initial test batch should cover:

1. Focused static and compatibility checks.
2. Focused burst/gap guard regression.
3. Live no-send RPA status proof.
4. Live shallow/deep history read proof.
5. Live no-send duplicate probe.
6. Short no-send soak.

Acceptance for this first batch:

- All focused tests pass.
- Live adapter remains `win32_ocr`.
- wxauto4 reserve is not used.
- History reads return `messages_ocr`.
- No live send is triggered during no-send probes.
- No login, blank render, blocked screen, or missing main window is observed.

## First Test Batch Result

Run time: 2026-05-25.

Focused automated tests passed:

- `python -m py_compile apps/wechat_ai_customer_service/adapters/wechat_win32_ocr_sidecar.py apps/wechat_ai_customer_service/workflows/listen_and_reply.py apps/wechat_ai_customer_service/tests/run_burst_message_rpa_semantic_batch_checks.py apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_compat_checks.py`
- `python apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_compat_checks.py`
- `python apps/wechat_ai_customer_service/tests/run_burst_message_rpa_semantic_batch_checks.py`
- `python apps/wechat_ai_customer_service/tests/run_recorder_capture_backfill_checks.py`
- `python apps/wechat_ai_customer_service/tests/run_workflow_logic_checks.py`

Live no-send RPA probe:

- File Transfer Assistant message reads passed at history depths `0`, `2`, `8`, and `14`.
- All message reads reported `adapter=win32_ocr`, `transport_priority=rpa_first`, `state=messages_ocr`.
- Deep history read at depth `14` returned `snapshot_count=15`.
- Duplicate probe returned `skipped` with `reason=no eligible unprocessed text messages`.
- Short soak passed three cycles after the window was restored.
- No live send was triggered during this test batch.

Finding:

- Initial passive `status()` can return `main_window_geometry_invalid` with geometry near `-32000,-32000` when WeChat is minimized. Subsequent RPA message reads restore the window and pass, and `status(interactive=True)` plus `capabilities(interactive=True)` both confirm `win32_ocr` normally.

Follow-up optimization:

- Health checks should treat passive minimized-window geometry as `needs_interactive_confirm` rather than final offline. The startup/preflight path should automatically run one interactive status/capability confirmation before showing "未找到微信" or "未登录" to the user.

Artifact:

- `runtime/apps/wechat_ai_customer_service/test_artifacts/rpa_stability_priority_tests/RPA_PRIORITY_TEST_20260525_004840/report.json`

## Startup Health Check Optimization Result

Run time: 2026-05-25.

Implemented:

- `WeChatConnector.status(interactive=True)` and `WeChatConnector.capabilities(interactive=True)` now retry once when the first RPA result is a recoverable geometry failure such as minimized, offscreen, or too-small WeChat window.
- Passive background probes remain non-invasive and do not restore or resize WeChat on their own.
- Startup self-check now preserves the underlying Win32/OCR failure reason even when the final connector payload is wrapped by the generic transport decision layer.
- `WeChatConnector.require_online()` now uses an interactive status probe because it is called by active workflows, not passive monitoring.
- Fixed a connector return-path defect where `call_compat_sidecar()` could omit the final payload return after successful or allow-failure calls.

Validation:

- `python -m py_compile apps/wechat_ai_customer_service/adapters/wechat_connector.py apps/wechat_ai_customer_service/admin_backend/services/wechat_startup_check.py apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_compat_checks.py`
- `python apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_compat_checks.py` passed 43 checks.
- `python apps/wechat_ai_customer_service/tests/run_admin_backend_checks.py` passed 20 checks.
- `python apps/wechat_ai_customer_service/tests/run_workflow_logic_checks.py` passed 43 checks.
- Live no-send minimize/restore test passed: passive status reported `main_window_geometry_invalid`, then startup self-check restored WeChat and passed with `scheme=win32_ocr_guarded_click`; final interactive status reported `adapter=win32_ocr`, `transport_priority=rpa_first`, and normalized geometry `980x860`.

Remaining watch item:

- If a future passive dashboard status is intended to recover WeChat automatically, it should call the interactive confirmation path explicitly. The current passive path is intentionally kept safe and non-invasive for anti-risk monitoring.

## Startup E2E Test Result

Run time: 2026-05-25 01:15-01:19.

Scope:

- Customer service tenant: `chejin`.
- Recorder tenant: `test02`.
- The customer-service test temporarily switched `chejin` to `record_only` to avoid sending messages to real chats, then restored the original `full_auto` setting.
- The tests used the same backend endpoints as the web console start/stop controls.

Results:

- Customer service passed after WeChat was minimized: startup self-check restored WeChat, selected `scheme=win32_ocr_guarded_click`, started the listener, started operator guard, installed hooks, and activated the floating indicator.
- AI smart recorder passed after WeChat was minimized: startup self-check restored WeChat, selected `scheme=win32_ocr_guarded_click`, started the recorder loop, started operator guard, installed hooks, and activated the floating indicator.
- Both modules stopped cleanly after the test; no customer-service or recorder loop process remained running.
- The admin page loaded successfully at `http://127.0.0.1:8765/`.

Window matrix:

- Too-small WeChat window was normalized to `980x860` and passed startup self-check.
- Partially offscreen WeChat window was moved back to `0,0,980,860` and passed startup self-check.
- All tested paths reported `adapter=win32_ocr` and `transport_priority=rpa_first`.

Artifacts:

- `runtime/apps/wechat_ai_customer_service/test_artifacts/rpa_startup_e2e/startup_e2e_20260525_011515.json`
- `runtime/apps/wechat_ai_customer_service/test_artifacts/rpa_startup_e2e/recorder_startup_e2e_20260525_011602.json`
- `runtime/apps/wechat_ai_customer_service/test_artifacts/rpa_startup_e2e/window_matrix_dpiaware_20260525_011850.json`

Follow-up:

- The Windows process tree for `admin_backend.app` currently appears as a parent process plus the actual listening process. Do not kill the non-listening parent manually; add a code-level single-instance/runbook guard later if duplicate backend launches keep causing confusion.

## Managed Listener Watchdog Optimization Result

Run time: 2026-05-25 01:24-01:31.

Finding:

- A low-risk File Transfer Assistant live short test sent one inbound test message successfully, then the managed customer-service listener timed out twice while running `listen_and_reply.py --once --send --write-data`.
- No matching customer-service audit event or automatic reply was found for the test token, so the live test did not complete a reply round.
- The root cause was that `realtime_reply.watchdog_timeout_seconds=25` was still being used as the whole managed-loop watchdog. That value is too short for the current RPA-first path, which can include window recovery, OCR, history backfill, intent routing, LLM synthesis, final visible polish, semantic batching, humanized typing, and post-send confirmation.
- Runtime state and settings were restored after aborting the live short test. `chejin` returned to `full_auto`, File Transfer Assistant was disabled again, and no managed listener/operator-guard/test-harness process remained.

Implemented:

- `managed_once_timeout_seconds()` now delegates to a dynamic estimator after honoring `WECHAT_LISTENER_ONCE_TIMEOUT_SECONDS`.
- The estimator uses the configured watchdog as a floor, then adds budget for enabled history backfill, intent LLM, realtime foreground LLM, guarded LLM reply synthesis, final polish, semantic batching, and humanized RPA typing.
- RPA-humanized send mode now has a safe minimum floor, preventing the manager from killing a valid but slower RPA round.

Validation:

- `python -m py_compile apps/wechat_ai_customer_service/scripts/run_customer_service_listener.py apps/wechat_ai_customer_service/tests/run_realtime_reply_optimization_checks.py`
- `python apps/wechat_ai_customer_service/tests/run_realtime_reply_optimization_checks.py` passed, including:
  - `listener_rpa_watchdog_timeout_estimate` with estimated timeout `108.0`.
  - `listener_watchdog_env_override` confirming explicit env override still wins.
  - existing watchdog timeout behavior still works.
- `python apps/wechat_ai_customer_service/tests/run_admin_backend_checks.py` passed 20 checks.
- `python apps/wechat_ai_customer_service/tests/run_workflow_logic_checks.py` passed 43 checks.
- `python apps/wechat_ai_customer_service/tests/run_burst_message_rpa_semantic_batch_checks.py` passed 23 checks.
- `python apps/wechat_ai_customer_service/tests/run_recorder_capture_backfill_checks.py` passed 4 checks.
- `python apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_compat_checks.py` passed 43 checks.

Artifact:

- `runtime/apps/wechat_ai_customer_service/test_artifacts/rpa_live_short/customer_service_RPA_SHORT_20260525_012437_progress.json`

Next live-test rule:

- Continue live customer-service testing with a single-round harness first. Do not run multi-round sends until the single round has produced one clean audit event, one clean reply, no duplicate listener process, and a clean stop.

## Single-Round Live Customer-Service Result

Run time: 2026-05-25 01:33-01:39.

First single-round attempt:

- Inbound File Transfer Assistant send passed through `adapter=win32_ocr`, `transport_priority=rpa_first`, and humanized `sendinput_unicode`.
- Managed listener started with `scheme=win32_ocr_guarded_click`.
- Operator guard started, hooks were installed, manual input lock was enabled, and the floating indicator reported `floating_indicator_active=true`.
- The listener no longer hit the 25-second watchdog. It processed the target message and produced a safe local recommendation.
- Send was blocked because final visible LLM polish called OpenAI and got `RemoteDisconnected('Remote end closed connection without response')`. The failure was incorrectly treated as non-degradable even though `allow_send_when_unavailable` is enabled.

Implemented follow-up fix:

- Expanded transient final-polish failure detection to include remote disconnect / remote end closed / connection closed / connection error / server disconnected cases.
- Added a regression check proving that `RemoteDisconnected('Remote end closed connection without response')` degrades when `allow_send_when_unavailable=true`, while strict mode and non-transient failures still block.

Second single-round attempt:

- Passed end to end.
- Inbound and outbound both used `adapter=win32_ocr` and `transport_priority=rpa_first`.
- The reply was sent through humanized RPA input with chunked `sendinput_unicode`, one simulated typo, send-point click, and post-send target confirmation.
- OCR message verification passed with `verified=true` and `verification_mode=messages`.
- Operator guard remained active during the run and then stopped cleanly.
- Runtime, settings, listener config, and state were restored after the test; `chejin` returned to `full_auto`, File Transfer Assistant returned to disabled, and no managed listener/operator-guard/test-harness process remained.

Validation:

- `python -m py_compile apps/wechat_ai_customer_service/workflows/listen_and_reply.py apps/wechat_ai_customer_service/tests/run_workflow_logic_checks.py`
- `python apps/wechat_ai_customer_service/tests/run_workflow_logic_checks.py` passed 43 checks.
- `python apps/wechat_ai_customer_service/tests/run_admin_backend_checks.py` passed 20 checks.
- `python apps/wechat_ai_customer_service/tests/run_realtime_reply_optimization_checks.py` passed.
- `python apps/wechat_ai_customer_service/tests/run_burst_message_rpa_semantic_batch_checks.py` passed 23 checks.
- `python apps/wechat_ai_customer_service/tests/run_recorder_capture_backfill_checks.py` passed 4 checks.
- `python apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_compat_checks.py` passed 43 checks.

Artifacts:

- `runtime/apps/wechat_ai_customer_service/test_artifacts/rpa_live_single/customer_service_RPA_SINGLE_20260525_013327.json`
- `runtime/apps/wechat_ai_customer_service/test_artifacts/rpa_live_single/customer_service_RPA_SINGLE_20260525_013605.json`
- `runtime/rpa_customer_single_live.py`

Remaining watch item:

- The successful live reply content was high enough quality to send, but the OCR-visible context still contained prior File Transfer Assistant test messages. Before any larger multi-round live test, prefer a harness that either starts from a cleaner chat window or raises `max_batch_messages` above 1 and asserts the semantic batch contains only the latest test marker.
