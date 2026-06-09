"""Contracts for the Brain First customer-service reply path.

The brain contract is intentionally small and JSON-friendly. It lets the
runtime audit what the LLM thought the customer asked, which authority sources
were used, and which short WeChat reply segments should be polished/sent.
"""

from __future__ import annotations

import json
import re
import unicodedata
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
    "product_name_price",
    "product_price",
    "product_alias",
    "price",
    "product_name_price",
    "product_price",
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

PRODUCT_AUTHORITY_LEVELS = {"product_master", "product_scoped_formal", "current_conversation_fact"}
POLICY_AUTHORITY_LEVELS = {"formal_knowledge", "product_scoped_formal", "current_conversation_fact"}
STYLE_ONLY_LEVELS = {"style_memory", "ai_experience_pool", "rag_experience", "llm_common_sense"}
FACT_CLAIM_REQUIRED_MODES = {"recommend_from_catalog", "compare_options", "quote_product_fact"}
NON_AUTHORITATIVE_ANALYSIS_FACT_TYPES = {
    "analysis",
    "reasoning",
    "recommendation_basis",
    "common_sense",
    "common_sense_analysis",
    "advice",
    "suggestion",
    "boundary",
    "risk_boundary",
    "safe_boundary",
    "caveat",
    "style",
}
FACT_TYPE_ALIASES = {
    "car": "product",
    "vehicle": "product",
    "vehicle_name": "product_name",
    "car_name": "product_name",
    "product_title": "product_name",
    "product_price": "price",
    "vehicle_price": "price",
    "car_price": "price",
    "quote": "price",
    "quoted_price": "price",
    "product_quote": "price",
    "product_stock": "stock",
    "product_inventory": "inventory",
    "product_availability": "availability",
    "product_year": "year",
    "product_mileage": "mileage",
    "product_condition": "condition",
    "product_location": "location",
    "product_specs": "configuration",
    "product_spec": "configuration",
    "specs": "configuration",
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
AMBIGUOUS_PRODUCT_FOLLOWUP_TERMS = (
    "这台",
    "这辆",
    "这个车",
    "它",
    "车况",
    "检测",
    "事故",
    "水泡",
    "火烧",
    "补漆",
    "换件",
    "油耗",
    "保养",
    "后期",
    "维护",
    "空间",
    "后备厢",
    "第二排",
    "试驾",
    "看车",
    "现车",
)
GREETING_TERMS = ("你好", "您好", "在吗", "在不在", "早", "早上好", "下午好", "晚上好", "哈喽", "hello", "hi")
GOODBYE_TERMS = ("再见", "拜拜", "回头聊", "下次聊", "谢谢", "谢了")
SOCIAL_SUMMON_TERMS = ("人呢", "在不", "在么", "在嘛", "有人吗", "老板在吗", "还在吗", "忙吗")
GENERIC_STALL_TERMS = (
    "我先看",
    "我看一下",
    "稍等",
    "等我看",
    "帮您看看",
    "我确认一下",
    "我先确认",
    "先确认一下",
    "马上回复",
    "我查一下",
)
CLEAR_BOUNDARY_REFUSAL_TERMS = (
    "不能帮",
    "没法帮",
    "无法帮",
    "不能做",
    "不能操作",
    "不能处理",
    "不能配合",
    "不能这么",
    "不可以这么",
    "不建议这么",
    "不能调",
    "不能改",
    "不能篡改",
    "不能承诺",
    "不能保证",
    "不能包过",
)
CLEAR_BOUNDARY_SUBSTANTIVE_TERMS = (
    "真实",
    "如实",
    "正常流程",
    "合规",
    "交易真实性",
    "违法",
    "违规",
    "诚信",
    "风险",
    "资方",
    "审批",
    "征信",
    "保险公司",
    "保单",
    "审核",
    "检测",
    "车况",
    "评估",
    "实际",
    "正式",
)
UNSUPPORTED_INFO_COLLECTION_TERMS = ("电话", "手机号", "联系方式", "预算", "轿车还是", "SUV", "suv", "资料", "补齐")
BUSINESS_REDIRECT_TERMS = (
    "预算",
    "车型",
    "车源",
    "看车",
    "试驾",
    "报价",
    "价格",
    "贷款",
    "置换",
    "过户",
    "车况",
    "公里",
    "库存",
    "到店",
)
UNNECESSARY_HANDOFF_VISIBLE_TERMS = ("转人工", "人工客服", "人工帮", "负责人", "专员")
INCOMPLETE_CONDITION_OPENERS = ("如果", "要是", "假如", "若", "但如果")
INCOMPLETE_TRAILING_TERMS = ("如果", "要是", "假如", "因为", "所以", "但是", "不过", "另外", "比如", "包括", "或者", "以及", "然后", "的话")
INSURANCE_TOPIC_TERMS = ("保险", "车损险", "理赔", "赔不赔", "赔吗", "报案", "定损", "保单", "剐蹭", "撞墙")
INSURANCE_REPLY_TERMS = ("保险", "车损险", "理赔", "报案", "定损", "保单", "保险公司", "不一定", "以保单", "审核")
CARGO_TOPIC_TERMS = ("后备厢", "后备箱", "装东西", "装载", "箱子", "灯架", "梯子", "工具箱", "第二排", "后排", "放倒", "大件", "空间", "塞得下", "塞下")
CARGO_REPLY_TERMS = ("后备厢", "后备箱", "装", "装载", "空间", "第二排", "后排", "放倒", "大件", "开口", "容积", "梯子", "工具箱", "尺寸", "实车", "比划", "塞得下", "塞下")
CARGO_FIT_CATEGORY_TERMS = ("suv", "mpv", "旅行", "两厢", "掀背", "皮卡", "van")
APPOINTMENT_TOPIC_TERMS = ("到店", "看车", "试驾", "预约", "排期", "安排", "过去", "来店", "周末", "周六", "周日", "上午", "下午", "几点")
APPOINTMENT_OVERCOMMIT_TERMS = (
    "过来就可以",
    "过来就行",
    "直接过来",
    "直接来",
    "来就可以",
    "来就行",
    "就可以过来",
    "就行过来",
)
APPOINTMENT_CONFIRMATION_BOUNDARY_TERMS = (
    "确认",
    "核实",
    "排期",
    "车源",
    "回复",
    "回您",
    "记下",
    "记上",
    "先记",
    "白跑",
)
TRADE_IN_TOPIC_TERMS = ("置换", "旧车", "收购", "估价", "评估", "验车", "卖车", "抵车款")
TRADE_IN_OVERCOMMIT_TERMS = (
    "上门验车",
    "上门检测",
    "当天打款",
    "当天可以打款",
    "当天能打款",
    "当天安排打款",
    "当天付款",
    "立刻打款",
    "马上打款",
)
TRADE_IN_FINAL_PRICE_TERMS = ("最终收购价", "最终收车价", "最终价格", "最终报价")
TRADE_IN_BOUNDARY_TERMS = (
    "以门店",
    "以实际",
    "以验车",
    "现场核验",
    "现场核实",
    "现场验车",
    "核验结果",
    "核实结果",
    "实车检测",
    "验车核实",
    "核实后",
    "确认后",
    "需要确认",
    "需要核实",
    "先初估",
    "初步评估",
    "大概区间",
    "不能直接",
    "不先承诺",
    "手续",
)
NO_NONSEDAN_AVAILABLE_TERMS = (
    "现有车源里都还是轿车",
    "现有车源都是轿车",
    "现车里都还是轿车",
    "现车都是轿车",
    "只有轿车",
    "都是轿车",
    "没有SUV",
    "没有suv",
    "暂无SUV",
    "暂无suv",
)
DEFAULT_QUALITY_REPLY_MAX_CHARS = 120
DEFAULT_QUALITY_MIXED_TOPIC_REPLY_MAX_CHARS = 180
DEFAULT_QUALITY_SPLIT_REPLY_MAX_CHARS = 150
DIRECT_RECOMMENDATION_TERMS = (
    "建议",
    "推荐",
    "主推",
    "首推",
    "优先",
    "先看",
    "更适合",
    "更偏",
    "偏向",
    "更稳",
    "更保值",
    "更好卖",
    "亏得少",
    "亏得少一点",
    "一般还是",
    "可以看",
    "可以先",
    "不建议",
    "排除",
    "选",
    "挑",
    "第一顺位",
    "第二顺位",
    "放第二",
)
CLEAR_RECOMMENDATION_STRUCTURE_TERMS = (
    "第一",
    "第二",
    "第三",
    "第一台",
    "第二台",
    "第三台",
    "第一款",
    "第二款",
    "第三款",
    "备选",
    "方向",
    "排序",
    "顺位",
    "放前面",
    "放后面",
    "预算最轻松",
    "性价比",
    "更贴合",
    "最贴合",
    "更均衡",
)
UNCERTAIN_BUT_SAFE_TERMS = ("暂无", "还没", "需要核实", "以实际", "以门店", "我确认后")
KNOWN_PRICE_UNCERTAINTY_TERMS = (
    "能不能压进",
    "能不能进",
    "能不能到",
    "能不能控制在",
    "看那台实际挂牌价",
    "看实际挂牌价",
    "挂牌价能不能",
    "报价能不能",
    "价格能不能",
)
OVER_BUDGET_CAVEAT_TERMS = (
    "超预算",
    "超您预算",
    "明显超",
    "预算会高",
    "价格会高",
    "会高一些",
    "高一些",
    "不在预算",
    "预算外",
    "只能作为备选",
    "备选",
    "不作为等价推荐",
)
QUALITY_WEAK_PRODUCT_ENTITY_TERMS = {
    "suv",
    "mpv",
    "轿车",
    "中型suv",
    "燃油suv",
    "家用suv",
    "商务车",
    "自动挡",
    "新能源",
    "混动",
    "纯电",
    "两厢",
    "三厢",
    "现车",
    "南京",
    "省油",
    "家用",
    "通勤",
    "空间",
    "2.0t",
    "25l",
    "2.5l",
}
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
        text = sanitize_forbidden_commitment_echo(text)
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


def sanitize_forbidden_commitment_echo(text: str) -> str:
    clean = str(text or "")
    replacements = (
        (r"不能(?:直接)?说(?:一定|肯定|保证)赔(?:或(?:一定|肯定|保证)?不赔)?", "不能直接下结论"),
        (r"不(?:能|敢)?(?:直接)?(?:保证|肯定|承诺)(?:会)?赔", "不能直接下结论"),
        (r"没法(?:直接)?(?:保证|肯定|承诺)(?:会)?赔", "不能直接下结论"),
        (r"无法(?:直接)?(?:保证|肯定|承诺)(?:会)?赔", "不能直接下结论"),
    )
    for pattern, replacement in replacements:
        clean = re.sub(pattern, replacement, clean)
    return normalize_space(clean)


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
        fact_type_key = re.sub(r"[\s\-]+", "_", fact_type.lower())
        fact_type = FACT_TYPE_ALIASES.get(fact_type_key, fact_type_key or fact_type)
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
        if is_uncertainty_boundary_fact_claim(
            fact_type=fact_type,
            value_text=value_text,
            source_level=source_level,
        ):
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


def is_uncertainty_boundary_fact_claim(*, fact_type: str, value_text: str, source_level: str) -> bool:
    if fact_type not in PRODUCT_MASTER_ONLY_FACT_TYPES:
        return False
    if source_level != "current_conversation_fact":
        return False
    return contains_any(
        value_text,
        (
            *UNCERTAIN_BUT_SAFE_TERMS,
            "需核实",
            "需要确认",
            "暂未确认",
            "暂时没有",
            "没有看到",
            "不能确认",
            "不敢凭印象",
            "以检测报告",
            "按检测报告",
            "看检测报告",
        ),
    )


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


def validate_social_visible_reply_contract(plan: dict[str, Any], *, current_message: str) -> dict[str, Any]:
    """Require Brain-authored visible acknowledgements for real social turns.

    This is a reply-ownership contract, not a local answer template.  It keeps
    guard/quality/scheduler layers from treating greetings, summons, thanks, or
    goodbyes as "no visible reply" while still requiring the Brain to author the
    actual customer-facing sentence.
    """

    if not social_message_requires_visible_brain_reply(current_message):
        return {"ok": True, "errors": [], "warnings": []}
    action = str(plan.get("recommended_action") or "send_reply").strip()
    answer_mode = str(plan.get("answer_mode") or "").strip()
    risk = plan.get("risk") if isinstance(plan.get("risk"), dict) else {}
    reply = join_reply_segments(plan.get("reply_segments", []) or [])
    errors: list[str] = []
    warnings: list[str] = []
    if action != "send_reply":
        errors.append("social_message_requires_send_reply")
    if not bool(plan.get("can_answer", True)):
        errors.append("social_message_requires_can_answer")
    if bool(risk.get("needs_handoff")):
        errors.append("social_message_must_not_handoff_without_hard_boundary")
    if not reply.strip():
        errors.append("social_message_requires_visible_brain_reply")
    if answer_mode and answer_mode not in {"soft_social_reply", "direct_answer", "soft_redirect_to_business"}:
        warnings.append("social_message_answer_mode_should_be_social_or_direct")
    if reply.strip() and visible_content_char_count(reply) > 80:
        warnings.append("social_message_reply_too_long")
    return {"ok": not errors, "errors": errors, "warnings": warnings}


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
    contextual_recommendation_question = is_contextual_recommendation_followup(question)
    recommendation_question = (
        contains_any(question, RECOMMENDATION_QUESTION_TERMS)
        or contains_any(question, COMPARISON_QUESTION_TERMS)
        or contextual_recommendation_question
        or is_broad_product_recommendation_request(question)
    )
    concrete_question = price_question or recommendation_question or bool(plan.get("facts_claimed"))
    product_terms = collect_quality_product_terms(plan, evidence_pack or {})
    has_product_evidence = bool(collect_authoritative_product_ids(evidence_pack or {}))
    budget_upper = extract_quality_budget_upper(question, evidence_pack or {})

    if is_social_only_message(question):
        if contains_any(clean_reply, UNSUPPORTED_INFO_COLLECTION_TERMS):
            errors.append("unsupported_info_collection_for_social_message")
        if len(clean_reply) > int(cfg.get("social_reply_soft_max_chars") or 80):
            warnings.append("social_reply_too_long")

    redirect_check = check_over_eager_business_redirect_after_social_fatigue(question, clean_reply, evidence_pack or {})
    if redirect_check.get("error"):
        errors.append(str(redirect_check["error"]))

    if concrete_question and is_generic_stall_reply(clean_reply):
        errors.append("generic_stall_reply_for_concrete_question")
    if contains_any(clean_reply, UNNECESSARY_HANDOFF_VISIBLE_TERMS):
        errors.append("unnecessary_handoff_language_for_send_reply")

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

    if contextual_recommendation_question and is_generic_stall_reply(clean_reply):
        errors.append("generic_stall_reply_for_contextual_recommendation")

    if contextual_recommendation_question and has_product_evidence:
        if not mentions_any_entity(clean_reply, product_terms):
            errors.append("missing_context_product_recommendation")
        relative_context_check = check_relative_context_product_binding(clean_reply, evidence_pack or {})
        if relative_context_check.get("error"):
            errors.append(str(relative_context_check["error"]))

    if recommendation_question and has_product_evidence:
        if not reply_has_clear_recommendation_or_choice(clean_reply, plan, evidence_pack or {}):
            errors.append("missing_clear_recommendation_or_choice")
        if budget_upper is not None and budget_upper > 0:
            budget_check = check_budget_fit_recommendation(
                clean_reply,
                evidence_pack or {},
                current_message=question,
                budget_upper=budget_upper,
            )
            if budget_check.get("error"):
                errors.append(str(budget_check["error"]))
            price_uncertainty_check = check_known_budget_fit_product_price_uncertainty(
                clean_reply,
                evidence_pack or {},
                budget_upper=budget_upper,
            )
            if price_uncertainty_check.get("error"):
                errors.append(str(price_uncertainty_check["error"]))
        multi_check = check_multi_product_recommendation_count(
            clean_reply,
            evidence_pack or {},
            current_message=question,
            budget_upper=budget_upper,
        )
        if multi_check.get("error"):
            errors.append(str(multi_check["error"]))

    if has_product_evidence and is_ambiguous_product_followup(question, evidence_pack or {}):
        ambiguous_followup_check = check_ambiguous_followup_product_binding(clean_reply, evidence_pack or {})
        if ambiguous_followup_check.get("error"):
            errors.append(str(ambiguous_followup_check["error"]))

    if contains_any(question, INSURANCE_TOPIC_TERMS) and not contains_any(clean_reply, INSURANCE_REPLY_TERMS):
        errors.append("missing_insurance_common_sense_topic")

    if contains_any(question, CARGO_TOPIC_TERMS) and not contains_any(clean_reply, CARGO_REPLY_TERMS):
        errors.append("missing_cargo_space_topic")
    if has_product_evidence and contains_any(question, CARGO_TOPIC_TERMS) and is_broad_product_recommendation_request(question):
        cargo_fit_check = check_available_cargo_fit_candidate_for_broad_request(
            clean_reply,
            evidence_pack or {},
            budget_upper=budget_upper,
        )
        if cargo_fit_check.get("error"):
            errors.append(str(cargo_fit_check["error"]))
    if has_product_evidence and contains_any(question, CARGO_TOPIC_TERMS):
        cargo_capacity_check = check_unverified_cargo_capacity_claim(clean_reply, evidence_pack or {})
        if cargo_capacity_check.get("error"):
            errors.append(str(cargo_capacity_check["error"]))

    appointment_check = check_appointment_confirmation_boundary(question, clean_reply)
    if appointment_check.get("error"):
        errors.append(str(appointment_check["error"]))
    trade_in_check = check_trade_in_process_boundary(question, clean_reply)
    if trade_in_check.get("error"):
        errors.append(str(trade_in_check["error"]))

    total_limit = int(cfg.get("quality_reply_max_chars") or DEFAULT_QUALITY_REPLY_MAX_CHARS)
    total_chars = visible_content_char_count(clean_reply)
    if is_mixed_topic_customer_message(question) and len(plan.get("reply_segments", []) or []) >= 2:
        total_limit = max(total_limit, int(cfg.get("quality_mixed_topic_reply_max_chars") or DEFAULT_QUALITY_MIXED_TOPIC_REPLY_MAX_CHARS))
    if total_limit > 0 and total_chars > total_limit:
        if split_reply_is_sendable(plan.get("reply_segments", []) or [], settings=cfg, total_chars=total_chars):
            warnings.append("split_reply_over_soft_total_limit")
        else:
            errors.append("reply_too_long")

    for segment in plan.get("reply_segments", []) or []:
        segment_text = normalize_space(str(segment))
        if len(segment_text) > int(cfg.get("quality_segment_soft_max_chars") or 96):
            warnings.append("reply_segment_too_long")
        if is_incomplete_reply_segment(segment_text):
            errors.append("incomplete_reply_segment")
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


def is_mixed_topic_customer_message(text: str) -> bool:
    question = normalize_space(text)
    if not contains_any(question, ("顺便", "另外", "还有", "同时", "也想", "再问", "再说")):
        return False
    topic_count = 0
    if contains_any(question, PRICE_QUESTION_TERMS + RECOMMENDATION_QUESTION_TERMS + COMPARISON_QUESTION_TERMS):
        topic_count += 1
    if contains_any(question, INSURANCE_TOPIC_TERMS):
        topic_count += 1
    if contains_any(question, ("贷款", "分期", "置换", "旧车", "首付", "月供")):
        topic_count += 1
    if contains_any(question, APPOINTMENT_TOPIC_TERMS):
        topic_count += 1
    if contains_any(question, CARGO_TOPIC_TERMS):
        topic_count += 1
    return topic_count >= 2


def reply_has_authority_fact_hint(reply: str) -> bool:
    text = str(reply or "")
    return bool(reply_has_authority_price_value(text) or CONCRETE_MILEAGE_RE.search(text)) or any(
        term in text for term in AUTHORITY_FACT_HINT_TERMS
    )


def reply_has_authority_price_value(text: str) -> bool:
    for match in PRICE_VALUE_RE.finditer(str(text or "")):
        if not price_value_looks_like_customer_budget(text, match.start(), match.end()):
            return True
    return False


def price_value_looks_like_customer_budget(text: str, start: int, end: int) -> bool:
    before = str(text or "")[max(0, start - 12) : start]
    after = str(text or "")[end : min(len(str(text or "")), end + 8)]
    context = before + after
    if contains_any(context, ("报价", "价格", "标价", "售价", "车价", "首付", "月供", "落地", "按这台", "这台", "这辆")):
        return False
    if contains_any(after, ("以内", "之内", "以下", "内", "左右", "上下")):
        return True
    if contains_any(before, ("预算", "价位", "控制在", "卡在")):
        return True
    return False


def plan_is_common_sense_only_advice(plan: dict[str, Any]) -> bool:
    evidence = plan.get("evidence_used") if isinstance(plan.get("evidence_used"), dict) else {}
    return bool(evidence.get("common_sense_topics")) and not (
        evidence.get("product_ids") or evidence.get("formal_knowledge_ids") or plan.get("facts_claimed")
    )


def is_incomplete_reply_segment(text: str) -> bool:
    clean = normalize_space(text).rstrip("。！？!?")
    if not clean:
        return False
    if clean.endswith(INCOMPLETE_TRAILING_TERMS):
        return True
    if is_dangling_condition_clause(clean):
        return True
    if is_dangling_decision_fragment(clean):
        return True
    if any(clean.startswith(prefix) for prefix in INCOMPLETE_CONDITION_OPENERS):
        # A condition-only clause such as "如果损失不大。" reads like a truncated reply.
        return not any(mark in clean for mark in ("，", ",", "；", ";", "就", "可以", "建议", "最好", "一般"))
    return False


def is_dangling_condition_clause(clean: str) -> bool:
    clauses = [item.strip() for item in re.split(r"[。！？!?；;]", clean) if item.strip()]
    if not clauses:
        return False
    last_clause = clauses[-1]
    condition_terms = (*INCOMPLETE_CONDITION_OPENERS, "如发现", "若发现", "未提前告知")
    condition_indexes: list[int] = []
    for term in condition_terms:
        if not term:
            continue
        start = last_clause.find(term)
        while start >= 0:
            # Avoid treating words such as "主要是..." as an unfinished
            # conditional merely because they contain "要是".
            if not (term == "要是" and start > 0 and last_clause[start - 1] == "主"):
                condition_indexes.append(start)
                break
            start = last_clause.find(term, start + 1)
    if not condition_indexes:
        return False
    tail = last_clause[min(condition_indexes) :]
    if condition_tail_has_complete_consequent(tail):
        return False
    outcome_terms = (
        "就",
        "可以",
        "可",
        "会",
        "按",
        "办理",
        "处理",
        "退",
        "赔",
        "补",
        "联系",
        "核实",
        "解决",
        "走",
        "一般",
        "通常",
        "还是",
        "更稳",
        "合适",
        "挺合适",
        "适合",
        "更适合",
        "更建议",
        "更偏",
        "建议",
        "推荐",
        "优先",
    )
    return not contains_any(tail, outcome_terms)


def condition_tail_has_complete_consequent(tail: str) -> bool:
    """Detect colloquial complete condition-result sentences.

    The quality gate should reject fragments like "如果损失不大，", but it
    must not punish natural WeChat wording such as "你要是想热闹一点，我投火锅".
    This is an expression-shape check, not a business-rule check.
    """

    parts = [normalize_space(item) for item in re.split(r"[，,]", str(tail or ""), maxsplit=1)]
    if len(parts) < 2:
        return False
    consequent = parts[1].strip()
    if not consequent:
        return False
    if consequent.endswith(INCOMPLETE_TRAILING_TERMS):
        return False
    if visible_content_char_count(consequent) < 3:
        return False
    return True


def is_dangling_decision_fragment(clean: str) -> bool:
    clauses = [item.strip() for item in re.split(r"[。！？!?；;]", clean) if item.strip()]
    if not clauses:
        return False
    last_clause = clauses[-1]
    if not contains_any(last_clause, ("要不要", "该不该", "是否需要")):
        return False
    decision_terms = ("出险", "走保险", "报保险", "贷款", "分期", "置换", "订车", "看车")
    if not contains_any(last_clause, decision_terms):
        return False
    completion_terms = (
        "要看",
        "取决于",
        "建议",
        "可以",
        "先",
        "再",
        "一般",
        "通常",
        "按",
        "看金额",
        "看维修",
        "看情况",
        "再决定",
    )
    return not contains_any(last_clause, completion_terms)


def visible_content_char_count(text: str) -> int:
    count = 0
    for char in str(text or ""):
        if not char.strip():
            continue
        category = unicodedata.category(char)
        if category.startswith("P") or category.startswith("Z"):
            continue
        count += 1
    return count


def split_reply_is_sendable(segments: list[Any], *, settings: dict[str, Any], total_chars: int) -> bool:
    """Allow complete multi-bubble replies to exceed the single-reply soft cap.

    Length is an expression-shape constraint, not an authority decision. If the
    Brain already produced 2-3 complete short WeChat bubbles, the sender/polish
    layer can deliver them safely; the quality gate should not discard the whole
    answer and fall back to a useless "wait while I check" message.
    """

    clean_segments = [normalize_space(str(item or "")) for item in segments if normalize_space(str(item or ""))]
    if len(clean_segments) < 2:
        return False
    max_segments = max(2, int(settings.get("max_reply_segments") or 3))
    if len(clean_segments) > max_segments:
        return False
    split_limit = int(settings.get("quality_split_reply_max_chars") or DEFAULT_QUALITY_SPLIT_REPLY_MAX_CHARS)
    if split_limit > 0 and total_chars > split_limit:
        return False
    segment_limit = int(settings.get("quality_segment_soft_max_chars") or 96)
    for segment in clean_segments:
        if visible_content_char_count(segment) > segment_limit:
            return False
        if is_incomplete_reply_segment(segment):
            return False
    return True


def contains_any(text: str, terms: tuple[str, ...] | list[str]) -> bool:
    clean = str(text or "")
    lower = clean.lower()
    return any(str(term or "").lower() in lower for term in terms if str(term or ""))


def is_social_only_message(text: str) -> bool:
    clean = re.sub(r"[\s。！？!?，,、~～\.\-_:：；;]+", "", str(text or "").strip()).lower()
    if not clean:
        return False
    terms = tuple(item.lower() for item in GREETING_TERMS + GOODBYE_TERMS + SOCIAL_SUMMON_TERMS)
    return clean in terms or (len(clean) <= 7 and any(term in clean for term in terms))


def check_over_eager_business_redirect_after_social_fatigue(question: str, reply: str, evidence_pack: dict[str, Any]) -> dict[str, Any]:
    """Flag repeated business pullback when strategy state says to soften it.

    This is a reviewer check only.  It does not write replacement wording and it
    does not weaken product/formal-knowledge authority rules.
    """

    state = extract_conversation_strategy_state(evidence_pack)
    if not state:
        return {}
    mode = str(state.get("suggested_engagement_mode") or "")
    fatigue = str(state.get("redirect_fatigue_level") or "")
    resisted = bool(state.get("customer_resists_business_redirect"))
    if mode not in {"social_companion", "soft_bridge"} and fatigue not in {"fatigued", "suppress"} and not resisted:
        return {}
    q = normalize_space(question)
    r = normalize_space(reply)
    if not q or not r:
        return {}
    if contains_any(q, BUSINESS_REDIRECT_TERMS + PRICE_QUESTION_TERMS + RECOMMENDATION_QUESTION_TERMS + COMPARISON_QUESTION_TERMS):
        return {}
    if not contains_any(r, BUSINESS_REDIRECT_TERMS):
        return {}
    if fatigue == "light" and not resisted:
        return {}
    return {"error": "over_eager_business_redirect_after_social_fatigue"}


def extract_conversation_strategy_state(evidence_pack: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(evidence_pack, dict):
        return {}
    for key in ("conversation_strategy_state", "strategy_state"):
        value = evidence_pack.get(key)
        if isinstance(value, dict) and value:
            return value
    conversation = evidence_pack.get("conversation") if isinstance(evidence_pack.get("conversation"), dict) else {}
    value = conversation.get("conversation_strategy_state")
    if isinstance(value, dict) and value:
        return value
    knowledge = evidence_pack.get("knowledge") if isinstance(evidence_pack.get("knowledge"), dict) else {}
    value = knowledge.get("conversation_strategy_state")
    if isinstance(value, dict) and value:
        return value
    return {}


def social_message_requires_visible_brain_reply(text: str) -> bool:
    clean = re.sub(r"[\s。！？!?，,、~～\.\-_:：；;]+", "", str(text or "").strip()).lower()
    if not clean:
        return False
    if is_social_only_message(text):
        return True
    terms = tuple(item.lower() for item in GREETING_TERMS + GOODBYE_TERMS + SOCIAL_SUMMON_TERMS)
    return len(clean) <= 7 and any(term in clean for term in terms)


def is_generic_stall_reply(text: str) -> bool:
    clean = normalize_space(text)
    if not contains_any(clean, GENERIC_STALL_TERMS):
        return False
    if is_clear_boundary_refusal_reply(clean):
        return False
    informative = PRICE_VALUE_RE.search(clean) or contains_any(clean, DIRECT_RECOMMENDATION_TERMS)
    return not informative and len(clean) <= 90


def is_clear_boundary_refusal_reply(text: str) -> bool:
    """Recognize Brain-authored refusals that answer a hard-boundary request.

    This is not a local reply template. It only prevents the quality gate from
    misclassifying a substantive refusal as a generic "I'll check" stall.
    """

    clean = normalize_space(text)
    if not clean:
        return False
    compact = re.sub(r"\s+", "", clean)
    if not contains_any(compact, CLEAR_BOUNDARY_REFUSAL_TERMS):
        return False
    if contains_any(compact, ("负责人", "专员", "人工客服", "马上回复", "稍后回复")) and not contains_any(
        compact,
        CLEAR_BOUNDARY_SUBSTANTIVE_TERMS,
    ):
        return False
    return contains_any(compact, CLEAR_BOUNDARY_SUBSTANTIVE_TERMS)


def check_appointment_confirmation_boundary(question: str, reply: str) -> dict[str, Any]:
    q = normalize_space(question)
    r = normalize_space(reply)
    if not contains_any(q, APPOINTMENT_TOPIC_TERMS):
        return {}
    if contains_any(r, APPOINTMENT_OVERCOMMIT_TERMS) and not contains_any(r, APPOINTMENT_CONFIRMATION_BOUNDARY_TERMS):
        return {"error": "appointment_commitment_without_confirmation_boundary"}
    if contains_any(q, ("电话", "手机号", "联系方式", "我叫", "姓", "周六", "周日", "上午", "下午", "晚上", "点")):
        if not contains_any(r, APPOINTMENT_CONFIRMATION_BOUNDARY_TERMS):
            return {"error": "missing_appointment_confirmation_boundary"}
    return {}


def check_trade_in_process_boundary(question: str, reply: str) -> dict[str, Any]:
    q = normalize_space(question)
    r = normalize_space(reply)
    if not contains_any(q + r, TRADE_IN_TOPIC_TERMS):
        return {}
    if contains_any(r, TRADE_IN_OVERCOMMIT_TERMS):
        return {"error": "trade_in_process_overcommit_without_formal_authority"}
    if contains_any(r, TRADE_IN_FINAL_PRICE_TERMS) and not trade_in_final_price_has_verification_boundary(r):
        return {"error": "trade_in_final_price_missing_verification_boundary"}
    return {}


def trade_in_final_price_has_verification_boundary(reply: str) -> bool:
    r = normalize_space(reply)
    if contains_any(r, ("最终价格以验车", "最终价格以门店", "最终价格以实际", "最终报价以验车", "最终收购价以验车")):
        return True
    if contains_any(
        r,
        (
            "以验车为准",
            "以门店验车",
            "以实际验车",
            "以现场核验",
            "以现场核实",
            "以实车检测",
            "按门店验车",
            "按实际车况",
            "按现场核验",
            "按现场核实",
            "验车核实后确认",
            "验车核实后再给",
            "验车核实后给",
            "验车核实后再确认",
            "现场核实后再给",
            "现场核验后再给",
            "实车检测后再给",
            "现场核验结果为准",
        ),
    ):
        return True
    return bool(
        re.search(
            r"(最终价格|最终报价|最终收购价).{0,28}(以|按).{0,24}(验车|门店|实际|车况|检测|核验|核实|现场|手续).{0,16}(为准|确认)",
            r,
        )
        or re.search(
            r"(以|按).{0,24}(验车|门店|实际|车况|检测|核验|核实|现场|手续).{0,16}(为准|确认).{0,28}(最终价格|最终报价|最终收购价)",
            r,
        )
        or re.search(
            r"(验车|现场|实车|车况|检测|核验|核实|手续).{0,12}(后|完).{0,12}(再)?(给|确认|核定).{0,8}(最终价格|最终报价|最终收购价|收购价|报价|价格)",
            r,
        )
        or re.search(
            r"(最终价格|最终报价|最终收购价|收购价|报价|价格).{0,14}(验车|现场|实车|车况|检测|核验|核实|手续).{0,12}(确认|核定|为准)",
            r,
        )
    )


def is_contextual_recommendation_followup(text: str) -> bool:
    """Detect relative follow-ups that ask Brain to use prior need context."""
    compact = re.sub(r"\s+", "", str(text or "")).lower()
    if not compact:
        return False
    context_terms = (
        "刚才",
        "前面",
        "上面",
        "按你说的",
        "按我说的",
        "按刚才",
        "按前面",
        "这两台",
        "这几个",
        "那两台",
        "那几个",
        "这个方向",
    )
    action_terms = (
        "挑",
        "推荐",
        "选",
        "筛",
        "给我",
        "直接",
        "别再问",
        "不用再问",
        "哪台",
        "哪个",
        "更适合",
    )
    return any(term in compact for term in context_terms) and any(term in compact for term in action_terms)


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


def check_budget_fit_recommendation(
    reply: str,
    evidence_pack: dict[str, Any],
    *,
    current_message: str = "",
    budget_upper: float,
) -> dict[str, Any]:
    items = iter_authoritative_product_items(evidence_pack)
    if not items:
        return {}
    affordable_ids: set[str] = set()
    for item in items:
        price = quality_product_price_wan(item)
        if price <= 0 or price > budget_upper + 0.03:
            continue
        affordable_ids.add(quality_product_identity(item) or str(item.get("name") or "budget_fit_product"))
    if not affordable_ids:
        return {}
    over_budget_mentioned_set: set[str] = set()
    affordable_mentioned_set: set[str] = set()
    for item in items:
        terms = product_item_quality_terms(item)
        if not terms or not mentions_any_entity(reply, terms):
            continue
        item_id = quality_product_identity(item) or str(item.get("name") or "")
        price = quality_product_price_wan(item)
        if price > budget_upper + 0.03:
            over_budget_mentioned_set.add(item_id or "over_budget")
        elif price > 0:
            affordable_mentioned_set.add(item_id or "affordable")
    over_budget_mentioned = sorted(over_budget_mentioned_set)
    affordable_mentioned = sorted(affordable_mentioned_set)
    if over_budget_mentioned and not affordable_mentioned:
        return {
            "error": "over_budget_recommendation_ignores_budget_fit_candidates",
            "over_budget_mentioned": over_budget_mentioned,
        }
    if (
        over_budget_mentioned
        and len(affordable_mentioned) < 2
        and is_broad_product_recommendation_request(current_message)
    ):
        if len(affordable_ids) < 2 and reply_marks_over_budget_caveat(reply):
            return {}
        return {
            "error": "over_budget_recommendation_fills_budget_slot",
            "over_budget_mentioned": over_budget_mentioned,
            "affordable_mentioned": affordable_mentioned,
            "affordable_candidate_count": len(affordable_ids),
        }
    return {}


def reply_marks_over_budget_caveat(reply: str) -> bool:
    return contains_any(reply, OVER_BUDGET_CAVEAT_TERMS)


def check_known_budget_fit_product_price_uncertainty(reply: str, evidence_pack: dict[str, Any], *, budget_upper: float) -> dict[str, Any]:
    if not contains_any(reply, KNOWN_PRICE_UNCERTAINTY_TERMS):
        return {}
    uncertain_affordable: list[str] = []
    for item in iter_authoritative_product_items(evidence_pack):
        price = quality_product_price_wan(item)
        if price <= 0 or price > budget_upper + 0.03:
            continue
        terms = product_item_quality_terms(item)
        if terms and mentions_any_entity(reply, terms):
            uncertain_affordable.append(str(item.get("id") or item.get("product_id") or item.get("name") or "budget_fit_product"))
    if uncertain_affordable:
        return {
            "error": "known_budget_fit_product_marked_price_uncertain",
            "product_ids": uncertain_affordable,
        }
    return {}


def check_multi_product_recommendation_count(
    reply: str,
    evidence_pack: dict[str, Any],
    *,
    current_message: str,
    budget_upper: float | None,
) -> dict[str, Any]:
    if not is_multi_product_recommendation_request(current_message):
        return {}
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in iter_authoritative_product_items(evidence_pack):
        item_id = quality_product_identity(item) or str(item.get("name") or "")
        if not item_id or item_id in seen:
            continue
        price = quality_product_price_wan(item)
        if budget_upper is not None and budget_upper > 0 and (price <= 0 or price > budget_upper + 0.03):
            continue
        seen.add(item_id)
        candidates.append(item)
    if len(candidates) < 2:
        return {}
    mentioned: list[str] = []
    for item in candidates:
        if mentions_direct_product_entity(reply, item):
            item_id = quality_product_identity(item) or str(item.get("name") or "")
            if item_id and item_id not in mentioned:
                mentioned.append(item_id)
    if len(mentioned) >= 2:
        return {}
    if reply_transparently_limits_multi_recommendation(reply, mentioned_count=len(mentioned)):
        return {}
    return {
        "error": "missing_multiple_product_recommendations",
        "mentioned_product_ids": mentioned,
        "candidate_count": len(candidates),
    }


def reply_transparently_limits_multi_recommendation(reply: str, *, mentioned_count: int) -> bool:
    if mentioned_count < 1:
        return False
    clean = normalize_space(reply)
    if not clean:
        return False
    no_second_terms = (
        "没有第二台",
        "暂时没有第二台",
        "当前没有第二台",
        "目前没有第二台",
        "只有一台",
        "只看到一台",
        "只确认到一台",
    )
    scope_terms = (
        "同时满足",
        "都满足",
        "完全贴合",
        "完全符合",
        "预算",
        "南京",
        "条件",
        "需求",
        "要求",
    )
    if contains_any(clean, no_second_terms) and contains_any(clean, scope_terms):
        return True
    explicit_limitation_terms = (
        "先看这一台",
        "不拿不贴合的车硬凑",
    )
    return contains_any(clean, explicit_limitation_terms) and contains_any(clean, no_second_terms)


def is_multi_product_recommendation_request(question: str) -> bool:
    clean = str(question or "")
    return contains_any(
        clean,
        (
            "两台",
            "两款",
            "两个",
            "两三个",
            "2台",
            "2款",
            "几个方向",
            "三台",
            "三款",
            "三个方向",
        ),
    ) and is_broad_product_recommendation_request(clean)


def reply_has_clear_recommendation_or_choice(reply: str, plan: dict[str, Any], evidence_pack: dict[str, Any]) -> bool:
    """Return whether the visible reply makes a concrete choice.

    This is deliberately a quality-contract helper, not a business rule.  Brain
    may express recommendations naturally ("主推/第一/备选/三个方向"), so the
    gate should recognize clear, product-anchored choices without forcing a
    narrow template.
    """

    clean = normalize_space(reply)
    if not clean:
        return False
    if contains_any(clean, DIRECT_RECOMMENDATION_TERMS):
        return True
    if not reply_mentions_authoritative_product(clean, evidence_pack):
        return False
    if contains_any(clean, CLEAR_RECOMMENDATION_STRUCTURE_TERMS):
        return True
    answer_mode = str(plan.get("answer_mode") or "").strip()
    if answer_mode in {"recommend_from_catalog", "compare_options"} and PRICE_VALUE_RE.search(clean):
        return True
    return False


def reply_mentions_authoritative_product(reply: str, evidence_pack: dict[str, Any]) -> bool:
    for item in iter_authoritative_product_items(evidence_pack):
        if mentions_direct_product_entity(reply, item):
            return True
    return False


def check_available_cargo_fit_candidate_for_broad_request(
    reply: str,
    evidence_pack: dict[str, Any],
    *,
    budget_upper: float | None,
) -> dict[str, Any]:
    candidates = collect_available_cargo_fit_candidates(evidence_pack, budget_upper=budget_upper)
    if not candidates:
        return {}
    candidate_ids = [quality_product_identity(item) or str(item.get("name") or "") for item in candidates[:5]]
    if contains_any(reply, NO_NONSEDAN_AVAILABLE_TERMS):
        return {
            "error": "contradicts_available_cargo_fit_candidate",
            "candidate_ids": candidate_ids,
        }
    if any(mentions_direct_product_entity(reply, item) for item in candidates):
        return {}
    return {
        "error": "missing_available_cargo_fit_candidate",
        "candidate_ids": candidate_ids,
    }


def collect_available_cargo_fit_candidates(evidence_pack: dict[str, Any], *, budget_upper: float | None) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in iter_authoritative_product_items(evidence_pack):
        if not is_cargo_fit_product_item(item):
            continue
        price = quality_product_price_wan(item)
        if budget_upper is not None and budget_upper > 0 and (price <= 0 or price > budget_upper + 0.03):
            continue
        identity = quality_product_identity(item) or str(item.get("name") or "")
        if identity and identity in seen:
            continue
        if identity:
            seen.add(identity)
        candidates.append(item)
    return candidates


def check_unverified_cargo_capacity_claim(reply: str, evidence_pack: dict[str, Any]) -> dict[str, Any]:
    """Block affirmative cargo-fit claims when no dimensions are available."""

    if cargo_dimension_evidence_available(evidence_pack):
        return {}
    check_text = str(reply or "")
    for neutral_phrase in ("能不能塞下", "能不能装下", "能否塞下", "能否装下", "是否塞下", "是否装下"):
        check_text = check_text.replace(neutral_phrase, "")
    affirmative_terms = (
        "大概率能塞",
        "大概率能装",
        "基本能塞",
        "基本能装",
        "应该能塞",
        "应该能装",
        "能塞下",
        "能装下",
        "塞得下",
        "装得下",
        "够装",
        "问题不大",
    )
    if contains_any(check_text, affirmative_terms):
        return {"error": "unverified_cargo_capacity_affirmative_claim"}
    return {}


def cargo_dimension_evidence_available(evidence_pack: dict[str, Any]) -> bool:
    dimension_terms = ("后备厢容积", "后备箱容积", "放倒后", "装载尺寸", "容积", "尺寸", "长", "宽", "高", "mm", "cm", "l")
    cargo_terms = ("后备厢", "后备箱", "装载", "第二排", "后排", "放倒", "梯子", "工具箱")
    for item in iter_authoritative_product_items(evidence_pack):
        text = json.dumps(item, ensure_ascii=False).lower()
        if contains_any(text, dimension_terms) and contains_any(text, cargo_terms):
            return True
    return False


def is_cargo_fit_product_item(item: dict[str, Any]) -> bool:
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    text = compact_entity_text(
        " ".join(
            str(value or "")
            for value in (
                item.get("category"),
                item.get("name"),
                item.get("title"),
                item.get("specs"),
                data.get("category"),
                data.get("name"),
                data.get("title"),
                data.get("specs"),
            )
        )
    )
    return any(compact_entity_text(term) in text for term in CARGO_FIT_CATEGORY_TERMS)


def check_relative_context_product_binding(reply: str, evidence_pack: dict[str, Any]) -> dict[str, Any]:
    recent_ids = collect_recent_context_product_ids(evidence_pack)
    visible_history_ids = collect_visible_history_context_product_ids(evidence_pack)
    allowed_ids = [*recent_ids]
    for item in visible_history_ids:
        add_unique_product_id(allowed_ids, item)
    if not allowed_ids:
        return {}
    allowed = set(allowed_ids)
    mentioned: list[str] = []
    disallowed: list[str] = []
    for item in iter_authoritative_product_items(evidence_pack):
        item_id = quality_product_identity(item)
        if not item_id or not mentions_direct_product_entity(reply, item):
            continue
        if item_id not in mentioned:
            mentioned.append(item_id)
        if item_id not in allowed and item_id not in disallowed:
            disallowed.append(item_id)
    if disallowed:
        return {
            "error": "relative_context_product_drift",
            "mentioned_product_ids": mentioned,
            "allowed_recent_product_ids": allowed_ids,
            "allowed_visible_history_product_ids": visible_history_ids,
            "disallowed_product_ids": disallowed,
        }
    if mentioned and not any(item in allowed for item in mentioned):
        return {
            "error": "missing_relative_context_product_reference",
            "mentioned_product_ids": mentioned,
            "allowed_recent_product_ids": allowed_ids,
            "allowed_visible_history_product_ids": visible_history_ids,
        }
    if not mentioned:
        return {
            "error": "missing_relative_context_product_reference",
            "mentioned_product_ids": [],
            "allowed_recent_product_ids": allowed_ids,
            "allowed_visible_history_product_ids": visible_history_ids,
        }
    return {}


def is_ambiguous_product_followup(question: str, evidence_pack: dict[str, Any]) -> bool:
    if not collect_primary_context_product_id(evidence_pack):
        return False
    if not contains_any(question, AMBIGUOUS_PRODUCT_FOLLOWUP_TERMS):
        return False
    if is_broad_product_recommendation_request(question):
        return False
    # If the customer explicitly names a product in this turn, let that explicit
    # mention override prior context. The drift guard is for natural follow-ups
    # such as "油耗和保养呢" or "车况会说清楚吗".
    for item in iter_authoritative_product_items(evidence_pack):
        if mentions_direct_product_entity(question, item):
            return False
    return True


def is_broad_product_recommendation_request(question: str) -> bool:
    clean = str(question or "")
    if contains_any(clean, ("这台", "这辆", "这个车", "它", "刚才", "前面", "上面", "这两台", "那两台")):
        return False
    return contains_any(
        clean,
        (
            "给我两三个",
            "两三个方向",
            "几个方向",
            "三个方向",
            "先按",
            "按预算",
            "推荐",
            "建议",
            "方向",
            "挑两台",
            "挑两款",
            "挑几个",
            "挑几台",
            "选两台",
            "选两款",
            "两台靠谱",
            "两款靠谱",
        ),
    )


def check_ambiguous_followup_product_binding(reply: str, evidence_pack: dict[str, Any]) -> dict[str, Any]:
    primary_id = collect_primary_context_product_id(evidence_pack)
    if not primary_id:
        return {}
    mentioned: list[str] = []
    drifted: list[str] = []
    first_positions: dict[str, int] = {}
    for item in iter_authoritative_product_items(evidence_pack):
        item_id = quality_product_identity(item)
        if not item_id:
            continue
        position = direct_product_entity_position(reply, item)
        if position < 0:
            continue
        if item_id not in mentioned:
            mentioned.append(item_id)
        first_positions[item_id] = min(first_positions.get(item_id, position), position)
        if item_id != primary_id and item_id not in drifted:
            drifted.append(item_id)
    if drifted:
        primary_position = first_positions.get(primary_id, -1)
        first_drift_position = min(first_positions.get(item_id, 10**9) for item_id in drifted)
        if primary_position >= 0 and primary_position < first_drift_position:
            return {}
        return {
            "error": "ambiguous_followup_product_drift",
            "primary_product_id": primary_id,
            "mentioned_product_ids": mentioned,
            "drifted_product_ids": drifted,
        }
    primary_item = find_authoritative_product_item_by_id(evidence_pack, primary_id)
    if primary_item and mentions_direct_product_entity(reply, primary_item):
        return {}
    return {}


def collect_recent_context_product_ids(evidence_pack: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for context in iter_conversation_contexts(evidence_pack):
        for item in context.get("recent_product_ids", []) or []:
            add_unique_product_id(ids, item)
        add_unique_product_id(ids, context.get("last_product_id"))
    return ids[:5]


def collect_visible_history_context_product_ids(evidence_pack: dict[str, Any]) -> list[str]:
    """Recover product context from prior visible assistant replies.

    This is a guard against quality-gate false positives when the conversation
    state did not persist all products from the last visible recommendation.
    Only self/bot history lines are considered, so a customer's casual product
    mention does not become an authorized "previous recommendation".
    """

    conversation = evidence_pack.get("conversation") if isinstance(evidence_pack.get("conversation"), dict) else {}
    history_text = str(conversation.get("history_text") or "")
    if not history_text:
        return []
    assistant_texts: list[str] = []
    for line in history_text.splitlines():
        clean = str(line or "").strip()
        if clean.startswith("[客服]") or clean.startswith("[AI客服]"):
            assistant_texts.append(clean)
    if not assistant_texts:
        return []
    ids: list[str] = []
    joined = "\n".join(assistant_texts[-4:])
    for item in iter_authoritative_product_items(evidence_pack):
        item_id = quality_product_identity(item)
        if not item_id or item_id in ids:
            continue
        if mentions_direct_product_entity(joined, item):
            ids.append(item_id)
    return ids[:5]


def collect_primary_context_product_id(evidence_pack: dict[str, Any]) -> str:
    for context in iter_conversation_contexts(evidence_pack):
        product_id = str(context.get("last_product_id") or "").strip()
        if product_id:
            return product_id
        recent_ids = context.get("recent_product_ids") if isinstance(context.get("recent_product_ids"), list) else []
        for item in recent_ids:
            product_id = str(item or "").strip()
            if product_id:
                return product_id
    return ""


def find_authoritative_product_item_by_id(evidence_pack: dict[str, Any], product_id: str) -> dict[str, Any]:
    wanted = str(product_id or "").strip()
    if not wanted:
        return {}
    for item in iter_authoritative_product_items(evidence_pack):
        if quality_product_identity(item) == wanted:
            return item
    return {}


def iter_conversation_contexts(evidence_pack: dict[str, Any]) -> list[dict[str, Any]]:
    contexts: list[dict[str, Any]] = []
    conversation = evidence_pack.get("conversation") if isinstance(evidence_pack.get("conversation"), dict) else {}
    context = conversation.get("context") if isinstance(conversation.get("context"), dict) else {}
    if context:
        contexts.append(context)
    knowledge = evidence_pack.get("knowledge") if isinstance(evidence_pack.get("knowledge"), dict) else {}
    context = knowledge.get("conversation_context") if isinstance(knowledge.get("conversation_context"), dict) else {}
    if context:
        contexts.append(context)
    return contexts


def add_unique_product_id(ids: list[str], value: Any) -> None:
    text = str(value or "").strip()
    if text and text not in ids:
        ids.append(text)


def quality_product_identity(item: dict[str, Any]) -> str:
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    for key in ("id", "product_id", "sku"):
        value = str(item.get(key) or data.get(key) or "").strip()
        if value:
            return value
    return ""


def extract_quality_budget_upper(question: str, evidence_pack: dict[str, Any]) -> float | None:
    texts = [str(question or "")]
    conversation = evidence_pack.get("conversation") if isinstance(evidence_pack.get("conversation"), dict) else {}
    context = conversation.get("context") if isinstance(conversation.get("context"), dict) else {}
    texts.append(str(context.get("last_customer_need_text") or ""))
    knowledge = evidence_pack.get("knowledge") if isinstance(evidence_pack.get("knowledge"), dict) else {}
    context = knowledge.get("conversation_context") if isinstance(knowledge.get("conversation_context"), dict) else {}
    texts.append(str(context.get("last_customer_need_text") or ""))
    values: list[float] = []
    for text in texts:
        values.extend(
            quality_budget_around_upper(float(item))
            for item in re.findall(r"(\d+(?:\.\d+)?)\s*(?:万|w|W)\s*(?:左右|上下|附近|出头)", text)
        )
        for start, end in re.findall(r"(\d+(?:\.\d+)?)\s*(?:到|-|~|至|—|－)\s*(\d+(?:\.\d+)?)\s*万", text):
            values.append(max(float(start), float(end)))
        values.extend(float(item) for item in re.findall(r"(\d+(?:\.\d+)?)\s*(?:万|w|W)", text))
        for start, end in re.findall(
            r"([零〇一二两三四五六七八九十百]+(?:点[零〇一二两三四五六七八九]+)?)\s*(?:到|-|~|至|—|－)\s*([零〇一二两三四五六七八九十百]+(?:点[零〇一二两三四五六七八九]+)?)\s*万",
            text,
        ):
            parsed = [parse_quality_chinese_wan_budget(start), parse_quality_chinese_wan_budget(end)]
            values.extend(item for item in parsed if item is not None)
        values.extend(
            quality_budget_around_upper(value)
            for value in (
                parse_quality_chinese_wan_budget(match.group(1))
                for match in re.finditer(
                    r"([零〇一二两三四五六七八九十百]+(?:点[零〇一二两三四五六七八九]+)?)\s*万\s*(?:左右|上下|附近|出头)",
                    text,
                )
            )
            if value is not None
        )
        values.extend(
            value
            for value in (
                parse_quality_chinese_wan_budget(match.group(0))
                for match in re.finditer(r"[零〇一二两三四五六七八九十百]+(?:点[零〇一二两三四五六七八九]+)?\s*万", text)
            )
            if value is not None
        )
    return max(values) if values else None


def quality_budget_around_upper(value: float) -> float:
    """Keep quality checks aligned with catalog ranking for "X万左右" budgets."""

    if value <= 0:
        return value
    if value <= 6:
        return value + 1.0
    if value <= 15:
        return value + 1.5
    return value * 1.12


def parse_quality_chinese_wan_budget(text: str) -> float | None:
    token = re.sub(r"\s*万.*$", "", str(text or "").strip())
    if not token:
        return None
    if "点" in token:
        integer_text, decimal_text = token.split("点", 1)
        integer_value = quality_chinese_integer_to_int(integer_text)
        digit_map = quality_chinese_digit_map()
        digits = []
        for char in decimal_text:
            if char not in digit_map:
                return None
            digits.append(str(digit_map[char]))
        if integer_value is None or not digits:
            return None
        return float(f"{integer_value}.{''.join(digits)}")
    integer_value = quality_chinese_integer_to_int(token)
    return float(integer_value) if integer_value is not None else None


def quality_chinese_integer_to_int(text: str) -> int | None:
    token = str(text or "").strip()
    if not token:
        return None
    digit_map = quality_chinese_digit_map()
    total = 0
    current = 0
    has_unit = False
    for char in token:
        if char in digit_map:
            current = digit_map[char]
            continue
        if char == "十":
            has_unit = True
            total += (current or 1) * 10
            current = 0
            continue
        if char == "百":
            has_unit = True
            total += (current or 1) * 100
            current = 0
            continue
        return None
    if has_unit:
        return total + current
    if len(token) == 1 and token in digit_map:
        return digit_map[token]
    return None


def quality_chinese_digit_map() -> dict[str, int]:
    return {
        "零": 0,
        "〇": 0,
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }


def quality_product_price_wan(item: dict[str, Any]) -> float:
    for container in (item, item.get("data") if isinstance(item.get("data"), dict) else {}):
        for key in ("price", "price_wan", "报价", "标价"):
            try:
                value = container.get(key)
            except AttributeError:
                continue
            parsed = parse_quality_price_value(value)
            if parsed > 0:
                return parsed
    return 0.0


def parse_quality_price_value(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "")
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:万|万元|w|W)?", text)
    return float(match.group(1)) if match else 0.0


def product_item_quality_terms(item: dict[str, Any]) -> list[str]:
    terms: list[str] = []
    for key in ("name", "title", "model", "sku", "id", "product_id"):
        add_unique_text(terms, item.get(key))
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    for key in ("name", "title", "model", "sku", "id", "product_id"):
        add_unique_text(terms, data.get(key))
    for aliases in (item.get("aliases"), item.get("alias"), item.get("matched_aliases"), data.get("aliases"), data.get("alias")):
        if isinstance(aliases, list):
            for alias in aliases:
                add_unique_text(terms, alias)
        else:
            add_unique_text(terms, aliases)
    return terms


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


def mentions_direct_product_entity(reply: str, item: dict[str, Any]) -> bool:
    return direct_product_entity_position(reply, item) >= 0


def direct_product_entity_position(reply: str, item: dict[str, Any]) -> int:
    clean_reply = compact_entity_text(reply)
    if not clean_reply:
        return -1
    positions: list[int] = []
    for term in product_item_quality_terms(item):
        compact = compact_entity_text(term)
        if not is_direct_product_entity_term(compact):
            continue
        index = clean_reply.find(compact)
        if index >= 0:
            positions.append(index)
    return min(positions) if positions else -1


def is_direct_product_entity_term(compact_term: str) -> bool:
    text = compact_entity_text(compact_term)
    if len(text) < 2:
        return False
    if text in {compact_entity_text(item) for item in QUALITY_WEAK_PRODUCT_ENTITY_TERMS}:
        return False
    if re.fullmatch(r"\d+(?:款|年|万|公里)?", text):
        return False
    if re.fullmatch(r"\d+(?:\.\d+)?[tTlL]", text):
        return False
    if re.fullmatch(r"\d{2,4}[a-z]+", text) and not re.search(r"[a-z]+\d", text):
        return False
    return True


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
        "如果客户只是问候、催促、感谢或告别，也必须由Brain生成一句简短自然的客户可见回复，不能空回复、不能转人工、不能机械沉默；"
        "如果客户使用“刚才/前面/这两台/直接挑”等指代表达，必须结合conversation.context、history_text和product_master候选延续上一轮需求，不能只回复“确认/稍等”；"
        "如果失败项包含relative_context_product_drift或missing_relative_context_product_reference，必须只围绕recent_product_ids/上一轮可见推荐商品回答，不能换成新的商品候选；"
        "如果失败项包含ambiguous_followup_product_drift，说明客户在问“车况/油耗/保养/这台”等模糊追问，必须默认指向conversation.context里的last_product_id，不能切到备选商品；"
        "如果失败项包含missing_cargo_space_topic，必须正面回应客户的后备厢/装载/空间约束，推荐理由里要解释哪台更贴合这个使用场景；"
        "如果失败项包含missing_available_cargo_fit_candidate或contradicts_available_cargo_fit_candidate，说明product_master里已有预算内装载/空间更贴合的非轿车候选，必须点名这些候选，不能说现有都是轿车，也不能只泛泛说以后再筛SUV；"
        "如果失败项包含known_budget_fit_product_marked_price_uncertain，说明商品库已有预算内价格，必须直接按product_master价格表达，不能说还要看报价能否压进预算；"
        "如果失败项包含over_budget_recommendation_fills_budget_slot，说明客户让你按预算挑多台车，超预算车型不能冒充预算内推荐；"
        "预算内候选不足两台时，可以先主推预算内候选，再把超预算车明确标成备选/预算外选择，并说明取舍，不能含糊成同等级推荐；"
        "如果失败项包含missing_multiple_product_recommendations，说明客户明确要两台/多台推荐，且product_master/catalog_candidates候选足够，必须给出至少两台符合预算或近预算的具体候选；"
        "若第二台不完全贴合空间/城市/车系偏好，也要把缺口说清楚，不能用“继续筛/再找找/后面补筛”代替具体推荐；"
        "如果失败项包含appointment_commitment_without_confirmation_boundary或missing_appointment_confirmation_boundary，说明客户涉及到店/预约/看车安排，必须先表达已记下，再说需要核实车源状态和门店排期，确认后回复，不能直接说“过来就可以/直接来”；"
        "如果失败项包含trade_in_process_overcommit_without_formal_authority或trade_in_final_price_missing_verification_boundary，说明置换/收购流程表达过度承诺，必须改成先初估、再按门店验车/手续核实确认，不能承诺上门验车、当天打款或最终收购价；"
        "回复要短，单条简单回复尽量控制在120个有效内容字符以内；复杂问题可拆成2到3条完整短句，总有效内容字符尽量不超过150，不能漏答子问题；"
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
    can_answer = bool(plan.get("can_answer", True))
    if not can_answer and plan_allows_safe_uncertain_send(plan, action=action, needs_handoff=needs_handoff):
        can_answer = True
    return {
        "can_answer": can_answer,
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


def plan_allows_safe_uncertain_send(plan: dict[str, Any], *, action: str, needs_handoff: bool) -> bool:
    if action != "send_reply" or needs_handoff:
        return False
    if not join_reply_segments(plan.get("reply_segments", []) or []):
        return False
    answer_mode = str(plan.get("answer_mode") or "")
    if answer_mode not in {"ask_clarifying_question", "soft_social_reply", "soft_redirect_to_business", "direct_answer"}:
        return False
    risk = plan.get("risk") if isinstance(plan.get("risk"), dict) else {}
    if str(risk.get("risk_level") or "low").lower() in {"high", "critical"}:
        return False
    return True


def compact_brain_plan(plan: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(plan) if isinstance(plan, dict) else {}
    if "reply_segments" in payload:
        payload["reply_segments"] = [str(item)[:240] for item in payload.get("reply_segments", []) or []]
    return payload
