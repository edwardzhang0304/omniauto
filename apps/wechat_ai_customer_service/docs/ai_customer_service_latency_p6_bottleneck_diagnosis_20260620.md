# P6 Latency Bottleneck Diagnosis Plan

## Purpose

P5 has reduced part of the Win32/OCR RPA tail, but live short-message replies can still feel slow. P6 is a diagnosis-first phase: run a clean baseline, identify where real time is spent, then decide which bottlenecks are worth fixing.

This phase must not change runtime behavior until the test data proves a specific, safe target.

## Non-Negotiable Boundaries

- Do not rename variables, constants, CLI commands, routes, file paths, JSON fields, public functions, or worker-facing contracts.
- Keep `add-friend-entry-click-plan` and all existing collaboration names stable.
- Do not change framework/module boundaries.
- Do not bypass Brain First. Customer-visible replies must still be authored by `customer_service_brain`.
- Do not use local hard-coded reply templates for speed.
- Do not skip product master, formal knowledge, guard, semantic review, or final visible polish.
- Do not optimize by shortening timeout ceilings and accepting missing/incomplete results.
- Do not skip target/session confirmation, input confirmation, post-send readability/blank-render checks, or RPA locks.
- Do not introduce mechanical repeated clicks, fixed-pixel clicking loops, or simultaneous mouse/keyboard actions.
- Do not add account-, product-, industry-, or tenant-specific rules to solve a local symptom.

Allowed in this phase:

- Add or use documentation, test scripts, artifact parsers, and offline analysis.
- Use existing optional timing fields and artifacts.
- Produce a prioritized fix list.
- Recommend future internal-only optimizations, but do not implement them in P6 diagnosis unless explicitly approved later.

## Timing Model

Each live or dry baseline must be summarized into the same stage model:

1. `signal_to_pending`: customer signal detected to pending queued.
2. `pending_to_capture_start`: pending queue wait before RPA capture.
3. `capture`: RPA/OCR capture and message extraction.
4. `capture_to_brain_start`: planning queue wait.
5. `brain`: evidence pack, Brain input, Brain LLM, plan validation, semantic review, guard.
6. `final_polish`: final visible polish queue, LLM/cache, verification.
7. `ready_to_send_start`: ready reply send queue wait.
8. `target_ready`: target/session/open-chat preparation.
9. `pre_send_guard`: strict target guard before typing.
10. `typing_input_confirm`: focus, clear draft, paste/type, input confirmation.
11. `send_trigger`: enter-only send trigger and humanized delay.
12. `post_send_guard`: post-send readability/blank-render guard.
13. `send_total`: full RPA send.
14. `end_to_end`: customer signal/pending to send finished.

For every stage, record:

- duration,
- queue vs active work,
- cache/seed hits,
- OCR call count and region,
- fallback/retry,
- first target vs second target,
- live vs dry mode.

## Test Matrix

### A. Static and Contract Baseline

Run before any diagnosis conclusions:

- `python -B -m py_compile` for touched/critical latency modules.
- `git diff --check` for P6 docs and recently touched latency files.
- Win32/OCR compatibility checks.
- Win32/OCR send/action risk checks.
- Humanized input checks.
- Workflow logic checks.
- Multi-session scheduler checks.
- Brain contract checks.
- File Transfer Assistant safety checks.
- Two-visible-session harness self-check.

Pass condition: all relevant checks pass. If any fail, classify as a current-version bug before doing speed analysis.

### B. Dry Baselines

Use dry reply-send for broad scenario coverage:

- `short_greeting`: very short social turns such as `你好` and `在吗`.
- `short_business`: short factual/business turns such as price, availability, finance/process boundaries.
- `boundary`: longer or more complex recommendation/policy/context turns.

Dry baselines answer:

- Is Brain/guard/final-polish path healthy?
- Does short-message optimization preserve business boundary quality?
- Is scheduler timing trace complete?
- Is latency dominated by non-RPA stages even when send is simulated?

Dry baselines cannot answer final Win32/OCR send cost.

### C. Low-Volume Live Baseline

Run one real two-session self-QA live short-greeting baseline first.

Live baseline answers:

- Does the current version still send correctly with operator guard/floating indicator active?
- What is real RPA send cost after P5?
- Does the reply avoid stale visual/OCR noise such as image text.
- Does WeChat remain online with no red-exclamation, security page, blank render, or send failure.

Only run live short-business or long-business if the short-greeting baseline is clean and the user wants deeper real-world speed sampling.

## Artifact Extraction Rules

Use existing artifacts first:

- `result.json`
- `partial_result.json`
- `scheduler_state_round_*.json`
- `audit.jsonl`
- `progress.jsonl`
- sidecar `send_timing`
- Brain `latency_trace`
- final polish payload

The diagnosis should produce a compact table per target:

| scenario | target | prompt | reply | end_to_end | capture | brain_llm | final_polish | send_queue_wait | send_total | target_ready | send_payload | input_confirm_ocr | cache/seed | verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |

If a field is unavailable, mark `missing`, do not infer as zero.

## Bottleneck Ranking Rules

Rank a stage as worth fixing only when all are true:

- It consumes at least 15% of end-to-end time, or at least 5 seconds in short-message live tests.
- It appears in at least two targets or two scenario runs, not one isolated artifact.
- It is not already explained by intentional safety behavior that cannot be removed.
- It can be improved internally without changing public contracts or Brain First ownership.
- It has a clear verification test.

Do not fix:

- one-off upstream LLM fluctuation,
- one-off WeChat render/window anomaly,
- intentional RPA humanized pacing that prevents high-risk mechanical behavior,
- hard safety checks without an equivalent or stronger replacement,
- dry-run-only artifacts that do not exist in live operation.

## Candidate Fix Directions After Diagnosis

### Candidate 1: Capture / Pending / Scheduler Idle Time

Symptoms:

- `pending_to_capture_start` or `capture` is repeatedly high.
- second session waits long before capture while Brain/polish resources are idle.
- scheduler tick intervals or capture serialization dominate short messages.

Potential future fixes:

- event-driven immediate capture for high-confidence short signals,
- reduce duplicate capture on unchanged sessions,
- clearer same-tick handoff from session monitor to capture queue,
- better per-session pending fairness.

Hard boundary: do not parallelize foreground WeChat RPA.

### Candidate 2: Final Polish Cache Miss / Queue Wait

Symptoms:

- short social replies spend multiple seconds in final polish while semantic content is simple.
- cache miss occurs due to test markers, volatile metadata, or irrelevant history.
- polish queue wait appears even when Brain is done.

Potential future fixes:

- stabilize cache keys by excluding nonsemantic volatile markers,
- pre-normalize Brain short-social draft before polish cache lookup,
- keep final polish verification but prefer already-approved cached micro verdicts.

Hard boundary: final polish is still required; do not bypass it for greetings.

### Candidate 3: Brain LLM / Evidence Pack Overhead

Symptoms:

- pure social short turns still carry broad product/history evidence.
- `brain_llm` is high even with no authority facts needed.
- low-authority profile is not consistently selected.

Potential future fixes:

- tighten generic low-authority profile routing,
- reduce auxiliary history/evidence for pure social turns,
- keep current conversation facts only when the customer explicitly continues prior topic.

Hard boundary: business short turns must still get product/formal knowledge.

### Candidate 4: RPA Target Ready / Open Chat

Symptoms:

- `target_ready` stays above 4-5 seconds after P4/P5.
- most of the time is repeated validation or open-chat activation confirmation.

Potential future fixes:

- session-key-aware short TTL safety cache,
- reuse current visible session proof only when hwnd/geometry/session_key match,
- reduce duplicate OCR within the same unchanged screenshot.

Hard boundary: final pre-send strict target guard stays.

### Candidate 5: OCR Engine Fixed Cost

Symptoms:

- ROI OCR still costs about the same as full OCR.
- per-call overhead dominates image size.
- OCR call count is low but each call remains expensive.

Potential future fixes:

- OCR engine warm process or pooling,
- batch OCR for same screenshot regions,
- avoid reinitialization inside hot path.

Hard boundary: OCR fallback and safety semantics remain unchanged.

### Candidate 6: RPA Input Confirmation

Symptoms:

- `typing_input_confirm` remains high even for short replies.
- input operation or after-input OCR dominates send payload.

Potential future fixes:

- tune clipboard chunk pacing within safe humanized limits,
- keep single enter-only send trigger,
- preserve after-input token/visual confirmation,
- improve fast visual confirm thresholds only with real screenshot evidence.

Hard boundary: no blind send, no zero-confirm send, no mouse+keyboard double trigger.

## Decision Output

P6 should end with:

1. Current version pass/fail status.
2. A compact baseline table for dry and live runs.
3. Top bottlenecks ranked by measured impact.
4. For each bottleneck: whether worth fixing now, why, and safest fix direction.
5. Explicit list of things not worth touching.
6. Recommendation for P7 implementation scope, if any.

## Stop Conditions

Stop and diagnose before more testing if:

- WeChat shows login/security/blank-render state.
- A live send is not verified.
- target/session mismatch appears.
- red exclamation or send failure appears.
- operator guard/floating indicator fails to start.
- tests show a behavior regression unrelated to speed.

## Acceptance For This P6 Diagnosis Phase

- Development document exists and is reviewed against P3/P4/P5 plans.
- Static/contract baseline passes.
- Dry baselines produce usable timing artifacts for short greeting, short business, and boundary scenarios.
- At least one low-volume live self-QA short-greeting baseline passes, or a clear environment blocker is documented.
- A prioritized bottleneck report is produced without changing runtime code.

## 2026-06-21 Baseline Results

### Static / Contract Baseline

All current-version checks passed before speed conclusions:

- `py_compile` for Win32/OCR sidecar, compat checks, File Transfer safety checks, and two-visible-session harness.
- `git diff --check` for the P6 document and recent latency files: passed with existing LF/CRLF warnings only.
- Win32/OCR compatibility: 157 checks passed.
- Win32/OCR send/action risk: 4 checks passed.
- Humanized input: 5 checks passed.
- Workflow logic: 118 checks passed.
- Multi-session scheduler: 127 checks passed.
- File Transfer Assistant safety: 10 checks passed.
- Brain contract: passed, including visual OCR / `GOLD SERIES` social-turn contamination guard.
- Two-visible-session harness self-check: passed.

No current-version regression was found in this baseline.

### Dry Baselines

Dry reply-send was used to measure Brain / polish / scheduler without real RPA send cost.

| scenario | targets | result | end-to-end | capture | brain_llm | final_polish | key finding |
| --- | --- | --- | --- | --- | --- | --- | --- |
| short_greeting dry | 2 | pass | 18s / 22s | 0s / 1s | 4.35s / 4.90s | 3.24s / 3.68s | Short social path is healthy; polish still costs about 3-4s on cache miss. |
| short_business dry | 2 | pass | 33s / 37s | 0s / 2s | 5.35s / 7.69s | 3.30s / 3.80s | Business short turns correctly use Brain/evidence; planner worker/repair adds more than pure greeting. |
| boundary dry | 2 logical replies, 4 segments | pass | 129s / 157s for primary replies | 0s / 2s | 8.53s / 10.35s | 3.41s / 4.49s | Boundary slowness is mainly evidence pack and repair paths, not OCR/RPA. |

Important boundary details:

- `evidence_pack_duration_seconds`: about 32.90s and 29.63s.
- `quality_repair_duration_seconds`: about 30.77s on one boundary reply.
- `planner_worker_duration_seconds`: about 116.68s / 145.87s.
- This means long/boundary replies are slowed by evidence assembly plus repair loops, not by final polish alone.

### Live Baselines

Low-volume live tests were run with operator guard / floating indicator enabled. No red-exclamation, send failure, security page, blank render, or target/session mismatch was found.

| scenario | result | replies | end-to-end | capture | brain_llm | final_polish | RPA send | target_ready | send_payload | key finding |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| short_greeting live | pass | 2 | 50s / 74s | 10s / 12s | 4.29s / 6.15s | 0.012s cache hit / 3.48s miss | 14.60s / 18.79s | 4.74s / 7.26s | 7.68s / 9.64s | Short-message live latency is dominated by capture + RPA send + queue/repair/polish miss. |
| short_business live | pass | 4 segments | 87s / 137s for primary replies | 13s / 13s | 4.20s / 5.71s | 3.59s / 3.42s | primary 20.76s / 20.91s; follow-up segments 16.69s / 15.59s | primary 5.33s / 5.64s | primary 13.52s / 12.57s | Business live latency is dominated by capture/pending, repair/review, and multi-segment RPA sends. |

Live prompt-send timing is not commercial runtime cost, but it confirms current RPA send mechanics:

- short greeting prompt sends: 21.72s / 15.69s.
- short business prompt sends: 24.13s / 16.77s.
- all prompt sends used guarded target confirmation, clipboard chunks, enter-only trigger, input seed, and verified send.

### Risk Scan

Artifact scans for the P6 runs found no real failure signals:

- no `Traceback`;
- no `send_failed` / `rpa_send_failed`;
- no red-exclamation or `发送失败`;
- no security page;
- no blank render;
- no target mismatch.

The only string hit was `send_input_not_ready` inside listener configuration names, not a runtime failure.

### Test Execution Note

The first attempt to run three dry baselines in parallel caused `capabilities_lock_timeout` for two runs. This is expected RPA capability-lock contention, not a product reply bug. Baselines must be run serially when they touch WeChat capability probing or the shared RPA lock.

## Bottleneck Ranking After Baseline

### 1. Boundary / Long-Question Evidence Pack And Repair Loops

Priority: highest for long/business quality-speed balance.

Evidence:

- Boundary dry primary replies had end-to-end 129s / 157s even with dry send.
- Evidence pack alone took about 30s each.
- One quality repair took about 30.8s.
- Planner worker took 116.7s / 145.9s.

Worth fixing: yes.

Safe direction:

- Audit why evidence pack for boundary scenarios takes about 30s.
- Split deterministic evidence retrieval cost from LLM/semantic repair cost.
- Cache or precompute tenant product/formal knowledge summaries if they are repeatedly rebuilt.
- Reduce duplicated repair/review loops only when the same reviewer result is already known.
- Preserve Brain First and authority rules; do not skip evidence for long/business cases.

### 2. Live Capture / Pending Queue Before Brain

Priority: high for short-message live speed.

Evidence:

- short greeting live capture: 10s / 12s.
- short business live capture: 13s / 13s.
- second target often has pending-to-capture delay: 11s in short greeting, 17s in short business.
- dry captures are near 0-2s, so this is real WeChat/RPA/capture behavior.

Worth fixing: yes.

Safe direction:

- Add a focused live capture timing chapter before behavior changes.
- Distinguish session-list scan, open-chat read, history backfill, OCR parse, and scheduler wait.
- Improve event-driven capture dispatch for high-confidence short signals without parallel foreground RPA.
- Avoid repeated capture of unchanged sessions.
- Keep session_key and target isolation.

### 3. RPA Send Tail For Live Replies

Priority: high, but only after capture diagnosis because P5 already improved part of it.

Evidence:

- short greeting live RPA send: 14.60s / 18.79s.
- short business live primary segment sends: 20.76s / 20.91s.
- send_payload for business primary segments: 13.52s / 12.57s.
- typing/input confirmation for longer replies: 8-9s.
- target_ready can still reach 7.26s.

Worth fixing: yes, but carefully.

Safe direction:

- For multi-segment replies to the same target, investigate whether target_ready proof can be safely reused between consecutive segments under the same hwnd/geometry/session_key.
- Tune clipboard chunk pacing only within humanized safe ranges.
- Continue studying OCR engine fixed cost for input confirmation.
- Keep after-input confirmation, enter-only trigger, pre-send guard, post-send blank-render guard.

### 4. Final Polish Cache Miss On Short Replies

Priority: medium-high.

Evidence:

- short greeting live first reply final polish cache hit: 0.012s.
- short greeting live second reply cache miss: 3.48s.
- short greeting dry cache misses: 3.24s / 3.68s.
- short business polish is consistently around 3.3-3.8s.

Worth fixing: yes, if done as cache/key normalization, not bypass.

Safe direction:

- Inspect why semantically similar short social drafts miss cache.
- Exclude test markers, volatile timestamps, session artifacts, and nonsemantic metadata from final-polish cache keys where safe.
- Keep final polish required and verification-only; do not skip for greetings.

### 5. Brain LLM Time For Short Turns

Priority: medium.

Evidence:

- short greeting live Brain LLM: 4.29s / 6.15s.
- short greeting dry Brain LLM: 4.35s / 4.90s.
- short business live Brain LLM: 4.20s / 5.71s.
- This is not the only bottleneck, but it is a repeatable 4-6s component.

Worth fixing: only after verifying low-authority profile input size and provider latency.

Safe direction:

- Keep `customer_service_brain` as author.
- Ensure pure social turns get minimal generic context.
- Do not apply the pure-social profile to business short turns.
- Avoid adding keyword-template replies.

### 6. OCR Engine Fixed Cost

Priority: medium.

Evidence:

- ROI input OCR still costs about 1.0-2.5s in live runs.
- P5 seed reuse removed one before-input OCR call, but each remaining OCR call still has nontrivial fixed cost.

Worth fixing: yes, if it can be done below the contract layer.

Safe direction:

- Investigate OCR engine warm process/pooling/batching.
- Keep full fallback and safety semantics.
- Do not replace OCR confirmation with blind send.

## P7 Recommendation

Do not start with more RPA guard removal.

Recommended P7 order:

1. Evidence pack / repair loop profiler for boundary cases.
2. Live capture breakdown profiler for short-message scenarios.
3. Same-target multi-segment send optimization design.
4. Final polish cache-key normalization audit for short social replies.
5. OCR engine fixed-cost investigation.

P7 should still be implemented chapter-by-chapter, with one small internal change followed by static tests, dry baseline, and only then low-volume live verification.
