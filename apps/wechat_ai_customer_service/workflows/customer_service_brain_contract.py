"""Contracts for the Brain First customer-service reply path.

The brain contract is intentionally small and JSON-friendly. It lets the
runtime audit what the LLM thought the customer asked, which authority sources
were used, and which short WeChat reply segments should be polished/sent.
"""

from __future__ import annotations

import re
from typing import Any


SCHEMA_VERSION = 1

ANSWER_MODES = {
    "direct_answer",
    "ask_clarifying_question",
    "soft_social_reply",
    "soft_redirect_to_business",
    "recommend_from_catalog",
    "compare_options",
    "quote_product_fact",
    "collect_customer_info",
    "handoff",
    "fallback_existing",
}

GUARD_ACTIONS = {"send_reply", "handoff", "handoff_for_approval", "fallback_existing"}

PRODUCT_FACT_TYPES = {
    "product",
    "product_name",
    "product_alias",
    "price",
    "stock",
    "inventory",
    "availability",
    "year",
    "mileage",
    "condition",
    "location",
    "configuration",
}

PRODUCT_MASTER_ONLY_FACT_TYPES = {
    "price",
    "stock",
    "inventory",
    "availability",
    "year",
    "mileage",
    "condition",
    "location",
    "configuration",
}

POLICY_FACT_TYPES = {
    "policy",
    "finance",
    "loan",
    "trade_in",
    "after_sales",
    "transfer",
    "contract",
    "invoice",
    "appointment",
    "handoff_rule",
}

PRODUCT_AUTHORITY_LEVELS = {"product_master", "product_scoped_formal"}
POLICY_AUTHORITY_LEVELS = {"formal_knowledge", "product_scoped_formal", "current_conversation_fact"}
STYLE_ONLY_LEVELS = {"style_memory", "ai_experience_pool", "rag_experience", "llm_common_sense"}
FACT_CLAIM_REQUIRED_MODES = {"recommend_from_catalog", "compare_options", "quote_product_fact"}
NON_AUTHORITATIVE_ANALYSIS_FACT_TYPES = {
    "analysis",
    "reasoning",
    "recommendation_basis",
    "common_sense",
    "common_sense_analysis",
    "style",
}
EVIDENCE_USED_ALIASES = {
    "product_ids": ("product_ids", "product_id", "product_master", "product_master_ids", "products"),
    "formal_knowledge_ids": (
        "formal_knowledge_ids",
        "formal_knowledge_id",
        "formal_knowledge",
        "policy_ids",
        "policies",
        "formal_ids",
    ),
    "conversation_fact_ids": (
        "conversation_fact_ids",
        "conversation_fact_id",
        "current_conversation_fact",
        "current_conversation_facts",
        "conversation_facts",
    ),
    "common_sense_topics": ("common_sense_topics", "common_sense", "llm_common_sense"),
    "style_ids": ("style_ids", "style_id", "style_context", "style_memory", "style_examples"),
    "rag_ids": ("rag_ids", "rag_id", "rag", "ai_experience_pool", "rag_experience"),
}
SOURCE_LEVEL_ALIASES = {
    "product": "product_master",
    "products": "product_master",
    "product_master_ids": "product_master",
    "policy": "formal_knowledge",
    "policies": "formal_knowledge",
    "formal": "formal_knowledge",
    "formal_knowledge_ids": "formal_knowledge",
    "conversation": "current_conversation_fact",
    "conversation_fact": "current_conversation_fact",
    "current_conversation": "current_conversation_fact",
    "common_sense": "llm_common_sense",
    "common-sense": "llm_common_sense",
    "style": "style_memory",
    "style_context": "style_memory",
    "rag": "rag_experience",
    "ai_pool": "ai_experience_pool",
}
FACT_HINT_TERMS = (
    "万",
    "库存",
    "现车",
    "表显",
    "公里",
    "车况",
    "检测报告",
    "原版原漆",
    "一手车",
    "贷款",
    "分期",
    "过户",
    "发票",
    "合同",
    "售后",
)
AUTHORITY_FACT_HINT_TERMS = (
    "库存",
    "现车",
    "原版原漆",
    "一手车",
    "贷款",
    "分期",
    "过户",
    "发票",
    "合同",
    "售后",
)

PRICE_QUESTION_TERMS = ("多少钱", "价格", "报价", "怎么卖", "几万", "多少米", "落地", "费用")
RECOMMENDATION_QUESTION_TERMS = ("推荐", "建议", "怎么选", "选哪", "哪款", "哪台", "哪个", "更适合", "优先", "挑一")
COMPARISON_QUESTION_TERMS = ("对比", "区别", "哪个好", "哪一个好", "比起来", "相比")
GREETING_TERMS = ("你好", "您好", "在吗", "在不在", "早", "早上好", "下午好", "晚上好", "哈喽", "hello", "hi")
GOODBYE_TERMS = ("再见", "拜拜", "回头聊", "下次聊", "谢谢", "谢了")
GENERIC_STALL_TERMS = ("我先看", "我看一下", "稍等", "等我看", "帮您看看", "我确认一下", "我查一下")
UNSUPPORTED_INFO_COLLECTION_TERMS = ("电话", "手机号", "联系方式", "预算", "轿车还是", "SUV", "suv", "资料", "补齐")
DIRECT_RECOMMENDATION_TERMS = (
    "建议",
    "推荐",
    "优先",
    "先看",
    "更适合",
    "可以看",
    "可以先",
    "不建议",
    "排除",
    "选",
    "挑",
)
UNCERTAIN_BUT_SAFE_TERMS = ("暂无", "还没", "需要核实", "以实际", "以门店", "我确认后")
PRICE_VALUE_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:万|万元|w|W)")
CONCRETE_MILEAGE_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:万)?\s*公里")


def normalize_answer_mode(value: Any) -> str:
    mode = str(value or "").strip()
    return mode if mode in ANSWER_MODES else "direct_answer"


def normalize_guard_action(value: Any, *, needs_handoff: bool = False) -> str:
    action = str(value or "").strip()
    if action not in GUARD_ACTIONS:
        action = "handoff" if needs_handoff else "send_reply"
    return action


def normalize_reply_segments(value: Any, *, max_segments: int = 3) -> list[str]:
    """Return clean, complete reply segments.

    The model is expected to output 1-3 short WeChat messages. If it returns a
    single long string, split it conservatively on Chinese sentence boundaries.
    """

    segments: list[str] = []
    if isinstance(value, list):
        raw_segments = [str(item or "") for item in value]
    else:
        raw_segments = split_reply_like_text(str(value or ""))
    for raw in raw_segments:
        text = normalize_space(raw)
        if not text:
            continue
        text = remove_trailing_ellipsis(text)
        if text and text not in segments:
            segments.append(text)
        if len(segments) >= max(1, int(max_segments or 3)):
            break
    return segments


def split_reply_like_text(text: str) -> list[str]:
    clean = normalize_space(text)
    if not clean:
        return []
    parts = re.split(r"(?<=[。！？!?])\s*", clean)
    return [part for part in parts if part]


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def remove_trailing_ellipsis(text: str) -> str:
    clean = str(text or "").strip()
    clean = re.sub(r"[…\.]{2,}$", "", clean).strip()
    return clean


def join_reply_segments(segments: list[str]) -> str:
    return "\n".join(segment.strip() for segment in segments if str(segment or "").strip())


def normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def normalize_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def normalize_fact_claims(value: Any) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return facts
    for item in value:
        if not isinstance(item, dict):
            continue
        fact_type = str(item.get("fact_type") or item.get("type") or item.get("category") or "").strip()
        source_level = str(item.get("source_level") or item.get("source") or item.get("authority") or "").strip()
        source_level_key = re.sub(r"[\s\-]+", "_", source_level.lower())
        source_level = SOURCE_LEVEL_ALIASES.get(source_level_key, source_level_key or source_level)
        source_id = str(
            item.get("source_id")
            or item.get("id")
            or item.get("product_id")
            or item.get("policy_id")
            or item.get("knowledge_id")
            or ""
        ).strip()
        value_text = str(item.get("value") or item.get("claim") or item.get("text") or "").strip()
        if source_level in STYLE_ONLY_LEVELS and fact_type in NON_AUTHORITATIVE_ANALYSIS_FACT_TYPES:
            continue
        fact = {
            "fact_type": fact_type,
            "value": value_text,
            "source_level": source_level,
            "source_id": source_id,
        }
        if fact["fact_type"] or fact["value"]:
            facts.append(fact)
    return facts


def normalize_brain_plan(raw_plan: dict[str, Any] | None, *, max_segments: int = 3) -> dict[str, Any]:
    plan = dict(raw_plan) if isinstance(raw_plan, dict) else {}
    risk = normalize_mapping(plan.get("risk"))
    needs_handoff = bool(risk.get("needs_handoff") or plan.get("needs_handoff"))
    answer_mode = normalize_answer_mode(plan.get("answer_mode"))
    if answer_mode == "handoff":
        needs_handoff = True
    segments = normalize_reply_segments(plan.get("reply_segments") or plan.get("reply"), max_segments=max_segments)
    action = normalize_guard_action(plan.get("recommended_action"), needs_handoff=needs_handoff)
    if answer_mode == "fallback_existing":
        action = "fallback_existing"
    try:
        confidence = float(plan.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    normalized = {
        "schema_version": int(plan.get("schema_version") or SCHEMA_VERSION),
        "can_answer": plan.get("can_answer", True) is not False,
        "understanding": normalize_mapping(plan.get("understanding")),
        "answer_mode": answer_mode,
        "reply_strategy": normalize_mapping(plan.get("reply_strategy")),
        "evidence_used": normalize_evidence_used(plan.get("evidence_used")),
        "facts_claimed": normalize_fact_claims(plan.get("facts_claimed")),
        "reply_segments": segments,
        "risk": {
            "risk_level": str(risk.get("risk_level") or "low").strip() or "low",
            "risk_tags": normalize_string_list(risk.get("risk_tags") or plan.get("risk_tags")),
            "needs_handoff": needs_handoff,
            "handoff_reason": str(risk.get("handoff_reason") or plan.get("handoff_reason") or "").strip(),
        },
        "recommended_action": action,
        "confidence": confidence,
        "reason": str(plan.get("reason") or "").strip(),
        "self_check": normalize_mapping(plan.get("self_check")),
    }
    return normalized


def normalize_evidence_used(value: Any) -> dict[str, list[str]]:
    payload = normalize_mapping(value)
    normalized: dict[str, list[str]] = {}
    for key, aliases in EVIDENCE_USED_ALIASES.items():
        values: list[str] = []
        for alias in aliases:
            for item in normalize_string_list(payload.get(alias)):
                if item not in values:
                    values.append(item)
        normalized[key] = values
    return normalized


def validate_brain_plan(plan: dict[str, Any], *, require_fact_claims: bool = False) -> dict[str, Any]:
    errors: list[str] = []
    if not plan.get("reply_segments") and plan.get("recommended_action") == "send_reply":
        errors.append("missing_reply_segments")
    if plan.get("answer_mode") not in ANSWER_MODES:
        errors.append("invalid_answer_mode")
    if plan.get("recommended_action") not in GUARD_ACTIONS:
        errors.append("invalid_recommended_action")
    facts = plan.get("facts_claimed", []) or []
    if require_fact_claims and plan_requires_fact_claims(plan) and not facts:
        errors.append("missing_fact_claims")
    for fact in plan.get("facts_claimed", []) or []:
        fact_type = str(fact.get("fact_type") or "").strip()
        source_level = str(fact.get("source_level") or "").strip()
        source_id = str(fact.get("source_id") or "").strip()
        if fact_type in PRODUCT_MASTER_ONLY_FACT_TYPES and source_level != "product_master":
            errors.append(f"product_master_fact_without_product_master_authority:{fact_type}")
        if fact_type in PRODUCT_FACT_TYPES and source_level not in PRODUCT_AUTHORITY_LEVELS:
            errors.append(f"product_fact_without_product_authority:{fact_type}")
        if fact_type in POLICY_FACT_TYPES and source_level not in POLICY_AUTHORITY_LEVELS:
            errors.append(f"policy_fact_without_formal_authority:{fact_type}")
        if fact_type in PRODUCT_FACT_TYPES and source_level in PRODUCT_AUTHORITY_LEVELS and not source_id:
            errors.append(f"product_fact_missing_source_id:{fact_type}")
        if fact_type in POLICY_FACT_TYPES and source_level in {"formal_knowledge", "product_scoped_formal"} and not source_id:
            errors.append(f"policy_fact_missing_source_id:{fact_type}")
        if source_level in STYLE_ONLY_LEVELS:
            errors.append(f"style_only_source_used_as_fact:{fact_type or source_level}")
    return {"ok": not errors, "errors": errors}


def verify_brain_reply_quality(
    plan: dict[str, Any],
    *,
    current_message: str,
    evidence_pack: dict[str, Any] | None = None,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Check whether a BrainPlan directly answers the current customer turn.

    This is a generic quality contract, not a business-rule source. It may
    reject evasive or mismatched replies, but it never authorizes product facts.
    """

    cfg = settings if isinstance(settings, dict) else {}
    if cfg.get("quality_verifier_enabled", True) is False:
        return {"ok": True, "errors": [], "warnings": [], "repair_instruction": ""}
    action = str(plan.get("recommended_action") or "send_reply")
    if action != "send_reply":
        return {"ok": True, "errors": [], "warnings": [], "repair_instruction": ""}

    question = normalize_space(current_message)
    reply = join_reply_segments(plan.get("reply_segments", []) or [])
    clean_reply = normalize_space(reply)
    errors: list[str] = []
    warnings: list[str] = []

    if not clean_reply:
        errors.append("empty_visible_reply")
    if exposes_ai_identity(clean_reply):
        errors.append("customer_visible_ai_identity_leak")
    if re.search(r"[…\.]{2,}\s*$", reply):
        errors.append("trailing_ellipsis_or_truncation")

    price_question = contains_any(question, PRICE_QUESTION_TERMS)
    recommendation_question = contains_any(question, RECOMMENDATION_QUESTION_TERMS) or contains_any(question, COMPARISON_QUESTION_TERMS)
    concrete_question = price_question or recommendation_question or bool(plan.get("facts_claimed"))
    product_terms = collect_quality_product_terms(plan, evidence_pack or {})
    has_product_evidence = bool(collect_authoritative_product_ids(evidence_pack or {}))

    if is_social_only_message(question):
        if contains_any(clean_reply, UNSUPPORTED_INFO_COLLECTION_TERMS):
            errors.append("unsupported_info_collection_for_social_message")
        if len(clean_reply) > int(cfg.get("social_reply_soft_max_chars") or 80):
            warnings.append("social_reply_too_long")

    if concrete_question and is_generic_stall_reply(clean_reply):
        errors.append("generic_stall_reply_for_concrete_question")

    if price_question:
        if has_product_evidence:
            if not PRICE_VALUE_RE.search(clean_reply) and not contains_any(clean_reply, UNCERTAIN_BUT_SAFE_TERMS):
                errors.append("missing_direct_price_response")
            if product_terms and not mentions_any_entity(clean_reply, product_terms):
                errors.append("missing_referenced_product_in_reply")
            if contains_any(clean_reply, ("预算", "轿车还是", "SUV", "suv")) and not PRICE_VALUE_RE.search(clean_reply):
                errors.append("asks_new_need_instead_of_answering_price")
        elif PRICE_VALUE_RE.search(clean_reply):
            errors.append("price_answer_without_product_evidence")

    if recommendation_question and has_product_evidence:
        if not contains_any(clean_reply, DIRECT_RECOMMENDATION_TERMS):
            errors.append("missing_clear_recommendation_or_choice")

    for segment in plan.get("reply_segments", []) or []:
        if len(str(segment)) > int(cfg.get("quality_segment_soft_max_chars") or 120):
            warnings.append("reply_segment_too_long")
            break

    instruction = build_quality_repair_instruction(errors=errors, warnings=warnings, current_message=question, reply=clean_reply)
    return {"ok": not errors, "errors": errors, "warnings": warnings, "repair_instruction": instruction}


def plan_requires_fact_claims(plan: dict[str, Any]) -> bool:
    if plan.get("recommended_action") != "send_reply":
        return False
    if plan_is_common_sense_only_advice(plan):
        return False
    answer_mode = str(plan.get("answer_mode") or "")
    if answer_mode in {"recommend_from_catalog", "quote_product_fact"}:
        return True
    evidence = plan.get("evidence_used") if isinstance(plan.get("evidence_used"), dict) else {}
    if evidence.get("product_ids") or evidence.get("formal_knowledge_ids"):
        return True
    reply = join_reply_segments(plan.get("reply_segments", []) or [])
    if answer_mode == "compare_options":
        return reply_has_authority_fact_hint(reply)
    return reply_has_authority_fact_hint(reply)


def reply_has_authority_fact_hint(reply: str) -> bool:
    text = str(reply or "")
    return bool(PRICE_VALUE_RE.search(text) or CONCRETE_MILEAGE_RE.search(text)) or any(
        term in text for term in AUTHORITY_FACT_HINT_TERMS
    )


def plan_is_common_sense_only_advice(plan: dict[str, Any]) -> bool:
    evidence = plan.get("evidence_used") if isinstance(plan.get("evidence_used"), dict) else {}
    return bool(evidence.get("common_sense_topics")) and not (
        evidence.get("product_ids") or evidence.get("formal_knowledge_ids") or plan.get("facts_claimed")
    )


def contains_any(text: str, terms: tuple[str, ...] | list[str]) -> bool:
    clean = str(text or "")
    lower = clean.lower()
    return any(str(term or "").lower() in lower for term in terms if str(term or ""))


def is_social_only_message(text: str) -> bool:
    clean = re.sub(r"[\s。！？!?，,、~～\.\-_:：；;]+", "", str(text or "").strip()).lower()
    if not clean:
        return False
    terms = tuple(item.lower() for item in GREETING_TERMS + GOODBYE_TERMS)
    return clean in terms or (len(clean) <= 7 and any(term in clean for term in terms))


def is_generic_stall_reply(text: str) -> bool:
    clean = normalize_space(text)
    if not contains_any(clean, GENERIC_STALL_TERMS):
        return False
    informative = PRICE_VALUE_RE.search(clean) or contains_any(clean, DIRECT_RECOMMENDATION_TERMS)
    return not informative and len(clean) <= 90


def exposes_ai_identity(text: str) -> bool:
    return contains_any(text, ("我是AI", "我是ai", "机器人", "自动回复", "智能客服", "大模型"))


def collect_quality_product_terms(plan: dict[str, Any], evidence_pack: dict[str, Any]) -> list[str]:
    terms: list[str] = []
    understanding = plan.get("understanding") if isinstance(plan.get("understanding"), dict) else {}
    entities = understanding.get("normalized_entities") if isinstance(understanding.get("normalized_entities"), list) else []
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        for key in ("raw", "normalized", "name", "alias"):
            add_unique_text(terms, entity.get(key))
    for item in iter_authoritative_product_items(evidence_pack):
        for key in ("name", "title", "model", "sku", "id", "product_id"):
            add_unique_text(terms, item.get(key))
        aliases = item.get("aliases") or item.get("alias")
        if isinstance(aliases, list):
            for alias in aliases:
                add_unique_text(terms, alias)
        else:
            add_unique_text(terms, aliases)
    return terms


def collect_authoritative_product_ids(evidence_pack: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for item in iter_authoritative_product_items(evidence_pack):
        for key in ("id", "product_id", "sku"):
            value = str(item.get(key) or "").strip()
            if value:
                ids.add(value)
    return ids


def iter_authoritative_product_items(evidence_pack: dict[str, Any]) -> list[dict[str, Any]]:
    knowledge = evidence_pack.get("knowledge") if isinstance(evidence_pack.get("knowledge"), dict) else {}
    evidence = knowledge.get("evidence") if isinstance(knowledge.get("evidence"), dict) else {}
    product_master = knowledge.get("product_master") if isinstance(knowledge.get("product_master"), dict) else {}
    buckets = (evidence.get("products", []), evidence.get("catalog_candidates", []), product_master.get("items", []))
    items: list[dict[str, Any]] = []
    for bucket in buckets:
        if not isinstance(bucket, list):
            continue
        for item in bucket:
            if isinstance(item, dict):
                items.append(item)
    return items


def add_unique_text(items: list[str], value: Any) -> None:
    text = str(value or "").strip()
    if text and text not in items:
        items.append(text)


def mentions_any_entity(reply: str, terms: list[str]) -> bool:
    clean_reply = compact_entity_text(reply)
    if not clean_reply:
        return False
    for term in terms:
        compact = compact_entity_text(term)
        if len(compact) < 2:
            continue
        if compact in clean_reply:
            return True
        for fragment in entity_fragments(compact):
            if fragment in clean_reply:
                return True
    return False


def compact_entity_text(text: str) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", str(text or "")).lower()


def entity_fragments(compact: str) -> list[str]:
    value = compact_entity_text(compact)
    fragments: list[str] = []
    if len(value) <= 3:
        return [value] if value else []
    for size in range(min(8, len(value)), 2, -1):
        for start in range(0, len(value) - size + 1):
            fragment = value[start : start + size]
            if fragment and fragment not in fragments and fragment_has_signal(fragment):
                fragments.append(fragment)
    return fragments[:24]


def fragment_has_signal(fragment: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", fragment) and re.search(r"[a-z0-9]", fragment)) or len(fragment) >= 4


def build_quality_repair_instruction(*, errors: list[str], warnings: list[str], current_message: str, reply: str) -> str:
    if not errors and not warnings:
        return ""
    return (
        "BrainPlan未通过通用质量自检。请重新理解当前客户消息并修复回复，必须先正面回答当前问题；"
        "商品事实只可来自product_master，政策流程只可来自formal_knowledge，AI经验池/历史聊天/常识只可辅助表达。"
        f" 当前客户消息：{current_message[:180]}；当前回复：{reply[:180]}；"
        f" 失败项：{', '.join(errors) if errors else '无'}；警告项：{', '.join(warnings) if warnings else '无'}。"
    )


def brain_plan_to_guard_candidate(plan: dict[str, Any]) -> dict[str, Any]:
    evidence = plan.get("evidence_used") if isinstance(plan.get("evidence_used"), dict) else {}
    used_evidence: list[str] = []
    used_evidence.extend(f"product:{item}" for item in evidence.get("product_ids", []) or [])
    used_evidence.extend(f"policy:{item}" for item in evidence.get("formal_knowledge_ids", []) or [])
    used_evidence.extend(f"conversation:{item}" for item in evidence.get("conversation_fact_ids", []) or [])
    used_evidence.extend(f"common_sense:{item}" for item in evidence.get("common_sense_topics", []) or [])
    used_evidence.extend(f"style:{item}" for item in evidence.get("style_ids", []) or [])
    used_evidence.extend(f"rag:{item}" for item in evidence.get("rag_ids", []) or [])
    if not used_evidence:
        used_evidence.append("conversation:current_message")
    action = str(plan.get("recommended_action") or "send_reply")
    needs_handoff = bool((plan.get("risk") or {}).get("needs_handoff") or action in {"handoff", "handoff_for_approval"})
    return {
        "can_answer": bool(plan.get("can_answer", True)),
        "reply": join_reply_segments(plan.get("reply_segments", []) or []),
        "confidence": float(plan.get("confidence") or 0.0),
        "recommended_action": action,
        "needs_handoff": needs_handoff,
        "used_evidence": used_evidence,
        "rag_used": any(item.startswith("rag:") for item in used_evidence),
        "structured_used": any(item.startswith(("product:", "policy:", "conversation:")) for item in used_evidence),
        "uncertain_points": [],
        "risk_tags": list(((plan.get("risk") or {}).get("risk_tags") or [])),
        "reason": str(plan.get("reason") or ""),
    }


def compact_brain_plan(plan: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(plan) if isinstance(plan, dict) else {}
    if "reply_segments" in payload:
        payload["reply_segments"] = [str(item)[:240] for item in payload.get("reply_segments", []) or []]
    return payload
