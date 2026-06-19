# AI Experience Runtime Usage Gate 2026-06-19

## Objective

Keep the existing Brain First architecture and public contracts unchanged while making tenant-specific AI experience pool data useful at runtime without letting it authorize facts or commitments.

The rule is: code stays generic, tenant data stays specific. A tenant such as chejin can accumulate concrete useful experience, but the program must only use that experience through generic source, quality, completeness, and authority rules.

## Non-Goals

- Do not rename variables, CLI routes, file paths, JSON fields, or internal API contracts.
- Do not clean or rewrite existing tenant experience data in this change.
- Do not promote AI experience pool items into formal knowledge automatically.
- Do not add customer-specific or industry-specific reply branches.
- Do not let RAG/AI experience authorize product facts, policies, prices, stock, condition, availability, finance, after-sales, contracts, invoices, appointments, or commitments.

## Minimal Design

### 1. Runtime Gate At Existing Evidence Boundary

Use the existing `compact_rag_evidence(...)` boundary in `reply_evidence_builder.py`.

Each retrieved hit is classified by generic runtime-use posture:

- `reference_experience`: complete enough to help Brain understand scenario, customer concern, follow-up strategy, or expression.
- `style_only`: useful only as tone/style material, not content evidence.
- `drop`: system/OCR noise, incomplete fragments, chat metadata, add-friend artifacts, or risky fact/commitment text.

This gate only evaluates the small set of hits already retrieved for the current turn. It does not scan the whole database and does not call another LLM.

### 2. Preserve Authority Boundary

The existing `rag_evidence.hits` content-evidence path remains authority-gated by `can_authorize_reply_content(...)`.

AI experience pool hits that pass the new gate are exposed only through `ai_experience_pool.source.hits` as auxiliary guidance:

- `can_authorize_reply_content` remains `False`.
- `rag_can_authorize` remains non-authoritative.
- Brain may use the hit for style/scenario/follow-up only.
- Guard still blocks unsupported facts or authority topics.

### 3. Prompt Contract

Brain prompt receives a compact AI experience pool summary when useful:

- authority level is still `ai_experience_pool`
- usage policy explicitly says experience/style only
- each hit has `runtime_usage`
- hit text is clipped and marked non-authoritative

### 4. Guard Backstop

Keep the existing Guard behavior:

- RAG-only authority topics are blocked.
- Product facts require product master.
- Policy/process commitments require formal knowledge.

No new customer-visible local wording is introduced.

## Implementation Steps

1. Add generic runtime-use helpers inside `reply_evidence_builder.py`.
2. Keep `rag_evidence.hits` unchanged for authoritative content basis.
3. Populate `ai_experience_pool.source.hits` with gated auxiliary hits.
4. Update `customer_service_brain.py` prompt compaction so auxiliary hits are visible to Brain.
5. Add focused tests for:
   - noisy AI experience hit is dropped
   - useful tenant-specific experience is passed as non-authoritative reference
   - risky commitment text is not exposed as runtime reference
   - formal RAG content evidence behavior remains unchanged

## Rollback

Revert only:

- this document
- the small helper additions in `reply_evidence_builder.py`
- the compact prompt addition in `customer_service_brain.py`
- the new/updated focused tests

No data migration or tenant data cleanup is required.

## Verification Plan

1. Static compile for touched Python files.
2. Focused AI experience authority tests.
3. Knowledge authority and Brain contract checks.
4. Existing RAG governance/runtime checks.
5. Offline simulation/regression.
6. Live WeChat assessment only after simulation passes and only as a shallow smoke test; this change affects reply evidence packaging, not RPA clicking/sending.
