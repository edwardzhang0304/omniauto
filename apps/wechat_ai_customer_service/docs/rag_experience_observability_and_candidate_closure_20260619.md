# AI Experience Observability And Candidate Closure - 2026-06-19

## Goal

Continue the RAG/AI experience pool optimization with the smallest safe change:

- make AI experience reference hits observable enough for operators to understand what was used;
- keep AI experience material non-authoritative during customer replies;
- verify that useful experience can become a pending review candidate without directly writing formal knowledge.

## Boundaries

- Do not rename existing CLI routes, JSON fields, public function names, or shared constants.
- Do not let AI experience pool hits authorize product facts, prices, stock, policies, availability, or commitments.
- Do not auto-apply AI experience into formal knowledge. Candidate generation may create pending review items only.
- Customer-visible replies remain Brain First: `customer_service_brain` authors visible wording, while RAG/experience layers provide evidence or advisory context only.

## Minimal Implementation

1. Keep current runtime behavior: formal runtime RAG hits remain separated from AI experience references.
2. Add compact trace metadata beside existing AI experience counts:
   - which non-authoritative hits were inspected;
   - which ones were included as reference/style guidance;
   - why dropped hits were dropped;
   - compact IDs and source types, not full private raw material.
3. Surface the same trace through `audit_summary`, so dry-run/live artifacts can answer:
   - "did experience pool participate?"
   - "which IDs participated?"
   - "why was any hit excluded?"
4. Extend focused tests:
   - reference IDs/reasons appear in audit payloads;
   - noise/risky hits are counted and explained;
   - candidate nomination still creates only pending review candidates;
   - candidate auto-apply remains disabled before human action.

## Acceptance Checks

- Static compile for touched files.
- `run_authority_gated_ai_experience_pool_checks.py`.
- `run_rag_candidate_nomination_checks.py`.
- `run_customer_service_real_wechat_fresh_long_flow_checks.py --dry-run --scenario context_bridge --max-turns 2`.
- Optional one-turn File Transfer Assistant live smoke only if the local WeChat session is stable.
