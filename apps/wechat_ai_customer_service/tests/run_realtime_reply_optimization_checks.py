"""Checks for real-time reply routing, token budget, and listener watchdog."""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
WORKFLOWS_ROOT = APP_ROOT / "workflows"
ADAPTERS_ROOT = APP_ROOT / "adapters"
SCRIPTS_ROOT = APP_ROOT / "scripts"
for path in (PROJECT_ROOT, APP_ROOT, WORKFLOWS_ROOT, ADAPTERS_ROOT, SCRIPTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from apps.wechat_ai_customer_service.knowledge_paths import tenant_context  # noqa: E402
from knowledge_loader import build_evidence_pack  # noqa: E402
from rag_answer_layer import extract_service_style_snippet  # noqa: E402
from realtime_reply_router import (  # noqa: E402
    build_need_summary,
    decide_realtime_reply_route,
    extract_budget_wan,
    initial_token_budget,
    maybe_build_realtime_reply,
    reply_similarity,
)
from listen_and_reply import build_realtime_context_combined, recent_customer_visible_reply_texts  # noqa: E402
from run_customer_service_listener import run_once  # noqa: E402


TENANT_ID = "chejin"


class Decision:
    matched = False
    need_handoff = False
    rule_name = "no_rule"
    reason = "no_rule_matched"
    reply_text = "收到，我先看一下。"


class Intent:
    intent = "product_inquiry"

    def to_dict(self) -> dict[str, Any]:
        return {"intent": self.intent}


def main() -> int:
    results = [
        check_local_recommendation_zero_token(),
        check_detailed_first_request_can_recommend_without_reasking_budget(),
        check_business_equipment_request_can_recommend_without_reasking_budget(),
        check_business_equipment_followup_direction_uses_candidates(),
        check_business_equipment_cargo_space_question_stays_local(),
        check_business_vehicle_compare_does_not_leak_unasked_tiguan(),
        check_city_business_guidance_does_not_leak_spouse_context(),
        check_vehicle_condition_disclosure_question_stays_local(),
        check_trade_in_on_site_followup_stays_local(),
        check_trade_in_condition_with_specific_vehicle_preference_uses_candidates(),
        check_specific_price_approval_requires_handoff(),
        check_same_day_delivery_after_testdrive_requires_handoff(),
        check_store_arrival_contact_requires_handoff(),
        check_split_need_burst_recommends_candidates_under_strict_budget(),
        check_short_strict_budget_cap_keeps_within_wording(),
        check_chinese_budget_range_prefers_longest_match(),
        check_realtime_context_bridge_uses_prior_need_for_followup_candidates(),
        check_recent_reply_requirement_context_keeps_strict_budget_when_marked_history_is_skipped(),
        check_context_bridge_current_visit_question_preempts_old_recommendation_need(),
        check_context_bridge_current_compare_question_preempts_candidate_refresh(),
        check_realtime_context_bridge_skips_unrelated_or_test_marked_history(),
        check_identity_probe_uses_local_denial_without_foreground_llm(),
        check_generic_recommendation_avoids_overused_random_push_phrase(),
        check_explicit_first_request_can_recommend_vehicle_sources(),
        check_specific_finance_question_does_not_force_vehicle_sources(),
        check_safe_no_deposit_report_visit_stays_local(),
        check_greeting_with_business_context_is_not_pure_greeting(),
        check_followup_can_recommend_vehicle_sources(),
        check_visit_report_prep_stays_appointment_style(),
        check_followup_visit_request_stays_appointment_style(),
        check_used_car_recommendation_filters_non_car_products(),
        check_trade_in_price_wording_stays_local(),
        check_repeated_scene_uses_reply_variant(),
        check_repeated_recommendation_structure_is_diverse(),
        check_high_risk_skips_foreground_llm(),
        check_rag_metadata_cleanup(),
        check_listener_watchdog_timeout(),
    ]
    failures = [item for item in results if not item.get("ok")]
    payload = {"ok": not failures, "failures": failures, "results": results}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


def check_local_recommendation_zero_token() -> dict[str, Any]:
    config = {"realtime_reply": {"enabled": True}, "llm_reply_synthesis": {"enabled": True}}
    message = "我刚拿驾照，想买台练手车，平时接娃买菜，别太费油。"
    with tenant_context(TENANT_ID):
        evidence_pack = build_evidence_pack(message, context={})
    route = decide_realtime_reply_route(
        config=config,
        combined=message,
        decision=Decision(),
        intent_result=Intent(),
        intent_assist={"intent": "product_inquiry", "evidence": {"safety": {"must_handoff": False}}},
        rag_reply={},
        llm_reply={},
        product_knowledge={},
        data_capture={},
        evidence_pack=evidence_pack,
    )
    reply = maybe_build_realtime_reply(
        config=config,
        route=route,
        combined=message,
        evidence_pack=evidence_pack,
        current_reply_text="",
    )
    budget = initial_token_budget(route)
    ok = (
        route.get("level") == "L1"
        and route.get("foreground_llm_allowed") is False
        and reply.get("applied") is True
        and reply.get("reason") == "first_broad_recommendation_stays_consultative"
        and not reply.get("used_product_ids")
        and budget.get("actual_total_tokens") == 0
        and "CHEJIN_" not in str(reply.get("reply_text") or "")
        and "聊天记录" not in str(reply.get("reply_text") or "")
        and "不乱推" not in str(reply.get("reply_text") or "")
    )
    return {"name": "local_recommendation_zero_token", "ok": ok, "route": route, "reply": reply, "budget": budget}


def check_detailed_first_request_can_recommend_without_reasking_budget() -> dict[str, Any]:
    config = {"realtime_reply": {"enabled": True}, "llm_reply_synthesis": {"enabled": True}}
    message = "刚拿驾照，想买台七八万练手车，平时接娃买菜，别太费油。"
    with tenant_context(TENANT_ID):
        evidence_pack = build_evidence_pack(message, context={})
        route = decide_realtime_reply_route(
            config=config,
            combined=message,
            decision=Decision(),
            intent_result=Intent(),
            intent_assist={"intent": "product_inquiry", "evidence": {"safety": {"must_handoff": False}}},
            rag_reply={},
            llm_reply={},
            product_knowledge={},
            data_capture={},
            evidence_pack=evidence_pack,
            recent_reply_texts=[],
        )
        reply = maybe_build_realtime_reply(
            config=config,
            route=route,
            combined=message,
            evidence_pack=evidence_pack,
            current_reply_text="",
            recent_reply_texts=[],
        )
    text = str(reply.get("reply_text") or "")
    ok = (
        route.get("level") == "L1"
        and route.get("reason") == "detailed_vehicle_need_ready_for_candidates"
        and reply.get("applied") is True
        and bool(reply.get("used_product_ids"))
        and not any(marker in text for marker in ("您把预算", "说下预算", "预算大概", "确认一下预算", "预算上限"))
        and any(marker in text for marker in ("检测报告", "车况", "公里"))
    )
    return {"name": "detailed_first_request_can_recommend_without_reasking_budget", "ok": ok, "route": route, "reply": reply}


def check_business_equipment_request_can_recommend_without_reasking_budget() -> dict[str, Any]:
    config = {"realtime_reply": {"enabled": True}, "llm_reply_synthesis": {"enabled": True}}
    message = "我开摄影工作室，想买台能拉灯架和相机箱的车，偶尔也接客户，预算16万以内。"
    with tenant_context(TENANT_ID):
        evidence_pack = build_evidence_pack(message, context={})
        route = decide_realtime_reply_route(
            config=config,
            combined=message,
            decision=Decision(),
            intent_result=Intent(),
            intent_assist={"intent": "product_inquiry", "evidence": {"safety": {"must_handoff": False}}},
            rag_reply={},
            llm_reply={},
            product_knowledge={},
            data_capture={},
            evidence_pack=evidence_pack,
            recent_reply_texts=[],
        )
        reply = maybe_build_realtime_reply(
            config=config,
            route=route,
            combined=message,
            evidence_pack=evidence_pack,
            current_reply_text="",
            recent_reply_texts=[],
        )
    text = str(reply.get("reply_text") or "")
    ok = (
        route.get("reason") == "detailed_vehicle_need_ready_for_candidates"
        and reply.get("applied") is True
        and bool(reply.get("used_product_ids"))
        and any(marker in text for marker in ("后备", "装载", "工作室", "接客户", "空间", "车况"))
        and not any(marker in text for marker in ("您把预算", "说下预算", "预算大概", "确认一下预算", "预算上限", "您先说下预算"))
    )
    return {"name": "business_equipment_request_can_recommend_without_reasking_budget", "ok": ok, "route": route, "reply": reply}


def check_business_equipment_followup_direction_uses_candidates() -> dict[str, Any]:
    config = {"realtime_reply": {"enabled": True}, "llm_reply_synthesis": {"enabled": True}}
    message = "你别只问我需求，先按16万内给我两三个方向，后备厢要实用一点。"
    recent = ["信息已经够先筛了：16万以内、工作室用车/偶尔接客户、后备厢和装载实用。"]
    with tenant_context(TENANT_ID):
        evidence_pack = build_evidence_pack(message, context={})
        route = decide_realtime_reply_route(
            config=config,
            combined=message,
            decision=Decision(),
            intent_result=Intent(),
            intent_assist={"intent": "product_inquiry", "evidence": {"safety": {"must_handoff": True, "reasons": ["no_relevant_business_evidence"]}}},
            rag_reply={},
            llm_reply={},
            product_knowledge={},
            data_capture={},
            evidence_pack=evidence_pack,
            recent_reply_texts=recent,
        )
        reply = maybe_build_realtime_reply(
            config=config,
            route=route,
            combined=message,
            evidence_pack=evidence_pack,
            current_reply_text="",
            recent_reply_texts=recent,
        )
    text = str(reply.get("reply_text") or "")
    ok = (
        route.get("reason") in {"explicit_vehicle_candidates_requested", "followup_ready_for_vehicle_candidates"}
        and route.get("level") == "L1"
        and reply.get("applied") is True
        and bool(reply.get("used_product_ids"))
        and "请示" not in text
        and "转人工" not in text
        and "16.8万" not in text
        and any(marker in text for marker in ("后备", "空间", "车况", "检测报告", "工作室"))
    )
    return {"name": "business_equipment_followup_direction_uses_candidates", "ok": ok, "route": route, "reply": reply}


def check_business_equipment_cargo_space_question_stays_local() -> dict[str, Any]:
    config = {"realtime_reply": {"enabled": True}, "llm_reply_synthesis": {"enabled": True}}
    message = "我有两套灯架、背景架和三个箱子，第二排能不能放倒装东西？"
    recent = ["可以先看途观L和奇骏，重点看后备厢和装载实用。"]
    route = decide_realtime_reply_route(
        config=config,
        combined=message,
        decision=Decision(),
        intent_result=Intent(),
        intent_assist={"intent": "product_inquiry", "evidence": {"safety": {"must_handoff": True, "reasons": ["no_relevant_business_evidence"]}}},
        rag_reply={},
        llm_reply={},
        product_knowledge={},
        data_capture={},
        evidence_pack={},
        recent_reply_texts=recent,
    )
    reply = maybe_build_realtime_reply(
        config=config,
        route=route,
        combined=message,
        evidence_pack={},
        current_reply_text="",
        recent_reply_texts=recent,
    )
    text = str(reply.get("reply_text") or "")
    ok = (
        route.get("reason") == "common_cargo_space_guidance_can_use_local_style"
        and route.get("foreground_llm_allowed") is False
        and reply.get("applied") is True
        and any(marker in text for marker in ("第二排", "后备厢", "实车", "尺寸", "现场", "装"))
        and "请示" not in text
        and "转人工" not in text
    )
    return {"name": "business_equipment_cargo_space_question_stays_local", "ok": ok, "route": route, "reply": reply}


def check_business_vehicle_compare_does_not_leak_unasked_tiguan() -> dict[str, Any]:
    config = {"realtime_reply": {"enabled": True}, "llm_reply_synthesis": {"enabled": True}}
    message = "奇骏和哈弗H6哪个更适合公司用？接客户也别太寒酸。"
    recent = [
        "从14万以内、工作室用车/偶尔接客户、后备厢和装载实用这个条件看，奇骏和哈弗H6可以先排在前面。"
    ]
    route = decide_realtime_reply_route(
        config=config,
        combined=message,
        decision=Decision(),
        intent_result=Intent(),
        intent_assist={"intent": "product_inquiry", "evidence": {"safety": {"must_handoff": False, "reasons": []}}},
        rag_reply={},
        llm_reply={},
        product_knowledge={},
        data_capture={},
        evidence_pack={},
        recent_reply_texts=recent,
    )
    reply = maybe_build_realtime_reply(
        config=config,
        route=route,
        combined=message,
        evidence_pack={},
        current_reply_text="",
        recent_reply_texts=recent,
    )
    text = str(reply.get("reply_text") or "")
    forbidden = ("途观", "老婆", "爱人", "女司机", "露营")
    ok = (
        route.get("reason") == "common_vehicle_compare_can_use_local_style"
        and reply.get("applied") is True
        and "奇骏" in text
        and ("H6" in text or "哈弗" in text)
        and not any(marker in text for marker in forbidden)
    )
    return {"name": "business_vehicle_compare_does_not_leak_unasked_tiguan", "ok": ok, "route": route, "reply": reply}


def check_city_business_guidance_does_not_leak_spouse_context() -> dict[str, Any]:
    config = {"realtime_reply": {"enabled": True}, "llm_reply_synthesis": {"enabled": True}}
    message = "市区跑展会比较多，油耗和后期维护哪个更稳？"
    recent = ["奇骏和哈弗H6都能看，重点核后备厢、车况和公司接待场景。"]
    route = decide_realtime_reply_route(
        config=config,
        combined=message,
        decision=Decision(),
        intent_result=Intent(),
        intent_assist={"intent": "product_inquiry", "evidence": {"safety": {"must_handoff": False, "reasons": []}}},
        rag_reply={},
        llm_reply={},
        product_knowledge={},
        data_capture={},
        evidence_pack={},
        recent_reply_texts=recent,
    )
    reply = maybe_build_realtime_reply(
        config=config,
        route=route,
        combined=message,
        evidence_pack={},
        current_reply_text="",
        recent_reply_texts=recent,
    )
    text = str(reply.get("reply_text") or "")
    forbidden = ("老婆", "爱人", "女士", "女司机", "她试", "她开")
    ok = (
        route.get("level") == "L1"
        and reply.get("applied") is True
        and any(marker in text for marker in ("市区", "油耗", "维护", "车况", "成本", "装载", "停车"))
        and not any(marker in text for marker in forbidden)
    )
    return {"name": "city_business_guidance_does_not_leak_spouse_context", "ok": ok, "route": route, "reply": reply}


def check_vehicle_condition_disclosure_question_stays_local() -> dict[str, Any]:
    config = {"realtime_reply": {"enabled": True}, "llm_reply_synthesis": {"enabled": True}}
    message = "车况这块我比较怕事故车，补漆和换件你们会说清楚吗？"
    route = decide_realtime_reply_route(
        config=config,
        combined=message,
        decision=Decision(),
        intent_result=Intent(),
        intent_assist={"intent": "unknown", "evidence": {"safety": {"must_handoff": False, "reasons": []}}},
        rag_reply={},
        llm_reply={},
        product_knowledge={},
        data_capture={},
        evidence_pack={},
        recent_reply_texts=[],
    )
    reply = maybe_build_realtime_reply(
        config=config,
        route=route,
        combined=message,
        evidence_pack={},
        current_reply_text="",
        recent_reply_texts=[],
    )
    text = str(reply.get("reply_text") or "")
    ok = (
        route.get("reason") == "common_inspection_guidance_can_use_local_style"
        and route.get("foreground_llm_allowed") is False
        and reply.get("applied") is True
        and any(marker in text for marker in ("检测报告", "出险", "补漆", "换件", "事故", "车况"))
        and "请示" not in text
        and "转人工" not in text
    )
    return {"name": "vehicle_condition_disclosure_question_stays_local", "ok": ok, "route": route, "reply": reply}


def check_trade_in_on_site_followup_stays_local() -> dict[str, Any]:
    config = {"realtime_reply": {"enabled": True}, "llm_reply_synthesis": {"enabled": True}}
    message = "老车有几处补漆，开过去能现场估吗？"
    route = decide_realtime_reply_route(
        config=config,
        combined=message,
        decision=Decision(),
        intent_result=Intent(),
        intent_assist={"intent": "product_inquiry", "evidence": {"safety": {"must_handoff": False, "reasons": []}}},
        rag_reply={},
        llm_reply={},
        product_knowledge={},
        data_capture={},
        evidence_pack={},
        recent_reply_texts=["置换可以先估一版，最终结合实车检测。"],
    )
    reply = maybe_build_realtime_reply(
        config=config,
        route=route,
        combined=message,
        evidence_pack={},
        current_reply_text="",
        recent_reply_texts=["置换可以先估一版，最终结合实车检测。"],
    )
    text = str(reply.get("reply_text") or "")
    ok = (
        route.get("reason") == "common_trade_in_collect_can_use_local_style"
        and route.get("foreground_llm_allowed") is False
        and reply.get("applied") is True
        and any(marker in text for marker in ("现场", "评估", "检测", "照片", "车况", "行情"))
        and "请示" not in text
        and "转人工" not in text
    )
    return {"name": "trade_in_on_site_followup_stays_local", "ok": ok, "route": route, "reply": reply}


def check_trade_in_condition_with_specific_vehicle_preference_uses_candidates() -> dict[str, Any]:
    config = {"realtime_reply": {"enabled": True}, "llm_reply_synthesis": {"enabled": True}}
    message = "如果置换价合适，我更想看途观L，奇骏当备选。"
    with tenant_context(TENANT_ID):
        evidence_pack = build_evidence_pack(message, context={})
        route = decide_realtime_reply_route(
            config=config,
            combined=message,
            decision=Decision(),
            intent_result=Intent(),
            intent_assist={"intent": "product_inquiry", "evidence": {"safety": {"must_handoff": False, "reasons": []}}},
            rag_reply={},
            llm_reply={},
            product_knowledge={},
            data_capture={},
            evidence_pack=evidence_pack,
            recent_reply_texts=["可以带过来估，现场看实车；途观L和奇骏都可以安排看。"],
        )
        reply = maybe_build_realtime_reply(
            config=config,
            route=route,
            combined=message,
            evidence_pack=evidence_pack,
            current_reply_text="这个需要负责人确认一下，我把情况记下，问清楚后再回复您。",
            recent_reply_texts=["可以带过来估，现场看实车；途观L和奇骏都可以安排看。"],
        )
    text = str(reply.get("reply_text") or "")
    ok = (
        route.get("reason") in {"explicit_vehicle_candidates_requested", "followup_ready_for_vehicle_candidates"}
        and route.get("foreground_llm_allowed") is False
        and reply.get("applied") is True
        and bool(reply.get("used_product_ids"))
        and any(marker in text for marker in ("途观", "奇骏", "备选", "车况", "检测"))
        and "车型年份" not in text
        and "发我车型" not in text
    )
    return {"name": "trade_in_condition_with_specific_vehicle_preference_uses_candidates", "ok": ok, "route": route, "reply": reply}


def check_specific_price_approval_requires_handoff() -> dict[str, Any]:
    message = "这台途观L价格15.8，你帮我问问15整能不能谈？"
    route = decide_realtime_reply_route(
        config={"realtime_reply": {"enabled": True}, "llm_reply_synthesis": {"enabled": True}},
        combined=message,
        decision=Decision(),
        intent_result=Intent(),
        intent_assist={"intent": "quote_request", "evidence": {"safety": {"must_handoff": False, "reasons": []}}},
        rag_reply={},
        llm_reply={},
        product_knowledge={},
        data_capture={},
        evidence_pack={},
        recent_reply_texts=["途观L可以优先看，价格再结合车况和置换确认。"],
    )
    ok = (
        route.get("level") == "L0"
        and route.get("reason") == "deterministic_handoff_or_high_risk_boundary"
        and route.get("foreground_llm_allowed") is False
    )
    return {"name": "specific_price_approval_requires_handoff", "ok": ok, "route": route}


def check_same_day_delivery_after_testdrive_requires_handoff() -> dict[str, Any]:
    message = "如果试驾没问题，我当天能不能直接办手续提车？"
    route = decide_realtime_reply_route(
        config={"realtime_reply": {"enabled": True}, "llm_reply_synthesis": {"enabled": True}},
        combined=message,
        decision=Decision(),
        intent_result=Intent(),
        intent_assist={"intent": "policy_inquiry", "evidence": {"safety": {"must_handoff": False, "reasons": []}}},
        rag_reply={},
        llm_reply={},
        product_knowledge={},
        data_capture={},
        evidence_pack={},
        recent_reply_texts=["试驾前带身份证和驾驶证就行，我这边先帮您核车源。"],
    )
    ok = (
        route.get("level") == "L0"
        and route.get("reason") == "deterministic_handoff_or_high_risk_boundary"
        and route.get("foreground_llm_allowed") is False
    )
    return {"name": "same_day_delivery_after_testdrive_requires_handoff", "ok": ok, "route": route}


def check_store_arrival_contact_requires_handoff() -> dict[str, Any]:
    message = "最后确认下，你们店地址和到了找谁？我别跑错。"
    route = decide_realtime_reply_route(
        config={"realtime_reply": {"enabled": True}, "llm_reply_synthesis": {"enabled": True}},
        combined=message,
        decision=Decision(),
        intent_result=Intent(),
        intent_assist={"intent": "policy_inquiry", "evidence": {"safety": {"must_handoff": False, "reasons": []}}},
        rag_reply={},
        llm_reply={},
        product_knowledge={},
        data_capture={},
        evidence_pack={},
        recent_reply_texts=["周六下午四点我先帮您核排期，车源和试驾一起确认。"],
    )
    ok = (
        route.get("level") == "L0"
        and route.get("reason") == "deterministic_handoff_or_high_risk_boundary"
        and route.get("foreground_llm_allowed") is False
    )
    return {"name": "store_arrival_contact_requires_handoff", "ok": ok, "route": route}


def check_split_need_burst_recommends_candidates_under_strict_budget() -> dict[str, Any]:
    config = {"realtime_reply": {"enabled": True}, "llm_reply_synthesis": {"enabled": True}}
    message = "客户连续补充同一个需求：\n- 帮我看个车。\n- 主要给我老婆开。\n- 她停车不太熟练。\n- 预算别超过9万。\n- 最好自动挡，有倒车影像。"
    with tenant_context(TENANT_ID):
        evidence_pack = build_evidence_pack(message, context={})
        route = decide_realtime_reply_route(
            config=config,
            combined=message,
            decision=Decision(),
            intent_result=Intent(),
            intent_assist={"intent": "product_inquiry", "evidence": {"safety": {"must_handoff": False}}},
            rag_reply={},
            llm_reply={},
            product_knowledge={},
            data_capture={},
            evidence_pack=evidence_pack,
            recent_reply_texts=[],
        )
        reply = maybe_build_realtime_reply(
            config=config,
            route=route,
            combined=message,
            evidence_pack=evidence_pack,
            current_reply_text="",
            recent_reply_texts=[],
        )
    text = str(reply.get("reply_text") or "")
    used_ids = set(reply.get("used_product_ids") or [])
    ok = (
        route.get("reason") == "detailed_vehicle_need_ready_for_candidates"
        and reply.get("applied") is True
        and bool(used_ids)
        and "chejin_mazda3_2020_20l" not in used_ids
        and "9.58万" not in text
        and any(marker in text for marker in ("老婆", "爱人", "停车", "倒车", "影像", "自动挡"))
        and not any(marker in text for marker in ("您把预算", "说下预算", "预算大概", "确认一下预算", "预算上限"))
    )
    return {"name": "split_need_burst_recommends_candidates_under_strict_budget", "ok": ok, "route": route, "reply": reply}


def check_short_strict_budget_cap_keeps_within_wording() -> dict[str, Any]:
    message = "我老婆开，预算别超9万，停车不太熟，自动挡带影像"
    summary = build_need_summary(message)
    ok = "9万以内" in summary and "9万左右" not in summary
    return {"name": "short_strict_budget_cap_keeps_within_wording", "ok": ok, "summary": summary}


def check_chinese_budget_range_prefers_longest_match() -> dict[str, Any]:
    cases = {
        "三四万": 3.5,
        "十三四万": 13.5,
        "十四五万": 14.5,
        "十五六万": 15.5,
    }
    parsed = {text: extract_budget_wan(f"预算{text}，想买个家用车") for text in cases}
    ok = all(abs(parsed[text] - expected) < 0.01 for text, expected in cases.items())
    return {"name": "chinese_budget_range_prefers_longest_match", "ok": ok, "parsed": parsed}


def check_realtime_context_bridge_uses_prior_need_for_followup_candidates() -> dict[str, Any]:
    config = {"realtime_reply": {"enabled": True}, "llm_reply_synthesis": {"enabled": True}}
    target_state = {
        "sent_replies": [
            {
                "processed_at": datetime.now().isoformat(),
                "message_contents": [
                    "我家两个小孩，平时老婆接送，预算9万内，想自动挡省油，最好有倒车影像。",
                ],
                "reply_text": "信息挺清楚了，9万内可以先按省油自动挡、好停车、车况透明去筛两三台。",
            }
        ]
    }
    current = "那你直接挑两台吧，别再问预算了"
    combined = build_realtime_context_combined(current, target_state)
    recent = [target_state["sent_replies"][0]["reply_text"]]
    with tenant_context(TENANT_ID):
        evidence_pack = build_evidence_pack(combined, context={})
        route = decide_realtime_reply_route(
            config=config,
            combined=combined,
            decision=Decision(),
            intent_result=Intent(),
            intent_assist={"intent": "product_inquiry", "evidence": {"safety": {"must_handoff": False}}},
            rag_reply={},
            llm_reply={},
            product_knowledge={},
            data_capture={},
            evidence_pack=evidence_pack,
            recent_reply_texts=recent,
        )
        reply = maybe_build_realtime_reply(
            config=config,
            route=route,
            combined=combined,
            evidence_pack=evidence_pack,
            current_reply_text="",
            recent_reply_texts=recent,
        )
    text = str(reply.get("reply_text") or "")
    used_ids = set(reply.get("used_product_ids") or [])
    ok = (
        "近期客户需求" in combined
        and route.get("level") == "L1"
        and route.get("reason") in {"followup_ready_for_vehicle_candidates", "explicit_vehicle_candidates_requested", "detailed_vehicle_need_ready_for_candidates"}
        and reply.get("applied") is True
        and bool(used_ids)
        and "chejin_haval_h6_2020_20t" not in used_ids
        and any(marker in text for marker in ("老婆", "爱人", "停车", "倒车", "影像", "自动挡", "省油"))
        and not any(marker in text for marker in ("您把预算", "说下预算", "预算大概", "确认一下预算", "预算上限"))
    )
    return {"name": "realtime_context_bridge_uses_prior_need_for_followup_candidates", "ok": ok, "combined": combined, "route": route, "reply": reply}


def check_recent_reply_requirement_context_keeps_strict_budget_when_marked_history_is_skipped() -> dict[str, Any]:
    config = {"realtime_reply": {"enabled": True}, "llm_reply_synthesis": {"enabled": True}}
    current = "那就按刚才说的，直接挑两台，别再问预算了"
    state = {
        "sent_replies": [
            {
                "processed_at": datetime.now().isoformat(),
                "message_contents": ["我老婆开，预算9万以内，自动挡带影像。(LIVEFLOW_20260519_CTX)"],
                "reply_text": "老板，需求这块已经不算泛了：9万以内、主要给您爱人开、自动挡、倒车/影像配置优先、日常家用代步。先把车况透明、好停车的放前面看。",
            }
        ]
    }
    combined = build_realtime_context_combined(current, state)
    recent = recent_customer_visible_reply_texts(state)
    with tenant_context(TENANT_ID):
        evidence_pack = build_evidence_pack(combined, context={})
        route = decide_realtime_reply_route(
            config=config,
            combined=combined,
            decision=Decision(),
            intent_result=Intent(),
            intent_assist={"intent": "product_inquiry", "evidence": {"safety": {"must_handoff": False}}},
            rag_reply={},
            llm_reply={},
            product_knowledge={},
            data_capture={},
            evidence_pack=evidence_pack,
            recent_reply_texts=recent,
        )
        reply = maybe_build_realtime_reply(
            config=config,
            route=route,
            combined=combined,
            evidence_pack=evidence_pack,
            current_reply_text="",
            recent_reply_texts=recent,
        )
    text = str(reply.get("reply_text") or "")
    used_ids = set(reply.get("used_product_ids") or [])
    ok = (
        combined == current
        and recent == [state["sent_replies"][0]["reply_text"]]
        and route.get("level") == "L1"
        and route.get("reason") in {"followup_ready_for_vehicle_candidates", "explicit_vehicle_candidates_requested"}
        and reply.get("applied") is True
        and bool(used_ids)
        and "chejin_mazda3_2020_20l" not in used_ids
        and "9.58万" not in text
        and any(marker in text for marker in ("9万以内", "停车", "倒车", "影像", "自动挡", "爱人", "老婆"))
        and not any(marker in text for marker in ("您把预算", "说下预算", "预算大概", "确认一下预算", "预算上限", "您先说下预算"))
    )
    return {
        "name": "recent_reply_requirement_context_keeps_strict_budget_when_marked_history_is_skipped",
        "ok": ok,
        "combined": combined,
        "recent": recent,
        "route": route,
        "reply": reply,
    }


def check_context_bridge_current_visit_question_preempts_old_recommendation_need() -> dict[str, Any]:
    config = {"realtime_reply": {"enabled": True}, "llm_reply_synthesis": {"enabled": True}}
    combined = (
        "近期客户需求：\n"
        "- 我想给我老婆换台代步车，平时接送孩子和买菜，预算9万以内，自动挡，最好有倒车影像。\n"
        "- 这两台里哪个更适合新手停车？我老婆倒车不太熟。\n"
        "当前客户问题：如果周末去看，能不能把检测报告也提前准备好？"
    )
    route = decide_realtime_reply_route(
        config=config,
        combined=combined,
        decision=Decision(),
        intent_result=Intent(),
        intent_assist={"intent": "product_inquiry", "evidence": {"safety": {"must_handoff": False}}},
        rag_reply={},
        llm_reply={},
        product_knowledge={},
        data_capture={},
        evidence_pack={},
        recent_reply_texts=["刚才推荐过凌派和Polo，可以重点看车况和停车辅助。"],
    )
    reply = maybe_build_realtime_reply(
        config=config,
        route=route,
        combined=combined,
        evidence_pack={},
        current_reply_text="",
        recent_reply_texts=["刚才推荐过凌派和Polo，可以重点看车况和停车辅助。"],
    )
    text = str(reply.get("reply_text") or "")
    ok = (
        route.get("reason") == "common_visit_timing_can_use_local_style"
        and reply.get("applied") is True
        and any(marker in text for marker in ("周末", "检测报告", "车源", "排期", "确认"))
        and not reply.get("used_product_ids")
    )
    return {"name": "context_bridge_current_visit_question_preempts_old_recommendation_need", "ok": ok, "route": route, "reply": reply}


def check_context_bridge_current_compare_question_preempts_candidate_refresh() -> dict[str, Any]:
    config = {"realtime_reply": {"enabled": True}, "llm_reply_synthesis": {"enabled": True}}
    combined = (
        "近期客户需求：\n"
        "- 我想给我老婆换台代步车，预算9万以内，自动挡，最好有倒车影像。\n"
        "当前客户问题：这两台里哪个更适合新手停车？我老婆倒车不太熟。"
    )
    recent = ["按您说的9万以内，可以先看凌派和Polo，重点看车况、自动挡和停车辅助。"]
    route = decide_realtime_reply_route(
        config=config,
        combined=combined,
        decision=Decision(),
        intent_result=Intent(),
        intent_assist={"intent": "product_inquiry", "evidence": {"safety": {"must_handoff": False}}},
        rag_reply={},
        llm_reply={},
        product_knowledge={},
        data_capture={},
        evidence_pack={},
        recent_reply_texts=recent,
    )
    reply = maybe_build_realtime_reply(
        config=config,
        route=route,
        combined=combined,
        evidence_pack={},
        current_reply_text="",
        recent_reply_texts=recent,
    )
    text = str(reply.get("reply_text") or "")
    ok = (
        route.get("reason") == "common_vehicle_compare_can_use_local_style"
        and reply.get("applied") is True
        and not reply.get("used_product_ids")
        and any(marker in text for marker in ("停车", "好停", "好开", "车况", "试"))
    )
    return {"name": "context_bridge_current_compare_question_preempts_candidate_refresh", "ok": ok, "route": route, "reply": reply}


def check_realtime_context_bridge_skips_unrelated_or_test_marked_history() -> dict[str, Any]:
    now = datetime.now().isoformat()
    clean_state = {
        "sent_replies": [
            {
                "processed_at": now,
                "message_contents": ["我老婆开，预算9万内，自动挡带影像。"],
                "reply_text": "我按9万内、自动挡、好停车帮您筛。",
            }
        ]
    }
    tagged_state = {
        "sent_replies": [
            {
                "processed_at": now,
                "message_contents": ["我老婆开，预算9万内，自动挡带影像。(LIVEFLOW_20260519_CTX)"],
                "reply_text": "我按9万内、自动挡、好停车帮您筛。(LIVEFLOW_20260519_CTX)",
            }
        ]
    }
    unrelated = build_realtime_context_combined("合同和发票怎么开？", clean_state)
    tagged = build_realtime_context_combined("那你直接挑两台吧，别再问预算了", tagged_state)
    ok = unrelated == "合同和发票怎么开？" and tagged == "那你直接挑两台吧，别再问预算了"
    return {"name": "realtime_context_bridge_skips_unrelated_or_test_marked_history", "ok": ok, "unrelated": unrelated, "tagged": tagged}


def check_identity_probe_uses_local_denial_without_foreground_llm() -> dict[str, Any]:
    message = "你这边是真人吗，还是AI自动回的？"
    config = {
        "realtime_reply": {"enabled": True},
        "llm_reply_synthesis": {"enabled": True, "identity_guard_enabled": True},
    }
    route = decide_realtime_reply_route(
        config=config,
        combined=message,
        decision=Decision(),
        intent_result=Intent(),
        intent_assist={"intent": "unknown", "evidence": {"safety": {"must_handoff": True, "reasons": ["no_relevant_business_evidence"]}}},
        rag_reply={},
        llm_reply={},
        product_knowledge={},
        data_capture={},
        evidence_pack={},
        recent_reply_texts=[],
    )
    reply = maybe_build_realtime_reply(
        config=config,
        route=route,
        combined=message,
        evidence_pack={},
        current_reply_text="",
        recent_reply_texts=[],
    )
    text = str(reply.get("reply_text") or "")
    ok = (
        route.get("level") == "L1"
        and route.get("reason") == "identity_probe_can_use_local_style"
        and route.get("foreground_llm_allowed") is False
        and reply.get("rule_name") == "realtime_identity_probe"
        and ("不是AI" in text or "不是机器人" in text)
        and not any(marker in text for marker in ("我是AI", "我是机器人", "转人工", "人工客服"))
    )
    return {"name": "identity_probe_uses_local_denial_without_foreground_llm", "ok": ok, "route": route, "reply": reply}


def check_generic_recommendation_avoids_overused_random_push_phrase() -> dict[str, Any]:
    config = {"realtime_reply": {"enabled": True}, "llm_reply_synthesis": {"enabled": True}}
    message = "我想先看看二手车，预算还没完全定，平时家里代步用。"
    route = decide_realtime_reply_route(
        config=config,
        combined=message,
        decision=Decision(),
        intent_result=Intent(),
        intent_assist={"intent": "product_inquiry", "evidence": {"safety": {"must_handoff": False}}},
        rag_reply={},
        llm_reply={},
        product_knowledge={},
        data_capture={},
        evidence_pack={},
        recent_reply_texts=[],
    )
    reply = maybe_build_realtime_reply(
        config=config,
        route=route,
        combined=message,
        evidence_pack={},
        current_reply_text="",
        recent_reply_texts=[],
    )
    text = str(reply.get("reply_text") or "")
    ok = reply.get("applied") is True and "不乱推" not in text and "乱推荐" not in text
    return {"name": "generic_recommendation_avoids_overused_random_push_phrase", "ok": ok, "route": route, "reply": reply}


def check_explicit_first_request_can_recommend_vehicle_sources() -> dict[str, Any]:
    config = {"realtime_reply": {"enabled": True}, "llm_reply_synthesis": {"enabled": True}}
    message = "预算十来万，直接给我挑两台靠谱的"
    with tenant_context(TENANT_ID):
        evidence_pack = build_evidence_pack(message, context={})
        route = decide_realtime_reply_route(
            config=config,
            combined=message,
            decision=Decision(),
            intent_result=Intent(),
            intent_assist={"intent": "product_inquiry", "evidence": {"safety": {"must_handoff": False}}},
            rag_reply={},
            llm_reply={},
            product_knowledge={},
            data_capture={},
            evidence_pack=evidence_pack,
            recent_reply_texts=[],
        )
        reply = maybe_build_realtime_reply(
            config=config,
            route=route,
            combined=message,
            evidence_pack=evidence_pack,
            current_reply_text="",
            recent_reply_texts=[],
        )
    text = str(reply.get("reply_text") or "")
    ok = (
        route.get("level") == "L1"
        and route.get("reason") == "explicit_vehicle_candidates_requested"
        and reply.get("applied") is True
        and bool(reply.get("used_product_ids"))
        and ("检测报告" in text or "车况" in text)
    )
    return {"name": "explicit_first_request_can_recommend_vehicle_sources", "ok": ok, "route": route, "reply": reply}


def check_specific_finance_question_does_not_force_vehicle_sources() -> dict[str, Any]:
    message = "具体贷款流程怎么走？"
    route = decide_realtime_reply_route(
        config={"realtime_reply": {"enabled": True}, "llm_reply_synthesis": {"enabled": True}},
        combined=message,
        decision=Decision(),
        intent_result=Intent(),
        intent_assist={"intent": "policy_inquiry", "evidence": {"safety": {"must_handoff": False}}},
        rag_reply={},
        llm_reply={},
        product_knowledge={},
        data_capture={},
        evidence_pack={},
        recent_reply_texts=[],
    )
    ok = route.get("reason") != "explicit_vehicle_candidates_requested"
    return {"name": "specific_finance_question_does_not_force_vehicle_sources", "ok": ok, "route": route}


def check_safe_no_deposit_report_visit_stays_local() -> dict[str, Any]:
    message = "我不想先交定金，先看车和报告，满意了再决定可以吧？"
    config = {"realtime_reply": {"enabled": True}, "llm_reply_synthesis": {"enabled": True}}
    route = decide_realtime_reply_route(
        config=config,
        combined=message,
        decision=Decision(),
        intent_result=Intent(),
        intent_assist={
            "intent": "unknown",
            "evidence": {
                "safety": {
                    "must_handoff": True,
                    "reasons": ["matched_faq_requires_handoff", "used_car_contract_manual_review", "no_relevant_business_evidence"],
                }
            },
        },
        rag_reply={},
        llm_reply={},
        product_knowledge={},
        data_capture={},
        evidence_pack={},
        recent_reply_texts=["分期方案要看金融审核，我先按首付比例帮您测方向。"],
    )
    reply = maybe_build_realtime_reply(
        config=config,
        route=route,
        combined=message,
        evidence_pack={},
        current_reply_text="",
        recent_reply_texts=[],
    )
    text = str(reply.get("reply_text") or reply.get("raw_reply_text") or "")
    ok = (
        route.get("reason") == "common_no_deposit_visit_can_use_local_style"
        and route.get("foreground_llm_allowed") is False
        and reply.get("applied") is True
        and any(marker in text for marker in ("先看", "检测报告", "满意", "定金"))
    )
    return {"name": "safe_no_deposit_report_visit_stays_local", "ok": ok, "route": route, "reply": reply}


def check_greeting_with_business_context_is_not_pure_greeting() -> dict[str, Any]:
    message = "你好，我从抖音直播间来的，家里接娃通勤用，预算十万左右，想先了解下。"
    route = decide_realtime_reply_route(
        config={"realtime_reply": {"enabled": True}, "llm_reply_synthesis": {"enabled": True}},
        combined=message,
        decision=Decision(),
        intent_result=type("GreetingIntent", (), {"intent": "greeting"})(),
        intent_assist={"intent": "greeting", "evidence": {"safety": {"must_handoff": False}}},
        rag_reply={},
        llm_reply={},
        product_knowledge={},
        data_capture={},
        evidence_pack={},
        recent_reply_texts=[],
    )
    ok = route.get("level") == "L1" and route.get("reason") == "common_recommendation_can_use_local_candidates"
    return {"name": "greeting_with_business_context_is_not_pure_greeting", "ok": ok, "route": route}


def check_followup_can_recommend_vehicle_sources() -> dict[str, Any]:
    config = {"realtime_reply": {"enabled": True}, "llm_reply_synthesis": {"enabled": True}}
    message = "那具体给我两台吧"
    recent = ["您这个需求我建议先按预算、用途和车况筛，我再帮您缩到两三台。"]
    with tenant_context(TENANT_ID):
        evidence_pack = build_evidence_pack(message, context={})
        route = decide_realtime_reply_route(
            config=config,
            combined=message,
            decision=Decision(),
            intent_result=Intent(),
            intent_assist={"intent": "product_inquiry", "evidence": {"safety": {"must_handoff": True, "reasons": ["no_relevant_business_evidence"]}}},
            rag_reply={},
            llm_reply={},
            product_knowledge={},
            data_capture={},
            evidence_pack=evidence_pack,
            recent_reply_texts=recent,
        )
        reply = maybe_build_realtime_reply(
            config=config,
            route=route,
            combined=message,
            evidence_pack=evidence_pack,
            current_reply_text="",
            recent_reply_texts=recent,
        )
    text = str(reply.get("reply_text") or "")
    ok = (
        route.get("level") == "L1"
        and route.get("reason") == "followup_ready_for_vehicle_candidates"
        and reply.get("applied") is True
        and bool(reply.get("used_product_ids"))
        and "检测报告" in text
    )
    return {"name": "followup_can_recommend_vehicle_sources", "ok": ok, "route": route, "reply": reply}


def check_followup_visit_request_stays_appointment_style() -> dict[str, Any]:
    config = {"realtime_reply": {"enabled": True}, "llm_reply_synthesis": {"enabled": True}}
    message = "如果合适，周六下午我带老婆过去看，能安排吗？"
    recent = ["我会先帮您缩到两三台，具体车况还是看检测报告。"]
    route = decide_realtime_reply_route(
        config=config,
        combined=message,
        decision=Decision(),
        intent_result=Intent(),
        intent_assist={"intent": "product_inquiry", "evidence": {"safety": {"must_handoff": False}}},
        rag_reply={},
        llm_reply={},
        product_knowledge={},
        data_capture={},
        evidence_pack={},
        recent_reply_texts=recent,
    )
    reply = maybe_build_realtime_reply(
        config=config,
        route=route,
        combined=message,
        evidence_pack={},
        current_reply_text="",
        recent_reply_texts=recent,
    )
    text = str(reply.get("reply_text") or "")
    ok = (
        route.get("level") == "L1"
        and route.get("reason") == "common_visit_timing_can_use_local_style"
        and reply.get("applied") is True
        and not reply.get("used_product_ids")
        and any(marker in text for marker in ("排期", "车源", "白跑", "到店", "时间"))
    )
    return {"name": "followup_visit_request_stays_appointment_style", "ok": ok, "route": route, "reply": reply}


def check_visit_report_prep_stays_appointment_style() -> dict[str, Any]:
    message = "我周六下午四点左右可以过去，能提前把检测报告和车准备好不？"
    config = {"realtime_reply": {"enabled": True}, "llm_reply_synthesis": {"enabled": True}}
    route = decide_realtime_reply_route(
        config=config,
        combined=message,
        decision=Decision(),
        intent_result=Intent(),
        intent_assist={"intent": "product_inquiry", "evidence": {"safety": {"must_handoff": False}}},
        rag_reply={},
        llm_reply={},
        product_knowledge={},
        data_capture={},
        evidence_pack={},
        recent_reply_texts=["价格这块我先帮您核，确认后回您。"],
    )
    reply = maybe_build_realtime_reply(
        config=config,
        route=route,
        combined=message,
        evidence_pack={},
        current_reply_text="",
        recent_reply_texts=[],
    )
    text = str(reply.get("reply_text") or reply.get("raw_reply_text") or "")
    ok = (
        route.get("reason") == "common_visit_timing_can_use_local_style"
        and reply.get("applied") is True
        and all(marker in text for marker in ("周六", "四点", "检测报告"))
        and any(marker in text for marker in ("车源", "排期", "试驾"))
    )
    return {"name": "visit_report_prep_stays_appointment_style", "ok": ok, "route": route, "reply": reply}


def check_used_car_recommendation_filters_non_car_products() -> dict[str, Any]:
    config = {"realtime_reply": {"enabled": True}, "llm_reply_synthesis": {"enabled": True}}
    message = "我老婆接娃开，预算十来万，别太费油，你说哪台省心？"
    evidence_pack = {
        "evidence": {
            "products": [
                {
                    "id": "packing_carton_ct_50",
                    "name": "五层加硬包装纸箱 CT-50",
                    "category": "包装耗材",
                    "price": 3.8,
                    "stock": 8000,
                    "spec": "50x40x30cm，五层加硬，牛皮纸色",
                },
                {
                    "id": "chejin_golf_2020_280tsi",
                    "name": "2020款大众高尔夫280TSI DSG舒适型",
                    "category": "二手车/紧凑型轿车",
                    "price": 8.28,
                    "stock": 1,
                    "spec": "2020年3月上牌，表显4.5万公里，1.4T自动挡，检测报告齐全",
                },
            ]
        }
    }
    route = decide_realtime_reply_route(
        config=config,
        combined=message,
        decision=Decision(),
        intent_result=Intent(),
        intent_assist={"intent": "product_inquiry", "evidence": {"safety": {"must_handoff": False}}},
        rag_reply={},
        llm_reply={},
        product_knowledge={},
        data_capture={},
        evidence_pack=evidence_pack,
        recent_reply_texts=[],
    )
    reply = maybe_build_realtime_reply(
        config=config,
        route=route,
        combined=message,
        evidence_pack=evidence_pack,
        current_reply_text="",
        recent_reply_texts=[],
    )
    text = str(reply.get("reply_text") or "")
    used_ids = set(reply.get("used_product_ids") or [])
    ok = (
        route.get("level") == "L1"
        and reply.get("applied") is True
        and "chejin_golf_2020_280tsi" in used_ids
        and "packing_carton_ct_50" not in used_ids
        and "纸箱" not in text
    )
    return {"name": "used_car_recommendation_filters_non_car_products", "ok": ok, "route": route, "reply": reply}


def check_trade_in_price_wording_stays_local() -> dict[str, Any]:
    config = {"realtime_reply": {"enabled": True}, "llm_reply_synthesis": {"enabled": True}}
    message = "你先给我估个准价，别给区间，能抵多少车款？"
    route = decide_realtime_reply_route(
        config=config,
        combined=message,
        decision=Decision(),
        intent_result=Intent(),
        intent_assist={"intent": "product_inquiry", "evidence": {"safety": {"must_handoff": False}}},
        rag_reply={},
        llm_reply={},
        product_knowledge={},
        data_capture={},
        evidence_pack={},
        recent_reply_texts=[],
    )
    reply = maybe_build_realtime_reply(
        config=config,
        route=route,
        combined=message,
        evidence_pack={},
        current_reply_text="",
        recent_reply_texts=[],
    )
    text = str(reply.get("reply_text") or "")
    ok = (
        route.get("level") == "L1"
        and route.get("reason") == "common_trade_in_collect_can_use_local_style"
        and reply.get("applied") is True
        and "核实" in text
        and "检测" in text
    )
    return {"name": "trade_in_price_wording_stays_local", "ok": ok, "route": route, "reply": reply}


def check_repeated_scene_uses_reply_variant() -> dict[str, Any]:
    config = {"realtime_reply": {"enabled": True}, "llm_reply_synthesis": {"enabled": True}}
    message = "那以后再卖哪个更保值？"
    route = decide_realtime_reply_route(
        config=config,
        combined=message,
        decision=Decision(),
        intent_result=Intent(),
        intent_assist={"intent": "product_inquiry", "evidence": {"safety": {"must_handoff": False}}},
        rag_reply={},
        llm_reply={},
        product_knowledge={},
        data_capture={},
        evidence_pack={},
    )
    first = maybe_build_realtime_reply(
        config=config,
        route=route,
        combined=message,
        evidence_pack={},
        current_reply_text="",
        recent_reply_texts=[],
    )
    second = maybe_build_realtime_reply(
        config=config,
        route=route,
        combined=message,
        evidence_pack={},
        current_reply_text="",
        recent_reply_texts=[str(first.get("reply_text") or "")],
    )
    ok = first.get("applied") is True and second.get("applied") is True and first.get("reply_text") != second.get("reply_text")
    return {"name": "repeated_scene_uses_reply_variant", "ok": ok, "first": first, "second": second}


def check_repeated_recommendation_structure_is_diverse() -> dict[str, Any]:
    config = {"realtime_reply": {"enabled": True}, "llm_reply_synthesis": {"enabled": True}}
    messages = [
        "预算十来万，家用通勤，有没有推荐？",
        "预算十来万，家用通勤，有没有推荐？",
        "预算十来万，家用通勤，有没有推荐？",
    ]
    replies: list[str] = []
    with tenant_context(TENANT_ID):
        for message in messages:
            evidence_pack = build_evidence_pack(message, context={})
            route = decide_realtime_reply_route(
                config=config,
                combined=message,
                decision=Decision(),
                intent_result=Intent(),
                intent_assist={"intent": "product_inquiry", "evidence": {"safety": {"must_handoff": False}}},
                rag_reply={},
                llm_reply={},
                product_knowledge={},
                data_capture={},
                evidence_pack=evidence_pack,
                recent_reply_texts=replies,
            )
            reply = maybe_build_realtime_reply(
                config=config,
                route=route,
                combined=message,
                evidence_pack=evidence_pack,
                current_reply_text="",
                recent_reply_texts=replies,
            )
            replies.append(str(reply.get("reply_text") or ""))
    similarities = [
        reply_similarity(replies[left], replies[right])
        for left in range(len(replies))
        for right in range(left + 1, len(replies))
    ]
    openers = [item[:12] for item in replies]
    ok = (
        len(set(replies)) == 3
        and len(set(openers)) >= 2
        and max(similarities, default=0.0) < 0.72
        and not any("不乱推" in item or "乱推荐" in item for item in replies)
    )
    return {
        "name": "repeated_recommendation_structure_is_diverse",
        "ok": ok,
        "replies": replies,
        "similarities": similarities,
        "openers": openers,
    }


def check_high_risk_skips_foreground_llm() -> dict[str, Any]:
    message = "你能保证这台车绝对不是事故车吗？如果水泡火烧赔多少钱？"
    route = decide_realtime_reply_route(
        config={"realtime_reply": {"enabled": True}, "llm_reply_synthesis": {"enabled": True}},
        combined=message,
        decision=Decision(),
        intent_result=Intent(),
        intent_assist={"intent": "product_inquiry", "evidence": {"safety": {"must_handoff": False}}},
        rag_reply={},
        llm_reply={},
        product_knowledge={},
        data_capture={},
        evidence_pack={},
    )
    ok = route.get("level") == "L0" and route.get("foreground_llm_allowed") is False
    return {"name": "high_risk_skips_foreground_llm", "ok": ok, "route": route}


def check_rag_metadata_cleanup() -> dict[str, Any]:
    raw = "聊天记录：江苏车金预算推荐话术 CHEJIN_20260508_202448 测试批次：CHEJIN_20260508_202448 客户：我8万预算怎么选？ 客服：您这个预算可以先看凯美瑞、思域和秦PLUS DM-i。您是在南京看车吗？ 意图标签：预算推荐"
    cleaned = extract_service_style_snippet(raw)
    ok = "聊天记录" not in cleaned and "CHEJIN_" not in cleaned and cleaned.startswith("您这个预算")
    return {"name": "rag_metadata_cleanup", "ok": ok, "cleaned": cleaned}


def check_listener_watchdog_timeout() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        log_path = Path(tmp) / "listener.log"
        result = run_once(
            [sys.executable, "-c", "import time; time.sleep(2); print('{\"ok\": true}')"],
            env={},
            cwd=PROJECT_ROOT,
            log_path=log_path,
            timeout_seconds=0.5,
        )
        log_text = log_path.read_text(encoding="utf-8")
    ok = result.get("watchdog_timeout") is True and "managed_listener_watchdog_timeout" in log_text
    return {"name": "listener_watchdog_timeout", "ok": ok, "result": result}


if __name__ == "__main__":
    raise SystemExit(main())
