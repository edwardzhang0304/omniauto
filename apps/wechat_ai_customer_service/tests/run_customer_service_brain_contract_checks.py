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
import listen_and_reply as workflow_module  # noqa: E402
from listen_and_reply import TargetConfig, process_target, should_adopt_customer_service_brain  # noqa: E402
from customer_service_brain_contract import (  # noqa: E402
    brain_plan_to_guard_candidate,
    join_reply_segments,
    normalize_brain_plan,
    validate_brain_plan,
    verify_brain_reply_quality,
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
        check_normalizes_brain_schema_aliases_without_authorizing_style_facts(),
        check_common_sense_brain_plan_uses_guard_advisor_mode(),
        check_source_id_list_validation_accepts_multiple_product_ids(),
        check_social_brain_plan_clears_soft_no_evidence_guard(),
        check_brain_first_failure_uses_safe_fallback_without_legacy(),
        check_rejects_product_scoped_master_fact(),
        check_rejects_formal_policy_fact_without_source_id(),
        check_quality_gate_rejects_generic_stall_for_price(),
        check_quality_gate_rejects_social_info_collection(),
        check_quality_gate_requires_clear_recommendation(),
        check_brain_prompt_separates_style_from_content_basis(),
        check_brain_prompt_includes_runtime_principles_without_authorizing_facts(),
        check_brain_prompt_compacts_large_context_under_timeout_budget(),
        check_repair_prompt_preserves_authority_boundaries(),
        check_shadow_non_blocking_defers_without_llm(),
        check_shadow_brain_runner_passes_guard(),
        check_brain_runner_rejects_quality_failed_plan(),
        check_guard_rejects_unsupported_price_without_product_master(),
        check_brain_adoption_gate(),
        check_process_target_brain_first_adopts(),
        check_process_target_brain_first_exception_uses_safe_fallback(),
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
    assert_true(len(slim["auxiliary"]["rag"]["hits"]) == 1, "RAG prompt hits should be capped")
    return CaseResult("brain_prompt_compacts_large_context_under_timeout_budget", True, {"prompt_estimate": estimate})


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
    return CaseResult("shadow_brain_runner_passes_guard", True, {"reason": event.get("reason"), "duration": event.get("duration_seconds")})


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


def check_guard_rejects_unsupported_price_without_product_master() -> CaseResult:
    plan = base_plan()
    with patched_evidence_pack(fake_evidence_pack(include_product=False)):
        event = run_brain(plan)
    assert_true(not event.get("applied"), f"price without product evidence must be rejected: {event}")
    errors = (event.get("plan_validation") or {}).get("errors", [])
    assert_true(any("product_fact_source_not_in_evidence" in str(item) for item in errors), f"expected source-id evidence rejection: {event}")
    return CaseResult("guard_rejects_unsupported_price_without_product_master", True, {"reason": event.get("reason"), "errors": errors})


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
    assert_true(event.get("customer_service_brain_adopted", {}).get("applied") is True, f"brain_first should adopt: {event}")
    assert_true(event.get("customer_service_brain_legacy_generators", {}).get("disabled") is True, f"legacy generators should be disabled: {event}")
    assert_true(decision.get("raw_reply_text") == "Brain回复", f"decision should use brain reply: {decision}")
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
    assert_true(brain.get("rule_name") == "customer_service_brain_safe_fallback", f"Brain exception should produce safe fallback: {event}")
    assert_true(event.get("customer_service_brain_adopted", {}).get("applied") is True, f"safe fallback should be adopted: {event}")
    assert_true(decision.get("raw_reply_text") == "在的，您说。", f"decision should not use legacy reply: {decision}")
    return CaseResult("process_target_brain_first_exception_uses_safe_fallback", True, {"rule": decision.get("rule_name")})


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


if __name__ == "__main__":
    raise SystemExit(main())
