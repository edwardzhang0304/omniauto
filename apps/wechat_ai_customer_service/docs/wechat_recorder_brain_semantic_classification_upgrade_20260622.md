# WeChat AI Recorder Brain Semantic Classification Upgrade 2026-06-22

## 1. Goal

Upgrade the WeChat AI Recorder structured export path from "rules plus LLM repair" toward an internal Recorder Brain layer: LLM first understands and classifies mixed raw chat content, then existing rule/guard/export code validates and maps the result.

This document governs the next implementation stage for `order_sheet_lab_v1` and recorder export internals.

## 2. Non-Negotiable Boundaries

- Do not rename public CLI routes, API routes, JSON fields, module keys, file paths, or public function names.
- Keep `order_sheet_lab_v1` as the module key and keep existing workbook headers unchanged.
- Keep current rule extractors, final row validators, de-duplication, MessageEnvelope handling, and export pipeline available as fallbacks.
- Do not let LLM output bypass validation. LLM classifies and proposes; code validates, normalizes, risk-tags, and exports.
- Do not add account-specific or industry-specific hard-coded business facts. Domain examples may live only in prompts/tests as generic extraction guidance.
- Preserve Brain First customer-service ownership rules. This recorder brain is for recorder semantic classification only and must not author customer-visible replies.

## 3. Current Gap

Current `order_sheet_lab_v1` already has LLM calls, but the LLM is mostly used as:

1. candidate upgrade after rule screening,
2. message segmentation,
3. row extraction,
4. row repair,
5. brand inference.

That still leaves the rule layer responsible for too many upstream decisions: whether a mixed message is an order candidate, where metadata ends and business content begins, whether a speaker prefix is semantic content, and how to split text that mixes product, teacher, receiver, address, quote, and OCR noise.

This is why small cleanup rules help, but cannot fully solve the general problem.

## 4. Target Architecture

Add a new internal layer named Recorder Brain semantic classification.

Pipeline after upgrade:

1. MessageEnvelope creates canonical semantic content and metadata separation.
2. Rule baseline still extracts rows as before.
3. Recorder Brain classifies each complex or ambiguous message into semantic blocks.
4. LLM row extraction receives only order-like semantic blocks when classification is confident.
5. Existing `_finalize_order_row`, cleanup, validation, risk flags, dedupe, and workbook export remain authoritative.
6. If classification fails, is low-confidence, malformed, or unavailable, fall back to current extraction flow.

## 5. Recorder Brain Output Contract

Internal only. No external API fields are changed.

Suggested internal payload:

```json
{
  "blocks": [
    {
      "block_id": "b1",
      "type": "order_item|gift_item|brand_context|person_metadata|receiver_info|address_info|quote_history|status_noise|followup_confirmation|other",
      "text": "source text span",
      "source_role": "current_message|metadata|quote|ocr_noise|context",
      "can_create_order_row": true,
      "fields_hint": {
        "product_name": "",
        "brand": "",
        "spec": "",
        "quantity": "",
        "unit": "",
        "sale_price": "",
        "total_sale": "",
        "name": "",
        "owner": "",
        "receiver": ""
      },
      "confidence": 0.0,
      "reason": "short audit reason"
    }
  ],
  "message_intent": "order|mixed_order|followup|noise|unknown",
  "confidence": 0.0,
  "warnings": []
}
```

## 6. Classification Rules For The LLM

The Recorder Brain prompt should be general and reusable:

- Group speaker names, chat titles, contact names, teacher names, and OCR/RPA speaker labels are metadata unless explicitly part of the order content.
- Quoted or historical preview text is not current order fact unless the current message clearly confirms or modifies it.
- A message may contain multiple blocks: order item, buyer/teacher metadata, receiver/address info, delivery note, settlement, or noise.
- Product facts must come from the raw text span, not from inference.
- Do not invent price, product, quantity, spec, owner, or receiver.
- Keep uncertain blocks as `other` or mark low confidence instead of forcing them into order rows.
- Multi-SKU messages should split into multiple order-like blocks when each item has independent product evidence.

## 7. Integration Strategy

### Phase A: Documentation And Contract Audit

- Add this document.
- Confirm existing public contracts remain unchanged.
- Add tests that assert route/module/output field names remain stable where relevant.

### Phase B: Internal Classifier Helper

- Add private helper methods inside `RecorderExportRunService`.
- Use existing `_call_deepseek_json_cached` so caching, failures, and stats remain consistent.
- Add module config keys only as optional internal config:
  - `recorder_brain_classification_enabled`
  - `recorder_brain_classification_min_confidence`
  - `recorder_brain_classification_max_calls_per_run`
- Defaults should be conservative and fail-safe.

### Phase C: Feed Classified Blocks Into Existing LLM Extraction

- For messages selected for LLM upgrade, classify first when enabled.
- If confident order blocks exist, call existing row extraction on those block texts instead of the entire mixed message.
- Keep current full-message extraction fallback when classification is unavailable or weak.
- Never skip `_finalize_order_row`.

### Phase D: Tests

Add focused tests using existing real conversation records and compact synthetic boundary cases where needed:

- Mixed message with teacher/person prefix plus product order.
- Multi-product message with shared teacher line.
- Quote/history text that must not become current product.
- Receiver/address info that must not pollute product name.
- Product label tokens such as `产品名称` are treated as labels, not product text.
- Classification failure falls back to current flow.
- Existing `order_sheet_lab_v1` regression remains green.

### Phase E: Acceptance

- `py_compile` touched files.
- `run_recorder_order_sheet_module_checks.py`.
- `run_recorder_capture_backfill_checks.py`.
- `run_smart_recorder_checks.py`.
- Real historical sample extraction scan.
- Real historical raw-message -> export-run -> xlsx smoke.
- `git diff --check`.

## 8. Risk Controls

- The classifier is advisory. Malformed/low-confidence output is ignored.
- LLM-classified rows must still pass existing product/person/noise cleanup and risk flags.
- Strong rule rows remain protected unless classification clearly improves quality.
- Budgets stay bounded; classification calls count separately to avoid runaway cost.
- Add clear stats fields internally so we can compare selected classified path vs fallback path.

## 9. Acceptance Definition

This stage is acceptable when:

1. Documentation and code agree.
2. Public contracts are unchanged.
3. Recorder Brain classification improves or preserves export quality on real historical samples.
4. Existing recorder/customer-service-adjacent regression tests pass.
5. Failure modes are safe: classification unavailable means current extraction path still runs.
