"""Offline checks for the Brain First customer-service contract.

These tests do not call an upstream LLM. They exercise manual-json BrainPlan
parsing, authority validation, guard integration, and shadow-mode payloads.
"""

from __future__ import annotations

import copy
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
WORKFLOWS_ROOT = APP_ROOT / "workflows"
ADAPTERS_ROOT = APP_ROOT / "adapters"
for path in (PROJECT_ROOT, WORKFLOWS_ROOT, APP_ROOT, ADAPTERS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
os.environ.setdefault("WECHAT_CLOUD_REQUIRED", "0")
os.environ.setdefault("WECHAT_CLOUD_STRICT_ONLINE", "0")

import customer_service_brain as brain_module  # noqa: E402
import customer_service_quality_reviewer as reviewer_module  # noqa: E402
import listen_and_reply as workflow_module  # noqa: E402
from apps.wechat_ai_customer_service.knowledge_paths import tenant_context  # noqa: E402
from listen_and_reply import (  # noqa: E402
    TargetConfig,
    process_target,
    select_product_ids_from_reply_event,
    product_ids_from_synthesis_payload,
    should_adopt_customer_service_brain,
)
from reply_evidence_builder import build_reply_evidence_pack, catalog_product_candidates, compact_knowledge_pack  # noqa: E402
from customer_service_brain_contract import (  # noqa: E402
    brain_plan_to_guard_candidate,
    extract_quality_budget_upper,
    is_incomplete_reply_segment,
    join_reply_segments,
    normalize_brain_plan,
    normalize_reply_segments,
    validate_brain_plan,
    verify_brain_reply_quality,
)
from llm_reply_guard import (  # noqa: E402
    guard_synthesized_reply,
    request_has_ai_identity_probe,
    validate_reply_fact_authority,
)
from customer_service_loop import ReplyDecision  # noqa: E402


@dataclass
class CaseResult:
    name: str
    ok: bool
    details: dict[str, Any]


def main() -> int:
    results = [
        check_normalize_and_candidate(),
        check_rejects_style_only_price_fact(),
        check_requires_fact_claims_for_factual_modes(),
        check_accepts_common_sense_compare_without_fact_claims(),
        check_drops_non_authoritative_advice_boundary_fact_claims(),
        check_reply_normalization_avoids_forbidden_commitment_echo(),
        check_normalizes_brain_schema_aliases_without_authorizing_style_facts(),
        check_current_conversation_can_authorize_product_reference_not_price(),
        check_common_sense_brain_plan_uses_guard_advisor_mode(),
        check_source_id_list_validation_accepts_multiple_product_ids(),
        check_formal_policy_source_id_prefixes_validate_against_evidence(),
        check_semantic_reviewer_authority_summary_reads_evidence_formal_ids(),
        check_social_brain_plan_clears_soft_no_evidence_guard(),
        check_brain_first_failure_uses_safe_fallback_without_legacy(),
        check_rejects_product_scoped_master_fact(),
        check_rejects_formal_policy_fact_without_source_id(),
        check_quality_gate_rejects_generic_stall_for_price(),
        check_quality_gate_rejects_social_info_collection(),
        check_quality_gate_requires_clear_recommendation(),
        check_quality_gate_rejects_contextual_recommendation_stall(),
        check_quality_gate_rejects_relative_context_product_drift(),
        check_quality_gate_accepts_visible_history_recent_product_context(),
        check_quality_gate_ignores_generic_alias_for_relative_context_binding(),
        check_quality_gate_rejects_over_budget_primary_recommendation(),
        check_quality_gate_rejects_over_budget_slot_for_budgeted_multi_recommendation(),
        check_quality_gate_allows_explicit_over_budget_backup_when_only_one_budget_fit(),
        check_quality_gate_rejects_single_candidate_for_multi_recommendation_request(),
        check_quality_gate_rejects_known_budget_fit_price_uncertainty(),
        check_quality_gate_accepts_clear_resale_choice_wording(),
        check_quality_gate_accepts_preference_wording_as_clear_choice(),
        check_quality_gate_allows_transparent_multi_recommendation_limitation(),
        check_quality_gate_rejects_ambiguous_followup_product_drift(),
        check_quality_gate_allows_anchored_backup_on_ambiguous_followup(),
        check_quality_gate_allows_ambiguous_followup_primary_product(),
        check_quality_gate_rejects_missing_cargo_space_topic(),
        check_quality_gate_allows_conservative_cargo_dimension_reply(),
        check_quality_gate_rejects_ignoring_available_cargo_fit_candidate(),
        check_quality_gate_rejects_incomplete_reply_segment(),
        check_quality_gate_accepts_complete_colloquial_condition_segment(),
        check_quality_gate_rejects_dangling_condition_clause(),
        check_quality_gate_rejects_dangling_decision_fragment(),
        check_quality_gate_rejects_missing_insurance_subtopic(),
        check_quality_gate_rejects_appointment_overcommit_without_confirmation(),
        check_quality_gate_rejects_trade_in_process_overcommit(),
        check_quality_gate_rejects_trade_in_final_price_without_boundary(),
        check_quality_gate_allows_bounded_trade_in_process_reply(),
        check_quality_gate_allows_sendable_split_reply_over_soft_total_limit(),
        check_quality_gate_rejects_overlong_visible_reply(),
        check_quality_gate_allows_mixed_topic_split_reply_budget(),
        check_semantic_reviewer_suspicious_detector(),
        check_semantic_reviewer_unavailable_soft_passes_normal_low_risk(),
        check_semantic_reviewer_relaxes_safe_common_sense_boundary_concern(),
        check_semantic_reviewer_relaxes_bounded_resale_advisory_concern(),
        check_semantic_reviewer_shadow_does_not_block_brain_reply(),
        check_semantic_reviewer_handoff_suggest_preserves_brain_handoff_reply(),
        check_semantic_reviewer_repair_blocks_when_repair_disabled(),
        check_semantic_reviewer_cannot_override_hard_authority_validation(),
        check_brain_prompt_separates_style_from_content_basis(),
        check_brain_prompt_includes_runtime_principles_without_authorizing_facts(),
        check_brain_prompt_marks_legacy_candidate_non_authoritative(),
        check_example_configs_keep_final_visible_micro_verify_required(),
        check_brain_safe_fallback_uses_product_candidates_when_quality_repair_unavailable(),
        check_brain_input_keeps_referenced_context_auxiliary(),
        check_brain_prompt_compacts_large_context_under_timeout_budget(),
        check_brain_timeout_budget_scales_with_prompt_pressure(),
        check_repair_prompt_preserves_authority_boundaries(),
        check_shadow_non_blocking_defers_without_llm(),
        check_shadow_brain_runner_passes_guard(),
        check_brain_runner_records_stage_timings(),
        check_brain_runner_rejects_quality_failed_plan(),
        check_repaired_deterministic_quality_soft_pass_requires_missing_context_anchor(),
        check_brain_runner_soft_passes_repaired_semantic_minor_nits(),
        check_brain_runner_coerces_usable_fallback_existing_plan(),
        check_brain_candidate_allows_safe_uncertain_send(),
        check_guard_downgrades_safe_uncertain_handoff_plan(),
        check_safe_uncertain_reply_budget_restatement_needs_no_product_fact(),
        check_uncertainty_boundary_condition_claim_is_not_product_fact(),
        check_brain_canonicalizes_context_product_price_to_product_master(),
        check_brain_rehydrates_context_product_fact_to_product_master(),
        check_brain_canonicalizes_year_model_price_text_to_product_master(),
        check_guard_rejects_unsupported_price_without_product_master(),
        check_guard_allows_customer_budget_restatement_without_product_master(),
        check_guard_allows_detail_topic_clarification_without_fact_claim(),
        check_guard_allows_general_resale_advisory_without_product_master(),
        check_guard_clears_soft_missing_authority_with_product_master(),
        check_guard_clears_soft_no_evidence_with_product_authority(),
        check_guard_clears_soft_finance_process_with_formal_knowledge(),
        check_guard_allows_soft_offtopic_customer_care_reply(),
        check_guard_illegal_request_uses_specific_refusal(),
        check_guard_v2_approves_authoritative_brain_handoff(),
        check_guard_v2_soft_handoff_is_repair_not_visible_reply(),
        check_guard_v2_product_conflict_requests_brain_repair(),
        check_guard_v2_identity_question_uses_brain_reply(),
        check_brain_runner_ignores_guard_visible_reply_source(),
        check_brain_product_ids_update_conversation_context_source(),
        check_reply_event_context_update_preserves_recent_ids_without_primary_context(),
        check_rejected_brain_payload_does_not_update_conversation_context_source(),
        check_reply_event_context_update_prefers_visible_reply_products(),
        check_visible_reply_product_mentions_update_recent_context(),
        check_visible_reply_preference_marker_updates_primary_context(),
        check_identity_probe_detector_ignores_test_tokens(),
        check_context_need_catalog_candidates_prefer_recent_mpv_need(),
        check_followup_preference_context_preserves_previous_budget(),
        check_context_budget_followup_catalog_candidates(),
        check_around_budget_catalog_candidates_prefer_near_budget(),
        check_context_feature_followup_catalog_candidates_prefer_recent_product(),
        check_cargo_budget_candidates_prioritize_nonsedan_fit(),
        check_finance_process_question_relaxes_soft_handoff_with_formal_boundary(),
        check_specific_finance_commitment_question_keeps_handoff(),
        check_appointment_schedule_question_relaxes_to_bounded_auto_reply(),
        check_finance_promise_and_lowest_price_combo_keeps_handoff(),
        check_intent_evidence_finance_process_safety_softened(),
        check_intent_evidence_specific_finance_commitment_stays_handoff(),
        check_recent_multi_product_context_candidates(),
        check_compact_knowledge_prioritizes_recent_context_products(),
        check_brain_adoption_gate(),
        check_process_target_brain_first_adopts(),
        check_process_target_brain_first_exception_uses_safe_fallback(),
        check_process_target_brain_first_nonadoptable_blocks_legacy_takeover(),
        check_process_target_brain_first_skips_legacy_expression_adapter(),
        check_process_target_shadow_does_not_adopt(),
    ]
    failures = [item for item in results if not item.ok]
    payload = {
        "ok": not failures,
        "results": [{"name": item.name, "ok": item.ok, **item.details} for item in results],
        "failures": [{"name": item.name, **item.details} for item in failures],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


def base_config(plan: dict[str, Any], *, include_product: bool = True, blocking_shadow_enabled: bool = True) -> dict[str, Any]:
    return {
        "customer_service_brain": {
            "enabled": True,
            "mode": "shadow",
            "provider": "manual_json",
            "brain_plan": plan,
            "min_confidence": 0.2,
            "require_evidence": True,
            "include_brain_input_in_audit": True,
            "blocking_shadow_enabled": blocking_shadow_enabled,
        },
        "llm_reply_synthesis": {
            "enabled": True,
            "provider": "manual_json",
            "min_confidence": 0.2,
            "require_evidence": True,
        },
        "final_visible_llm_polish": {"enabled": False},
        "_test_brain_product_enabled": include_product,
    }


def base_plan() -> dict[str, Any]:
    return {
        "can_answer": True,
        "understanding": {
            "user_intent": "询问具体车型报价",
            "normalized_entities": [{"raw": "秦plus", "normalized": "比亚迪秦PLUS", "entity_type": "product"}],
        },
        "answer_mode": "quote_product_fact",
        "reply_strategy": {"style": "concise_human"},
        "evidence_used": {"product_ids": ["chejin_qinplus_2022_dmi55"]},
        "facts_claimed": [
            {
                "fact_type": "price",
                "value": "8.68万",
                "source_level": "product_master",
                "source_id": "chejin_qinplus_2022_dmi55",
            }
        ],
        "reply_segments": ["秦PLUS这台目前报价8.68万。", "您要是主要通勤省油，这个方向挺合适。"],
        "risk": {"risk_level": "low", "risk_tags": [], "needs_handoff": False},
        "recommended_action": "send_reply",
        "confidence": 0.86,
        "reason": "商品库命中具体车型和价格。",
    }


def check_normalize_and_candidate() -> CaseResult:
    plan = normalize_brain_plan(base_plan())
    candidate = brain_plan_to_guard_candidate(plan)
    assert_true(plan["answer_mode"] == "quote_product_fact", "answer_mode should be preserved")
    assert_true(len(plan["reply_segments"]) == 2, "reply should keep two short segments")
    assert_true("product:chejin_qinplus_2022_dmi55" in candidate["used_evidence"], "product evidence id should be declared")
    assert_true("8.68万" in join_reply_segments(plan["reply_segments"]), "joined reply should include price")
    return CaseResult("normalize_and_candidate", True, {"candidate": candidate})


def check_rejects_style_only_price_fact() -> CaseResult:
    plan = copy.deepcopy(base_plan())
    plan["facts_claimed"][0]["source_level"] = "ai_experience_pool"
    normalized = normalize_brain_plan(plan)
    validation = validate_brain_plan(normalized)
    assert_true(not validation["ok"], "style-only source cannot authorize price")
    assert_true(any("style_only_source_used_as_fact" in item for item in validation["errors"]), "expected style-only error")
    return CaseResult("rejects_style_only_price_fact", True, {"errors": validation["errors"]})


def check_requires_fact_claims_for_factual_modes() -> CaseResult:
    plan = copy.deepcopy(base_plan())
    plan["facts_claimed"] = []
    normalized = normalize_brain_plan(plan)
    validation = validate_brain_plan(normalized, require_fact_claims=True)
    assert_true(not validation["ok"], "factual BrainPlan should declare facts_claimed")
    assert_true("missing_fact_claims" in validation["errors"], "expected missing_fact_claims")
    return CaseResult("requires_fact_claims_for_factual_modes", True, {"errors": validation["errors"]})


def check_accepts_common_sense_compare_without_fact_claims() -> CaseResult:
    plan = copy.deepcopy(base_plan())
    plan.update(
        {
            "answer_mode": "compare_options",
            "evidence_used": {"common_sense_topics": ["老人易晕车时优先筛舒适性、底盘稳定性和空间便利性"]},
            "facts_claimed": [],
            "reply_segments": [
                "老人容易晕车的话，我建议先看坐姿舒服、底盘稳、后排不压抑的车。",
                "具体车源可以再按10万内、15万内两个预算段往里筛。",
            ],
        }
    )
    normalized = normalize_brain_plan(plan)
    validation = validate_brain_plan(normalized, require_fact_claims=True)
    assert_true(validation["ok"], f"generic common-sense comparison should not require product fact claims: {validation}")
    return CaseResult("accepts_common_sense_compare_without_fact_claims", True, {"validation": validation})


def check_drops_non_authoritative_advice_boundary_fact_claims() -> CaseResult:
    normalized = normalize_brain_plan(
        {
            "can_answer": True,
            "answer_mode": "direct_answer",
            "evidence_used": {"common_sense_topics": ["insurance_self_collision"]},
            "facts_claimed": [
                {
                    "fact_type": "boundary",
                    "value": "一般要看车损险和保单责任，不保证赔付。",
                    "source_level": "llm_common_sense",
                },
                {
                    "fact_type": "suggestion",
                    "value": "建议先报案并保留现场照片。",
                    "source_level": "llm_common_sense",
                },
            ],
            "reply_segments": [
                "一般看您有没有车损险，有的话这种自己撞墙通常可以先报保险处理。",
                "但具体还要按保单责任和保险公司审核来定，建议先报案并拍现场。",
            ],
            "recommended_action": "send_reply",
            "confidence": 0.83,
        }
    )
    validation = validate_brain_plan(normalized, require_fact_claims=True)
    assert_true(normalized.get("facts_claimed") == [], "common-sense advice/boundary claims must not become authority facts")
    assert_true(validation["ok"], f"common-sense advice plan should validate without style-only facts: {validation}")
    return CaseResult("drops_non_authoritative_advice_boundary_fact_claims", True, {"validation": validation})


def check_reply_normalization_avoids_forbidden_commitment_echo() -> CaseResult:
    segments = normalize_reply_segments(
        ["这种情况一般看车损险，不能直接说一定赔或一定不赔，具体以保单和保险公司审核为准。"],
        max_segments=2,
    )
    reply = join_reply_segments(segments)
    assert_true("一定赔" not in reply and "保证赔" not in reply, f"forbidden commitment echo should be cleaned: {reply}")
    assert_true("不能直接下结论" in reply, f"boundary meaning should remain after cleaning: {reply}")
    return CaseResult("reply_normalization_avoids_forbidden_commitment_echo", True, {"reply": reply})


def check_normalizes_brain_schema_aliases_without_authorizing_style_facts() -> CaseResult:
    plan = copy.deepcopy(base_plan())
    plan["evidence_used"] = {
        "product_master": ["chejin_qinplus_2022_dmi55"],
        "common_sense": ["通勤省油可以优先看混动或小排量车型"],
    }
    plan["facts_claimed"] = [
        {
            "type": "price",
            "claim": "8.68万",
            "source": "product_master",
            "product_id": "chejin_qinplus_2022_dmi55",
        },
        {
            "type": "analysis",
            "claim": "通勤省油方向可以看混动",
            "source": "common_sense",
        },
    ]
    normalized = normalize_brain_plan(plan)
    validation = validate_brain_plan(normalized, require_fact_claims=True)
    assert_true(normalized["evidence_used"]["product_ids"] == ["chejin_qinplus_2022_dmi55"], "product_master alias should normalize")
    assert_true(normalized["evidence_used"]["common_sense_topics"], "common_sense alias should normalize")
    assert_true(len(normalized["facts_claimed"]) == 1, "non-authoritative common-sense analysis should not become a fact claim")
    assert_true(validation["ok"], f"normalized authoritative price fact should pass: {validation}")
    return CaseResult(
        "normalizes_brain_schema_aliases_without_authorizing_style_facts",
        True,
        {"facts": normalized["facts_claimed"], "evidence": normalized["evidence_used"]},
    )


def check_current_conversation_can_authorize_product_reference_not_price() -> CaseResult:
    product_reference = copy.deepcopy(base_plan())
    product_reference.update(
        {
            "answer_mode": "direct_answer",
            "evidence_used": {"conversation_fact_ids": ["last_product_id"]},
            "facts_claimed": [
                {
                    "fact_type": "product_name",
                    "value": "客户继续问刚才提到的秦PLUS",
                    "source_level": "current_conversation_fact",
                    "source_id": "last_product_id",
                }
            ],
            "reply_segments": ["您问的还是刚才那台秦PLUS，我接着这个方向说。"],
        }
    )
    reference_validation = validate_brain_plan(normalize_brain_plan(product_reference), require_fact_claims=True)
    assert_true(reference_validation["ok"], f"conversation product reference should validate: {reference_validation}")

    price_claim = copy.deepcopy(product_reference)
    price_claim["facts_claimed"] = [
        {
            "fact_type": "price",
            "value": "8.68万",
            "source_level": "current_conversation_fact",
            "source_id": "last_product_price",
        }
    ]
    price_validation = validate_brain_plan(normalize_brain_plan(price_claim), require_fact_claims=True)
    assert_true(
        "product_master_fact_without_product_master_authority:price" in price_validation["errors"],
        f"conversation price must still require product master authority: {price_validation}",
    )
    alias_price_claim = copy.deepcopy(product_reference)
    alias_price_claim["facts_claimed"] = [
        {
            "fact_type": "product_price",
            "value": "8.68万",
            "source_level": "current_conversation_fact",
            "source_id": "last_product_price",
        }
    ]
    alias_price_validation = validate_brain_plan(normalize_brain_plan(alias_price_claim), require_fact_claims=True)
    assert_true(
        "product_master_fact_without_product_master_authority:price" in alias_price_validation["errors"],
        f"product_price alias must normalize to price authority checks: {alias_price_validation}",
    )
    return CaseResult(
        "current_conversation_can_authorize_product_reference_not_price",
        True,
        {"reference": reference_validation, "price": price_validation},
    )


def check_common_sense_brain_plan_uses_guard_advisor_mode() -> CaseResult:
    plan = copy.deepcopy(base_plan())
    plan.update(
        {
            "answer_mode": "direct_answer",
            "evidence_used": {"common_sense_topics": ["new_driver_car_choice"]},
            "facts_claimed": [],
            "reply_segments": ["刚拿驾照的话，我建议先避开太大的SUV和冷门豪华品牌。"],
        }
    )
    normalized = normalize_brain_plan(plan)
    assert_true(
        brain_module.brain_plan_is_common_sense_advisory(normalized),
        "common-sense-only BrainPlan should be allowed to clear soft no-evidence guard blocks",
    )
    factual = normalize_brain_plan(base_plan())
    assert_true(
        not brain_module.brain_plan_is_common_sense_advisory(factual),
        "product fact BrainPlan must not use common-sense advisor mode",
    )
    return CaseResult("common_sense_brain_plan_uses_guard_advisor_mode", True, {"common_sense": True})


def check_source_id_list_validation_accepts_multiple_product_ids() -> CaseResult:
    plan = copy.deepcopy(base_plan())
    plan["facts_claimed"][0]["source_id"] = "chejin_qinplus_2022_dmi55, chejin_camry_2021_20g"
    pack = fake_evidence_pack(include_product=True)
    pack["knowledge"]["product_master"]["items"].append(
        {
            "id": "chejin_camry_2021_20g",
            "name": "2021款丰田凯美瑞2.0G",
            "price": 13.98,
            "authority_level": "product_master",
        }
    )
    validation = brain_module.validate_plan_against_evidence(normalize_brain_plan(plan), pack)
    assert_true(validation["ok"], f"comma-separated product source ids should validate: {validation}")
    return CaseResult("source_id_list_validation_accepts_multiple_product_ids", True, {"validation": validation})


def check_formal_policy_source_id_prefixes_validate_against_evidence() -> CaseResult:
    pack = fake_evidence_pack(include_product=True)
    pack["knowledge"]["evidence"]["faq"] = [{"intent": "chejin_loan_policy", "question": "贷款政策"}]
    pack["knowledge"]["evidence"]["policies"] = {
        "payment_policy": {"id": "payment_policy", "text": "贷款审批以资方审核为准，不能承诺包过。"}
    }
    pack["knowledge"]["formal_knowledge"]["faq"] = [{"intent": "chejin_loan_policy", "question": "贷款政策"}]
    pack["knowledge"]["formal_knowledge"]["policies"] = {
        "payment_policy": {"id": "payment_policy", "text": "贷款审批以资方审核为准，不能承诺包过。"}
    }
    pack["evidence_ids"] = ["faq:chejin_loan_policy", "policy:payment_policy"]
    pack["audit_summary"]["evidence_ids"] = [
        "product:chejin_qinplus_2022_dmi55",
        "faq:chejin_loan_policy",
        "policy:payment_policy",
    ]
    plan = copy.deepcopy(base_plan())
    plan.update(
        {
            "answer_mode": "handoff",
            "evidence_used": {
                "product_ids": ["product:chejin_qinplus_2022_dmi55"],
                "formal_knowledge_ids": ["faq:chejin_loan_policy", "policies.payment_policy"],
            },
            "facts_claimed": [
                {
                    "fact_type": "product_match",
                    "value": "客户提到秦PLUS",
                    "source_level": "product_master",
                    "source_id": "product:chejin_qinplus_2022_dmi55",
                },
                {
                    "fact_type": "loan",
                    "value": "贷款审批以资方审核为准，不能承诺包过",
                    "source_level": "formal_knowledge",
                    "source_id": "policy:payment_policy",
                },
                {
                    "fact_type": "handoff_rule",
                    "value": "贷款包过承诺需转人工评估",
                    "source_level": "formal_knowledge",
                    "source_id": "chejin_loan_policy",
                },
            ],
            "reply_segments": [
                "这个我不能先给您包过承诺，贷款审批要以资方最终审核为准。",
                "秦PLUS这台可以先按车型和征信做一对一评估。",
            ],
            "recommended_action": "handoff",
            "risk": {"risk_level": "high", "risk_tags": ["finance_commitment"], "needs_handoff": True},
        }
    )
    validation = brain_module.validate_plan_against_evidence(normalize_brain_plan(plan), pack)
    assert_true(validation["ok"], f"formal source ids with common prefixes should validate: {validation}")
    return CaseResult("formal_policy_source_id_prefixes_validate_against_evidence", True, {"validation": validation})


def check_semantic_reviewer_authority_summary_reads_evidence_formal_ids() -> CaseResult:
    pack = fake_evidence_pack(include_product=False)
    pack["knowledge"]["evidence"]["faq"] = [
        {"intent": "chejin_acquisition_policy", "question": "置换流程怎么走"}
    ]
    pack["knowledge"]["evidence"]["policies"] = {
        "payment_policy": {"text": "付款与手续以门店确认为准。"}
    }
    pack["evidence_ids"] = ["faq:chejin_acquisition_policy", "policy:payment_policy"]
    pack["audit_summary"]["evidence_ids"] = ["faq:chejin_acquisition_policy"]
    summary = reviewer_module.compact_authority_evidence_for_review(pack)
    formal_ids = summary.get("formal_knowledge_ids") or []
    joined = "\n".join(str(item) for item in formal_ids)
    assert_true(
        "chejin_acquisition_policy" in joined,
        f"semantic reviewer authority summary should include FAQ intent evidence: {summary}",
    )
    assert_true(
        "payment_policy" in joined,
        f"semantic reviewer authority summary should include policy evidence: {summary}",
    )
    return CaseResult(
        "semantic_reviewer_authority_summary_reads_evidence_formal_ids",
        True,
        {"formal_knowledge_ids": formal_ids},
    )


def check_social_brain_plan_clears_soft_no_evidence_guard() -> CaseResult:
    plan = copy.deepcopy(base_plan())
    plan.update(
        {
            "answer_mode": "soft_social_reply",
            "evidence_used": {"conversation_ids": ["c1"]},
            "facts_claimed": [],
            "reply_segments": ["在呢，您说。"],
            "recommended_action": "send_reply",
            "risk": {"risk_level": "low", "risk_tags": [], "needs_handoff": False},
        }
    )
    pack = fake_evidence_pack(include_product=False)
    pack["current_message"] = "在吗"
    pack["current_batch"] = [{"id": "msg-social", "sender": "许聪", "content": "在吗"}]
    pack["conversation"]["current_batch_text"] = "[许聪] 在吗"
    pack["safety"] = {"must_handoff": True, "reasons": ["no_relevant_business_evidence"], "allowed_auto_reply": False}
    pack["knowledge"]["safety"] = dict(pack["safety"])
    pack["intent_tags"] = ["social"]
    pack["knowledge"]["intent_tags"] = ["social"]
    config = base_config(plan, include_product=False)
    config["customer_service_brain"]["mode"] = "brain_first"
    config["customer_service_brain"]["fallback_to_legacy_on_error"] = False
    with patched_evidence_pack(pack):
        event = brain_module.maybe_run_customer_service_brain(
            config=config,
            target_name="许聪",
            target_state={"conversation_context": {}},
            batch=[{"id": "msg-social", "sender": "许聪", "content": "在吗"}],
            combined="在吗",
            decision=ReplyDecision("", "", False, False, ""),
            reply_text="",
            intent_assist={},
            rag_reply={},
            llm_reply={},
            product_knowledge={},
            data_capture={},
            raw_capture={"conversation": {"conversation_id": "c1", "chat_type": "private"}},
            customer_profile=None,
        )
    assert_true(event.get("applied") is True and event.get("adoptable") is True, f"social Brain reply should apply: {event}")
    assert_true(event.get("rule_name") == "customer_service_brain_reply", f"social turn should not handoff: {event}")
    assert_true("在" in event.get("reply_text", ""), f"social reply should remain natural: {event}")
    return CaseResult("social_brain_plan_clears_soft_no_evidence_guard", True, {"reason": event.get("reason")})


def check_brain_first_failure_uses_safe_fallback_without_legacy() -> CaseResult:
    config = base_config(base_plan())
    config["customer_service_brain"]["mode"] = "brain_first"
    config["customer_service_brain"]["provider"] = "openai"
    config["customer_service_brain"]["fallback_to_legacy_on_error"] = False
    original = brain_module.run_brain_llm

    def fail_llm(**_: Any) -> dict[str, Any]:
        return {"ok": False, "provider": "openai", "model": "unit", "error": "TimeoutError('unit')"}

    try:
        brain_module.run_brain_llm = fail_llm
        with patched_evidence_pack(fake_evidence_pack(include_product=False)):
            event = brain_module.maybe_run_customer_service_brain(
                config=config,
                target_name="许聪",
                target_state={"conversation_context": {}},
                batch=[{"id": "msg-ack", "sender": "许聪", "content": "好，尽快回我"}],
                combined="好，尽快回我",
                decision=ReplyDecision("", "", False, False, ""),
                reply_text="旧链路回复",
                intent_assist={},
                rag_reply={},
                llm_reply={},
                product_knowledge={},
                data_capture={},
                raw_capture={"conversation": {"conversation_id": "c1", "chat_type": "private"}},
                customer_profile=None,
            )
    finally:
        brain_module.run_brain_llm = original
    assert_true(event.get("applied") is True and event.get("adoptable") is True, f"strict Brain fallback should be adoptable: {event}")
    assert_true(event.get("rule_name") == "customer_service_brain_safe_fallback", f"expected safe fallback: {event}")
    assert_true(event.get("reply_text") == "好的，我这边尽快给您回。", f"safe fallback should be contextual: {event}")
    return CaseResult("brain_first_failure_uses_safe_fallback_without_legacy", True, {"reason": event.get("reason")})


def check_brain_safe_fallback_uses_product_candidates_when_quality_repair_unavailable() -> CaseResult:
    plan = copy.deepcopy(base_plan())
    plan["answer_mode"] = "recommend_from_catalog"
    plan["evidence_used"] = {"product_ids": ["chejin_mazda3_2020_20l", "chejin_camry_2021_20g"]}
    plan["facts_claimed"] = [
        {
            "fact_type": "price",
            "value": "9.58万",
            "source_level": "product_master",
            "source_id": "chejin_mazda3_2020_20l",
        },
        {
            "fact_type": "price",
            "value": "8.98万",
            "source_level": "product_master",
            "source_id": "chejin_camry_2021_20g",
        },
    ]
    plan["reply_segments"] = ["我这边先确认一下，马上回复您。"]
    plan["recommended_action"] = "send_reply"
    config = base_config(plan)
    config["customer_service_brain"]["mode"] = "brain_first"
    config["customer_service_brain"]["fallback_to_legacy_on_error"] = False
    config["customer_service_brain"]["quality_repair_enabled"] = False
    question = "那就按刚才说的，直接挑两台，别再问预算了。"
    with patched_evidence_pack(fake_two_candidate_recommendation_pack(question)):
        event = brain_module.maybe_run_customer_service_brain(
            config=config,
            target_name="许聪",
            target_state={
                "conversation_context": {
                    "last_customer_need_text": "预算十万左右，接娃通勤，别太费油，南京能看最好。",
                    "last_customer_need_terms": ["预算十万左右", "通勤", "费油", "南京能看"],
                }
            },
            batch=[{"id": "msg-recommend", "sender": "许聪", "content": question}],
            combined=question,
            decision=ReplyDecision("", "", False, False, ""),
            reply_text="",
            intent_assist={},
            rag_reply={},
            llm_reply={},
            product_knowledge={},
            data_capture={},
            raw_capture={"conversation": {"conversation_id": "c1", "chat_type": "private"}},
            customer_profile=None,
        )
    reply = str(event.get("reply_text") or "")
    assert_true(event.get("rule_name") == "customer_service_brain_safe_fallback", f"expected safe fallback: {event}")
    assert_true("马自达3" in reply and "凯美瑞" in reply, f"fallback should keep product candidate anchors: {event}")
    assert_true("9.58" in reply and "8.98" in reply, f"fallback should keep product-master prices: {event}")
    assert_true("马上回复" not in reply, f"fallback should not degrade to low-information stall when evidence exists: {event}")
    detailed_need = "我开摄影工作室，想买台能拉灯架和相机箱的车，偶尔也接客户，预算16万以内。"
    detailed_reply = brain_module.brain_safe_fallback_reply(
        detailed_need,
        evidence_pack=fake_two_candidate_recommendation_pack(detailed_need),
    )
    assert_true(
        "马自达3" in detailed_reply and "凯美瑞" in detailed_reply,
        f"detailed need fallback should also keep candidate anchors: {detailed_reply}",
    )
    return CaseResult("brain_safe_fallback_uses_product_candidates_when_quality_repair_unavailable", True, {"reply": reply})


def check_rejects_product_scoped_master_fact() -> CaseResult:
    plan = copy.deepcopy(base_plan())
    plan["facts_claimed"][0]["source_level"] = "product_scoped_formal"
    normalized = normalize_brain_plan(plan)
    validation = validate_brain_plan(normalized, require_fact_claims=True)
    assert_true(not validation["ok"], "product master facts must not be authorized by product-scoped formal knowledge")
    assert_true(
        any("product_master_fact_without_product_master_authority:price" == item for item in validation["errors"]),
        f"expected product-master-only error: {validation}",
    )
    return CaseResult("rejects_product_scoped_master_fact", True, {"errors": validation["errors"]})


def check_rejects_formal_policy_fact_without_source_id() -> CaseResult:
    plan = copy.deepcopy(base_plan())
    plan.update(
        {
            "answer_mode": "direct_answer",
            "evidence_used": {"formal_knowledge_ids": ["loan_policy_1"]},
            "facts_claimed": [
                {
                    "fact_type": "loan",
                    "value": "分期以资方审批为准",
                    "source_level": "formal_knowledge",
                    "source_id": "",
                }
            ],
            "reply_segments": ["分期可以先算方向，具体以资方审批为准。"],
        }
    )
    normalized = normalize_brain_plan(plan)
    validation = validate_brain_plan(normalized, require_fact_claims=True)
    assert_true(not validation["ok"], "formal policy facts should name a formal source id")
    assert_true("policy_fact_missing_source_id:loan" in validation["errors"], f"expected source id error: {validation}")
    return CaseResult("rejects_formal_policy_fact_without_source_id", True, {"errors": validation["errors"]})


def check_quality_gate_rejects_generic_stall_for_price() -> CaseResult:
    plan = copy.deepcopy(base_plan())
    plan["reply_segments"] = ["我先帮您看看，稍等。"]
    normalized = normalize_brain_plan(plan)
    quality = verify_brain_reply_quality(
        normalized,
        current_message="秦plus多少钱",
        evidence_pack=fake_evidence_pack(include_product=True),
        settings={},
    )
    assert_true(not quality["ok"], f"price question should not accept generic stall: {quality}")
    assert_true("missing_direct_price_response" in quality["errors"], f"expected direct price error: {quality}")
    assert_true("generic_stall_reply_for_concrete_question" in quality["errors"], f"expected stall error: {quality}")
    return CaseResult("quality_gate_rejects_generic_stall_for_price", True, {"errors": quality["errors"]})


def check_quality_gate_rejects_social_info_collection() -> CaseResult:
    plan = copy.deepcopy(base_plan())
    plan.update(
        {
            "answer_mode": "soft_social_reply",
            "evidence_used": {"product_ids": []},
            "facts_claimed": [],
            "reply_segments": ["我看过资料了，还差个电话，您发我一下。"],
        }
    )
    normalized = normalize_brain_plan(plan)
    quality = verify_brain_reply_quality(
        normalized,
        current_message="在吗",
        evidence_pack=fake_evidence_pack(include_product=True),
        settings={},
    )
    assert_true(not quality["ok"], f"social greeting should not collect unsupported info: {quality}")
    assert_true("unsupported_info_collection_for_social_message" in quality["errors"], f"expected info-collection error: {quality}")
    return CaseResult("quality_gate_rejects_social_info_collection", True, {"errors": quality["errors"]})


def check_quality_gate_requires_clear_recommendation() -> CaseResult:
    plan = copy.deepcopy(base_plan())
    plan.update(
        {
            "answer_mode": "recommend_from_catalog",
            "reply_segments": ["这两台车都还可以，您预算大概多少？"],
            "facts_claimed": [
                {
                    "fact_type": "product",
                    "value": "比亚迪秦PLUS、凯美瑞",
                    "source_level": "product_master",
                    "source_id": "chejin_qinplus_2022_dmi55",
                }
            ],
        }
    )
    normalized = normalize_brain_plan(plan)
    quality = verify_brain_reply_quality(
        normalized,
        current_message="秦PLUS和凯美瑞通勤哪个更适合，帮我挑一台",
        evidence_pack=fake_evidence_pack(include_product=True),
        settings={},
    )
    assert_true(not quality["ok"], f"choice question should require a clear recommendation: {quality}")
    assert_true("missing_clear_recommendation_or_choice" in quality["errors"], f"expected recommendation error: {quality}")
    return CaseResult("quality_gate_requires_clear_recommendation", True, {"errors": quality["errors"]})


def check_quality_gate_rejects_contextual_recommendation_stall() -> CaseResult:
    plan = copy.deepcopy(base_plan())
    plan.update(
        {
            "answer_mode": "recommend_from_catalog",
            "reply_segments": ["好的，我先确认一下，马上回复您。"],
            "facts_claimed": [],
        }
    )
    normalized = normalize_brain_plan(plan)
    quality = verify_brain_reply_quality(
        normalized,
        current_message="那就按刚才说的，直接挑两台，别再问预算了。",
        evidence_pack=fake_evidence_pack(include_product=True),
        settings={},
    )
    assert_true(not quality["ok"], f"context follow-up should not allow generic stall reply: {quality}")
    assert_true(
        "generic_stall_reply_for_contextual_recommendation" in quality["errors"],
        f"expected contextual stall error: {quality}",
    )
    assert_true(
        "missing_context_product_recommendation" in quality["errors"],
        f"expected missing context product recommendation error: {quality}",
    )
    return CaseResult("quality_gate_rejects_contextual_recommendation_stall", True, {"errors": quality["errors"]})


def check_quality_gate_rejects_relative_context_product_drift() -> CaseResult:
    plan = copy.deepcopy(base_plan())
    plan.update(
        {
            "answer_mode": "compare_options",
            "evidence_used": {"common_sense_topics": ["新手停车优先小车"]},
            "facts_claimed": [],
            "reply_segments": [
                "这两台里我更偏向Polo。",
                "Polo车身小一点，新手倒车停车压力更小。",
            ],
        }
    )
    pack = fake_evidence_pack(include_product=True)
    products = [
        {
            "id": "chejin_golf_2020_280tsi",
            "name": "2020款大众高尔夫280TSI DSG舒适型",
            "aliases": ["高尔夫", "大众高尔夫"],
            "price": 8.28,
            "authority_level": "product_master",
        },
        {
            "id": "chejin_civic_2020_220turbo",
            "name": "2020款本田思域220TURBO CVT劲动版",
            "aliases": ["思域", "本田思域"],
            "price": 7.58,
            "authority_level": "product_master",
        },
        {
            "id": "chejin_polo_2018_15l",
            "name": "2018款大众Polo 1.5L 自动安驾型",
            "aliases": ["Polo", "大众Polo"],
            "price": 4.88,
            "authority_level": "product_master",
        },
    ]
    pack["conversation"]["context"] = {"recent_product_ids": ["chejin_golf_2020_280tsi", "chejin_civic_2020_220turbo"]}
    pack["knowledge"]["conversation_context"] = dict(pack["conversation"]["context"])
    for bucket in (
        pack["knowledge"]["evidence"]["products"],
        pack["knowledge"]["evidence"]["catalog_candidates"],
        pack["knowledge"]["product_master"]["items"],
    ):
        bucket.extend(products)
    quality = verify_brain_reply_quality(
        normalize_brain_plan(plan),
        current_message="这两台里哪个更适合新手停车？我老婆倒车不太熟。",
        evidence_pack=pack,
        settings={},
    )
    assert_true(not quality["ok"], f"relative product drift should be rejected: {quality}")
    assert_true(
        "relative_context_product_drift" in quality["errors"],
        f"expected relative context drift error: {quality}",
    )
    return CaseResult("quality_gate_rejects_relative_context_product_drift", True, {"errors": quality["errors"]})


def check_quality_gate_accepts_visible_history_recent_product_context() -> CaseResult:
    plan = copy.deepcopy(base_plan())
    plan.update(
        {
            "answer_mode": "compare_options",
            "evidence_used": {
                "product_ids": ["chejin_qinplus_2022_dmi55", "chejin_haval_h6_2020_20t"],
                "conversation_fact_ids": ["recent_product_ids", "last_customer_need_text"],
            },
            "facts_claimed": [
                {
                    "fact_type": "product_name",
                    "value": "秦PLUS",
                    "source_level": "product_master",
                    "source_id": "chejin_qinplus_2022_dmi55",
                },
                {
                    "fact_type": "price",
                    "value": "8.68万",
                    "source_level": "product_master",
                    "source_id": "chejin_qinplus_2022_dmi55",
                },
                {
                    "fact_type": "product_name",
                    "value": "哈弗H6",
                    "source_level": "product_master",
                    "source_id": "chejin_haval_h6_2020_20t",
                },
                {
                    "fact_type": "price",
                    "value": "7.28万",
                    "source_level": "product_master",
                    "source_id": "chejin_haval_h6_2020_20t",
                },
            ],
            "reply_segments": [
                "那我就按刚才那两台直接给您定：首推秦PLUS，8.68万，预算内更适合接送孩子和买菜。",
                "第二台放哈弗H6，7.28万，空间更宽敞，停车就比秦PLUS稍微费点心。",
            ],
        }
    )
    pack = fake_evidence_pack(include_product=True)
    h6 = {
        "id": "chejin_haval_h6_2020_20t",
        "name": "2020款哈弗H6 2.0GDIT 自动冠军版",
        "aliases": ["哈弗H6", "H6"],
        "price": 7.28,
        "authority_level": "product_master",
    }
    for bucket in (
        pack["knowledge"]["evidence"]["products"],
        pack["knowledge"]["evidence"]["catalog_candidates"],
        pack["knowledge"]["product_master"]["items"],
    ):
        bucket.append(copy.deepcopy(h6))
    pack["conversation"]["context"] = {
        "recent_product_ids": ["chejin_qinplus_2022_dmi55"],
        "last_customer_need_text": "预算9万以内，自动挡，接送孩子买菜。",
    }
    pack["knowledge"]["conversation_context"] = dict(pack["conversation"]["context"])
    pack["conversation"]["history_text"] = (
        "[客户] 我想给老婆换台代步车，预算9万以内。\n"
        "[客服] 首推秦PLUS DM-i，8.68万；第二台可看哈弗H6自动挡，7.28万，空间更宽敞。"
    )
    quality = verify_brain_reply_quality(
        normalize_brain_plan(plan),
        current_message="那就按刚才说的，直接挑两台，别再问预算了。",
        evidence_pack=pack,
        settings={},
    )
    assert_true(quality["ok"], f"visible assistant history should recover recent product context: {quality}")
    return CaseResult("quality_gate_accepts_visible_history_recent_product_context", True, {"quality": quality})


def check_quality_gate_ignores_generic_alias_for_relative_context_binding() -> CaseResult:
    plan = copy.deepcopy(base_plan())
    plan.update(
        {
            "answer_mode": "compare_options",
            "evidence_used": {"product_ids": ["chejin_golf_2020_280tsi", "chejin_civic_2020_220turbo"]},
            "facts_claimed": [
                {
                    "fact_type": "product_name",
                    "value": "高尔夫",
                    "source_level": "product_master",
                    "source_id": "chejin_golf_2020_280tsi",
                },
                {
                    "fact_type": "price",
                    "value": "8.28万",
                    "source_level": "product_master",
                    "source_id": "chejin_golf_2020_280tsi",
                },
                {
                    "fact_type": "product_name",
                    "value": "思域",
                    "source_level": "product_master",
                    "source_id": "chejin_civic_2020_220turbo",
                },
                {
                    "fact_type": "price",
                    "value": "7.58万",
                    "source_level": "product_master",
                    "source_id": "chejin_civic_2020_220turbo",
                },
            ],
            "reply_segments": [
                "直接给你两台：高尔夫8.28万和思域7.58万，都在9万内。",
                "接送孩子和买菜，我更偏高尔夫，自动挡好开，停车也更省心。",
            ],
        }
    )
    pack = fake_evidence_pack(include_product=False)
    products = [
        {
            "id": "chejin_golf_2020_280tsi",
            "name": "2020款大众高尔夫280TSI DSG舒适型",
            "aliases": ["高尔夫", "大众高尔夫"],
            "price": 8.28,
            "authority_level": "product_master",
        },
        {
            "id": "chejin_civic_2020_220turbo",
            "name": "2020款本田思域220TURBO CVT劲动版",
            "aliases": ["思域", "本田思域"],
            "price": 7.58,
            "authority_level": "product_master",
        },
        {
            "id": "chejin_camry_2021_20g",
            "name": "2021款丰田凯美瑞2.0G豪华版",
            "aliases": ["凯美瑞", "8万预算", "自动挡省油", "通勤"],
            "price": 8.98,
            "authority_level": "product_master",
        },
    ]
    pack["conversation"]["context"] = {
        "recent_product_ids": ["chejin_golf_2020_280tsi", "chejin_civic_2020_220turbo"],
        "last_customer_need_text": "预算9万以内，自动挡，接送孩子和买菜。",
    }
    pack["knowledge"]["conversation_context"] = dict(pack["conversation"]["context"])
    for bucket in (
        pack["knowledge"]["evidence"]["products"],
        pack["knowledge"]["evidence"]["catalog_candidates"],
        pack["knowledge"]["product_master"]["items"],
    ):
        bucket.extend(copy.deepcopy(products))
    quality = verify_brain_reply_quality(
        normalize_brain_plan(plan),
        current_message="那就按刚才说的，直接挑两台，别再问预算了。",
        evidence_pack=pack,
        settings={},
    )
    assert_true(quality["ok"], f"generic aliases should not trigger relative context drift: {quality}")
    return CaseResult("quality_gate_ignores_generic_alias_for_relative_context_binding", True, {"quality": quality})


def check_quality_gate_rejects_over_budget_primary_recommendation() -> CaseResult:
    plan = copy.deepcopy(base_plan())
    plan.update(
        {
            "answer_mode": "recommend_from_catalog",
            "evidence_used": {"product_ids": ["chejin_audi_a4l_2018_40tfsi", "chejin_nio_es6_2019_performance"]},
            "facts_claimed": [
                {
                    "fact_type": "product",
                    "value": "奥迪A4L",
                    "source_level": "product_master",
                    "source_id": "chejin_audi_a4l_2018_40tfsi",
                },
                {
                    "fact_type": "product",
                    "value": "蔚来ES6",
                    "source_level": "product_master",
                    "source_id": "chejin_nio_es6_2019_performance",
                },
            ],
            "reply_segments": [
                "按你刚才的需求，我先给你挑两台：奥迪A4L和蔚来ES6，都是自动挡。",
                "A4L是14.5万，ES6是16.8万，但这两台都超你刚说的9万内。",
            ],
        }
    )
    pack = fake_evidence_pack(include_product=True)
    pack["conversation"]["context"] = {"last_customer_need_text": "预算9万以内，自动挡，最好有倒车影像。"}
    pack["knowledge"]["product_master"]["items"].extend(
        [
            {
                "id": "chejin_audi_a4l_2018_40tfsi",
                "name": "2018款奥迪A4L 40 TFSI 进取型",
                "aliases": ["奥迪A4L", "A4L"],
                "price": 14.5,
                "authority_level": "product_master",
            },
            {
                "id": "chejin_nio_es6_2019_performance",
                "name": "2019款蔚来ES6 性能版",
                "aliases": ["蔚来ES6", "ES6"],
                "price": 16.8,
                "authority_level": "product_master",
            },
        ]
    )
    quality = verify_brain_reply_quality(
        normalize_brain_plan(plan),
        current_message="近期客户需求：预算9万以内，自动挡，最好有倒车影像。\n当前客户问题：那就按刚才说的，直接挑两台，别再问预算了。",
        evidence_pack=pack,
        settings={},
    )
    assert_true(not quality["ok"], f"over-budget primary recommendation should fail when budget-fit candidates exist: {quality}")
    assert_true(
        "over_budget_recommendation_ignores_budget_fit_candidates" in quality["errors"],
        f"expected over-budget recommendation error: {quality}",
    )
    return CaseResult("quality_gate_rejects_over_budget_primary_recommendation", True, {"errors": quality["errors"]})


def check_quality_gate_rejects_over_budget_slot_for_budgeted_multi_recommendation() -> CaseResult:
    plan = copy.deepcopy(base_plan())
    plan.update(
        {
            "answer_mode": "recommend_from_catalog",
            "evidence_used": {"product_ids": ["chejin_qinplus_2022_dmi55", "chejin_audi_a4l_2018_40tfsi"]},
            "facts_claimed": [
                {
                    "fact_type": "product",
                    "value": "秦PLUS",
                    "source_level": "product_master",
                    "source_id": "chejin_qinplus_2022_dmi55",
                },
                {
                    "fact_type": "product",
                    "value": "奥迪A4L",
                    "source_level": "product_master",
                    "source_id": "chejin_audi_a4l_2018_40tfsi",
                },
            ],
            "reply_segments": [
                "我先给你挑两台：秦PLUS和A4L。",
                "秦PLUS是8.68万，更贴近十万预算；A4L是14.5万，明显超预算，就当备选。",
            ],
        }
    )
    pack = fake_evidence_pack(include_product=True)
    pack["conversation"]["context"] = {"last_customer_need_text": "预算十万左右，接娃通勤，别太费油。"}
    budget_fit_and_over_budget = [
        {
            "id": "chejin_polo_2018_15l",
            "name": "2018款大众Polo 1.5L 自动安享型",
            "aliases": ["Polo", "大众Polo"],
            "price": 4.58,
            "authority_level": "product_master",
        },
        {
            "id": "chejin_audi_a4l_2018_40tfsi",
            "name": "2018款奥迪A4L 40 TFSI 进取型",
            "aliases": ["奥迪A4L", "A4L"],
            "price": 14.5,
            "authority_level": "product_master",
        },
    ]
    for bucket in (
        pack["knowledge"]["evidence"]["products"],
        pack["knowledge"]["evidence"]["catalog_candidates"],
        pack["knowledge"]["product_master"]["items"],
    ):
        bucket.extend(copy.deepcopy(budget_fit_and_over_budget))
    quality = verify_brain_reply_quality(
        normalize_brain_plan(plan),
        current_message="近期客户需求：预算十万左右，接娃通勤，别太费油。\n当前客户问题：那你直接给我挑两台靠谱的，南京能看最好。",
        evidence_pack=pack,
        settings={},
    )
    assert_true(not quality["ok"], f"over-budget recommendation slot should fail for budgeted multi-recommendation: {quality}")
    assert_true(
        "over_budget_recommendation_fills_budget_slot" in quality["errors"],
        f"expected over-budget slot error: {quality}",
    )
    return CaseResult(
        "quality_gate_rejects_over_budget_slot_for_budgeted_multi_recommendation",
        True,
        {"errors": quality["errors"]},
    )


def check_quality_gate_allows_explicit_over_budget_backup_when_only_one_budget_fit() -> CaseResult:
    plan = copy.deepcopy(base_plan())
    plan.update(
        {
            "answer_mode": "recommend_from_catalog",
            "evidence_used": {"product_ids": ["chejin_camry_2021_20g", "chejin_audi_a4l_2018_40tfsi"]},
            "facts_claimed": [
                {
                    "fact_type": "product_name",
                    "value": "凯美瑞",
                    "source_level": "product_master",
                    "source_id": "chejin_camry_2021_20g",
                },
                {
                    "fact_type": "product_name",
                    "value": "奥迪A4L",
                    "source_level": "product_master",
                    "source_id": "chejin_audi_a4l_2018_40tfsi",
                },
            ],
            "reply_segments": [
                "十万左右我主推凯美瑞，8.98万，南京能看，油耗和稳定性都更稳。",
                "A4L是14.5万，明显超预算，只能当预算外备选，不和凯美瑞算同档推荐。",
            ],
        }
    )
    pack = fake_evidence_pack(include_product=False)
    pack["conversation"]["context"] = {"last_customer_need_text": "预算十万左右，接娃通勤，别太费油。"}
    candidates = [
        {
            "id": "chejin_camry_2021_20g",
            "name": "2021款丰田凯美瑞 2.0G 豪华版",
            "aliases": ["凯美瑞", "丰田凯美瑞"],
            "price": 8.98,
            "authority_level": "product_master",
        },
        {
            "id": "chejin_audi_a4l_2018_40tfsi",
            "name": "2018款奥迪A4L 40 TFSI 进取型",
            "aliases": ["奥迪A4L", "A4L"],
            "price": 14.5,
            "authority_level": "product_master",
        },
    ]
    for bucket in (
        pack["knowledge"]["evidence"]["products"],
        pack["knowledge"]["evidence"]["catalog_candidates"],
        pack["knowledge"]["product_master"]["items"],
    ):
        bucket.extend(copy.deepcopy(candidates))
    quality = verify_brain_reply_quality(
        normalize_brain_plan(plan),
        current_message="近期客户需求：预算十万左右，接娃通勤，别太费油。\n当前客户问题：那你直接给我挑两台靠谱的，南京能看最好。",
        evidence_pack=pack,
        settings={},
    )
    assert_true(
        quality["ok"],
        f"explicit over-budget backup should pass when only one budget-fit candidate exists: {quality}",
    )
    return CaseResult(
        "quality_gate_allows_explicit_over_budget_backup_when_only_one_budget_fit",
        True,
        {"errors": quality["errors"], "warnings": quality["warnings"]},
    )


def check_quality_gate_rejects_single_candidate_for_multi_recommendation_request() -> CaseResult:
    plan = copy.deepcopy(base_plan())
    plan.update(
        {
            "answer_mode": "recommend_from_catalog",
            "evidence_used": {"product_ids": ["chejin_qinplus_2022_dmi55"]},
            "facts_claimed": [
                {
                    "fact_type": "product_name",
                    "value": "秦PLUS",
                    "source_level": "product_master",
                    "source_id": "chejin_qinplus_2022_dmi55",
                }
            ],
            "reply_segments": [
                "我先明确推荐这台秦PLUS，8.68万，通勤省油更合适。",
                "第二台我继续帮你筛，不拿超预算的硬凑。",
            ],
        }
    )
    pack = fake_evidence_pack(include_product=True)
    pack["conversation"]["context"] = {"last_customer_need_text": "预算十万左右，接娃通勤，别太费油。"}
    second_budget_fit = {
        "id": "chejin_polo_2018_15l",
        "name": "2018款大众Polo 1.5L 自动安享型",
        "aliases": ["Polo", "大众Polo"],
        "price": 4.58,
        "authority_level": "product_master",
    }
    for bucket in (
        pack["knowledge"]["evidence"]["products"],
        pack["knowledge"]["evidence"]["catalog_candidates"],
        pack["knowledge"]["product_master"]["items"],
    ):
        bucket.append(copy.deepcopy(second_budget_fit))
    quality = verify_brain_reply_quality(
        normalize_brain_plan(plan),
        current_message="近期客户需求：预算十万左右，接娃通勤，别太费油。\n当前客户问题：那你直接给我挑两台靠谱的，南京能看最好。",
        evidence_pack=pack,
        settings={},
    )
    assert_true(not quality["ok"], f"single-candidate reply should fail when customer asked for two and candidates exist: {quality}")
    assert_true(
        "missing_multiple_product_recommendations" in quality["errors"],
        f"expected missing multi-product recommendation error: {quality}",
    )
    return CaseResult(
        "quality_gate_rejects_single_candidate_for_multi_recommendation_request",
        True,
        {"errors": quality["errors"]},
    )


def check_quality_gate_allows_transparent_multi_recommendation_limitation() -> CaseResult:
    plan = copy.deepcopy(base_plan())
    plan.update(
        {
            "answer_mode": "recommend_from_catalog",
            "evidence_used": {"product_ids": ["chejin_camry_2021_20g"]},
            "facts_claimed": [
                {
                    "fact_type": "price",
                    "value": "2021款凯美瑞2.0G 8.98万",
                    "source_level": "product_master",
                    "source_id": "chejin_camry_2021_20g",
                }
            ],
            "reply_segments": [
                "按你这个需求，我先明确推荐2021款凯美瑞2.0G，8.98万，南京现车。",
                "这台更贴近你十万左右、接娃通勤、别太费油的要求。",
                "当前已确认车源里暂时没有第二台同时满足十万左右和南京优先，我再按这个条件继续筛。",
            ],
        }
    )
    pack = fake_evidence_pack(include_product=True)
    pack["conversation"]["context"] = {"last_customer_need_text": "预算十万左右，接娃通勤，别太费油，南京优先。"}
    quality = verify_brain_reply_quality(
        normalize_brain_plan(plan),
        current_message="近期客户需求：预算十万左右，接娃通勤，别太费油，南京能看最好。\n当前客户问题：那你直接给我挑两台靠谱的，南京能看最好。",
        evidence_pack=pack,
        settings={},
    )
    assert_true(quality["ok"], f"transparent candidate limitation should pass: {quality}")
    return CaseResult(
        "quality_gate_allows_transparent_multi_recommendation_limitation",
        True,
        {"quality": quality},
    )


def check_quality_gate_rejects_known_budget_fit_price_uncertainty() -> CaseResult:
    plan = copy.deepcopy(base_plan())
    plan.update(
        {
            "answer_mode": "recommend_from_catalog",
            "evidence_used": {"product_ids": ["chejin_golf_2020_280tsi", "chejin_civic_2020_220turbo"]},
            "facts_claimed": [
                {
                    "fact_type": "product_name",
                    "value": "高尔夫",
                    "source_level": "product_master",
                    "source_id": "chejin_golf_2020_280tsi",
                },
                {
                    "fact_type": "product_name",
                    "value": "思域",
                    "source_level": "product_master",
                    "source_id": "chejin_civic_2020_220turbo",
                },
            ],
            "reply_segments": [
                "首推高尔夫，8.28万这台更贴合9万内预算。",
                "另一台先给你放思域做备选，但要看实际挂牌价能不能压进你预算。",
            ],
        }
    )
    pack = fake_evidence_pack(include_product=True)
    products = [
        {
            "id": "chejin_golf_2020_280tsi",
            "name": "2020款大众高尔夫280TSI DSG舒适型",
            "aliases": ["高尔夫", "大众高尔夫"],
            "price": 8.28,
            "authority_level": "product_master",
        },
        {
            "id": "chejin_civic_2020_220turbo",
            "name": "2020款本田思域220TURBO CVT劲动版",
            "aliases": ["思域", "本田思域"],
            "price": 7.58,
            "authority_level": "product_master",
        },
    ]
    for bucket in (
        pack["knowledge"]["evidence"]["products"],
        pack["knowledge"]["evidence"]["catalog_candidates"],
        pack["knowledge"]["product_master"]["items"],
    ):
        bucket.extend(products)
    pack["conversation"]["context"] = {"last_customer_need_text": "预算9万以内，自动挡。"}
    quality = verify_brain_reply_quality(
        normalize_brain_plan(plan),
        current_message="那就按刚才说的，直接挑两台，别再问预算了。",
        evidence_pack=pack,
        settings={},
    )
    assert_true(not quality["ok"], f"known in-budget product price should not be marked uncertain: {quality}")
    assert_true(
        "known_budget_fit_product_marked_price_uncertain" in quality["errors"],
        f"expected known price uncertainty error: {quality}",
    )
    return CaseResult("quality_gate_rejects_known_budget_fit_price_uncertainty", True, {"errors": quality["errors"]})


def check_quality_gate_accepts_clear_resale_choice_wording() -> CaseResult:
    plan = copy.deepcopy(base_plan())
    plan.update(
        {
            "answer_mode": "compare_options",
            "evidence_used": {"product_ids": ["chejin_camry_2021_20g"], "common_sense_topics": ["used_car_resale_value"]},
            "facts_claimed": [
                {
                    "fact_type": "product",
                    "value": "2021款丰田凯美瑞2.0G",
                    "source_level": "product_master",
                    "source_id": "chejin_camry_2021_20g",
                }
            ],
            "reply_segments": [
                "这两台里如果看后面再卖、亏得少一点，一般还是凯美瑞更稳。",
                "它家用受众更广，后期维护预期也更稳定；A4L质感好，但价格波动通常更吃车况。",
            ],
        }
    )
    pack = fake_evidence_pack(include_product=True)
    pack["knowledge"]["product_master"]["items"].append(
        {
            "id": "chejin_camry_2021_20g",
            "name": "2021款丰田凯美瑞2.0G",
            "aliases": ["凯美瑞", "丰田凯美瑞"],
            "price": 9.58,
            "authority_level": "product_master",
        }
    )
    pack["knowledge"]["product_master"]["items"].append(
        {
            "id": "chejin_audi_a4l_2018_40tfsi",
            "name": "2018款奥迪A4L 40 TFSI 进取型",
            "aliases": ["A4L", "奥迪A4L"],
            "price": 14.5,
            "authority_level": "product_master",
        }
    )
    quality = verify_brain_reply_quality(
        normalize_brain_plan(plan),
        current_message="这两台里哪个后面再卖亏得少点？",
        evidence_pack=pack,
        settings={},
    )
    assert_true(quality["ok"], f"clear resale choice wording should pass quality gate: {quality}")
    return CaseResult("quality_gate_accepts_clear_resale_choice_wording", True, {"quality": quality})


def check_quality_gate_accepts_preference_wording_as_clear_choice() -> CaseResult:
    plan = normalize_brain_plan(
        {
            **base_plan(),
            "answer_mode": "compare_options",
            "evidence_used": {
                "product_ids": ["chejin_tiguanl_2021_330tsi", "chejin_xtrail_2020_25l"],
                "common_sense_topics": ["接待观感", "装载实用性"],
            },
            "facts_claimed": [
                {
                    "fact_type": "price",
                    "value": "途观L 15.8万",
                    "source_level": "product_master",
                    "source_id": "chejin_tiguanl_2021_330tsi",
                },
                {
                    "fact_type": "price",
                    "value": "奇骏 11.5万",
                    "source_level": "product_master",
                    "source_id": "chejin_xtrail_2020_25l",
                },
            ],
            "reply_segments": [
                "要显得稍微体面点接客户，我明确更偏途观L。",
                "这台15.8万在预算内，接待和装东西都更顺手；奇骏更偏务实，我会放第二顺位。",
            ],
        }
    )
    pack = fake_evidence_pack(include_product=False)
    products = [
        {
            "id": "chejin_tiguanl_2021_330tsi",
            "name": "2021款大众途观L 330TSI 自动两驱智享版",
            "aliases": ["途观L", "大众途观", "SUV", "2.0T"],
            "price": 15.8,
            "authority_level": "product_master",
        },
        {
            "id": "chejin_xtrail_2020_25l",
            "name": "2020款日产奇骏2.5L CVT四驱豪华版",
            "aliases": ["奇骏", "日产奇骏", "SUV", "2.5L"],
            "price": 11.5,
            "authority_level": "product_master",
        },
    ]
    for bucket in (
        pack["knowledge"]["evidence"]["products"],
        pack["knowledge"]["evidence"]["catalog_candidates"],
        pack["knowledge"]["product_master"]["items"],
    ):
        bucket.extend(copy.deepcopy(products))
    quality = verify_brain_reply_quality(
        plan,
        current_message="如果要显得稍微体面点接客户，途观L和奇骏你更偏哪台？",
        evidence_pack=pack,
        settings={},
    )
    assert_true(quality["ok"], f'preference wording such as "更偏/第二顺位" should pass: {quality}')
    return CaseResult("quality_gate_accepts_preference_wording_as_clear_choice", True, {"quality": quality})


def check_quality_gate_rejects_ambiguous_followup_product_drift() -> CaseResult:
    plan = normalize_brain_plan(
        {
            **base_plan(),
            "answer_mode": "direct_answer",
            "evidence_used": {"product_ids": ["chejin_xtrail_2020_25l"]},
            "facts_claimed": [
                {
                    "fact_type": "configuration",
                    "value": "奇骏2.5L",
                    "source_level": "product_master",
                    "source_id": "chejin_xtrail_2020_25l",
                }
            ],
            "reply_segments": [
                "这台是奇骏2.5L，市区跑客户不算特别省油，后期保养看记录和车况。",
            ],
        }
    )
    pack = pack_with_tiguan_primary_and_xtrail_backup()
    quality = verify_brain_reply_quality(
        plan,
        current_message="油耗和后期保养呢？我平时市区跑客户比较多，不想维护太麻烦。",
        evidence_pack=pack,
        settings={},
    )
    assert_true(not quality["ok"], f"ambiguous follow-up should reject backup-product drift: {quality}")
    assert_true("ambiguous_followup_product_drift" in quality["errors"], f"expected drift error: {quality}")
    return CaseResult("quality_gate_rejects_ambiguous_followup_product_drift", True, {"errors": quality["errors"]})


def check_quality_gate_allows_anchored_backup_on_ambiguous_followup() -> CaseResult:
    plan = normalize_brain_plan(
        {
            **base_plan(),
            "answer_mode": "direct_answer",
            "evidence_used": {"product_ids": ["chejin_tiguanl_2021_330tsi", "chejin_xtrail_2020_25l"]},
            "facts_claimed": [
                {
                    "fact_type": "product_name",
                    "value": "途观L",
                    "source_level": "product_master",
                    "source_id": "chejin_tiguanl_2021_330tsi",
                },
                {
                    "fact_type": "product_name",
                    "value": "奇骏",
                    "source_level": "product_master",
                    "source_id": "chejin_xtrail_2020_25l",
                },
            ],
            "reply_segments": [
                "途观L接客户更体面。",
                "如果主要看市区油耗和保养，我更偏奇骏这个方向。",
            ],
        }
    )
    quality = verify_brain_reply_quality(
        plan,
        current_message="油耗和后期保养呢？我平时市区跑客户比较多，不想维护太麻烦。",
        evidence_pack=pack_with_tiguan_primary_and_xtrail_backup(),
        settings={},
    )
    assert_true(quality["ok"], f"anchored backup comparison should pass once primary product is answered first: {quality}")
    return CaseResult("quality_gate_allows_anchored_backup_on_ambiguous_followup", True, {"quality": quality})


def check_quality_gate_allows_ambiguous_followup_primary_product() -> CaseResult:
    plan = normalize_brain_plan(
        {
            **base_plan(),
            "answer_mode": "direct_answer",
            "evidence_used": {"product_ids": ["chejin_tiguanl_2021_330tsi"]},
            "facts_claimed": [
                {
                    "fact_type": "price",
                    "value": "途观L 15.8万",
                    "source_level": "product_master",
                    "source_id": "chejin_tiguanl_2021_330tsi",
                }
            ],
            "reply_segments": [
                "途观L市区油耗不算最低，但空间和接待感更贴你场景；保养主要看记录和车况。",
            ],
        }
    )
    pack = pack_with_tiguan_primary_and_xtrail_backup()
    quality = verify_brain_reply_quality(
        plan,
        current_message="油耗和后期保养呢？我平时市区跑客户比较多，不想维护太麻烦。",
        evidence_pack=pack,
        settings={},
    )
    assert_true(quality["ok"], f"primary-product follow-up should pass: {quality}")
    return CaseResult("quality_gate_allows_ambiguous_followup_primary_product", True, {"quality": quality})


def check_quality_gate_rejects_missing_cargo_space_topic() -> CaseResult:
    plan = normalize_brain_plan(
        {
            **base_plan(),
            "answer_mode": "recommend_from_catalog",
            "evidence_used": {"product_ids": ["chejin_camry_2021_20g", "chejin_audi_a4l_2018_40tfsi"]},
            "facts_claimed": [
                {
                    "fact_type": "price",
                    "value": "凯美瑞 8.98万",
                    "source_level": "product_master",
                    "source_id": "chejin_camry_2021_20g",
                }
            ],
            "reply_segments": [
                "先给你三个方向：凯美瑞偏家用实用，A4L偏体面通勤，思域偏年轻好开。",
                "主推凯美瑞2.0G，8.98万，2021年上牌，南京现车。",
            ],
        }
    )
    pack = fake_evidence_pack(include_product=False)
    pack["knowledge"]["product_master"]["items"].extend(
        [
            {
                "id": "chejin_camry_2021_20g",
                "name": "2021款丰田凯美瑞2.0G豪华版",
                "aliases": ["凯美瑞"],
                "price": 8.98,
                "authority_level": "product_master",
            },
            {
                "id": "chejin_audi_a4l_2018_40tfsi",
                "name": "2018款奥迪A4L 40 TFSI 进取型",
                "aliases": ["A4L", "奥迪A4L"],
                "price": 14.5,
                "authority_level": "product_master",
            },
        ]
    )
    quality = verify_brain_reply_quality(
        plan,
        current_message="先按16万内给我两三个方向，后备厢要实用一点。",
        evidence_pack=pack,
        settings={},
    )
    assert_true(not quality["ok"], f"cargo-space question should require cargo-space coverage: {quality}")
    assert_true("missing_cargo_space_topic" in quality["errors"], f"expected cargo topic error: {quality}")
    return CaseResult("quality_gate_rejects_missing_cargo_space_topic", True, {"errors": quality["errors"]})


def check_quality_gate_allows_conservative_cargo_dimension_reply() -> CaseResult:
    plan = normalize_brain_plan(
        {
            **base_plan(),
            "answer_mode": "direct_answer",
            "evidence_used": {"product_ids": ["chejin_xtrail_2020_25l"], "common_sense_topics": ["装载能力需看实物尺寸"]},
            "facts_claimed": [
                {
                    "fact_type": "product_name",
                    "value": "2020款日产奇骏2.5L CVT智联豪华版",
                    "source_level": "product_master",
                    "source_id": "chejin_xtrail_2020_25l",
                }
            ],
            "reply_segments": [
                "这台奇骏能不能塞下梯子和两三个工具箱，我这边不能直接给您下结论。",
                "主要看梯子长度和工具箱尺寸，您把大概尺寸发我，或者到店实车比划一下最稳。",
            ],
        }
    )
    pack = fake_evidence_pack(include_product=False)
    pack["knowledge"]["product_master"]["items"].append(
        {
            "id": "chejin_xtrail_2020_25l",
            "name": "2020款日产奇骏2.5L CVT智联豪华版",
            "aliases": ["奇骏"],
            "price": 11.5,
            "authority_level": "product_master",
        }
    )
    quality = verify_brain_reply_quality(
        plan,
        current_message="后排放倒后，梯子和两三个工具箱能不能塞得下？",
        evidence_pack=pack,
        settings={},
    )
    assert_true(quality["ok"], f"conservative cargo dimension reply should pass: {quality}")
    risky = copy.deepcopy(plan)
    risky["reply_segments"] = ["奇骏后排放倒后空间比较规整，梯子和两三个工具箱大概率能塞，问题不大。"]
    risky_quality = verify_brain_reply_quality(
        normalize_brain_plan(risky),
        current_message="后排放倒后，梯子和两三个工具箱能不能塞得下？",
        evidence_pack=pack,
        settings={},
    )
    assert_true(
        "unverified_cargo_capacity_affirmative_claim" in risky_quality["errors"],
        f"unverified cargo capacity claim should be blocked: {risky_quality}",
    )
    return CaseResult(
        "quality_gate_allows_conservative_cargo_dimension_reply",
        True,
        {"quality": quality, "risky_errors": risky_quality["errors"]},
    )


def check_quality_gate_rejects_ignoring_available_cargo_fit_candidate() -> CaseResult:
    bad_plan = normalize_brain_plan(
        {
            **base_plan(),
            "answer_mode": "recommend_from_catalog",
            "evidence_used": {"product_ids": ["chejin_bmw320_2019_m"]},
            "facts_claimed": [],
            "reply_segments": [
                "先给您结论：14万内现有更合适的先看宝马320Li和现代领动。",
                "我这边现有车源里都还是轿车，您要装物料更合适看SUV方向，我接着给您筛。",
            ],
        }
    )
    pack = fake_evidence_pack(include_product=True)
    pack["knowledge"]["product_master"]["items"].extend(
        [
            {
                "id": "chejin_xtrail_2020_25l",
                "name": "2020款日产奇骏2.5L CVT智联豪华版",
                "aliases": ["奇骏", "日产奇骏"],
                "category": "二手车/SUV",
                "price": 11.5,
                "authority_level": "product_master",
            },
            {
                "id": "chejin_haval_h6_2020_20t",
                "name": "2020款哈弗H6 2.0GDIT 自动冠军版",
                "aliases": ["哈弗H6", "H6"],
                "category": "二手车/SUV",
                "price": 7.28,
                "authority_level": "product_master",
            },
        ]
    )
    quality = verify_brain_reply_quality(
        bad_plan,
        current_message="先按14万内给我两三个方向，不想只看轿车，后备厢要能放物料。",
        evidence_pack=pack,
        settings={},
    )
    assert_true(not quality["ok"], f"available cargo-fit candidate should not be ignored: {quality}")
    assert_true(
        "contradicts_available_cargo_fit_candidate" in quality["errors"]
        or "missing_available_cargo_fit_candidate" in quality["errors"],
        f"expected cargo candidate error: {quality}",
    )

    good_plan = normalize_brain_plan(
        {
            **base_plan(),
            "answer_mode": "recommend_from_catalog",
            "evidence_used": {"product_ids": ["chejin_xtrail_2020_25l", "chejin_haval_h6_2020_20t"]},
            "facts_claimed": [],
            "reply_segments": [
                "14万内我会先看奇骏和哈弗H6这两个SUV方向。",
                "奇骏更兼顾接客户和装物料，H6更省预算，后备厢实用性也比轿车方向稳。",
            ],
        }
    )
    good_quality = verify_brain_reply_quality(
        good_plan,
        current_message="先按14万内给我两三个方向，不想只看轿车，后备厢要能放物料。",
        evidence_pack=pack,
        settings={},
    )
    assert_true(good_quality["ok"], f"cargo-fit concrete product recommendation should pass: {good_quality}")
    return CaseResult("quality_gate_rejects_ignoring_available_cargo_fit_candidate", True, {"errors": quality["errors"]})


def pack_with_tiguan_primary_and_xtrail_backup() -> dict[str, Any]:
    pack = fake_evidence_pack(include_product=False)
    pack["conversation"]["context"] = {
        "last_product_id": "chejin_tiguanl_2021_330tsi",
        "recent_product_ids": ["chejin_tiguanl_2021_330tsi", "chejin_xtrail_2020_25l"],
    }
    products = [
        {
            "id": "chejin_tiguanl_2021_330tsi",
            "name": "2021款大众途观L 330TSI 自动两驱智享版",
            "aliases": ["途观L", "大众途观"],
            "price": 15.8,
            "authority_level": "product_master",
        },
        {
            "id": "chejin_xtrail_2020_25l",
            "name": "2020款日产奇骏2.5L CVT四驱豪华版",
            "aliases": ["奇骏", "日产奇骏"],
            "price": 11.5,
            "authority_level": "product_master",
        },
    ]
    for bucket in (
        pack["knowledge"]["evidence"]["products"],
        pack["knowledge"]["evidence"]["catalog_candidates"],
        pack["knowledge"]["product_master"]["items"],
    ):
        bucket.extend(copy.deepcopy(products))
    return pack


def check_quality_gate_rejects_incomplete_reply_segment() -> CaseResult:
    plan = normalize_brain_plan(
        {
            **base_plan(),
            "answer_mode": "direct_answer",
            "evidence_used": {"common_sense_topics": ["insurance_claim_common_sense"]},
            "facts_claimed": [],
            "reply_segments": [
                "自己剐蹭墙一般先报保险、拍照留存、再定损维修。",
                "如果损失不大。",
            ],
        }
    )
    quality = verify_brain_reply_quality(
        plan,
        current_message="自己撞墙了保险赔吗？",
        evidence_pack=fake_evidence_pack(include_product=False),
        settings={"quality_segment_soft_max_chars": 96},
    )
    assert_true("incomplete_reply_segment" in quality["errors"], f"expected incomplete segment error: {quality}")
    return CaseResult("quality_gate_rejects_incomplete_reply_segment", True, {"errors": quality["errors"]})


def check_quality_gate_accepts_complete_colloquial_condition_segment() -> CaseResult:
    plan = normalize_brain_plan(
        {
            "can_answer": True,
            "answer_mode": "soft_social_reply",
            "evidence_used": {
                "common_sense_topics": ["聚餐饮食选择"],
                "style_ids": ["customer_service_style_guidelines"],
            },
            "facts_claimed": [],
            "reply_segments": [
                "我偏向火锅，晚上吃着更有氛围，也比较好聊天。",
                "你要是今天想吃得更热闹一点，我这一票投火锅。",
            ],
            "recommended_action": "send_reply",
            "confidence": 0.95,
            "risk": {"risk_level": "low", "risk_tags": ["small_talk"], "needs_handoff": False},
        }
    )
    quality = verify_brain_reply_quality(
        plan,
        current_message="你觉得今天晚上吃火锅还是烤肉？",
        evidence_pack=fake_evidence_pack(include_product=False),
        settings={},
    )
    assert_true(quality["ok"], f"complete colloquial condition reply should pass quality gate: {quality}")
    assert_true(
        not is_incomplete_reply_segment("你要是今天想吃得更热闹一点，我这一票投火锅。"),
        "condition + consequent colloquial sentence should not be treated as incomplete",
    )
    assert_true(
        is_incomplete_reply_segment("如果损失不大，"),
        "condition-only dangling clause should still be rejected",
    )
    return CaseResult("quality_gate_accepts_complete_colloquial_condition_segment", True, {"quality": quality})


def check_quality_gate_rejects_dangling_condition_clause() -> CaseResult:
    bad_plan = normalize_brain_plan(
        {
            **base_plan(),
            "answer_mode": "direct_answer",
            "evidence_used": {"formal_knowledge_ids": ["after_sales_policy"]},
            "facts_claimed": [],
            "reply_segments": [
                "我们在售车都会检测，重大事故、水泡、火烧车不售。",
                "质保期内如果发现这类问题且未提前告知。",
            ],
        }
    )
    bad_quality = verify_brain_reply_quality(
        bad_plan,
        current_message="能不能保证不是事故水泡火烧？",
        evidence_pack=fake_evidence_pack(include_product=False),
        settings={},
    )
    assert_true(not bad_quality["ok"], f"dangling condition should fail: {bad_quality}")
    assert_true("incomplete_reply_segment" in bad_quality["errors"], f"expected incomplete segment: {bad_quality}")

    good_plan = normalize_brain_plan(
        {
            **base_plan(),
            "answer_mode": "direct_answer",
            "evidence_used": {"formal_knowledge_ids": ["after_sales_policy"]},
            "facts_claimed": [],
            "reply_segments": [
                "我们在售车都会检测，重大事故、水泡、火烧车不售。",
                "质保期内如果发现这类问题且未提前告知，可以按合同约定处理。",
            ],
        }
    )
    good_quality = verify_brain_reply_quality(
        good_plan,
        current_message="能不能保证不是事故水泡火烧？",
        evidence_pack=fake_evidence_pack(include_product=False),
        settings={},
    )
    assert_true(good_quality["ok"], f"complete condition should pass: {good_quality}")

    natural_plan = normalize_brain_plan(
        {
            **base_plan(),
            "answer_mode": "compare_options",
            "evidence_used": {"common_sense_topics": ["resale_value_common_sense"]},
            "facts_claimed": [],
            "reply_segments": [
                "主要是这类家用车接受度更高，后续出手时买家顾虑往往也更少。",
                "要是你更看重省心保值，我建议优先看凯美瑞。",
            ],
        }
    )
    natural_quality = verify_brain_reply_quality(
        natural_plan,
        current_message="这两台里哪个后面再卖亏得少点？",
        evidence_pack=fake_evidence_pack(include_product=False),
        settings={},
    )
    assert_true(natural_quality["ok"], f"natural conditional recommendation should pass: {natural_quality}")
    return CaseResult("quality_gate_rejects_dangling_condition_clause", True, {"errors": bad_quality["errors"]})


def check_quality_gate_rejects_dangling_decision_fragment() -> CaseResult:
    bad_plan = normalize_brain_plan(
        {
            **base_plan(),
            "answer_mode": "direct_answer",
            "evidence_used": {"common_sense_topics": ["insurance_claim_common_sense"]},
            "facts_claimed": [],
            "reply_segments": [
                "自己剐蹭墙一般先报案定损，常见是走车损险。",
                "要不要出险。",
            ],
        }
    )
    bad_quality = verify_brain_reply_quality(
        bad_plan,
        current_message="自己撞墙了保险赔吗？",
        evidence_pack=fake_evidence_pack(include_product=False),
        settings={},
    )
    assert_true(not bad_quality["ok"], f"dangling decision should fail: {bad_quality}")
    assert_true("incomplete_reply_segment" in bad_quality["errors"], f"expected incomplete segment: {bad_quality}")

    good_plan = normalize_brain_plan(
        {
            **base_plan(),
            "answer_mode": "direct_answer",
            "evidence_used": {"common_sense_topics": ["insurance_claim_common_sense"]},
            "facts_claimed": [],
            "reply_segments": [
                "自己剐蹭墙一般先报案定损，常见是走车损险。",
                "要不要出险，要看维修金额和次年保费影响，别急着定。",
            ],
        }
    )
    good_quality = verify_brain_reply_quality(
        good_plan,
        current_message="自己撞墙了保险赔吗？",
        evidence_pack=fake_evidence_pack(include_product=False),
        settings={},
    )
    assert_true(good_quality["ok"], f"complete decision should pass: {good_quality}")
    return CaseResult("quality_gate_rejects_dangling_decision_fragment", True, {"errors": bad_quality["errors"]})


def check_quality_gate_rejects_missing_insurance_subtopic() -> CaseResult:
    plan = copy.deepcopy(base_plan())
    plan.update(
        {
            "answer_mode": "recommend_from_catalog",
            "evidence_used": {"product_ids": ["chejin_qinplus_2022_dmi55"], "common_sense_topics": ["insurance_claim_common_sense"]},
            "reply_segments": [
                "省油家用车可以先看秦PLUS，日常通勤成本比较友好。",
                "如果想空间更大，我也可以再帮您筛两台轿车。"
            ],
        }
    )
    quality = verify_brain_reply_quality(
        normalize_brain_plan(plan),
        current_message="我想看省油的家用车，顺便问下如果自己剐蹭墙了保险一般怎么处理？",
        evidence_pack=fake_evidence_pack(include_product=True),
        settings={"quality_segment_soft_max_chars": 96},
    )
    assert_true("missing_insurance_common_sense_topic" in quality["errors"], f"expected missing insurance subtopic error: {quality}")
    return CaseResult("quality_gate_rejects_missing_insurance_subtopic", True, {"errors": quality["errors"]})


def check_quality_gate_rejects_appointment_overcommit_without_confirmation() -> CaseResult:
    risky_plan = copy.deepcopy(base_plan())
    risky_plan.update(
        {
            "answer_mode": "collect_customer_info",
            "evidence_used": {"conversation_fact_ids": ["current_message.clean_text"]},
            "facts_claimed": [],
            "reply_segments": [
                "好的王先生，收到您的电话和时间了。",
                "您周六下午两点左右过来就可以，到店前跟我说一声，我这边跟您对接看车。",
            ],
        }
    )
    current_message = "可以，我叫王先生，电话13912345678，周六下午两点左右过去。"
    risky_quality = verify_brain_reply_quality(
        normalize_brain_plan(risky_plan),
        current_message=current_message,
        evidence_pack=fake_evidence_pack(include_product=True),
        settings={},
    )
    assert_true(
        not risky_quality["ok"],
        f"appointment overcommit should fail without source/schedule confirmation boundary: {risky_quality}",
    )
    assert_true(
        "appointment_commitment_without_confirmation_boundary" in risky_quality["errors"]
        or "missing_appointment_confirmation_boundary" in risky_quality["errors"],
        f"expected appointment boundary error: {risky_quality}",
    )

    safe_plan = copy.deepcopy(risky_plan)
    safe_plan["reply_segments"] = [
        "好的王先生，联系方式和周六下午两点到店时间我记下了。",
        "我先确认车源状态和门店排期，确认好就回您，避免您白跑。",
    ]
    safe_quality = verify_brain_reply_quality(
        normalize_brain_plan(safe_plan),
        current_message=current_message,
        evidence_pack=fake_evidence_pack(include_product=True),
        settings={},
    )
    assert_true(safe_quality["ok"], f"safe appointment boundary wording should pass: {safe_quality}")
    return CaseResult(
        "quality_gate_rejects_appointment_overcommit_without_confirmation",
        True,
        {"risky_errors": risky_quality["errors"], "safe_errors": safe_quality["errors"]},
    )


def check_quality_gate_rejects_trade_in_process_overcommit() -> CaseResult:
    plan = copy.deepcopy(base_plan())
    plan.update(
        {
            "answer_mode": "direct_answer",
            "evidence_used": {"formal_knowledge_ids": ["chejin_acquisition_policy"]},
            "facts_claimed": [],
            "reply_segments": [
                "可以走置换，我们可以上门验车，确认后当天可以打款。",
                "最终收购价验完车就能给您定下来。",
            ],
        }
    )
    quality = verify_brain_reply_quality(
        normalize_brain_plan(plan),
        current_message="我还有台2018年的朗逸想置换，6万多公里，苏州牌，大概流程怎么走？",
        evidence_pack=fake_evidence_pack(include_product=False),
        settings={},
    )
    assert_true(not quality["ok"], f"trade-in overcommit should fail: {quality}")
    assert_true(
        "trade_in_process_overcommit_without_formal_authority" in quality["errors"],
        f"expected trade-in process overcommit error: {quality}",
    )
    return CaseResult("quality_gate_rejects_trade_in_process_overcommit", True, {"errors": quality["errors"]})


def check_quality_gate_rejects_trade_in_final_price_without_boundary() -> CaseResult:
    plan = copy.deepcopy(base_plan())
    plan.update(
        {
            "answer_mode": "direct_answer",
            "evidence_used": {"formal_knowledge_ids": ["chejin_acquisition_policy"]},
            "facts_claimed": [],
            "reply_segments": [
                "可以走置换，先线上初估，再安排验车。",
                "验车后会结合车况、手续和行情出最终收购价。",
            ],
        }
    )
    quality = verify_brain_reply_quality(
        normalize_brain_plan(plan),
        current_message="我还有台2018年的朗逸想置换，6万多公里，苏州牌，大概流程怎么走？",
        evidence_pack=fake_evidence_pack(include_product=False),
        settings={},
    )
    assert_true(not quality["ok"], f"trade-in final price without boundary should fail: {quality}")
    assert_true(
        "trade_in_final_price_missing_verification_boundary" in quality["errors"],
        f"expected trade-in final price boundary error: {quality}",
    )
    return CaseResult("quality_gate_rejects_trade_in_final_price_without_boundary", True, {"errors": quality["errors"]})


def check_quality_gate_allows_bounded_trade_in_process_reply() -> CaseResult:
    plan = copy.deepcopy(base_plan())
    plan.update(
        {
            "answer_mode": "direct_answer",
            "evidence_used": {"formal_knowledge_ids": ["chejin_acquisition_policy"]},
            "facts_claimed": [],
            "reply_segments": [
                "可以走置换，您先发旧车年份、公里数、车况和手续，我这边先做初估。",
                "具体价格要按门店验车和手续核实后确认，我先帮您看个大概区间。",
            ],
        }
    )
    quality = verify_brain_reply_quality(
        normalize_brain_plan(plan),
        current_message="我还有台2018年的朗逸想置换，6万多公里，苏州牌，大概流程怎么走？",
        evidence_pack=fake_evidence_pack(include_product=False),
        settings={},
    )
    assert_true(quality["ok"], f"bounded trade-in process reply should pass: {quality}")
    onsite_plan = copy.deepcopy(base_plan())
    onsite_plan.update(
        {
            "answer_mode": "direct_answer",
            "evidence_used": {"formal_knowledge_ids": ["chejin_acquisition_policy"]},
            "facts_claimed": [],
            "reply_segments": [
                "大概流程是先线上初估，您先把车型配置、过户次数和车况发我。",
                "再按验车和手续核实确认，最终收购价要以现场核验结果为准。",
                "您这台2018年朗逸、6万多公里、苏州牌，我先按这些信息帮您登记初估。",
            ],
        }
    )
    onsite_quality = verify_brain_reply_quality(
        normalize_brain_plan(onsite_plan),
        current_message="我还有台2018年的朗逸想置换，6万多公里，苏州牌，大概流程怎么走？",
        evidence_pack=fake_evidence_pack(include_product=False),
        settings={},
    )
    assert_true(onsite_quality["ok"], f"onsite verification boundary should pass: {onsite_quality}")
    post_check_plan = copy.deepcopy(base_plan())
    post_check_plan.update(
        {
            "answer_mode": "direct_answer",
            "evidence_used": {"formal_knowledge_ids": ["chejin_acquisition_policy"]},
            "facts_claimed": [],
            "reply_segments": [
                "您的2018年朗逸可以先做初步估价。",
                "验车核实后再给最终收购价，您可以先看初估再决定是否到店。",
            ],
        }
    )
    post_check_quality = verify_brain_reply_quality(
        normalize_brain_plan(post_check_plan),
        current_message="如果置换价合适，我今天下午就过来看车，能先留车吗？",
        evidence_pack=fake_evidence_pack(include_product=False),
        settings={},
    )
    assert_true(post_check_quality["ok"], f"post-check final price boundary should pass: {post_check_quality}")
    return CaseResult(
        "quality_gate_allows_bounded_trade_in_process_reply",
        True,
        {"quality": quality, "onsite_quality": onsite_quality, "post_check_quality": post_check_quality},
    )


def check_quality_gate_rejects_overlong_visible_reply() -> CaseResult:
    plan = copy.deepcopy(base_plan())
    plan.update(
        {
            "answer_mode": "recommend_from_catalog",
            "reply_segments": [
                "省油家用这边更建议先看凌派和领动，都是紧凑型自动挡，日常通勤和家用都挺合适。",
                "凌派空间更占优，领动价格更低；另外凌派右前门有轻微钣金，领动左前门更换过，这些都已经明确告知。",
                "自己剐蹭墙一般按单方事故处理，通常看车损险；小剐蹭很多人会先对比维修费、次年保费影响、是否伤到第三方财物、现场照片、维修报价、定损口径、是否需要垫付维修费和后续理赔材料。",
            ],
        }
    )
    quality = verify_brain_reply_quality(
        normalize_brain_plan(plan),
        current_message="我想看省油的家用车，顺便问下如果自己剐蹭墙了保险一般怎么处理？",
        evidence_pack=fake_evidence_pack(include_product=True),
        settings={"quality_reply_max_chars": 120, "quality_segment_soft_max_chars": 96},
    )
    assert_true("reply_too_long" in quality["errors"], f"expected overlong reply error: {quality}")
    return CaseResult("quality_gate_rejects_overlong_visible_reply", True, {"errors": quality["errors"]})


def check_quality_gate_allows_sendable_split_reply_over_soft_total_limit() -> CaseResult:
    plan = copy.deepcopy(base_plan())
    plan.update(
        {
            "answer_mode": "recommend_from_catalog",
            "reply_segments": [
                "你好，欢迎从抖音直播间过来，接娃通勤、预算10万左右的话，我先给您一个初步方向。",
                "偏家用空间这边，可以先看2021款凯美瑞2.0G豪华版，现价8.98万。偏小车好停这边，有2018款大众Polo自动挡，现价4.58万。",
                "这两台一个更偏家用取向，一个更偏城市代步取向，您更看重省油、空间还是好停车，我再顺着给您细聊。",
            ],
        }
    )
    quality = verify_brain_reply_quality(
        normalize_brain_plan(plan),
        current_message="你好，我从抖音直播间来的，家里接娃通勤用，预算十万左右，想先了解下。",
        evidence_pack=fake_evidence_pack(include_product=True),
        settings={
            "quality_reply_max_chars": 120,
            "quality_split_reply_max_chars": 150,
            "quality_segment_soft_max_chars": 96,
        },
    )
    assert_true(quality["ok"], f"sendable split reply should pass soft total limit: {quality}")
    assert_true(
        "split_reply_over_soft_total_limit" in quality["warnings"],
        f"sendable split reply should retain a soft warning: {quality}",
    )
    return CaseResult("quality_gate_allows_sendable_split_reply_over_soft_total_limit", True, {"quality": quality})


def check_quality_gate_allows_mixed_topic_split_reply_budget() -> CaseResult:
    plan = copy.deepcopy(base_plan())
    plan["reply_segments"] = [
        "秦PLUS这台目前8.68万。",
        "通勤省油方向它挺合适，先看这台没问题。",
        "自己剐蹭墙一般先看车损险，小剐蹭可比较维修费和次年保费影响。",
    ]
    quality = verify_brain_reply_quality(
        normalize_brain_plan(plan),
        current_message="秦plus多少钱？顺便问下自己剐蹭墙了保险一般怎么处理？",
        evidence_pack=fake_evidence_pack(include_product=True),
        settings={
            "quality_reply_max_chars": 120,
            "quality_mixed_topic_reply_max_chars": 180,
            "quality_segment_soft_max_chars": 96,
        },
    )
    assert_true(quality["ok"], f"mixed-topic split reply should pass expanded budget: {quality}")
    return CaseResult("quality_gate_allows_mixed_topic_split_reply_budget", True, {"quality": quality})


def check_semantic_reviewer_suspicious_detector() -> CaseResult:
    settings = {"semantic_reviewer_long_reply_chars": 110}
    plan = normalize_brain_plan(base_plan())
    simple_price_plan = copy.deepcopy(base_plan())
    simple_price_plan["reply_segments"] = ["秦PLUS这台目前报价8.68万。"]
    greeting_plan = copy.deepcopy(base_plan())
    greeting_plan.update(
        {
            "answer_mode": "soft_social_reply",
            "evidence_used": {"conversation_fact_ids": ["current_turn"]},
            "facts_claimed": [],
            "reply_segments": ["在的，您说。"],
        }
    )
    short_split_plan = copy.deepcopy(base_plan())
    short_split_plan["reply_segments"] = ["有的，这台目前报价8.68万。", "如果您方便，我再把车况和手续一起发您。"]
    should_skip_simple_price = reviewer_module.should_invoke_semantic_reviewer(
        plan=normalize_brain_plan(simple_price_plan),
        current_message="秦plus多少钱？",
        evidence_pack=fake_evidence_pack(include_product=True),
        deterministic_quality={"ok": True, "errors": [], "warnings": []},
        settings=settings,
    )
    should_review_followup_price = reviewer_module.should_invoke_semantic_reviewer(
        plan=plan,
        current_message="你刚才没回答价格，秦plus多少钱？",
        evidence_pack=fake_evidence_pack(include_product=True),
        deterministic_quality={"ok": True, "errors": [], "warnings": []},
        settings=settings,
    )
    should_skip_greeting = reviewer_module.should_invoke_semantic_reviewer(
        plan=normalize_brain_plan(greeting_plan),
        current_message="你好",
        evidence_pack=fake_evidence_pack(include_product=False),
        deterministic_quality={"ok": True, "errors": [], "warnings": []},
        settings=settings,
    )
    should_skip_short_split = reviewer_module.should_invoke_semantic_reviewer(
        plan=normalize_brain_plan(short_split_plan),
        current_message="秦plus多少钱？",
        evidence_pack=fake_evidence_pack(include_product=True),
        deterministic_quality={"ok": True, "errors": [], "warnings": []},
        settings=settings,
    )
    assert_true(should_skip_simple_price is False, "simple price question should avoid extra reviewer latency")
    assert_true(should_review_followup_price is True, "complaint/follow-up price question should enter semantic review")
    assert_true(should_skip_greeting is False, "plain greeting should not pay semantic reviewer latency")
    assert_true(should_skip_short_split is False, "two concise complete segments should not pay semantic reviewer latency by default")
    return CaseResult(
        "semantic_reviewer_suspicious_detector",
        True,
        {
            "simple_price": should_skip_simple_price,
            "followup_price": should_review_followup_price,
            "greeting": should_skip_greeting,
            "short_split": should_skip_short_split,
        },
    )


def check_semantic_reviewer_unavailable_soft_passes_normal_low_risk() -> CaseResult:
    plan = normalize_brain_plan(base_plan())
    plan["recommended_action"] = "send_reply"
    plan["risk"] = {"risk_level": "normal", "risk_tags": [], "needs_handoff": False}
    deterministic_quality = {"ok": True, "errors": [], "warnings": []}
    assert_true(
        reviewer_module.plan_customer_visible_risk(plan) == "low",
        "normal/routine Brain risk labels should be treated as low customer-visible risk",
    )
    assert_true(
        reviewer_module.plan_allows_unavailable_soft_pass(plan, deterministic_quality=deterministic_quality),
        "reviewer outage should not block deterministic-pass, low-risk send_reply plans",
    )
    medium_plan = copy.deepcopy(plan)
    medium_plan["risk"] = {
        "risk_level": "medium",
        "risk_tags": ["second_candidate_requires_caveat"],
        "needs_handoff": False,
    }
    assert_true(
        reviewer_module.plan_allows_unavailable_soft_pass(medium_plan, deterministic_quality=deterministic_quality),
        "reviewer outage should not block deterministic-pass normal medium-risk plans without hard risk tags",
    )
    risky_plan = copy.deepcopy(plan)
    risky_plan["risk"] = {"risk_level": "normal", "risk_tags": ["finance_commitment"], "needs_handoff": False}
    assert_true(
        not reviewer_module.plan_allows_unavailable_soft_pass(risky_plan, deterministic_quality=deterministic_quality),
        "hard risk tags must not soft-pass reviewer outages",
    )
    failed_quality_plan = copy.deepcopy(plan)
    assert_true(
        not reviewer_module.plan_allows_unavailable_soft_pass(
            failed_quality_plan,
            deterministic_quality={"ok": False, "errors": ["missing_answer"]},
        ),
        "deterministic quality failures must not soft-pass reviewer outages",
    )
    return CaseResult(
        "semantic_reviewer_unavailable_soft_passes_normal_low_risk",
        True,
        {"risk": reviewer_module.plan_customer_visible_risk(plan)},
    )


def check_semantic_reviewer_relaxes_safe_common_sense_boundary_concern() -> CaseResult:
    plan = normalize_brain_plan(
        {
            "can_answer": True,
            "answer_mode": "direct_answer",
            "evidence_used": {"common_sense_topics": ["insurance_self_collision"]},
            "facts_claimed": [],
            "reply_segments": [
                "一般看您有没有车损险，有的话这种自己倒车撞墙通常可以先报保险处理。",
                "但交强险不赔自己车损，最终还得按保单责任和保险公司审核来定。",
            ],
            "recommended_action": "send_reply",
            "risk": {"risk_level": "low", "needs_handoff": False},
            "confidence": 0.86,
        }
    )
    review = reviewer_module.review_brain_reply_semantics(
        settings={
            "quality_gate_v2_enabled": True,
            "semantic_reviewer_enabled": True,
            "semantic_reviewer_mode": "always",
            "semantic_reviewer_result": {
                "status": "ok",
                "verdict": "repair",
                "confidence": 0.88,
                "semantic_errors": [
                    "回复可以更完整一点，直答力度略弱，但没有承诺赔付结果。",
                ],
                "hard_boundary_concerns": ["insurance claim guidance requires formal_knowledge"],
                "repair_instruction": "需要正式保险知识。",
                "customer_visible_risk": "medium",
                "reason": "overly strict reviewer",
            },
        },
        brain_input={
            "current_message": {"clean_text": "我自己倒车撞墙了，这种保险一般赔不赔？"},
            "conversation": {},
            "target": {"target_name": "文件传输助手"},
        },
        evidence_pack={},
        plan=plan,
        deterministic_quality={"ok": True, "errors": [], "warnings": []},
        force=True,
    )
    assert_true(review.get("ok") is True, f"safe common-sense insurance reply should not be overblocked: {review}")
    assert_true(review.get("verdict") == "pass", "relaxed common-sense review should pass")
    assert_true(review.get("common_sense_relaxed_concerns"), "review should audit relaxed concerns")
    assert_true(review.get("common_sense_relaxed_semantic_errors"), "review should audit relaxed semantic suggestions")
    return CaseResult("semantic_reviewer_relaxes_safe_common_sense_boundary_concern", True, {"review": review})


def check_semantic_reviewer_relaxes_bounded_resale_advisory_concern() -> CaseResult:
    plan = normalize_brain_plan(
        {
            "can_answer": True,
            "answer_mode": "compare_options",
            "evidence_used": {
                "product_ids": ["chejin_camry_2021_20g"],
                "conversation_fact_ids": ["recent_product_ids", "last_customer_need_text"],
                "common_sense_topics": ["used_car_resale_value"],
            },
            "facts_claimed": [
                {
                    "fact_type": "product",
                    "value": "2021款丰田凯美瑞2.0G豪华版",
                    "source_level": "product_master",
                    "source_id": "chejin_camry_2021_20g",
                }
            ],
            "reply_segments": [
                "这两台里我更偏向凯美瑞，后面再卖通常更稳一些。",
                "不过二手车最终还得看具体车况、里程和后续市场情况。",
            ],
            "recommended_action": "send_reply",
            "risk": {"risk_level": "low", "needs_handoff": False},
            "confidence": 0.88,
        }
    )
    review = reviewer_module.review_brain_reply_semantics(
        settings={
            "quality_gate_v2_enabled": True,
            "semantic_reviewer_enabled": True,
            "semantic_reviewer_mode": "always",
            "semantic_reviewer_result": {
                "status": "ok",
                "verdict": "repair",
                "confidence": 0.9,
                "semantic_errors": [
                    "“两台”中的另一台未在当前可确认事实上明确，回复直接做比较，存在轻微上下文跳跃",
                    "回答给出倾向但理由偏泛，未处理比较对象不明带来的沟通风险",
                ],
                "hard_boundary_concerns": [
                    "候选回复对二手车转卖保值性作出相对明确判断，但另一台车未由product_master在当前请求中明确落定，存在基于未授权商品对象进行事实性比较的越权疑虑",
                ],
                "repair_instruction": "不要直接对未明确车型下结论。",
                "customer_visible_risk": "medium",
                "reason": "overly strict reviewer",
            },
        },
        brain_input={
            "current_message": {"clean_text": "这两台里哪个后面再卖亏得少点？"},
            "conversation": {
                "context": {
                    "recent_product_ids": ["chejin_camry_2021_20g", "chejin_audi_a4l_2018_40tfsi"],
                    "last_customer_need_text": "接娃通勤，预算十万左右。",
                }
            },
            "target": {"target_name": "文件传输助手"},
        },
        evidence_pack=fake_evidence_pack(include_product=True),
        plan=plan,
        deterministic_quality={"ok": True, "errors": [], "warnings": []},
        force=True,
    )
    assert_true(review.get("ok") is True, f"bounded resale advisory should not be overblocked: {review}")
    assert_true(review.get("verdict") == "pass", "bounded advisory review should pass")
    assert_true(review.get("bounded_advisory_relaxed_concerns"), "review should audit relaxed bounded-advisory concerns")
    assert_true(review.get("bounded_advisory_relaxed_semantic_errors"), "review should audit relaxed bounded-advisory semantic errors")
    return CaseResult("semantic_reviewer_relaxes_bounded_resale_advisory_concern", True, {"review": review})


def check_semantic_reviewer_shadow_does_not_block_brain_reply() -> CaseResult:
    config = base_config(base_plan())
    config["customer_service_brain"].update(
        {
            "mode": "brain_first",
            "semantic_reviewer_mode": "shadow",
            "semantic_reviewer_result": {
                "verdict": "repair",
                "confidence": 0.91,
                "semantic_errors": ["unit_shadow_would_repair"],
                "hard_boundary_concerns": [],
                "repair_instruction": "单元测试：如果不是shadow应交回Brain修复。",
                "customer_visible_risk": "low",
                "reason": "shadow audit only",
            },
        }
    )
    with patched_evidence_pack(fake_evidence_pack(include_product=True)):
        event = brain_module.maybe_run_customer_service_brain(
            config=config,
            target_name="许聪",
            target_state={"conversation_context": {}},
            batch=[{"id": "msg1", "sender": "许聪", "content": "秦plus多少钱"}],
            combined="秦plus多少钱",
            decision=ReplyDecision("", "", False, False, ""),
            reply_text="",
            intent_assist={},
            rag_reply={},
            llm_reply={},
            product_knowledge={},
            data_capture={},
            raw_capture={"conversation": {"conversation_id": "c1", "chat_type": "private"}},
            customer_profile=None,
        )
    review = event.get("quality_gate_v2") or {}
    assert_true(event.get("rule_name") == "customer_service_brain_reply", f"shadow review must not block reply: {event}")
    assert_true(review.get("shadow_verdict") == "repair", f"shadow verdict should be audited: {review}")
    assert_true(review.get("enforced") is False, f"shadow review should not be enforced: {review}")
    return CaseResult("semantic_reviewer_shadow_does_not_block_brain_reply", True, {"review": review})


def check_semantic_reviewer_handoff_suggest_preserves_brain_handoff_reply() -> CaseResult:
    plan = copy.deepcopy(base_plan())
    plan.update(
        {
            "can_answer": False,
            "answer_mode": "handoff",
            "recommended_action": "handoff",
            "evidence_used": {
                "product_ids": ["chejin_qinplus_2022_dmi55"],
                "formal_knowledge_ids": ["chejin_loan_policy"],
                "style_ids": ["customer_service_style_guidelines"],
            },
            "facts_claimed": [
                {
                    "fact_type": "product_name",
                    "value": "客户提到的秦PLUS可匹配到2022款比亚迪秦PLUS DM-i 55KM",
                    "source_level": "product_master",
                    "source_id": "chejin_qinplus_2022_dmi55",
                },
                {
                    "fact_type": "loan",
                    "value": "贷款审批以资方最终审核为准，不能承诺100%通过",
                    "source_level": "formal_knowledge",
                    "source_id": "chejin_loan_policy",
                },
            ],
            "reply_segments": [
                "这个不能先给您包过承诺，贷款还是要以资方最终审核为准。",
                "秦PLUS这台可以做分期，首付、利率和月供要结合车价和征信评估。",
                "您愿意的话，我安排金融专员按正式流程给您评估。",
            ],
            "risk": {"risk_level": "high", "risk_tags": ["finance_commitment"], "needs_handoff": True},
            "confidence": 0.95,
            "reason": "正式金融边界需要人工承接，但可先给出安全说明。",
        }
    )
    config = base_config(plan)
    config["customer_service_brain"].update(
        {
            "mode": "brain_first",
            "semantic_reviewer_mode": "always",
            "semantic_reviewer_result": {
                "verdict": "handoff_suggest",
                "confidence": 0.98,
                "semantic_errors": [],
                "hard_boundary_concerns": ["贷款包过属于金融审批硬边界，需要人工承接"],
                "repair_instruction": "应转人工承接，但候选回复本身没有事实错误。",
                "customer_visible_risk": "high",
                "reason": "候选回复已经明确拒绝越权承诺，并给出人工承接路径。",
            },
        }
    )
    evidence_pack = fake_evidence_pack(include_product=True)
    formal_item = {"id": "chejin_loan_policy", "title": "贷款政策", "answer": "贷款审批以资方最终审核为准，不能承诺100%通过。"}
    evidence_pack["knowledge"]["evidence"]["faq"] = [formal_item]
    evidence_pack["knowledge"]["formal_knowledge"]["faq"] = [formal_item]
    evidence_pack["knowledge"]["safety"] = {"must_handoff": True, "reasons": ["finance_details_need_human"], "allowed_auto_reply": False}
    evidence_pack["safety"] = {"must_handoff": True, "reasons": ["finance_details_need_human"], "allowed_auto_reply": False}
    evidence_pack["audit_summary"]["evidence_ids"].append("faq:chejin_loan_policy")
    with patched_evidence_pack(evidence_pack):
        event = brain_module.maybe_run_customer_service_brain(
            config=config,
            target_name="许聪",
            target_state={"conversation_context": {}},
            batch=[{"id": "msg1", "sender": "许聪", "content": "能不能保证贷款包过"}],
            combined="能不能保证贷款包过",
            decision=ReplyDecision("", "", False, False, ""),
            reply_text="",
            intent_assist={},
            rag_reply={},
            llm_reply={},
            product_knowledge={},
            data_capture={},
            raw_capture={"conversation": {"conversation_id": "c1", "chat_type": "private"}},
            customer_profile=None,
        )
    assert_true(event.get("rule_name") == "customer_service_brain_handoff", f"Brain handoff reply should survive reviewer handoff suggestion: {event}")
    assert_true(event.get("needs_handoff") is True, f"handoff action should be preserved: {event}")
    assert_true(event.get("visible_reply_source") == "brain_plan.reply_segments", f"visible reply must come from Brain: {event}")
    assert_true("包过承诺" in event.get("reply_text", ""), f"specific Brain boundary reply should be visible: {event}")
    assert_true("quality_repair" not in event, f"handoff suggestion should not trigger repair when Brain already chose handoff: {event}")
    soft_pass = event.get("quality_handoff_soft_pass") or {}
    assert_true(soft_pass.get("ok"), f"soft pass should be audited: {event}")
    return CaseResult(
        "semantic_reviewer_handoff_suggest_preserves_brain_handoff_reply",
        True,
        {"rule": event.get("rule_name"), "reply": event.get("reply_text"), "soft_pass": soft_pass},
    )


def check_semantic_reviewer_repair_blocks_when_repair_disabled() -> CaseResult:
    config = base_config(base_plan())
    config["customer_service_brain"].update(
        {
            "mode": "brain_first",
            "quality_repair_enabled": False,
            "semantic_reviewer_mode": "always",
            "semantic_reviewer_result": {
                "verdict": "repair",
                "confidence": 0.94,
                "semantic_errors": ["does_not_answer_current_question"],
                "hard_boundary_concerns": [],
                "repair_instruction": "请直接回答客户当前问价，不要绕到无关问题。",
                "customer_visible_risk": "medium",
                "reason": "unit reviewer repair",
            },
        }
    )
    with patched_evidence_pack(fake_evidence_pack(include_product=True)):
        event = brain_module.maybe_run_customer_service_brain(
            config=config,
            target_name="许聪",
            target_state={"conversation_context": {}},
            batch=[{"id": "msg1", "sender": "许聪", "content": "秦plus多少钱"}],
            combined="秦plus多少钱",
            decision=ReplyDecision("", "", False, False, ""),
            reply_text="",
            intent_assist={},
            rag_reply={},
            llm_reply={},
            product_knowledge={},
            data_capture={},
            raw_capture={"conversation": {"conversation_id": "c1", "chat_type": "private"}},
            customer_profile=None,
        )
    review = event.get("quality_gate_v2") or {}
    repair = event.get("quality_repair") or {}
    assert_true(event.get("rule_name") == "customer_service_brain_safe_fallback", f"semantic repair failure should safe fallback: {event}")
    assert_true(review.get("verdict") == "repair" and review.get("enforced") is True, f"review should be enforced: {review}")
    assert_true(repair.get("error") == "quality_repair_disabled", f"repair should be skipped by config: {repair}")
    return CaseResult(
        "semantic_reviewer_repair_blocks_when_repair_disabled",
        True,
        {"reason": event.get("reason"), "review": review, "repair": repair},
    )


def check_semantic_reviewer_cannot_override_hard_authority_validation() -> CaseResult:
    plan = copy.deepcopy(base_plan())
    plan["facts_claimed"][0]["source_level"] = "ai_experience_pool"
    config = base_config(plan)
    config["customer_service_brain"].update(
        {
            "mode": "brain_first",
            "semantic_reviewer_mode": "always",
            "semantic_reviewer_result": {
                "verdict": "pass",
                "confidence": 0.99,
                "semantic_errors": [],
                "hard_boundary_concerns": [],
                "repair_instruction": "",
                "customer_visible_risk": "low",
                "reason": "unit reviewer pass cannot authorize facts",
            },
        }
    )
    with patched_evidence_pack(fake_evidence_pack(include_product=True)):
        event = brain_module.maybe_run_customer_service_brain(
            config=config,
            target_name="许聪",
            target_state={"conversation_context": {}},
            batch=[{"id": "msg1", "sender": "许聪", "content": "秦plus多少钱"}],
            combined="秦plus多少钱",
            decision=ReplyDecision("", "", False, False, ""),
            reply_text="",
            intent_assist={},
            rag_reply={},
            llm_reply={},
            product_knowledge={},
            data_capture={},
            raw_capture={"conversation": {"conversation_id": "c1", "chat_type": "private"}},
            customer_profile=None,
        )
    validation = event.get("plan_validation") or {}
    assert_true(event.get("reason") == "brain_plan_validation_failed", f"hard validation must run before semantic reviewer: {event}")
    assert_true("quality_gate_v2" not in event, f"semantic reviewer must not run after hard authority failure: {event}")
    assert_true(any("style_only_source_used_as_fact" in item for item in validation.get("errors", [])), f"expected hard source error: {validation}")
    return CaseResult("semantic_reviewer_cannot_override_hard_authority_validation", True, {"validation": validation})


def check_brain_prompt_separates_style_from_content_basis() -> CaseResult:
    evidence_pack = fake_evidence_pack(include_product=True)
    brain_input = brain_module.build_brain_input(
        settings={"mode": "shadow", "max_reply_segments": 3},
        target_name="许聪",
        target_state={"conversation_context": {}},
        batch=[{"id": "msg1", "sender": "许聪", "content": "秦plus多少钱"}],
        combined="秦plus多少钱",
        raw_capture={"conversation": {"conversation_id": "c1", "chat_type": "private"}},
        evidence_pack=evidence_pack,
    )
    prompt_pack = brain_module.build_brain_prompt_pack(settings={}, brain_input=brain_input)
    slim = prompt_pack["user"]["brain_input"]
    content_evidence = slim["content_basis"]["evidence"]
    auxiliary = slim["auxiliary"]
    assert_true("style_examples" not in content_evidence, "style examples must not be part of content basis")
    assert_true(bool(auxiliary.get("style_context")), "style examples should remain available as auxiliary style context")
    return CaseResult(
        "brain_prompt_separates_style_from_content_basis",
        True,
        {"content_basis_keys": sorted(content_evidence.keys()), "style_context_count": len(auxiliary.get("style_context") or [])},
    )


def check_brain_prompt_includes_runtime_principles_without_authorizing_facts() -> CaseResult:
    config = base_config(base_plan())
    config["llm_reply_synthesis"]["identity_guard_enabled"] = True
    settings = brain_module.effective_brain_settings(config)
    evidence_pack = fake_evidence_pack(include_product=True)
    brain_input = brain_module.build_brain_input(
        settings=settings,
        target_name="许聪",
        target_state={"conversation_context": {}},
        batch=[{"id": "msg1", "sender": "许聪", "content": "你是不是AI，秦plus多少钱"}],
        combined="你是不是AI，秦plus多少钱",
        raw_capture={"conversation": {"conversation_id": "c1", "chat_type": "private"}},
        evidence_pack=evidence_pack,
    )
    prompt_pack = brain_module.build_brain_prompt_pack(settings=settings, brain_input=brain_input)
    slim = prompt_pack["user"]["brain_input"]
    principles = slim.get("runtime_principles") or {}
    assert_true("runtime_principles" in prompt_pack["system"], "Brain system prompt should point to runtime principles")
    assert_true(principles.get("authority") == "non_authoritative_runtime_principles", "runtime principles must not authorize facts")
    assert_true("谨慎" in str(principles.get("role_persona") or ""), "persona prompt should be visible to Brain")
    assert_true(
        (principles.get("identity_guard") or {}).get("enabled") is True,
        "Brain should inherit identity_guard_enabled before planning",
    )
    assert_true(
        "不承认AI" in str((principles.get("identity_guard") or {}).get("customer_visible_rule") or ""),
        "Brain should receive the AI-exposure concealment rule",
    )
    assert_true(
        any("product_master" in item for item in principles.get("authority_boundary", []) or []),
        "runtime principles should restate product-master authority without replacing it",
    )
    return CaseResult(
        "brain_prompt_includes_runtime_principles_without_authorizing_facts",
        True,
        {
            "identity_guard": (principles.get("identity_guard") or {}).get("enabled"),
            "authority": principles.get("authority"),
        },
    )


def check_brain_prompt_marks_legacy_candidate_non_authoritative() -> CaseResult:
    settings = brain_module.effective_brain_settings(base_config(base_plan()))
    evidence_pack = fake_evidence_pack(include_product=True)
    evidence_pack["existing_reply"] = {
        "authority": "non_authoritative_legacy_candidate",
        "reply_text": "旧链路候选：直接说可以包过贷款。",
    }
    brain_input = brain_module.build_brain_input(
        settings=settings,
        target_name="许聪",
        target_state={"conversation_context": {}},
        batch=[{"id": "msg1", "sender": "许聪", "content": "秦plus多少钱"}],
        combined="秦plus多少钱",
        raw_capture={"conversation": {"conversation_id": "c1", "chat_type": "private"}},
        evidence_pack=evidence_pack,
    )
    prompt_pack = brain_module.build_brain_prompt_pack(settings=settings, brain_input=brain_input)
    prompt_text = json.dumps(prompt_pack, ensure_ascii=False)
    assert_true("legacy_candidate_policy" in prompt_text, "Brain prompt should include legacy candidate policy")
    assert_true("不能作为上级答案" in prompt_pack["system"], "system prompt should explicitly demote legacy candidates")
    assert_true("包过贷款" not in prompt_text, "legacy candidate draft text should not enter Brain content basis")
    return CaseResult("brain_prompt_marks_legacy_candidate_non_authoritative", True, {})


def check_example_configs_keep_final_visible_micro_verify_required() -> CaseResult:
    paths = [
        APP_ROOT / "configs" / "default.example.json",
        APP_ROOT / "configs" / "jiangsu_chejin_xucong_live.example.json",
    ]
    checked: list[str] = []
    for path in paths:
        config = json.loads(path.read_text(encoding="utf-8"))
        polish = config.get("final_visible_llm_polish") if isinstance(config.get("final_visible_llm_polish"), dict) else {}
        assert_true(polish.get("enabled") is True, f"{path.name} should enable final visible polish by default")
        assert_true(polish.get("required_for_send") is True, f"{path.name} should require final visible polish before send")
        assert_true(
            str(polish.get("brain_source_policy") or "") == "llm_micro_verify",
            f"{path.name} should keep Brain source on micro verify",
        )
        assert_true(
            str(polish.get("handoff_source_policy") or "") == "llm_micro_verify",
            f"{path.name} should keep handoff source on micro verify",
        )
        channels = set(polish.get("micro_verify_source_channels") or [])
        assert_true({"brain", "handoff"} <= channels, f"{path.name} should protect brain and handoff channels")
        checked.append(path.name)
    return CaseResult("example_configs_keep_final_visible_micro_verify_required", True, {"checked": checked})


def check_brain_input_keeps_referenced_context_auxiliary() -> CaseResult:
    settings = brain_module.effective_brain_settings(base_config(base_plan()))
    evidence_pack = fake_evidence_pack(include_product=True)
    brain_input = brain_module.build_brain_input(
        settings=settings,
        target_name="实验订货群",
        target_state={"conversation_context": {}},
        batch=[
            {
                "id": "msg-ref-1",
                "sender": "许聪",
                "content": "这个还有吗",
                "quoted_fragments": [{"text": "张老师：旧消息 试剂盒 9盒 1元", "reason": "quote_line"}],
                "quality_flags": ["quote_contamination"],
            }
        ],
        combined="这个还有吗",
        raw_capture={"conversation": {"conversation_id": "c1", "chat_type": "group"}},
        evidence_pack=evidence_pack,
    )
    current = brain_input["current_message"]
    assert_true(current.get("clean_text") == "这个还有吗", "clean current text should not include quote content")
    assert_true(current.get("referenced_context"), "quote should be preserved as referenced context")
    assert_true(
        "试剂盒" in current["referenced_context"][0]["text"],
        f"referenced context should carry quote text for pronoun understanding: {current}",
    )
    prompt_pack = brain_module.build_brain_prompt_pack(settings=settings, brain_input=brain_input)
    slim_current = prompt_pack["user"]["brain_input"]["current_message"]
    assert_true(
        "referenced_context_policy" in slim_current,
        "prompt should state quote context policy separately from current message",
    )
    return CaseResult(
        "brain_input_keeps_referenced_context_auxiliary",
        True,
        {"referenced_context_count": len(current.get("referenced_context") or [])},
    )


def check_brain_prompt_compacts_large_context_under_timeout_budget() -> CaseResult:
    settings = brain_module.effective_brain_settings(base_config(base_plan()))
    pack = fake_evidence_pack(include_product=True)
    long_text = "这是一段用于模拟历史聊天和知识命中的长文本。" * 120
    pack["conversation"]["history_text"] = long_text
    pack["conversation"]["conversation_summary"] = long_text
    pack["conversation"]["current_batch_text"] = "客户问：我想买MPV，家用商务都能兼顾，预算二十万左右。"
    pack["knowledge"]["product_master"]["items"] = [
        {
            "id": f"product_{idx}",
            "name": f"测试车型{idx}",
            "price": 8.0 + idx,
            "mileage": f"{idx}.2万公里",
            "description": long_text,
            "shipping": long_text,
            "warranty": long_text,
            "reply_templates": {"recommend": long_text, "price": long_text},
            "authority_level": "product_master",
        }
        for idx in range(18)
    ]
    pack["knowledge"]["formal_knowledge"]["faq"] = [
        {"id": f"faq_{idx}", "question": "能贷款吗", "answer": long_text}
        for idx in range(12)
    ]
    pack["knowledge"]["evidence"]["style_examples"] = [
        {"id": f"style_{idx}", "customer_message": "预算多少", "service_reply": long_text}
        for idx in range(8)
    ]
    pack["rag"] = {"hits": [{"id": f"rag_{idx}", "text": long_text} for idx in range(12)]}
    brain_input = brain_module.build_brain_input(
        settings=settings,
        target_name="许聪",
        target_state={"conversation_context": {}},
        batch=[{"id": "msg-long", "sender": "许聪", "content": "MPV有合适的吗"}],
        combined="MPV有合适的吗",
        raw_capture={"conversation": {"conversation_id": "c1", "chat_type": "private"}},
        evidence_pack=pack,
    )
    prompt_pack = brain_module.build_brain_prompt_pack(settings=settings, brain_input=brain_input)
    estimate = brain_module.estimate_prompt_pack(prompt_pack)
    assert_true(
        estimate["prompt_chars"] < 9000,
        f"Brain prompt should stay compact enough to avoid local timeout pressure: {estimate}",
    )
    slim = prompt_pack["user"]["brain_input"]
    assert_true(len(slim["content_basis"]["product_master"]["items"]) == 5, "product master prompt items should be capped")
    product_prompt_text = json.dumps(slim["content_basis"]["product_master"]["items"], ensure_ascii=False)
    assert_true("description" not in product_prompt_text, "product prompt should not carry bulky description fields")
    assert_true("reply_templates" not in product_prompt_text, "product prompt should not carry template-sized reply fields")
    assert_true("shipping" not in product_prompt_text and "warranty" not in product_prompt_text, "product prompt should omit irrelevant long policy fields")
    assert_true(len(slim["auxiliary"]["rag"]["hits"]) == 1, "RAG prompt hits should be capped")
    return CaseResult("brain_prompt_compacts_large_context_under_timeout_budget", True, {"prompt_estimate": estimate})


def check_brain_timeout_budget_scales_with_prompt_pressure() -> CaseResult:
    settings = brain_module.effective_brain_settings(
        {
            "customer_service_brain": {
                "timeout_seconds": 35,
                "large_prompt_timeout_seconds": 60,
                "very_large_prompt_timeout_seconds": 90,
                "fallback_timeout_seconds": 45,
                "large_prompt_timeout_threshold_chars": 5000,
                "very_large_prompt_timeout_threshold_chars": 12000,
                "quality_repair_timeout_seconds": 12,
            }
        }
    )
    short_timeout = brain_module.resolve_brain_llm_timeout(settings, {"prompt_chars": 3200})
    large_timeout = brain_module.resolve_brain_llm_timeout(settings, {"prompt_chars": 6200})
    very_large_timeout = brain_module.resolve_brain_llm_timeout(settings, {"prompt_chars": 4200, "initial_prompt_chars": 13000})
    repair_short_timeout = brain_module.resolve_brain_llm_timeout(
        settings,
        {"prompt_chars": 3200},
        base_key="quality_repair_timeout_seconds",
    )
    repair_large_timeout = brain_module.resolve_brain_llm_timeout(
        settings,
        {"prompt_chars": 6200},
        base_key="quality_repair_timeout_seconds",
    )
    fallback_timeout = brain_module.resolve_brain_fallback_timeout(settings, very_large_timeout)
    assert_true(short_timeout == 35, f"short Brain prompt should keep fast budget, got {short_timeout}")
    assert_true(large_timeout == 60, f"large Brain prompt should use 60s budget, got {large_timeout}")
    assert_true(very_large_timeout == 90, f"very large or pre-compression-heavy Brain prompt should use 90s budget, got {very_large_timeout}")
    assert_true(repair_short_timeout == 12, f"short repair prompt should keep repair budget, got {repair_short_timeout}")
    assert_true(repair_large_timeout == 60, f"large repair prompt should inherit large budget, got {repair_large_timeout}")
    assert_true(fallback_timeout == 45, f"fallback should have independent shorter budget, got {fallback_timeout}")
    return CaseResult(
        "brain_timeout_budget_scales_with_prompt_pressure",
        True,
        {
            "short_timeout": short_timeout,
            "large_timeout": large_timeout,
            "very_large_timeout": very_large_timeout,
            "repair_short_timeout": repair_short_timeout,
            "repair_large_timeout": repair_large_timeout,
            "fallback_timeout": fallback_timeout,
        },
    )


def check_repair_prompt_preserves_authority_boundaries() -> CaseResult:
    settings = brain_module.effective_brain_settings(base_config(base_plan()))
    evidence_pack = fake_evidence_pack(include_product=True)
    brain_input = brain_module.build_brain_input(
        settings=settings,
        target_name="许聪",
        target_state={"conversation_context": {}},
        batch=[{"id": "msg1", "sender": "许聪", "content": "秦plus多少钱"}],
        combined="秦plus多少钱",
        raw_capture={"conversation": {"conversation_id": "c1", "chat_type": "private"}},
        evidence_pack=evidence_pack,
    )
    quality = {
        "ok": False,
        "errors": ["missing_direct_price_response"],
        "warnings": [],
        "repair_instruction": "需要正面回答价格。",
    }
    prompt_pack = brain_module.build_brain_repair_prompt_pack(
        settings=settings,
        brain_input=brain_input,
        plan=normalize_brain_plan(base_plan()),
        quality=quality,
    )
    system = prompt_pack["system"]
    assert_true("product_master" in system, "repair prompt should preserve product-master authority")
    assert_true("formal_knowledge" in system, "repair prompt should preserve formal-knowledge authority")
    assert_true("catalog_candidates" in system and "未在本轮证据中出现的商品" in system, "repair prompt should restrict replacement products to current evidence")
    assert_true("AI经验池" in system and "不能授权事实" in system, "repair prompt should keep AI experience pool non-authoritative")
    return CaseResult("repair_prompt_preserves_authority_boundaries", True, {"system_chars": len(system)})


def check_shadow_non_blocking_defers_without_llm() -> CaseResult:
    plan = base_plan()
    with patched_evidence_pack_failure():
        event = run_brain(plan, blocking_shadow_enabled=False)
    assert_true(event["enabled"], "brain should be enabled")
    assert_true(event.get("shadow_mode") is True, "shadow marker should remain visible")
    assert_true(event.get("deferred") is True, f"non-blocking shadow should defer: {event}")
    assert_true(event.get("applied") is False, f"non-blocking shadow must not produce a live reply: {event}")
    assert_true(event.get("adoptable") is False, f"non-blocking shadow must not be adoptable: {event}")
    assert_true(event.get("reason") == "shadow_non_blocking_deferred", f"unexpected reason: {event}")
    assert_true(event.get("duration_seconds", 999) < 0.05, f"shadow deferral should be fast: {event}")
    return CaseResult("shadow_non_blocking_defers_without_llm", True, {"duration": event.get("duration_seconds")})


def check_shadow_brain_runner_passes_guard() -> CaseResult:
    plan = base_plan()
    with patched_evidence_pack(fake_evidence_pack(include_product=True)):
        event = run_brain(plan)
    assert_true(event["enabled"], "brain should be enabled")
    assert_true(event["applied"], f"brain should pass guard: {event}")
    assert_true(event.get("shadow_mode") is True, "default test mode should be shadow")
    assert_true(event.get("adoptable") is False, "shadow should not be adoptable")
    assert_true("8.68万" in event.get("reply_text", ""), "brain reply should be available for audit")
    sources = event.get("authority_sources") if isinstance(event.get("authority_sources"), dict) else {}
    assert_true(
        "chejin_qinplus_2022_dmi55" in sources.get("product_master", []),
        f"authority sources should include product master id: {event}",
    )
    return CaseResult("shadow_brain_runner_passes_guard", True, {"reason": event.get("reason"), "duration": event.get("duration_seconds")})


def check_brain_runner_records_stage_timings() -> CaseResult:
    plan = base_plan()
    with patched_evidence_pack(fake_evidence_pack(include_product=True)):
        event = run_brain(plan)
    timings = event.get("stage_timings") if isinstance(event.get("stage_timings"), dict) else {}
    timeline = event.get("stage_timeline") if isinstance(event.get("stage_timeline"), dict) else {}
    trace = event.get("latency_trace") if isinstance(event.get("latency_trace"), dict) else {}
    required = {
        "evidence_pack",
        "brain_input",
        "brain_llm",
        "plan_normalization_validation",
        "deterministic_quality",
        "guard",
        "total",
    }
    missing = sorted(required - set(timings))
    assert_true(not missing, f"Brain audit should include stage timings, missing={missing}: {event}")
    for key in required:
        assert_true(isinstance(timings.get(key), (int, float)), f"timing {key} should be numeric: {timings}")
        assert_true(float(timings.get(key) or 0) >= 0, f"timing {key} should be non-negative: {timings}")
    assert_true(
        float(timings.get("total") or 0) >= float(timings.get("brain_llm") or 0),
        f"total should cover Brain LLM: {timings}",
    )
    for key in required - {"total"}:
        item = timeline.get(key) if isinstance(timeline.get(key), dict) else {}
        assert_true(item.get("started_at") and item.get("finished_at"), f"timeline {key} should have start/end: {timeline}")
        assert_true(trace.get(f"{key}_started_at") and trace.get(f"{key}_finished_at"), f"trace should include {key}: {trace}")
    assert_true(trace.get("brain_llm_duration_seconds") is not None, f"trace should include Brain LLM duration: {trace}")
    return CaseResult("brain_runner_records_stage_timings", True, {"timings": timings, "trace": trace})


def check_brain_runner_rejects_quality_failed_plan() -> CaseResult:
    plan = copy.deepcopy(base_plan())
    plan["reply_segments"] = ["我先帮您看看，稍等。"]
    with patched_evidence_pack(fake_evidence_pack(include_product=True)):
        event = run_brain(plan)
    assert_true(not event.get("applied"), f"quality-failed BrainPlan must not apply: {event}")
    assert_true(event.get("reason") == "brain_quality_verification_failed", f"expected quality failure: {event}")
    errors = (event.get("quality_verification") or {}).get("errors", [])
    assert_true("missing_direct_price_response" in errors, f"expected quality errors in audit: {event}")
    return CaseResult("brain_runner_rejects_quality_failed_plan", True, {"reason": event.get("reason"), "errors": errors})


def check_repaired_deterministic_quality_soft_pass_requires_missing_context_anchor() -> CaseResult:
    plan = copy.deepcopy(base_plan())
    plan["evidence_used"] = {"product_ids": ["chejin_qinplus_2022_dmi55"], "conversation_fact_ids": []}
    quality = {
        "ok": False,
        "errors": ["relative_context_product_drift"],
        "warnings": [],
        "repair_instruction": "Brain 已修复后，确定性质量门仍缺少可靠会话锚。",
    }
    no_anchor_pack = fake_evidence_pack(include_product=True)
    soft = brain_module.repaired_deterministic_quality_soft_pass_decision(
        settings={},
        plan=plan,
        quality=quality,
        evidence_pack=no_anchor_pack,
    )
    assert_true(soft.get("ok"), f"context uncertainty without anchor should defer to guard after repair: {soft}")

    anchored_pack = fake_evidence_pack(include_product=True)
    anchored_pack["conversation"]["context"] = {"last_product_id": "chejin_camry_2021_20g"}
    blocked = brain_module.repaired_deterministic_quality_soft_pass_decision(
        settings={},
        plan=plan,
        quality=quality,
        evidence_pack=anchored_pack,
    )
    assert_true(not blocked.get("ok"), f"known context anchor must not be soft-passed: {blocked}")
    assert_true(
        blocked.get("reason") == "known_context_anchor_must_be_repaired_by_brain",
        f"unexpected block reason: {blocked}",
    )
    return CaseResult(
        "repaired_deterministic_quality_soft_pass_requires_missing_context_anchor",
        True,
        {"soft": soft, "blocked": blocked},
    )


def check_brain_runner_soft_passes_repaired_semantic_minor_nits() -> CaseResult:
    plan = copy.deepcopy(base_plan())
    plan.update(
        {
            "answer_mode": "recommend_from_catalog",
            "understanding": {"intent": "预算内家用代步推荐", "must": "9万内、自动挡、最好倒车影像"},
            "facts_claimed": [
                {
                    "fact_type": "price",
                    "value": "8.68万",
                    "source_level": "product_master",
                    "source_id": "chejin_qinplus_2022_dmi55",
                }
            ],
            "reply_segments": ["按您的预算内，我建议先看秦PLUS，报价8.68万，自动挡，通勤代步比较贴近。"],
        }
    )
    repaired_plan = copy.deepcopy(plan)
    repaired_plan["reply_segments"] = [
        "按您的预算内，我建议先看秦PLUS，报价8.68万，自动挡，接送孩子和买菜都比较贴近日常用车。",
        "倒车影像这项商品资料没写明，我会按实车配置再帮您核一下。",
    ]
    config = base_config(plan)
    config["customer_service_brain"].update(
        {
            "semantic_reviewer_mode": "always",
            "semantic_reviewer_cache_enabled": False,
            "semantic_reviewer_result": {
                "status": "ok",
                "verdict": "repair",
                "confidence": 0.72,
                "semantic_errors": ["推荐逻辑还可以更聚焦，倒车影像偏好可表达得更完整。"],
                "hard_boundary_concerns": [],
                "repair_instruction": "保持商品库事实不变，补齐倒车影像边界说明。",
                "customer_visible_risk": "low",
                "reason": "minor_focus_nit",
            },
        }
    )
    with patched_evidence_pack(fake_evidence_pack(include_product=True)), patched_brain_repair(repaired_plan):
        event = brain_module.maybe_run_customer_service_brain(
            config=config,
            target_name="许聪",
            target_state={"conversation_context": {}},
            batch=[{"id": "msg1", "sender": "许聪", "content": "预算9万以内自动挡，最好倒车影像，有什么推荐"}],
            combined="预算9万以内自动挡，最好倒车影像，有什么推荐",
            decision=ReplyDecision("", "", False, False, ""),
            reply_text="",
            intent_assist={},
            rag_reply={},
            llm_reply={},
            product_knowledge={},
            data_capture={},
            raw_capture={"conversation": {"conversation_id": "c1", "chat_type": "private"}},
            customer_profile=None,
        )
    assert_true(event.get("applied"), f"repaired actionable Brain reply should apply: {event}")
    assert_true(event.get("rule_name") == "customer_service_brain_reply", f"expected Brain reply: {event}")
    assert_true(event.get("repaired_quality_soft_pass", {}).get("ok"), f"expected post-repair soft pass audit: {event}")
    assert_true("秦PLUS" in event.get("reply_text", ""), f"reply should keep actionable product answer: {event}")
    assert_true("马上回复" not in event.get("reply_text", ""), f"reply must not degrade to generic stall: {event}")
    return CaseResult(
        "brain_runner_soft_passes_repaired_semantic_minor_nits",
        True,
        {"reason": event.get("reason"), "soft_pass": event.get("repaired_quality_soft_pass")},
    )


def check_brain_runner_coerces_usable_fallback_existing_plan() -> CaseResult:
    plan = copy.deepcopy(base_plan())
    plan["answer_mode"] = "fallback_existing"
    plan["recommended_action"] = "fallback_existing"
    with patched_evidence_pack(fake_evidence_pack(include_product=True)):
        event = run_brain(plan)
    assert_true(event.get("applied"), f"usable fallback_existing BrainPlan should apply after coercion: {event}")
    assert_true(event.get("rule_name") == "customer_service_brain_reply", f"coerced plan should send Brain reply: {event}")
    assert_true(event.get("needs_handoff") is False, f"coerced plan should not need handoff: {event}")
    assert_true(event.get("brain_fallback_existing_coerced"), f"audit should record coercion: {event}")
    return CaseResult(
        "brain_runner_coerces_usable_fallback_existing_plan",
        True,
        {"reason": event.get("reason"), "coerced": event.get("brain_fallback_existing_coerced")},
    )


def check_brain_candidate_allows_safe_uncertain_send() -> CaseResult:
    plan = normalize_brain_plan(
        {
            **base_plan(),
            "can_answer": False,
            "answer_mode": "ask_clarifying_question",
            "recommended_action": "send_reply",
            "risk": {"risk_level": "low", "needs_handoff": False, "risk_tags": ["missing_product_fact"]},
            "evidence_used": {
                "product_ids": ["chejin_tiguanl_2021_330tsi"],
                "conversation_fact_ids": ["last_product_id"],
                "common_sense_topics": ["装载场景需要核实座椅放倒"],
            },
            "reply_segments": [
                "你这套器材确实更看重第二排放倒和装载灵活性。",
                "这台我暂时没看到座椅放倒的权威信息，不能随口定；我先按装载实用方向继续给你筛。",
            ],
        }
    )
    candidate = brain_plan_to_guard_candidate(plan)
    assert_true(candidate.get("can_answer") is True, f"safe uncertain send should remain answerable: {candidate}")
    assert_true(candidate.get("recommended_action") == "send_reply", f"action should remain send_reply: {candidate}")

    handoff_plan = normalize_brain_plan(
        {
            **base_plan(),
            "can_answer": False,
            "answer_mode": "handoff",
            "recommended_action": "handoff",
            "risk": {"risk_level": "high", "needs_handoff": True},
            "reply_segments": ["这个需要负责人确认。"],
        }
    )
    handoff_candidate = brain_plan_to_guard_candidate(handoff_plan)
    assert_true(handoff_candidate.get("can_answer") is False, f"real handoff should not be softened: {handoff_candidate}")
    assert_true(handoff_candidate.get("needs_handoff") is True, f"real handoff should stay handoff: {handoff_candidate}")
    return CaseResult("brain_candidate_allows_safe_uncertain_send", True, {"candidate": candidate})


def check_guard_downgrades_safe_uncertain_handoff_plan() -> CaseResult:
    plan = normalize_brain_plan(
        {
            **base_plan(),
            "can_answer": False,
            "answer_mode": "handoff",
            "recommended_action": "handoff",
            "risk": {
                "risk_level": "high",
                "needs_handoff": True,
                "risk_tags": ["no_authoritative_product_specs", "cannot_confirm_loading_fit"],
            },
            "evidence_used": {
                "product_ids": ["chejin_qinplus_2022_dmi55"],
                "conversation_fact_ids": ["last_product_id", "last_customer_need_text"],
            },
            "facts_claimed": [
                {
                    "fact_type": "product_name",
                    "value": "2022款比亚迪秦PLUS DM-i 55KM",
                    "source_level": "product_master",
                    "source_id": "chejin_qinplus_2022_dmi55",
                }
            ],
            "reply_segments": [
                "这台秦PLUS我这边暂时查不到第二排放倒方式和装载尺寸。",
                "能不能装下这批器材，最好按实车尺寸核一下或现场试装。"
            ],
        }
    )
    assert_true(
        brain_module.brain_plan_allows_soft_evidence_override(plan),
        f"safe uncertain handoff plan should be eligible for soft evidence override: {plan}",
    )
    pack = fake_evidence_pack(include_product=True)
    pack["safety"] = {"must_handoff": True, "reasons": ["no_relevant_business_evidence"], "allowed_auto_reply": False}
    pack["knowledge"]["safety"] = dict(pack["safety"])
    pack["intent_tags"] = ["product"]
    pack["knowledge"]["intent_tags"] = ["product"]
    guard = guard_synthesized_reply(
        candidate=brain_plan_to_guard_candidate(plan),
        evidence_pack=pack,
        settings={"require_evidence": True, "advisor_mode": "clear_common_sense_recommendation"},
    )
    assert_true(guard.get("allowed") is True and guard.get("action") == "send_reply", f"guard should downgrade safe uncertainty: {guard}")
    assert_true("实车" in str(guard.get("reply") or ""), f"reply should preserve practical guidance: {guard}")
    return CaseResult("guard_downgrades_safe_uncertain_handoff_plan", True, {"guard": guard})


def check_safe_uncertain_reply_budget_restatement_needs_no_product_fact() -> CaseResult:
    plan = normalize_brain_plan(
        {
            "can_answer": False,
            "answer_mode": "ask_clarifying_question",
            "evidence_used": {
                "conversation_fact_ids": [
                    "last_customer_need_text",
                    "last_product_id",
                    "last_product_price",
                    "recent_product_ids",
                ]
            },
            "facts_claimed": [],
            "reply_segments": [
                "这项我先不敢凭印象答，第二排能不能放倒得按具体车型配置核实。",
                "你刚提到的是途观L吗？我确认后，顺带按16万内再给你两三个更能装的方向。",
            ],
            "risk": {
                "risk_level": "medium",
                "risk_tags": ["no_authoritative_product_fact", "avoid_unverified_vehicle_config"],
                "needs_handoff": False,
            },
            "recommended_action": "send_reply",
            "confidence": 0.9,
            "reason": "No authoritative vehicle configuration fact, but customer budget restatement is not a product quote.",
        }
    )
    validation = validate_brain_plan(plan, require_fact_claims=True)
    candidate = brain_plan_to_guard_candidate(plan)
    assert_true(validation["ok"], f"budget restatement in safe uncertain reply should not require product fact claims: {validation}")
    assert_true(candidate["can_answer"] is True, f"safe uncertain send should be adopted as customer-visible clarification: {candidate}")
    return CaseResult(
        "safe_uncertain_reply_budget_restatement_needs_no_product_fact",
        True,
        {"validation": validation, "candidate": candidate},
    )


def check_uncertainty_boundary_condition_claim_is_not_product_fact() -> CaseResult:
    plan = normalize_brain_plan(
        {
            "can_answer": True,
            "answer_mode": "direct_answer",
            "evidence_used": {
                "product_ids": ["chejin_tiguanl_2021_330tsi"],
                "formal_knowledge_ids": ["chejin_inspection_policy"],
                "conversation_fact_ids": ["last_product_id"],
            },
            "facts_claimed": [
                {
                    "fact_type": "disclosure_policy",
                    "value": "在售车辆会如实告知补漆、钣金和更换件情况",
                    "source_level": "formal_knowledge",
                    "source_id": "chejin_inspection_policy",
                },
                {
                    "fact_type": "condition",
                    "value": "这台途观L的具体补漆和换件明细需要按检测报告核实",
                    "source_level": "current_conversation_fact",
                    "source_id": "last_product_id",
                },
            ],
            "reply_segments": [
                "会说清楚的，补漆、钣金和更换件情况都会如实告知。",
                "你刚问的这台途观L，具体补漆和换件明细我需要按检测报告给你核实。",
            ],
            "risk": {"needs_handoff": False},
            "recommended_action": "send_reply",
            "confidence": 0.9,
            "reason": "Unverified detail boundary is not a product condition fact.",
        }
    )
    fact_types = [fact.get("fact_type") for fact in plan.get("facts_claimed", [])]
    validation = validate_brain_plan(plan, require_fact_claims=True)
    assert_true("condition" not in fact_types, f"uncertainty boundary should not remain as condition fact: {plan}")
    assert_true(validation["ok"], f"remaining formal disclosure fact should validate: {validation}")

    unsafe = normalize_brain_plan(
        {
            **base_plan(),
            "evidence_used": {"conversation_fact_ids": ["last_product_id"]},
            "facts_claimed": [
                {
                    "fact_type": "condition",
                    "value": "这台途观L原版原漆",
                    "source_level": "current_conversation_fact",
                    "source_id": "last_product_id",
                }
            ],
            "reply_segments": ["这台途观L原版原漆。"],
        }
    )
    unsafe_validation = validate_brain_plan(unsafe, require_fact_claims=True)
    assert_true(
        "product_master_fact_without_product_master_authority:condition" in unsafe_validation["errors"],
        f"assertive condition fact must still require product master: {unsafe_validation}",
    )
    return CaseResult(
        "uncertainty_boundary_condition_claim_is_not_product_fact",
        True,
        {"fact_types": fact_types, "validation": validation, "unsafe_validation": unsafe_validation},
    )


def check_brain_canonicalizes_context_product_price_to_product_master() -> CaseResult:
    plan = normalize_brain_plan(
        {
            "can_answer": True,
            "answer_mode": "recommend_from_catalog",
            "evidence_used": {
                "product_ids": ["chejin_qinplus_2022_dmi55"],
                "conversation_fact_ids": ["last_product_price"],
            },
            "facts_claimed": [
                {
                    "fact_type": "price",
                    "value": "8.68",
                    "source_level": "current_conversation_fact",
                    "source_id": "last_product_price",
                }
            ],
            "reply_segments": ["秦PLUS这台8.68万，适合通勤。"],
            "risk": {"needs_handoff": False},
            "recommended_action": "send_reply",
            "confidence": 0.85,
            "reason": "context price originated from product master",
        }
    )
    pack = fake_evidence_pack(include_product=True)
    pack["conversation"]["context"] = {
        "last_product_id": "chejin_qinplus_2022_dmi55",
        "last_product_price": 8.68,
        "recent_product_ids": ["chejin_qinplus_2022_dmi55"],
    }
    changed = brain_module.canonicalize_conversation_product_fact_sources(plan, pack)
    validation = validate_brain_plan(plan, require_fact_claims=True)
    evidence_validation = brain_module.validate_plan_against_evidence(plan, pack)
    assert_true(changed and changed[0]["source_id"] == "chejin_qinplus_2022_dmi55", f"price fact should be canonicalized: {changed}")
    assert_true(plan["facts_claimed"][0]["source_level"] == "product_master", f"source should be product_master: {plan}")
    assert_true(validation["ok"], f"canonicalized plan should validate: {validation}")
    assert_true(evidence_validation["ok"], f"canonicalized source should be in evidence: {evidence_validation}")
    return CaseResult(
        "brain_canonicalizes_context_product_price_to_product_master",
        True,
        {"changed": changed, "validation": validation, "evidence_validation": evidence_validation},
    )


def check_brain_rehydrates_context_product_fact_to_product_master() -> CaseResult:
    plan = normalize_brain_plan(
        {
            "can_answer": True,
            "answer_mode": "direct_answer",
            "evidence_used": {
                "conversation_fact_ids": ["last_product_id", "last_product_price"],
            },
            "facts_claimed": [
                {
                    "fact_type": "price",
                    "value": "8.68",
                    "source_level": "current_conversation_fact",
                    "source_id": "last_product_price",
                }
            ],
            "reply_segments": ["秦PLUS这台8.68万，预算内可以先看。"],
            "risk": {"needs_handoff": False},
            "recommended_action": "send_reply",
            "confidence": 0.86,
            "reason": "context reference should be traced back to product master",
        }
    )
    pack = fake_evidence_pack(include_product=False)
    pack["conversation"]["context"] = {
        "last_product_id": "chejin_qinplus_2022_dmi55",
        "last_product_price": 8.68,
        "recent_product_ids": ["chejin_qinplus_2022_dmi55"],
    }
    with tenant_context("chejin"):
        hydrated = brain_module.augment_evidence_pack_with_plan_product_ids(pack, plan)
        changed = brain_module.canonicalize_conversation_product_fact_sources(plan, pack)
        validation = validate_brain_plan(plan, require_fact_claims=True)
        evidence_validation = brain_module.validate_plan_against_evidence(plan, pack)
    assert_true(
        hydrated == ["chejin_qinplus_2022_dmi55"],
        f"context product id should be rehydrated from product master before authority checks: {hydrated}",
    )
    assert_true(changed and changed[0]["source_id"] == "chejin_qinplus_2022_dmi55", f"context fact should canonicalize: {changed}")
    assert_true(validation["ok"], f"rehydrated context fact should validate: {validation}")
    assert_true(evidence_validation["ok"], f"rehydrated source should exist in evidence: {evidence_validation}")
    return CaseResult(
        "brain_rehydrates_context_product_fact_to_product_master",
        True,
        {"hydrated": hydrated, "changed": changed, "validation": validation, "evidence_validation": evidence_validation},
    )


def check_brain_canonicalizes_year_model_price_text_to_product_master() -> CaseResult:
    plan = normalize_brain_plan(
        {
            "can_answer": True,
            "answer_mode": "direct_answer",
            "evidence_used": {
                "product_ids": ["chejin_tiguanl_2021_330tsi"],
                "formal_knowledge_ids": ["payment_policy"],
                "conversation_fact_ids": ["last_product_id", "last_product_price"],
            },
            "facts_claimed": [
                {
                    "fact_type": "price",
                    "value": "2021款大众途观L 330TSI价格15.8万",
                    "source_level": "current_conversation_fact",
                    "source_id": "last_product_price",
                }
            ],
            "reply_segments": ["按这台15.8万算，首付一半大概7.9万，剩下走贷款审核。"],
            "risk": {"needs_handoff": False},
            "recommended_action": "send_reply",
            "confidence": 0.9,
            "reason": "context price originated from product master, despite year/model numbers in the claim text",
        }
    )
    product = {
        "id": "chejin_tiguanl_2021_330tsi",
        "name": "2021款大众途观L 330TSI 自动两驱智享版",
        "aliases": ["途观L", "大众途观"],
        "price": 15.8,
        "authority_level": "product_master",
    }
    pack = fake_evidence_pack(include_product=False)
    pack["conversation"]["context"] = {
        "last_product_id": "chejin_tiguanl_2021_330tsi",
        "last_product_price": 15.8,
        "recent_product_ids": ["chejin_tiguanl_2021_330tsi"],
    }
    knowledge = pack["knowledge"]
    evidence = knowledge["evidence"]
    evidence["products"] = [product]
    evidence["catalog_candidates"] = [product]
    knowledge["product_master"]["items"] = [product]
    pack["audit_summary"]["evidence_ids"] = ["product:chejin_tiguanl_2021_330tsi"]
    changed = brain_module.canonicalize_conversation_product_fact_sources(plan, pack)
    validation = validate_brain_plan(plan, require_fact_claims=True)
    evidence_validation = brain_module.validate_plan_against_evidence(plan, pack)
    assert_true(changed and changed[0]["source_id"] == "chejin_tiguanl_2021_330tsi", f"year/model price text should be canonicalized: {changed}")
    assert_true(plan["facts_claimed"][0]["source_level"] == "product_master", f"source should be product_master: {plan}")
    assert_true(validation["ok"], f"canonicalized plan should validate: {validation}")
    assert_true(evidence_validation["ok"], f"canonicalized source should be in evidence: {evidence_validation}")
    return CaseResult(
        "brain_canonicalizes_year_model_price_text_to_product_master",
        True,
        {"changed": changed, "validation": validation, "evidence_validation": evidence_validation},
    )


def check_guard_rejects_unsupported_price_without_product_master() -> CaseResult:
    plan = base_plan()
    with patched_evidence_pack(fake_evidence_pack(include_product=False)):
        event = run_brain(plan)
    assert_true(not event.get("applied"), f"price without product evidence must be rejected: {event}")
    errors = (event.get("plan_validation") or {}).get("errors", [])
    assert_true(any("product_fact_source_not_in_evidence" in str(item) for item in errors), f"expected source-id evidence rejection: {event}")
    return CaseResult("guard_rejects_unsupported_price_without_product_master", True, {"reason": event.get("reason"), "errors": errors})


def check_guard_allows_customer_budget_restatement_without_product_master() -> CaseResult:
    pack = fake_evidence_pack(include_product=False)
    pack["current_message"] = "你好，我从直播间来的，家里接娃通勤用，预算十万左右，想先了解下。"
    pack["conversation"]["current_batch_text"] = "[客户] 你好，我从直播间来的，家里接娃通勤用，预算十万左右，想先了解下。"

    restatement = validate_reply_fact_authority("10万左右可以先按省油、省心、好开的家用方向筛。", pack)
    assert_true(restatement.get("ok"), f"customer budget restatement should not be treated as a new price fact: {restatement}")

    concrete_quote = validate_reply_fact_authority("这台车现在8.68万，适合您看。", pack)
    assert_true(not concrete_quote.get("ok"), f"new concrete quote still requires product master evidence: {concrete_quote}")
    return CaseResult(
        "guard_allows_customer_budget_restatement_without_product_master",
        True,
        {"restatement": restatement, "concrete_quote": concrete_quote},
    )


def check_guard_allows_detail_topic_clarification_without_fact_claim() -> CaseResult:
    empty_pack = fake_evidence_pack(include_product=False)
    clarification = validate_reply_fact_authority(
        "在的，您说。您刚刚是想接着看MPV，还是先问那台车的公里数和颜色？",
        empty_pack,
    )
    assert_true(clarification.get("ok"), f"detail-topic clarification should not be treated as a product fact: {clarification}")

    concrete_claim = validate_reply_fact_authority("这台表显4.8万公里，车况透明，到店可看。", empty_pack)
    assert_true(not concrete_claim.get("ok"), f"concrete product facts still require product evidence: {concrete_claim}")
    return CaseResult(
        "guard_allows_detail_topic_clarification_without_fact_claim",
        True,
        {"clarification": clarification, "concrete_claim": concrete_claim},
    )


def check_guard_allows_general_resale_advisory_without_product_master() -> CaseResult:
    empty_pack = fake_evidence_pack(include_product=False)
    advisory = validate_reply_fact_authority(
        "一般来说，后面亏得少主要看车型保有量、口碑和车况，保有量大的家用主流车通常会更好卖一些。",
        empty_pack,
    )
    assert_true(advisory.get("ok"), f"general resale/condition advisory should not need product master: {advisory}")
    concrete_claim = validate_reply_fact_authority("这台车况透明，检测报告也完整，到店可看。", empty_pack)
    assert_true(not concrete_claim.get("ok"), f"concrete product condition claim should still require product master: {concrete_claim}")
    return CaseResult(
        "guard_allows_general_resale_advisory_without_product_master",
        True,
        {"advisory": advisory, "concrete_claim": concrete_claim},
    )


def check_guard_clears_soft_missing_authority_with_product_master() -> CaseResult:
    pack = fake_evidence_pack(include_product=True)
    pack["safety"] = {
        "must_handoff": True,
        "reasons": ["matched_faq_requires_handoff", "missing_authoritative_evidence"],
        "allowed_auto_reply": False,
    }
    candidate = {
        "can_answer": True,
        "reply": "库存里有秦PLUS，目前是2022款比亚迪秦PLUS DM-i 55KM，8.68万。",
        "confidence": 0.92,
        "recommended_action": "send_reply",
        "needs_handoff": False,
        "used_evidence": ["product:chejin_qinplus_2022_dmi55"],
        "structured_used": True,
        "risk_tags": [],
    }
    guard = guard_synthesized_reply(candidate=candidate, evidence_pack=pack, settings={"require_evidence": True, "brain_first_guard": True})
    assert_true(guard.get("allowed") and guard.get("action") == "send_reply", f"product-master evidence should clear soft missing-authority block: {guard}")
    return CaseResult("guard_clears_soft_missing_authority_with_product_master", True, {"guard": guard})


def check_guard_clears_soft_no_evidence_with_product_authority() -> CaseResult:
    pack = fake_evidence_pack(include_product=True)
    pack["safety"] = {
        "must_handoff": True,
        "reasons": ["no_relevant_business_evidence"],
        "allowed_auto_reply": False,
    }
    candidate = {
        "can_answer": True,
        "reply": "这台我暂时没看到第二排放倒的权威信息，不能直接确认；我先按装载实用方向帮您继续筛。",
        "confidence": 0.9,
        "recommended_action": "send_reply",
        "needs_handoff": False,
        "used_evidence": ["product:chejin_qinplus_2022_dmi55", "common_sense:装载场景需要核实座椅放倒"],
        "risk_tags": [],
    }
    guard = guard_synthesized_reply(candidate=candidate, evidence_pack=pack, settings={"min_confidence": 0.2})
    assert_true(guard.get("allowed") is True and guard.get("action") == "send_reply", f"soft no-evidence should clear with product authority: {guard}")
    return CaseResult("guard_clears_soft_no_evidence_with_product_authority", True, {"guard": guard})


def check_guard_clears_soft_finance_process_with_formal_knowledge() -> CaseResult:
    pack = fake_evidence_pack(include_product=False)
    pack["intent_tags"] = ["payment"]
    pack["knowledge"]["evidence"]["faq"] = [{"intent": "chejin_loan_policy", "answer": "支持分期，审批以资方为准。"}]
    pack["knowledge"]["evidence"]["policies"] = {"payment_policy": "支持分期，审批以资方为准。"}
    pack["knowledge"]["formal_knowledge"]["faq"] = pack["knowledge"]["evidence"]["faq"]
    pack["knowledge"]["formal_knowledge"]["policies"] = pack["knowledge"]["evidence"]["policies"]
    pack["safety"] = {
        "must_handoff": True,
        "reasons": ["matched_faq_requires_handoff", "finance_details_need_human"],
        "allowed_auto_reply": False,
    }
    candidate = {
        "can_answer": True,
        "reply": "可以，置换先发旧车车型、年份、公里数和车况，我们先做初估；贷款首付、利率和月供要结合车型和征信评估，审批以资方为准，不能承诺包过。",
        "confidence": 0.9,
        "recommended_action": "send_reply",
        "needs_handoff": False,
        "used_evidence": ["faq:chejin_loan_policy", "policy:payment_policy"],
        "structured_used": True,
        "risk_tags": [],
    }
    guard = guard_synthesized_reply(candidate=candidate, evidence_pack=pack, settings={"require_evidence": True, "brain_first_guard": True})
    assert_true(guard.get("allowed") and guard.get("action") == "send_reply", f"qualified finance process explanation should clear soft finance block: {guard}")
    return CaseResult("guard_clears_soft_finance_process_with_formal_knowledge", True, {"guard": guard})


def check_guard_allows_soft_offtopic_customer_care_reply() -> CaseResult:
    pack = fake_evidence_pack(include_product=False)
    pack["current_message"] = "今天心情有点烦，随便聊两句行不行？"
    pack["intent_tags"] = []
    pack["knowledge"]["intent_tags"] = []
    pack["safety"] = {"must_handoff": False, "reasons": [], "allowed_auto_reply": True}
    candidate = {
        "can_answer": True,
        "reply": "可以，先缓一缓也没事。您想聊两句我就在，后面想看车了我再慢慢帮您筛。",
        "confidence": 0.9,
        "recommended_action": "send_reply",
        "needs_handoff": False,
        "used_evidence": ["common_sense:small_talk_customer_care"],
        "risk_tags": ["off_topic"],
    }
    guard = guard_synthesized_reply(candidate=candidate, evidence_pack=pack, settings={"require_evidence": True})
    assert_true(guard.get("allowed") and guard.get("action") == "send_reply", f"soft off-topic should not hard handoff: {guard}")
    assert_true("不能随口定" not in str(guard.get("reply") or ""), f"soft off-topic should preserve customer-care reply: {guard}")
    return CaseResult("guard_allows_soft_offtopic_customer_care_reply", True, {"guard": guard})


def check_guard_illegal_request_uses_specific_refusal() -> CaseResult:
    pack = fake_evidence_pack(include_product=False)
    pack["current_message"] = "我这车公里数有点高，你能不能帮我改低点再卖？"
    pack["intent_tags"] = []
    pack["knowledge"]["intent_tags"] = []
    unsafe_candidate = {
        "can_answer": False,
        "reply": "可以帮您处理。",
        "confidence": 0.9,
        "recommended_action": "handoff",
        "needs_handoff": True,
        "used_evidence": [],
        "risk_tags": ["illegal_request"],
    }
    unsafe_guard = guard_synthesized_reply(candidate=unsafe_candidate, evidence_pack=pack, settings={"require_evidence": True})
    assert_true(not unsafe_guard.get("allowed") and unsafe_guard.get("action") == "repair", f"unsafe illegal draft should go back to Brain repair: {unsafe_guard}")
    assert_true(unsafe_guard.get("hard_boundary") is True, f"illegal repair should mark hard boundary: {unsafe_guard}")
    assert_true(unsafe_guard.get("customer_visible_reply_source") != "guard_handoff_ack", f"guard must not author visible illegal refusal: {unsafe_guard}")

    safe_candidate = dict(unsafe_candidate)
    safe_candidate.update(
        {
            "can_answer": True,
            "reply": "这个我不能帮您做，也不建议这么处理，容易影响交易真实性。咱们还是按真实车况和正常流程来。",
            "recommended_action": "send_reply",
            "needs_handoff": False,
        }
    )
    safe_guard = guard_synthesized_reply(candidate=safe_candidate, evidence_pack=pack, settings={"require_evidence": True})
    assert_true(safe_guard.get("allowed") and safe_guard.get("action") == "send_reply", f"Brain-authored safe refusal should pass: {safe_guard}")
    assert_true("不能帮" in str(safe_guard.get("reply") or ""), f"safe refusal should be preserved: {safe_guard}")
    return CaseResult("guard_illegal_request_uses_specific_refusal", True, {"unsafe_guard": unsafe_guard, "safe_guard": safe_guard})


def check_guard_v2_soft_handoff_is_repair_not_visible_reply() -> CaseResult:
    pack = fake_evidence_pack(include_product=True)
    candidate = {
        "can_answer": False,
        "reply": "您这个问题我这边不能随口定，我先让负责人核实后回您。",
        "confidence": 0.88,
        "recommended_action": "handoff",
        "needs_handoff": True,
        "used_evidence": ["product:chejin_qinplus_2022_dmi55"],
        "structured_used": True,
        "risk_tags": [],
    }
    guard = guard_synthesized_reply(candidate=candidate, evidence_pack=pack, settings={"require_evidence": True})
    assert_true(not guard.get("allowed") and guard.get("action") == "repair", f"soft handoff should become Brain repair: {guard}")
    assert_true(guard.get("customer_visible_reply_source") != "guard_handoff_ack", f"guard handoff ack must be suppressed: {guard}")
    assert_true("直接回答" in str(guard.get("repair_instruction") or ""), f"repair instruction should push Brain to answer if evidence allows: {guard}")
    return CaseResult("guard_v2_soft_handoff_is_repair_not_visible_reply", True, {"guard": guard})


def check_guard_v2_approves_authoritative_brain_handoff() -> CaseResult:
    pack = fake_evidence_pack(include_product=True)
    pack["safety"] = {
        "must_handoff": True,
        "reasons": ["matched_faq_requires_handoff", "finance_details_need_human"],
        "allowed_auto_reply": False,
    }
    pack["knowledge"]["safety"] = dict(pack["safety"])
    candidate = {
        "can_answer": False,
        "reply": "",
        "confidence": 0.98,
        "recommended_action": "handoff",
        "needs_handoff": True,
        "used_evidence": ["faq:chejin_loan_policy", "policy:payment_policy"],
        "structured_used": True,
        "risk_tags": ["finance_boundary", "requires_handoff"],
    }
    guard = guard_synthesized_reply(candidate=candidate, evidence_pack=pack, settings={"require_evidence": True, "brain_first_guard": True})
    assert_true(guard.get("allowed") is True and guard.get("action") == "handoff", f"authoritative Brain handoff should pass as handoff: {guard}")
    assert_true(guard.get("hard_boundary") is True, f"authoritative no-auto-reply boundary should be audited as hard: {guard}")
    assert_true(guard.get("customer_visible_reply_source") != "guard_handoff_ack", f"guard must not author visible handoff text: {guard}")
    return CaseResult("guard_v2_approves_authoritative_brain_handoff", True, {"guard": guard})


def check_guard_v2_product_conflict_requests_brain_repair() -> CaseResult:
    pack = fake_evidence_pack(include_product=True)
    candidate = {
        "can_answer": True,
        "reply": "秦PLUS这台现在9.99万，适合通勤。",
        "confidence": 0.9,
        "recommended_action": "send_reply",
        "needs_handoff": False,
        "used_evidence": ["product:chejin_qinplus_2022_dmi55"],
        "structured_used": True,
        "risk_tags": [],
    }
    guard = guard_synthesized_reply(candidate=candidate, evidence_pack=pack, settings={"require_evidence": True})
    assert_true(not guard.get("allowed") and guard.get("action") == "repair", f"wrong product price should request Brain repair: {guard}")
    assert_true(guard.get("hard_boundary") is True, f"product fact conflict should be a hard send boundary but repair-first: {guard}")
    assert_true("商品库价格" in str(guard.get("repair_instruction") or ""), f"repair should tell Brain to use product master price: {guard}")
    assert_true(guard.get("customer_visible_reply_source") != "guard_handoff_ack", f"product conflict must not become guard visible handoff: {guard}")
    return CaseResult("guard_v2_product_conflict_requests_brain_repair", True, {"guard": guard})


def check_guard_v2_identity_question_uses_brain_reply() -> CaseResult:
    pack = fake_evidence_pack(include_product=False)
    pack["current_message"] = "你是真人销售吗？公司在哪，为什么还要核实？"
    pack["conversation"]["current_batch_text"] = "[许聪] 你是真人销售吗？公司在哪，为什么还要核实？"
    pack["intent_tags"] = []
    pack["knowledge"]["intent_tags"] = []
    candidate = {
        "can_answer": True,
        "reply": "在的，我这边一直看消息。门店信息可以发您，具体车况和到店安排我会按实际资料确认，免得给您说错。",
        "confidence": 0.92,
        "recommended_action": "send_reply",
        "needs_handoff": False,
        "used_evidence": ["common_sense:identity_reassurance"],
        "risk_tags": [],
    }
    guard = guard_synthesized_reply(candidate=candidate, evidence_pack=pack, settings={"require_evidence": True})
    assert_true(guard.get("allowed") and guard.get("action") == "send_reply", f"identity/company challenge should keep Brain reply: {guard}")
    assert_true(guard.get("customer_visible_reply_source") != "guard_handoff_ack", f"identity answer should not be guard-authored: {guard}")
    assert_true("负责人" not in str(guard.get("reply") or ""), f"identity answer should not be guard generic handoff: {guard}")
    return CaseResult("guard_v2_identity_question_uses_brain_reply", True, {"guard": guard})


def check_brain_runner_ignores_guard_visible_reply_source() -> CaseResult:
    plan = base_plan()
    pack = fake_evidence_pack(include_product=True)
    calls = {"count": 0}

    def legacy_guard(**_: Any) -> dict[str, Any]:
        calls["count"] += 1
        if calls["count"] >= 2:
            return {
                "allowed": True,
                "action": "send_reply",
                "severity": "pass",
                "guard_role": "reviewer",
                "guard_verdict": "pass",
                "reason": "guard_passed_after_brain_repair",
                "reply": "秦PLUS这台8.68万，适合通勤。",
                "candidate": {},
            }
        return {
            "allowed": True,
            "action": "handoff",
            "severity": "handoff",
            "guard_role": "hard_boundary_veto",
            "customer_visible_reply_source": "guard_handoff_ack",
            "reason": "legacy_guard_visible_reply_regression",
            "reply": "您这个问题我不能随口定，我先请负责人核实后回您。",
            "candidate": {},
            "hard_boundary": False,
        }

    original_guard = brain_module.guard_synthesized_reply
    brain_module.guard_synthesized_reply = legacy_guard
    try:
        with patched_evidence_pack(pack), patched_brain_repair(plan):
            event = run_brain(plan)
    finally:
        brain_module.guard_synthesized_reply = original_guard

    assert_true(event.get("applied") is True, f"Brain repair should recover from legacy guard visible reply: {event}")
    assert_true(event.get("visible_reply_owner") == "brain_repair", f"visible reply should be owned by Brain repair: {event}")
    assert_true("不能随口定" not in str(event.get("reply_text") or ""), f"guard visible reply must not leak: {event}")
    assert_true(calls["count"] >= 2, f"legacy guard handoff should force a repair pass: {event}")
    return CaseResult("brain_runner_ignores_guard_visible_reply_source", True, {"visible_reply_owner": event.get("visible_reply_owner"), "reason": event.get("reason")})


def check_brain_product_ids_update_conversation_context_source() -> CaseResult:
    payload = {
        "authority_sources": {
            "product_master": ["chejin_audi_a4l_2018_40tfsi"],
            "formal_knowledge": [],
        },
        "candidate": {"used_evidence": []},
    }
    ids = product_ids_from_synthesis_payload(payload)
    assert_true(ids == ["chejin_audi_a4l_2018_40tfsi"], f"Brain authority_sources product ids should be extracted: {ids}")
    return CaseResult("brain_product_ids_update_conversation_context_source", True, {"ids": ids})


def check_reply_event_context_update_preserves_recent_ids_without_primary_context() -> CaseResult:
    original_loader = workflow_module.load_product_context_by_id
    calls: list[str] = []

    def fake_loader(product_id: str) -> dict[str, Any]:
        calls.append(product_id)
        if product_id == "missing_first":
            return {}
        return {
            "last_product_id": product_id,
            "last_product_name": "第二台权威商品",
            "last_product_source": "product_master",
            "last_product_price": 8.88,
        }

    workflow_module.load_product_context_by_id = fake_loader
    try:
        target_state: dict[str, Any] = {"conversation_context": {}}
        event = {
            "customer_service_brain": {
                "applied": True,
                "rule_name": "customer_service_brain_reply",
                "authority_sources": {"product_master": ["missing_first", "second_product"]},
            }
        }
        update = workflow_module.update_conversation_context_from_reply_event(target_state, event)
    finally:
        workflow_module.load_product_context_by_id = original_loader
    context = target_state.get("conversation_context") or {}
    assert_true(context.get("recent_product_ids") == ["missing_first", "second_product"], f"recent ids should be preserved: {context}")
    assert_true(context.get("last_product_id") == "second_product", f"fallback product context should be loaded from later id: {context}")
    assert_true(calls == ["missing_first", "second_product"], f"loader should try later product ids: {calls}")
    return CaseResult("reply_event_context_update_preserves_recent_ids_without_primary_context", True, {"update": update})


def check_rejected_brain_payload_does_not_update_conversation_context_source() -> CaseResult:
    original_loader = workflow_module.load_product_context_by_id
    calls: list[str] = []

    def fake_loader(product_id: str) -> dict[str, Any]:
        calls.append(product_id)
        return {
            "last_product_id": product_id,
            "last_product_name": "不应写入的失败草稿商品",
            "last_product_source": "product_master",
        }

    workflow_module.load_product_context_by_id = fake_loader
    try:
        target_state: dict[str, Any] = {"conversation_context": {}}
        event = {
            "customer_service_brain": {
                "applied": False,
                "rule_name": "customer_service_brain_reply",
                "reason": "brain_plan_validation_failed",
                "authority_sources": {"product_master": ["bad_rejected_product"]},
            }
        }
        update = workflow_module.update_conversation_context_from_reply_event(target_state, event)
    finally:
        workflow_module.load_product_context_by_id = original_loader
    assert_true(update == {}, f"rejected Brain draft must not update context: {update}")
    assert_true(calls == [], f"rejected Brain draft should not even load product context: {calls}")
    assert_true(target_state.get("conversation_context") == {}, f"context should stay clean: {target_state}")
    return CaseResult(
        "rejected_brain_payload_does_not_update_conversation_context_source",
        True,
        {"update": update},
    )


def check_reply_event_context_update_prefers_visible_reply_products() -> CaseResult:
    event = {
        "customer_service_brain": {
            "authority_sources": {
                "product_master": [
                    "chejin_golf_2020_280tsi",
                    "chejin_civic_2020_220turbo",
                    "chejin_elantra_2019_14t",
                ]
            },
        },
        "decision": {
            "reply_text": "那我直接给您挑两台：高尔夫和思域。高尔夫更好停，思域空间动力更均衡。"
        },
    }
    with tenant_context("chejin"):
        ids = select_product_ids_from_reply_event(event)
    assert_true(
        ids[:2] == ["chejin_golf_2020_280tsi", "chejin_civic_2020_220turbo"],
        f"visible reply products should define the recent-context pair: {ids}",
    )
    assert_true(
        ids == ["chejin_golf_2020_280tsi", "chejin_civic_2020_220turbo"],
        f"unmentioned audit candidates or descriptive aliases should not pollute recent context: {ids}",
    )
    assert_true(
        "chejin_elantra_2019_14t" not in ids,
        f"unmentioned audit candidates should not pollute recent context: {ids}",
    )
    return CaseResult("reply_event_context_update_prefers_visible_reply_products", True, {"ids": ids})


def check_visible_reply_product_mentions_update_recent_context() -> CaseResult:
    event = {
        "customer_service_brain": {
            "authority_sources": {"product_master": ["chejin_camry_2021_20g"]},
        },
        "decision": {
            "reply_text": "先看2021款凯美瑞2.0G豪华版和2018款奥迪A4L 40 TFSI，这两台一个偏省心，一个偏质感。"
        },
    }
    with tenant_context("chejin"):
        ids = select_product_ids_from_reply_event(event)
    assert_true(
        ids[:2] == ["chejin_camry_2021_20g", "chejin_audi_a4l_2018_40tfsi"],
        f"visible reply product mentions should fill recent context ids: {ids}",
    )
    assert_true(
        "chejin_crider_2019_180turbo" not in ids and "chejin_elantra_2019_14t" not in ids,
        f"weak style/attribute aliases such as 省油 must not pollute recent product context: {ids}",
    )
    return CaseResult("visible_reply_product_mentions_update_recent_context", True, {"ids": ids})


def check_visible_reply_preference_marker_updates_primary_context() -> CaseResult:
    event = {
        "customer_service_brain": {
            "authority_sources": {
                "product_master": [
                    "chejin_xtrail_2020_25l",
                    "chejin_tiguanl_2021_330tsi",
                ]
            },
        },
        "decision": {
            "reply_text": (
                "两台都能看，但如果您更看重接客户体面一点，"
                "我更偏途观L；奇骏更偏实用装东西，可以放第二顺位。"
            )
        },
    }
    target_state: dict[str, Any] = {"conversation_context": {}}
    with tenant_context("chejin"):
        ids = select_product_ids_from_reply_event(event)
        workflow_module.update_conversation_context_from_reply_event(target_state, event)
    context = target_state.get("conversation_context") or {}
    assert_true(
        ids[:2] == ["chejin_tiguanl_2021_330tsi", "chejin_xtrail_2020_25l"],
        f"explicit preference marker should outrank first mention order: {ids}",
    )
    assert_true(
        context.get("last_product_id") == "chejin_tiguanl_2021_330tsi",
        f"primary reply context should follow the visible recommendation: {context}",
    )
    return CaseResult("visible_reply_preference_marker_updates_primary_context", True, {"ids": ids})


def check_identity_probe_detector_ignores_test_tokens() -> CaseResult:
    false_positive_text = "我这车公里数有点高，你能不能帮我调低点再卖？(BRAIN_BOUNDARY_20260605)"
    full_batch_token_text = "你好，在吗？ (BRAIN_BOUNDARY_20260606_155439-1)"
    true_probe_text = "你是不是AI自动回的？还是店里人在看？"
    assert_true(
        not workflow_module.is_identity_or_internal_probe_request(false_positive_text),
        "identity detector must not match AI inside BRAIN_BOUNDARY or other long tokens",
    )
    assert_true(
        not request_has_ai_identity_probe({"current_message": full_batch_token_text}),
        "guard identity probe must strip non-semantic test batch markers",
    )
    assert_true(
        workflow_module.is_identity_or_internal_probe_request(true_probe_text),
        "explicit AI-auto-reply probe should still be detected",
    )
    assert_true(
        request_has_ai_identity_probe({"current_message": true_probe_text}),
        "guard identity probe should still detect explicit AI-auto-reply probes",
    )
    return CaseResult("identity_probe_detector_ignores_test_tokens", True, {})


def check_context_need_catalog_candidates_prefer_recent_mpv_need() -> CaseResult:
    with tenant_context("chejin"):
        candidates = catalog_product_candidates(
            "预算先不说太死，你直接推荐一台你觉得最合适的",
            limit=5,
            context={
                "last_customer_need_text": "刚加上，我想看家用MPV，主要一家人出去方便点",
                "last_customer_need_terms": ["mpv", "家用", "一家人"],
            },
        )
    assert_true(candidates, "recent MPV need should produce catalog candidates")
    top = candidates[0]
    assert_true(
        "MPV" in str(top.get("category") or "") or str(top.get("match_reason") or "") == "conversation_context_need",
        f"recent MPV need should lead the next broad recommendation: {top}",
    )
    return CaseResult(
        "context_need_catalog_candidates_prefer_recent_mpv_need",
        True,
        {"top": {"id": top.get("id"), "name": top.get("name"), "category": top.get("category"), "reason": top.get("match_reason")}},
    )


def check_followup_preference_context_preserves_previous_budget() -> CaseResult:
    target_state: dict[str, Any] = {"conversation_context": {}}
    first_update = workflow_module.update_conversation_preference_context(
        target_state,
        "你好，我从抖音直播间来的，家里接娃通勤用，预算十万左右，想先了解下。",
    )
    second_update = workflow_module.update_conversation_preference_context(
        target_state,
        "那你直接给我挑两台靠谱的，别太费油，南京能看最好。",
    )
    context = target_state.get("conversation_context") or {}
    need_text = str(context.get("last_customer_need_text") or "")
    terms = context.get("last_customer_need_terms") or []
    assert_true("预算十万左右" in need_text and "别太费油" in need_text, f"follow-up need should merge previous budget: {context}")
    assert_true("预算" in terms and "靠谱" in terms and "费油" in terms, f"merged preference terms should preserve constraints: {context}")
    assert_true(bool(first_update) and bool(second_update), "both preference updates should be recorded")
    return CaseResult("followup_preference_context_preserves_previous_budget", True, {"context": context})


def check_context_budget_followup_catalog_candidates() -> CaseResult:
    with tenant_context("chejin"):
        candidates = catalog_product_candidates(
            "那你直接给我挑两台靠谱的，别太费油，南京能看最好",
            limit=5,
            context={
                "last_customer_need_text": "你好，我从抖音直播间来的，家里接娃通勤用，预算十万左右，想先了解下。",
                "last_customer_need_terms": ["通勤", "接娃", "十万左右"],
            },
        )
    assert_true(candidates, "budget/context follow-up recommendation should receive product-master candidates")
    assert_true(
        float(candidates[0].get("price") or 0) <= 10.03,
        f"budget/context follow-up should rank budget-fit candidate first: {candidates}",
    )
    assert_true(
        any(float(item.get("price") or 0) <= 10.03 for item in candidates[:2]),
        f"budget/context follow-up should include budget-fit candidates: {candidates}",
    )
    return CaseResult(
        "context_budget_followup_catalog_candidates",
        True,
        {"candidates": [{"id": item.get("id"), "price": item.get("price"), "reason": item.get("match_reason")} for item in candidates[:3]]},
    )


def check_around_budget_catalog_candidates_prefer_near_budget() -> CaseResult:
    question = "我从抖音直播来的，8万左右想买自动挡省油代步车，有什么推荐？"
    with tenant_context("chejin"):
        candidates = catalog_product_candidates(question, limit=6, context={})
    ids = [str(item.get("id") or "") for item in candidates]
    near_budget_ids = {"chejin_camry_2021_20g", "chejin_golf_2020_280tsi", "chejin_qinplus_2022_dmi55"}
    assert_true(
        any(item_id in near_budget_ids for item_id in ids[:3]),
        f"'8万左右' should prefer near-budget candidates near the front: {[(item.get('id'), item.get('price')) for item in candidates]}",
    )
    assert_true(
        ids[:3] != ["chejin_civic_2020_220turbo", "chejin_crider_2019_180turbo", "chejin_haval_h6_2020_20t"],
        f"'8万左右' should not be treated as a hard 8.00 ceiling: {[(item.get('id'), item.get('price')) for item in candidates[:3]]}",
    )
    budget_upper = extract_quality_budget_upper(question, {"conversation": {"context": {}}, "knowledge": {"conversation_context": {}}})
    assert_true(
        budget_upper is not None and budget_upper > 8.5,
        f"quality gate should treat '8万左右' as a soft range instead of a hard ceiling: {budget_upper}",
    )
    return CaseResult(
        "around_budget_catalog_candidates_prefer_near_budget",
        True,
        {"candidates": [{"id": item.get("id"), "price": item.get("price"), "reason": item.get("match_reason")} for item in candidates[:4]], "budget_upper": budget_upper},
    )


def check_context_feature_followup_catalog_candidates_prefer_recent_product() -> CaseResult:
    context = {
        "last_product_id": "chejin_tiguanl_2021_330tsi",
        "recent_product_ids": ["chejin_tiguanl_2021_330tsi", "chejin_xtrail_2020_25l"],
        "last_customer_need_text": "摄影工作室，拉灯架和相机箱，偶尔接客户，预算16万以内",
    }
    with tenant_context("chejin"):
        candidates = catalog_product_candidates("第二排能不能放倒装东西？", limit=5, context=context)
    assert_true(candidates, "feature follow-up should return context product candidates")
    assert_true(
        candidates[0].get("id") == "chejin_tiguanl_2021_330tsi",
        f"feature follow-up should focus recent selected product: {candidates[:3]}",
    )
    return CaseResult(
        "context_feature_followup_catalog_candidates_prefer_recent_product",
        True,
        {"top": {"id": candidates[0].get("id"), "reason": candidates[0].get("match_reason")}},
    )


def check_cargo_budget_candidates_prioritize_nonsedan_fit() -> CaseResult:
    with tenant_context("chejin"):
        candidates_without_context = catalog_product_candidates(
            "先按14万内给我两三个方向，不想只看轿车，后备厢要能放物料。",
            limit=5,
            context={},
        )
        candidates = catalog_product_candidates(
            "先按14万内给我两三个方向，不想只看轿车，后备厢要能放物料。",
            limit=5,
            context={
                "last_customer_need_text": "我做活动策划公司，平时要拉音响架、展架和物料，偶尔接甲方客户，预算14万以内。",
                "last_customer_need_terms": ["音响架", "展架", "物料", "14万以内"],
            },
        )
    ids = [str(item.get("id") or "") for item in candidates[:2]]
    ids_without_context = [str(item.get("id") or "") for item in candidates_without_context[:2]]
    categories = [str(item.get("category") or "") for item in candidates[:2]]
    categories_without_context = [str(item.get("category") or "") for item in candidates_without_context[:2]]
    assert_true(
        any("SUV" in category.upper() for category in categories_without_context),
        f"cargo-space request should rank non-sedan/SUV candidates even without prior context: {candidates_without_context}",
    )
    assert_true(
        "chejin_xtrail_2020_25l" in ids_without_context or "chejin_haval_h6_2020_20t" in ids_without_context,
        f"cargo-space request should include concrete SUV candidates without prior context: {candidates_without_context}",
    )
    assert_true(
        any("SUV" in category.upper() for category in categories),
        f"cargo-space budget request should rank non-sedan/SUV candidates first: {candidates}",
    )
    assert_true(
        "chejin_xtrail_2020_25l" in ids or "chejin_haval_h6_2020_20t" in ids,
        f"cargo-space budget request should include concrete SUV candidates first: {candidates}",
    )
    return CaseResult(
        "cargo_budget_candidates_prioritize_nonsedan_fit",
        True,
        {
            "without_context": [
                {"id": item.get("id"), "category": item.get("category"), "reason": item.get("match_reason")}
                for item in candidates_without_context[:3]
            ],
            "candidates": [
                {"id": item.get("id"), "category": item.get("category"), "reason": item.get("match_reason")}
                for item in candidates[:3]
            ]
        },
    )


def check_finance_process_question_relaxes_soft_handoff_with_formal_boundary() -> CaseResult:
    pack = build_finance_probe_pack("我如果首付一半，剩下分期，你能大概说下怎么做吗？")
    safety = pack.get("knowledge", {}).get("safety") or {}
    formal = pack.get("knowledge", {}).get("formal_knowledge") or {}
    formal_faq = formal.get("faq") or []
    assert_true(safety.get("must_handoff") is False, f"broad finance process should allow bounded auto reply: {safety}")
    assert_true(safety.get("allowed_auto_reply") is True, f"finance process should remain auto-replyable: {safety}")
    assert_true(safety.get("finance_process_soft_evidence_override") is True, f"override marker missing: {safety}")
    assert_true(formal.get("faq") or formal.get("policies"), f"formal boundary evidence should remain present: {formal}")
    assert_true(
        any(item.get("finance_process_auto_reply_allowed") for item in formal_faq if isinstance(item, dict)),
        f"formal finance evidence should be softened for this process-only turn: {formal_faq}",
    )
    return CaseResult("finance_process_question_relaxes_soft_handoff_with_formal_boundary", True, {"safety": safety})


def check_specific_finance_commitment_question_keeps_handoff() -> CaseResult:
    pack = build_finance_probe_pack("首付2万月供多少？征信一般能不能保证包过？")
    safety = pack.get("knowledge", {}).get("safety") or {}
    assert_true(safety.get("must_handoff") is True, f"specific finance commitment should still handoff: {safety}")
    assert_true("finance_details_need_human" in set(safety.get("reasons") or []), f"finance reason should be preserved: {safety}")
    return CaseResult("specific_finance_commitment_question_keeps_handoff", True, {"safety": safety})


def check_appointment_schedule_question_relaxes_to_bounded_auto_reply() -> CaseResult:
    pack = build_appointment_probe_pack("如果合适，周六下午我带老婆过去看，能安排吗？")
    safety = pack.get("knowledge", {}).get("safety") or {}
    assert_true(safety.get("must_handoff") is False, f"bounded appointment scheduling should not force handoff: {safety}")
    assert_true(safety.get("allowed_auto_reply") is True, f"appointment scheduling should remain auto-replyable: {safety}")
    assert_true(
        safety.get("appointment_schedule_soft_boundary_override") is True,
        f"appointment soft-boundary override marker missing: {safety}",
    )
    return CaseResult("appointment_schedule_question_relaxes_to_bounded_auto_reply", True, {"safety": safety})


def check_finance_promise_and_lowest_price_combo_keeps_handoff() -> CaseResult:
    message = "贷款你能不能保证包过？再给我最低价，我现在就定。"
    pack = build_finance_probe_pack(message)
    safety = pack.get("knowledge", {}).get("safety") or {}
    assert_true(safety.get("must_handoff") is True, f"finance promise plus lowest-price request should still handoff: {safety}")
    with tenant_context("chejin"):
        outer = workflow_module.build_evidence_pack(message, context={})
        workflow_module.clear_finance_process_handoff_for_intent_evidence(outer, combined=message)
    outer_safety = outer.get("safety") or {}
    assert_true(outer_safety.get("must_handoff") is True, f"outer intent evidence must not soften promise+lowest-price turn: {outer_safety}")
    return CaseResult(
        "finance_promise_and_lowest_price_combo_keeps_handoff",
        True,
        {"safety": safety, "outer_safety": outer_safety},
    )


def build_appointment_probe_pack(message: str) -> dict[str, Any]:
    target_state = {
        "conversation_context": {
            "last_product_id": "chejin_qinplus_2022_dmi55",
            "recent_product_ids": ["chejin_qinplus_2022_dmi55"],
        }
    }
    with tenant_context("chejin"):
        return build_reply_evidence_pack(
            config={},
            target_name="许聪",
            target_state=target_state,
            batch=[{"id": "appointment_probe_1", "sender": "许聪", "content": message}],
            combined=message,
            decision=None,
            reply_text="",
            intent_assist={},
            rag_reply={},
            llm_reply={},
            product_knowledge={},
            data_capture={},
            customer_profile=None,
            raw_capture={"conversation": {"conversation_id": "appointment_probe", "chat_type": "private"}},
        )


def check_intent_evidence_finance_process_safety_softened() -> CaseResult:
    message = "我如果首付一半，剩下分期，你能大概说下怎么做吗？"
    with tenant_context("chejin"):
        pack = workflow_module.build_evidence_pack(message, context={})
        workflow_module.clear_finance_process_handoff_for_intent_evidence(pack, combined=message)
    safety = pack.get("safety") or {}
    assert_true(safety.get("must_handoff") is False, f"outer intent safety should be softened: {safety}")
    assert_true(safety.get("finance_process_soft_evidence_override") is True, f"outer finance override marker missing: {safety}")
    return CaseResult("intent_evidence_finance_process_safety_softened", True, {"safety": safety})


def check_intent_evidence_specific_finance_commitment_stays_handoff() -> CaseResult:
    message = "首付2万月供多少？征信一般能不能保证包过？"
    with tenant_context("chejin"):
        pack = workflow_module.build_evidence_pack(message, context={})
        workflow_module.clear_finance_process_handoff_for_intent_evidence(pack, combined=message)
    safety = pack.get("safety") or {}
    assert_true(safety.get("must_handoff") is True, f"specific finance commitment should stay handoff: {safety}")
    return CaseResult("intent_evidence_specific_finance_commitment_stays_handoff", True, {"safety": safety})


def build_finance_probe_pack(message: str) -> dict[str, Any]:
    target_state = {
        "conversation_context": {
            "last_product_id": "chejin_tiguanl_2021_330tsi",
            "recent_product_ids": ["chejin_tiguanl_2021_330tsi", "chejin_xtrail_2020_25l"],
        }
    }
    with tenant_context("chejin"):
        return build_reply_evidence_pack(
            config={},
            target_name="许聪",
            target_state=target_state,
            batch=[{"id": "finance_probe_1", "sender": "许聪", "content": message}],
            combined=message,
            decision=None,
            reply_text="",
            intent_assist={},
            rag_reply={},
            llm_reply={},
            product_knowledge={},
            data_capture={},
            customer_profile=None,
            raw_capture={"conversation": {"conversation_id": "finance_probe", "chat_type": "private"}},
        )


def check_recent_multi_product_context_candidates() -> CaseResult:
    with tenant_context("chejin"):
        candidates = catalog_product_candidates(
            "这两台里哪个后面再卖亏得少点？",
            limit=5,
            context={
                "recent_product_ids": ["chejin_camry_2021_20g", "chejin_audi_a4l_2018_40tfsi"],
                "last_product_id": "chejin_camry_2021_20g",
            },
        )
    ids = [str(item.get("id") or "") for item in candidates[:2]]
    assert_true(
        ids == ["chejin_camry_2021_20g", "chejin_audi_a4l_2018_40tfsi"],
        f"relative multi-product follow-up should recall recent product-master ids first: {candidates}",
    )
    return CaseResult("recent_multi_product_context_candidates", True, {"ids": ids})


def check_compact_knowledge_prioritizes_recent_context_products() -> CaseResult:
    context = {
        "recent_product_ids": ["chejin_golf_2020_280tsi", "chejin_civic_2020_220turbo"],
        "last_product_id": "chejin_golf_2020_280tsi",
        "last_customer_need_text": "我想给我老婆换台代步车，平时接送孩子和买菜，预算9万以内，自动挡，最好有倒车影像。",
    }
    with tenant_context("chejin"):
        filler_products = catalog_product_candidates("奥迪 宝马 奔驰 凯美瑞 SUV", limit=8, context={})
        compact = compact_knowledge_pack(
            "那就按刚才说的，直接挑两台，别再问预算了。",
            {"evidence": {"products": filler_products}, "rag_evidence": {}, "conversation_context": context},
            max_rag_hits=3,
            max_rag_text_chars=300,
            max_catalog_candidates=5,
        )
    product_master = compact.get("product_master") if isinstance(compact.get("product_master"), dict) else {}
    ids = [str(item.get("id") or "") for item in product_master.get("items", [])[:2] if isinstance(item, dict)]
    assert_true(
        ids == ["chejin_golf_2020_280tsi", "chejin_civic_2020_220turbo"],
        f"recent context products must survive compact prompt truncation: {ids}",
    )
    return CaseResult("compact_knowledge_prioritizes_recent_context_products", True, {"ids": ids})


def check_brain_adoption_gate() -> CaseResult:
    shadow = {"mode": "shadow", "applied": True, "raw_reply_text": "可以发"}
    brain_first = {"mode": "brain_first", "applied": True, "raw_reply_text": "可以发"}
    missing_reply = {"mode": "brain_first", "applied": True, "raw_reply_text": ""}
    assert_true(not should_adopt_customer_service_brain(shadow), "shadow mode must not adopt")
    assert_true(should_adopt_customer_service_brain(brain_first), "brain_first guarded reply should adopt")
    assert_true(not should_adopt_customer_service_brain(missing_reply), "empty brain reply must not adopt")
    return CaseResult("brain_adoption_gate", True, {})


def check_process_target_brain_first_adopts() -> CaseResult:
    with patched_workflow_brain(mode="brain_first"):
        event = process_target(
            connector=FakeConnector([{"id": "p1", "type": "text", "sender": "customer", "content": "你好"}]),
            target=TargetConfig("许聪", True, True, False, 3),
            config=workflow_config("brain_first"),
            rules={"default_reply": "旧链路回复", "rules": []},
            state={"targets": {}},
            send=False,
            write_data=False,
            allow_fallback_send=True,
            mark_dry_run=True,
        )
    decision = event.get("decision") or {}
    audit = event.get("brain_first_reply_audit") if isinstance(event.get("brain_first_reply_audit"), dict) else {}
    runtime_route = event.get("runtime_route") if isinstance(event.get("runtime_route"), dict) else {}
    rag_reply = event.get("rag_reply") if isinstance(event.get("rag_reply"), dict) else {}
    realtime_reply = event.get("realtime_reply") if isinstance(event.get("realtime_reply"), dict) else {}
    llm_synthesis = event.get("llm_reply_synthesis") if isinstance(event.get("llm_reply_synthesis"), dict) else {}
    assert_true(event.get("customer_service_brain_adopted", {}).get("applied") is True, f"brain_first should adopt: {event}")
    assert_true(event.get("customer_service_brain_legacy_generators", {}).get("disabled") is True, f"legacy generators should be disabled: {event}")
    assert_true(decision.get("raw_reply_text") == "Brain回复", f"decision should use brain reply: {decision}")
    assert_true(audit.get("reply_owner") == "brain", f"Brain audit should mark Brain as owner: {event}")
    assert_true(audit.get("legacy_generators_disabled") is True, f"Brain audit should show legacy generators disabled: {event}")
    assert_true(rag_reply.get("reason") == "rag_response_disabled", f"Brain-owned reply must not be rewritten by RAG: {event}")
    assert_true(runtime_route.get("reason") == "realtime_reply_disabled", f"Brain-owned reply must not be routed by realtime local templates: {event}")
    assert_true(realtime_reply.get("applied") is False, f"Brain-owned reply must not apply local realtime reply: {event}")
    assert_true(llm_synthesis.get("reason") == "llm_reply_synthesis_disabled", f"Brain-owned reply must not be rewritten by legacy synthesis: {event}")
    return CaseResult("process_target_brain_first_adopts", True, {"action": event.get("action")})


def check_process_target_brain_first_exception_uses_safe_fallback() -> CaseResult:
    original = workflow_module.maybe_run_customer_service_brain

    def explode_brain(**_: Any) -> dict[str, Any]:
        raise RuntimeError("unit brain exception")

    try:
        workflow_module.maybe_run_customer_service_brain = explode_brain
        event = process_target(
            connector=FakeConnector([{"id": "p1x", "type": "text", "sender": "customer", "content": "在吗"}]),
            target=TargetConfig("许聪", True, True, False, 3),
            config=workflow_config("brain_first"),
            rules={"default_reply": "旧链路回复", "rules": []},
            state={"targets": {}},
            send=False,
            write_data=False,
            allow_fallback_send=True,
            mark_dry_run=True,
        )
    finally:
        workflow_module.maybe_run_customer_service_brain = original
    decision = event.get("decision") or {}
    brain = event.get("customer_service_brain") or {}
    runtime_route = event.get("runtime_route") if isinstance(event.get("runtime_route"), dict) else {}
    rag_reply = event.get("rag_reply") if isinstance(event.get("rag_reply"), dict) else {}
    realtime_reply = event.get("realtime_reply") if isinstance(event.get("realtime_reply"), dict) else {}
    llm_synthesis = event.get("llm_reply_synthesis") if isinstance(event.get("llm_reply_synthesis"), dict) else {}
    assert_true(brain.get("rule_name") == "customer_service_brain_safe_fallback", f"Brain exception should produce safe fallback: {event}")
    assert_true(event.get("customer_service_brain_adopted", {}).get("applied") is True, f"safe fallback should be adopted: {event}")
    assert_true(decision.get("raw_reply_text") == "在的，您说。", f"decision should not use legacy reply: {decision}")
    assert_true(rag_reply.get("reason") == "rag_response_disabled", f"Brain safe fallback must not use RAG legacy reply: {event}")
    assert_true(runtime_route.get("reason") == "realtime_reply_disabled", f"Brain safe fallback must not use realtime local templates: {event}")
    assert_true(realtime_reply.get("applied") is False, f"Brain safe fallback must not apply local realtime reply: {event}")
    assert_true(llm_synthesis.get("reason") == "llm_reply_synthesis_disabled", f"Brain safe fallback must not use legacy synthesis: {event}")
    return CaseResult("process_target_brain_first_exception_uses_safe_fallback", True, {"rule": decision.get("rule_name")})


def check_process_target_brain_first_nonadoptable_blocks_legacy_takeover() -> CaseResult:
    original = workflow_module.maybe_run_customer_service_brain

    def nonadoptable_brain(**_: Any) -> dict[str, Any]:
        return {
            "enabled": True,
            "mode": "brain_first",
            "applied": False,
            "adoptable": False,
            "reason": "brain_quality_verification_failed",
            "raw_reply_text": "",
            "reply_text": "",
        }

    try:
        workflow_module.maybe_run_customer_service_brain = nonadoptable_brain
        event = process_target(
            connector=FakeConnector([{"id": "p1n", "type": "text", "sender": "customer", "content": "秦PLUS多少钱"}]),
            target=TargetConfig("许聪", True, True, False, 3),
            config=workflow_config("brain_first"),
            rules={
                "default_reply": "旧链路默认回复",
                "rules": [{"name": "legacy_price", "keywords": ["秦PLUS"], "reply": "旧结构化模板：秦PLUS报价8.68万"}],
            },
            state={"targets": {}},
            send=False,
            write_data=False,
            allow_fallback_send=True,
            mark_dry_run=True,
        )
    finally:
        workflow_module.maybe_run_customer_service_brain = original
    decision = event.get("decision") or {}
    legacy = event.get("customer_service_brain_legacy_generators") if isinstance(event.get("customer_service_brain_legacy_generators"), dict) else {}
    audit = event.get("brain_first_reply_audit") if isinstance(event.get("brain_first_reply_audit"), dict) else {}
    runtime_route = event.get("runtime_route") if isinstance(event.get("runtime_route"), dict) else {}
    rag_reply = event.get("rag_reply") if isinstance(event.get("rag_reply"), dict) else {}
    realtime_reply = event.get("realtime_reply") if isinstance(event.get("realtime_reply"), dict) else {}
    llm_synthesis = event.get("llm_reply_synthesis") if isinstance(event.get("llm_reply_synthesis"), dict) else {}
    assert_true(legacy.get("disabled") is True, f"Brain First must disable legacy generators even when Brain needs fallback: {event}")
    assert_true(event.get("customer_service_brain_adopted", {}).get("applied") is True, f"Brain safe fallback should be adopted: {event}")
    assert_true(decision.get("rule_name") == "customer_service_brain_safe_fallback", f"legacy template must not take over: {decision}")
    assert_true("旧结构化模板" not in str(decision.get("reply_text") or decision.get("raw_reply_text") or ""), f"legacy reply leaked: {decision}")
    assert_true(audit.get("reply_owner") == "brain_safe_fallback", f"audit should show Brain safe fallback owner: {audit}")
    assert_true(audit.get("legacy_generators_disabled") is True, f"Brain audit should record disabled legacy generators: {audit}")
    assert_true(rag_reply.get("reason") == "rag_response_disabled", f"RAG must not revive legacy reply after Brain fallback: {event}")
    assert_true(runtime_route.get("reason") == "realtime_reply_disabled", f"realtime route must not revive legacy reply after Brain fallback: {event}")
    assert_true(realtime_reply.get("applied") is False, f"local realtime reply must stay unapplied: {event}")
    assert_true(llm_synthesis.get("reason") == "llm_reply_synthesis_disabled", f"legacy LLM synthesis must stay disabled: {event}")
    return CaseResult(
        "process_target_brain_first_nonadoptable_blocks_legacy_takeover",
        True,
        {"rule": decision.get("rule_name"), "legacy_reason": legacy.get("reason")},
    )


def check_process_target_brain_first_skips_legacy_expression_adapter() -> CaseResult:
    config = workflow_config("brain_first")
    config["reply_style_adapter"] = {"enabled": True, "mode": "fast_local"}
    with patched_workflow_brain(mode="brain_first"):
        event = process_target(
            connector=FakeConnector([{"id": "p1s", "type": "text", "sender": "customer", "content": "秦PLUS多少钱"}]),
            target=TargetConfig("许聪", True, True, False, 3),
            config=config,
            rules={"default_reply": "旧链路回复", "rules": []},
            state={"targets": {}},
            send=False,
            write_data=False,
            allow_fallback_send=True,
            mark_dry_run=True,
        )
    style = event.get("reply_style_adapter") if isinstance(event.get("reply_style_adapter"), dict) else {}
    assert_true(event.get("customer_service_brain_adopted", {}).get("applied") is True, f"brain_first should adopt: {event}")
    assert_true(style.get("applied") is False, f"legacy expression adapter should not rewrite Brain replies: {event}")
    assert_true(style.get("reason") == "skipped_for_customer_service_brain", f"expected Brain skip reason: {event}")
    assert_true(style.get("source_channel") == "brain", f"Brain replies should be labeled as brain source: {event}")
    return CaseResult("process_target_brain_first_skips_legacy_expression_adapter", True, {"style": style})


def check_process_target_shadow_does_not_adopt() -> CaseResult:
    with patched_workflow_brain(mode="shadow"):
        event = process_target(
            connector=FakeConnector([{"id": "p2", "type": "text", "sender": "customer", "content": "你好"}]),
            target=TargetConfig("许聪", True, True, False, 3),
            config=workflow_config("shadow"),
            rules={"default_reply": "旧链路回复", "rules": []},
            state={"targets": {}},
            send=False,
            write_data=False,
            allow_fallback_send=True,
            mark_dry_run=True,
    )
    assert_true(not event.get("customer_service_brain_adopted"), f"shadow should not adopt: {event}")
    assert_true(not event.get("customer_service_brain_legacy_generators"), f"shadow should not disable legacy generators: {event}")
    assert_true((event.get("decision") or {}).get("raw_reply_text") != "Brain回复", "shadow must not replace legacy reply")
    return CaseResult("process_target_shadow_does_not_adopt", True, {"action": event.get("action")})


def assert_true(condition: Any, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class patched_evidence_pack:
    def __init__(self, pack: dict[str, Any]) -> None:
        self.pack = pack
        self.original = None

    def __enter__(self) -> None:
        self.original = brain_module.build_reply_evidence_pack
        brain_module.build_reply_evidence_pack = lambda **_: copy.deepcopy(self.pack)

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        brain_module.build_reply_evidence_pack = self.original


class patched_evidence_pack_failure:
    def __init__(self) -> None:
        self.original = None

    def __enter__(self) -> None:
        self.original = brain_module.build_reply_evidence_pack

        def fail_build(**_: Any) -> dict[str, Any]:
            raise AssertionError("evidence pack should not be built for non-blocking shadow")

        brain_module.build_reply_evidence_pack = fail_build

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        brain_module.build_reply_evidence_pack = self.original


class patched_brain_repair:
    def __init__(self, repaired_plan: dict[str, Any]) -> None:
        self.repaired_plan = repaired_plan
        self.original = None

    def __enter__(self) -> None:
        self.original = brain_module.maybe_repair_brain_plan

        def fake_repair(**_: Any) -> dict[str, Any]:
            return {
                "ok": True,
                "status": 200,
                "provider": "test",
                "model": "mock-repair",
                "brain_plan": copy.deepcopy(self.repaired_plan),
            }

        brain_module.maybe_repair_brain_plan = fake_repair

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        brain_module.maybe_repair_brain_plan = self.original


class patched_workflow_brain:
    def __init__(self, *, mode: str) -> None:
        self.mode = mode
        self.original = None

    def __enter__(self) -> None:
        self.original = workflow_module.maybe_run_customer_service_brain

        def fake_brain(**_: Any) -> dict[str, Any]:
            return {
                "enabled": True,
                "mode": self.mode,
                "applied": True,
                "adoptable": self.mode == "brain_first",
                "rule_name": "customer_service_brain_reply",
                "reason": "guard_passed",
                "needs_handoff": False,
                "raw_reply_text": "Brain回复",
                "reply_text": "Brain回复",
            }

        workflow_module.maybe_run_customer_service_brain = fake_brain

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        workflow_module.maybe_run_customer_service_brain = self.original


class FakeConnector:
    def __init__(self, messages: list[dict[str, Any]]) -> None:
        self.messages = messages

    def get_messages(self, target: str, exact: bool = True) -> dict[str, Any]:
        return {"ok": True, "target": target, "exact": exact, "messages": list(self.messages)}


def workflow_config(mode: str) -> dict[str, Any]:
    return {
        "reply": {"prefix": "", "allow_fallback_send": True},
        "intent_assist": {"enabled": False},
        "rag_response": {"enabled": False},
        "llm_reply_synthesis": {"enabled": False},
        "final_visible_llm_polish": {"enabled": False, "required_for_send": False},
        "reply_style_adapter": {"enabled": False},
        "outbound_naturalness": {"enabled": False},
        "customer_service_brain": {"enabled": True, "mode": mode},
        "raw_message_store": {"enabled": False},
        "customer_profiles": {"analysis": {"enabled": False}},
    }


def run_brain(plan: dict[str, Any], *, blocking_shadow_enabled: bool = True) -> dict[str, Any]:
    return brain_module.maybe_run_customer_service_brain(
        config=base_config(plan, blocking_shadow_enabled=blocking_shadow_enabled),
        target_name="许聪",
        target_state={"conversation_context": {}},
        batch=[{"id": "msg1", "sender": "许聪", "content": "秦plus多少钱"}],
        combined="秦plus多少钱",
        decision=ReplyDecision("", "", False, False, ""),
        reply_text="",
        intent_assist={},
        rag_reply={},
        llm_reply={},
        product_knowledge={},
        data_capture={},
        raw_capture={"conversation": {"conversation_id": "c1", "chat_type": "private"}},
        customer_profile=None,
    )


def fake_evidence_pack(*, include_product: bool) -> dict[str, Any]:
    product = {
        "id": "chejin_qinplus_2022_dmi55",
        "name": "2022款比亚迪秦PLUS DM-i 55KM",
        "aliases": ["秦PLUS", "秦plus", "比亚迪秦PLUS", "秦PLUS DM-i"],
        "price": 8.68,
        "authority_level": "product_master",
    }
    products = [product] if include_product else []
    return {
        "schema_version": 1,
        "target": "许聪",
        "current_message": "秦plus多少钱",
        "current_batch": [{"id": "msg1", "sender": "许聪", "content": "秦plus多少钱"}],
        "conversation": {
            "context": {},
            "history": [],
            "history_count": 0,
            "history_text": "",
            "current_batch_text": "[许聪] 秦plus多少钱",
            "conversation_summary": "",
            "raw_conversation_id": "c1",
        },
        "knowledge": {
            "evidence": {
                "products": products,
                "catalog_candidates": products,
                "faq": [],
                "policies": {},
                "product_scoped": [],
                "style_examples": [{"id": "style1", "service_reply": "短句、自然、不机械。"}],
            },
            "product_master": {
                "authority_level": "product_master",
                "can_authorize_product_facts": True,
                "items": products,
            },
            "formal_knowledge": {
                "authority_level": "formal_knowledge",
                "faq": [],
                "policies": {},
                "product_scoped": [],
            },
            "rag_evidence": {"hits": []},
            "ai_experience_pool": {
                "authority_level": "ai_experience_pool",
                "can_authorize_reply_content": False,
                "excluded_hit_count": 1,
            },
            "safety": {"must_handoff": False, "reasons": [], "allowed_auto_reply": True},
            "intent_tags": ["product", "quote"],
        },
        "authority_order": [],
        "common_sense": {},
        "safety": {"must_handoff": False, "reasons": [], "allowed_auto_reply": True},
        "intent_tags": ["product", "quote"],
        "ai_experience_pool": {
            "authority_level": "ai_experience_pool",
            "can_authorize_reply_content": False,
            "excluded_hit_count": 1,
        },
        "rag": {"hits": []},
        "audit_summary": {
            "structured_evidence_count": len(products),
            "runtime_rag_hit_count": 0,
            "rag_hit_count": 0,
            "excluded_ai_experience_pool_hit_count": 1,
            "evidence_ids": ["product:chejin_qinplus_2022_dmi55"] if include_product else [],
        },
    }


def fake_two_candidate_recommendation_pack(message: str) -> dict[str, Any]:
    products = [
        {
            "id": "chejin_mazda3_2020_20l",
            "name": "2020款马自达3昂克赛拉2.0L 自动质雅版",
            "aliases": ["马自达3", "昂克赛拉"],
            "price": 9.58,
            "unit": "万",
            "authority_level": "product_master",
            "match_reason": "budget_alternative_price_fit",
        },
        {
            "id": "chejin_camry_2021_20g",
            "name": "2021款丰田凯美瑞2.0G豪华版",
            "aliases": ["凯美瑞"],
            "price": 8.98,
            "unit": "万",
            "authority_level": "product_master",
            "match_reason": "budget_alternative_price_fit",
        },
    ]
    context = {
        "last_customer_need_text": "预算十万左右，接娃通勤，别太费油，南京能看最好。",
        "last_customer_need_terms": ["预算十万左右", "通勤", "费油", "南京能看"],
    }
    return {
        "schema_version": 1,
        "target": "许聪",
        "current_message": message,
        "current_batch": [{"id": "msg-recommend", "sender": "许聪", "content": message}],
        "conversation": {
            "context": context,
            "history": [],
            "history_count": 0,
            "history_text": "",
            "current_batch_text": f"[许聪] {message}",
            "conversation_summary": "",
            "raw_conversation_id": "c1",
        },
        "knowledge": {
            "evidence": {
                "products": products,
                "catalog_candidates": products,
                "faq": [],
                "policies": {},
                "product_scoped": [],
                "style_examples": [{"id": "style1", "service_reply": "短句、自然、不机械。"}],
            },
            "product_master": {
                "authority_level": "product_master",
                "can_authorize_product_facts": True,
                "items": products,
            },
            "formal_knowledge": {
                "authority_level": "formal_knowledge",
                "faq": [],
                "policies": {},
                "product_scoped": [],
            },
            "conversation_context": context,
            "rag_evidence": {"hits": []},
            "ai_experience_pool": {
                "authority_level": "ai_experience_pool",
                "can_authorize_reply_content": False,
                "excluded_hit_count": 1,
            },
            "safety": {"must_handoff": False, "reasons": [], "allowed_auto_reply": True},
            "intent_tags": ["product", "recommendation"],
        },
        "authority_order": [],
        "common_sense": {},
        "safety": {"must_handoff": False, "reasons": [], "allowed_auto_reply": True},
        "intent_tags": ["product", "recommendation"],
        "ai_experience_pool": {
            "authority_level": "ai_experience_pool",
            "can_authorize_reply_content": False,
            "excluded_hit_count": 1,
        },
        "rag": {"hits": []},
        "audit_summary": {
            "structured_evidence_count": len(products),
            "runtime_rag_hit_count": 0,
            "rag_hit_count": 0,
            "excluded_ai_experience_pool_hit_count": 1,
            "evidence_ids": [f"product:{item['id']}" for item in products],
        },
    }


if __name__ == "__main__":
    raise SystemExit(main())
