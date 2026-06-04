# WeChat AI Recorder OCR MessageEnvelope Release Notes 2026-06-04

## Scope

This release hardens the WeChat AI Recorder OCR/RPA capture path and the `order_sheet_lab_v1` structured export module. The goal is to keep OCR metadata out of semantic order extraction, use program-read timestamps for recorder exports, reduce duplicate rows caused by repeated OCR scans, and preserve compatibility with the WeChat AI Customer Service workflow.

## Main Changes

- Added a shared MessageEnvelope layer for OCR/RPA messages so group speaker names, quoted fragments, bubble metadata, OCR quality flags, and semantic content are separated before recorder/customer-service logic consumes the message.
- Updated raw message persistence so OCR/RPA `captured_at`, `observed_at`, and `message_time` are based on the time the program actually reads the message. Screen-visible time is preserved separately as `screen_time_text`.
- Hardened OCR near-duplicate handling:
  - Exact OCR repeats only merge when message identity, source screen time, or very-close observed time indicates the same visible bubble.
  - Partial/fuzzy OCR fragments can still merge into a more complete bubble.
  - Old visible duplicates no longer refresh export-window timestamps unless the incoming OCR capture is clearly more complete.
- Updated raw-message export to use the MessageEnvelope view and display program-read time.
- Updated the lab order export workbook so date and time are separated into `日期` and `时间` columns.
- Improved `order_sheet_lab_v1` extraction for:
  - Brand context inheritance and brand display in product names.
  - Chinese/English brand-like prefixes such as `源叶`, `白鲨`, and `思科捷`.
  - Multi-product messages split by `元` as the product-ending signal.
  - Broken-line specs such as `SJ-\nMN0579`, composing them into `SJ-MN0579`.
  - Long formulation specs such as `10 mM * 1mL in DMSO`.
  - Context-based buyer-name fallback within a short recent-message window.
- Added close-window duplicate row dedupe before Excel generation, keyed by date, buyer, owner, receiver, record type, brand, product, spec, quantity, unit, sale price, and total sale.
- Added validation-marker stripping so test markers such as `【验收标记 ...】` do not pollute product names or specs.
- Increased risk surfacing by carrying MessageEnvelope quality/risk flags into recorder export rows and preserving review status for uncertain rows.
- Added regression coverage for OCR metadata separation, quote filtering, timestamp behavior, OCR duplicate handling, lab-order extraction, spec repair, duplicate row dedupe, and recorder/customer-service compatibility.

## Validation

The following checks passed locally:

- `python -m py_compile apps\wechat_ai_customer_service\admin_backend\services\raw_message_store.py apps\wechat_ai_customer_service\admin_backend\services\recorder_export_run_service.py apps\wechat_ai_customer_service\tests\run_smart_recorder_checks.py apps\wechat_ai_customer_service\tests\run_recorder_order_sheet_module_checks.py`
- `python -B apps\wechat_ai_customer_service\tests\run_smart_recorder_checks.py`
- `python -B apps\wechat_ai_customer_service\tests\run_recorder_order_sheet_module_checks.py`
- `python -B apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_compat_checks.py`
- `python -B apps\wechat_ai_customer_service\tests\run_workflow_logic_checks.py`
- `git diff --check`

## Live Smoke Test

A small live smoke test was run against the WeChat group `新数据测试` using default send-rate protection:

- Sent 2 validation messages.
- Captured 2 raw OCR/RPA messages.
- Extracted 3 order rows.
- Verified separated date/time output, brand extraction, multi-product split, and `SJ-MN0579 10 mM * 1mL in DMSO` spec repair.

Known live-test boundary:

- OCR can still misrecognize product text, for example `槲皮素` may be read as `皮素`. The structured exporter cannot safely infer missing OCR characters without stronger visual or product-library evidence, so those rows should remain reviewable.

## Compatibility Notes

- The customer-service workflow continues to treat OCR/RPA speaker labels as metadata rather than customer message body.
- Recorder-only flows should not automatically promote recorder messages into formal knowledge. RAG/knowledge learning remains governed by the existing learning settings and contamination guard.
- Runtime tenant data, local account data, WeChat logs, and generated live-test artifacts are intentionally not part of this release commit.
