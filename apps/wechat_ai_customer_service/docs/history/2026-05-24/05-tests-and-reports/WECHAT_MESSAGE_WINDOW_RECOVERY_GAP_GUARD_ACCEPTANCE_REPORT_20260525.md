# WeChat Message Window Recovery Gap Guard Acceptance Report

## Scope

This report covers the RPA-first message-window recovery work for WeChat customer service and AI recorder burst/backfill robustness.

The goal was to ensure that when customer messages exceed the visible WeChat page, the runtime can recover older visible history with pure RPA, avoid missed or duplicated replies, and avoid any accidental wxauto4 execution path.

## Implementation Summary

- Customer service now tracks processed message content with exact and normalized content keys.
- Gap guard blocks customer-visible replies when a prior processed anchor exists but cannot be found after history backfill.
- Win32/OCR sidecar history loading now captures multiple scroll snapshots, merges them chronologically, and reports `snapshot_count`.
- The sidecar restores the chat to the latest position after deep history reads.
- OCR time-only rows such as `昨天23:57` are filtered as message noise.
- Processed message keys now include stable line and adjacent-line fragments, so OCR split bubbles do not trigger duplicate replies.
- Default and Chejin live configs now allow deeper max history backfill (`max_load_times: 12`) while keeping normal `load_times` light.
- wxauto4 remains disabled unless explicitly enabled as a technical reserve; acceptance checks require `win32_ocr.*` or `rpa.history_load`.

## Knowledge Priority Contract

When product master, formal knowledge base, and RAG experience all contain relevant content, runtime priority is:

1. Product master and structured product/item facts.
2. Formal curated knowledge base policies, FAQs, rules, and handoff constraints.
3. RAG experience only as supplemental style/context when governance allows it.
4. LLM synthesis only within the above evidence boundaries.

Specific formal rules beat generic rules. For example, `special_invoice_rule` correctly wins over generic `invoice` for a VAT special invoice question.

## Static And Full Regression

Final full regression completed on 2026-05-25.

Passed commands:

- `python -m py_compile apps/wechat_ai_customer_service/adapters/wechat_win32_ocr_sidecar.py apps/wechat_ai_customer_service/workflows/listen_and_reply.py apps/wechat_ai_customer_service/tests/run_burst_message_rpa_semantic_batch_checks.py apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_compat_checks.py`
- `python apps/wechat_ai_customer_service/tests/run_burst_message_rpa_semantic_batch_checks.py`
- `python apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_compat_checks.py`
- `python apps/wechat_ai_customer_service/tests/run_workflow_logic_checks.py`
- `python apps/wechat_ai_customer_service/tests/run_offline_regression.py`
- `python apps/wechat_ai_customer_service/tests/run_customer_service_diverse_long_checks.py`
- `python apps/wechat_ai_customer_service/tests/run_realtime_reply_optimization_checks.py`
- `python apps/wechat_ai_customer_service/tests/run_style_adapter_checks.py`
- `python apps/wechat_ai_customer_service/tests/run_smart_recorder_checks.py`
- `python apps/wechat_ai_customer_service/tests/run_recorder_capture_backfill_checks.py`
- `python apps/wechat_ai_customer_service/tests/run_recorder_order_sheet_module_checks.py`
- `python apps/wechat_ai_customer_service/tests/run_boundary_matrix_checks.py`
- `python apps/wechat_ai_customer_service/tests/run_real_chat_rag_first_checks.py`
- `python apps/wechat_ai_customer_service/tests/run_rag_boundary_checks.py`
- `python apps/wechat_ai_customer_service/tests/run_knowledge_contamination_guard_checks.py`
- `python apps/wechat_ai_customer_service/tests/run_runtime_start_cloud_guard_checks.py`
- `python apps/wechat_ai_customer_service/tests/run_vps_local_two_port_shared_sync_checks.py`
- `python apps/wechat_ai_customer_service/tests/run_admin_backend_checks.py`
- `python apps/wechat_ai_customer_service/tests/run_standard_workflow_checks.py`
- `python apps/wechat_ai_customer_service/tests/run_workflow_reliability_quick_checks.py`
- `python apps/wechat_ai_customer_service/tests/run_llm_reply_synthesis_checks.py`
- `python apps/wechat_ai_customer_service/tests/run_knowledge_runtime_checks.py`
- `python apps/wechat_ai_customer_service/tests/run_product_master_split_checks.py`
- `python apps/wechat_ai_customer_service/tests/run_multi_tenant_auth_sync_checks.py`
- `python apps/wechat_ai_customer_service/tests/run_local_auth_shared_console_checks.py`
- `python apps/wechat_ai_customer_service/tests/run_jiangsu_chejin_used_car_checks.py`
- `python apps/wechat_ai_customer_service/tests/run_jiangsu_chejin_llm_synthesis_checks.py`

Final full regression duration: about 120.58 seconds.

## Live RPA Findings And Fixes

Live target: File Transfer Assistant.

Initial status:

- `adapter`: `win32_ocr`
- `transport_priority`: `rpa_first`
- wxauto4 reserve: disabled / not used

Observed and resolved issues:

- The first burst attempt hit the local send-rate guard at the sixth message. This was expected protection, not a WeChat failure.
- With test-only burst-limit override, 12 messages were sent through `win32_ocr` using `clipboard_once` only for this approved burst test.
- The first processing attempt safely blocked with `gap_risk=true` because the old sidecar only returned one scrolled viewport rather than cumulative history.
- After cumulative multi-snapshot history recovery, read-only live history recovered B01-B12 with `requested_load_times=14`, `snapshot_count=15`.
- Live processing then recovered the anchor with `gap_risk=false`, `loaded_message_count=23`, `final_eligible_count=20`, and sent a reply through `sendinput_unicode`.
- A duplicate second reply exposed OCR split-fragment drift. Fragment keys were added and covered by regression checks.
- Post-fix live duplicate probe returned `skipped` with `reason=no eligible unprocessed text messages`; no third reply was sent.

Key artifacts:

- `runtime/apps/wechat_ai_customer_service/test_artifacts/message_window_gap_guard_live/GAPGUARD_20260524_235553/report.json`
- `runtime/apps/wechat_ai_customer_service/test_artifacts/message_window_gap_guard_live/GAPGUARD_PROCESS_20260525_001048/report.json`
- `runtime/apps/wechat_ai_customer_service/test_artifacts/message_window_gap_guard_live/GAPGUARD_DUPPROBE_20260525_001717/report.json`

## Long Soak

No-send live RPA soak completed:

- Duration: 426.5 seconds
- Cycles: 10
- Status: all cycles online
- Adapter: `win32_ocr` in all cycles
- Message reads: all cycles `messages_ocr`
- History reads: cycles 1, 5, and 10 used `requested_load_times=2`, `snapshot_count=3`
- No login window, blocked screen, blank render, or wxauto4 reserve usage observed

Artifact:

- `runtime/apps/wechat_ai_customer_service/test_artifacts/message_window_gap_guard_live/SOAK_20260525_002135/report.json`

## Acceptance Result

Accepted for handoff.

The current implementation meets the requested RPA-first behavior for burst message recovery:

- Pure RPA path verified.
- wxauto4 not used.
- History beyond the visible page can be recovered.
- Unsafe continuity gaps pause instead of replying.
- OCR split fragments are suppressed after processing.
- Static, regression, live, and soak checks passed.
