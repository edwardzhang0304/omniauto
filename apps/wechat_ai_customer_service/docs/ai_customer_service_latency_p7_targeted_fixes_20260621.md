# P7 Targeted Latency Fixes

## Scope

This phase fixes only bottlenecks proven by the P6 baseline. It must preserve the current framework, public names, CLI routes, JSON fields, and Brain First ownership.

## Boundaries

- Do not rename variables, paths, CLI commands, public functions, JSON fields, or worker-facing contracts.
- Do not change customer-visible reply ownership. Brain remains the author of visible replies.
- Do not add local reply templates or account-specific answer branches.
- Do not shorten timeout ceilings as a substitute for correct work.
- Do not bypass evidence, guard, semantic review, final visible polish, target/session checks, or RPA safety checks.
- Additive internal timing fields are allowed. Existing fields must keep their names and meaning.

## P6 Findings To Fix

1. Boundary dry-run showed `evidence_pack_duration_seconds` around 29-33 seconds.
2. Chejin tenant reproduction confirmed `knowledge_loader.build_evidence_pack()` takes about 28-29 seconds for catalog-style product recommendation turns.
3. The same message under the default tenant takes about 1-2 seconds, so the slow path is tenant data dependent.
4. P6 artifacts show the slow chejin path includes AI experience pool reference hits. These are auxiliary only and cannot authorize product facts or commitments.
5. One P6 boundary reply showed `quality_repair_duration_seconds` around 30 seconds. The later P7 retest did not reproduce repair after the evidence-pack cache fix, so repair logic must not be changed without a fresh artifact proving the exact hard/soft trigger.

## Chapter 1: Cache AI Experience Reference Retrieval Internals

Problem:

`RagService.search_experience_references()` rebuilds reference chunks into scored index entries on every customer message. For tenants with a large AI experience pool, this repeatedly runs tokenization, semantic expansion, vector building, and scoring for the same reference corpus.

Fix direction:

- Cache reference index entries in memory per tenant and source-state signature.
- Invalidate automatically when the underlying experience source changes.
- Keep returned hit structure unchanged.
- Keep AI experience pool auxiliary and non-authoritative.
- Add internal timing fields so future artifacts can separate reference-index build time from scoring time.

Verification:

- Offline chejin evidence-pack timing should drop after the first warm call.
- `run_customer_service_brain_contract_checks.py` must pass.
- `run_realtime_reply_optimization_checks.py` or focused RAG checks must pass where practical.
- Boundary dry-run should show lower `evidence_pack_duration_seconds` without changing reply contracts.

## Chapter 2: Repair Path Audit Before Behavior Changes

Problem:

P6 had one slow repair sample, but the artifact available after repair did not preserve enough pre-repair detail to prove that a warning-only finding caused the repair. P7 boundary dry-run after Chapter 1 passed with no `quality_repair_duration_seconds`, so the safe conclusion is to audit and observe before changing repair behavior.

Fix direction:

- Do not change repair behavior until a fresh failing artifact proves the exact trigger.
- If a future artifact proves warning-only quality causes repair, fix only that warning-only path.
- Preserve hard errors, authority conflicts, missing direct answer, safety concerns, and guard repair behavior.
- Keep final visible polish required.
- Preserve Brain First: reviewers and guards still provide feedback; they do not author customer-visible replacements.

Verification:

- Boundary dry-run should report no unnecessary `quality_repair_duration_seconds` for safe product-master replies.
- If repair reappears, preserve the pre-repair quality/semantic-review reason in audit before changing runtime behavior.

## Chapter 3: Capture Breakdown Before Behavior Changes

Problem:

Short-message live tests still spend about 10-13 seconds in capture and pending/capture wait, but the current artifact is not detailed enough to safely optimize.

Fix direction:

- Add additive timing fields around capture queue wait, session scan/open-chat read, OCR parse, history backfill, and scheduler handoff.
- Do not parallelize foreground WeChat RPA.
- Do not weaken target/session isolation.

Verification:

- Scheduler checks pass.
- One low-volume live short-greeting run produces capture breakdown with verified sends.

## Chapter 4: Same-Target Multi-Segment Send Reuse Design Only

Problem:

Live short-business replies with multiple segments pay repeated send tail cost. This may be optimizable only when consecutive segments target the same hwnd/session/geometry.

Fix direction:

- Document and prototype only after Chapter 3 data.
- Final pre-send strict target guard remains.
- No blind send, no mouse plus keyboard double trigger, no repeated fixed-pixel clicking.

Verification:

- Win32/OCR compat, risk, humanized input, scheduler checks.
- Low-volume live test only if dry/static gates pass.

## Current P7 Acceptance

P7 can be considered complete only when:

- Chapter 1 has code changes, tests, and artifact evidence.
- Chapter 2 has audit evidence; behavior changes are only allowed if a fresh artifact proves the trigger.
- Chapter 3 has at least documentation or additive timing if live data is still needed.
- No public contract names are changed.
- No Brain First or RPA safety guards are weakened.
- All relevant tests pass, or any environment-only blocker is explicitly documented.
