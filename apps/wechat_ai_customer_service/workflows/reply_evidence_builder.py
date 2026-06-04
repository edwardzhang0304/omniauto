"""Evidence packaging for guarded LLM reply synthesis.

This module is intentionally additive. It reuses the existing structured
knowledge and runtime-allowed retrieval output, then packages it for an LLM that can write a
natural WeChat reply. The package is audit-friendly so operators can verify
that product master, formal knowledge and current conversation facts actually participated.
"""

from __future__ import annotations

import re
from typing import Any

from apps.wechat_ai_customer_service.platform_understanding_rules import intent_group
from admin_backend.services.raw_message_store import RawMessageStore
from apps.wechat_ai_customer_service.admin_backend.services.conversation_history import assemble_conversation_history
from knowledge_loader import build_evidence_pack
from knowledge_runtime import KnowledgeRuntime
from evidence_authority import (
    PRODUCT_MASTER_CATEGORY_ID,
    annotate_authority,
    authority_order_payload,
    can_authorize_reply_content,
    dedupe_authoritative_products,
)
from llm_common_sense_layer import build_common_sense_guidance, common_sense_prompt_fragment
from product_name_matcher import collect_matched_aliases, compact_match_text


DEFAULT_MAX_HISTORY_MESSAGES = 40
DEFAULT_HISTORY_CHAR_BUDGET = 12000
DEFAULT_MAX_RAG_HITS = 5
DEFAULT_MAX_TEXT_CHARS = 900
GENERIC_CATALOG_ALIAS_TERMS = {
    "mpv",
    "suv",
    "商务车",
    "保姆车",
    "新能源",
    "电动车",
    "绿牌",
    "混动",
    "油车",
    "家用",
    "通勤",
    "省心",
    "空间",
    "七座",
    "自动挡",
}

CATALOG_PRICE_SUPERLATIVE_TERMS = (
    "最贵",
    "价格最高",
    "报价最高",
    "标价最高",
    "最高价",
    "最高价格",
    "高端",
    "贵的车",
)

CATALOG_LIST_REQUEST_TERMS = (
    "报价",
    "标价",
    "价格表",
    "报价单",
    "车源",
    "库存",
    "现车",
    "在售",
    "有哪些车",
    "有什么车",
    "你们这儿",
    "你们这边",
    "发一下价格",
    "发下价格",
    "发一下报价",
    "发下报价",
)

QUOTE_HARD_BOUNDARY_TERMS = (
    "最低",
    "底价",
    "优惠",
    "折扣",
    "少点",
    "便宜点",
    "包过",
    "保证",
    "绝对",
    "定金",
    "订金",
    "事故",
    "水泡",
    "火烧",
    "赔",
    "赔付",
)

RELATIVE_CONTEXT_PRODUCT_TERMS = (
    "这辆",
    "这台",
    "这个",
    "这款",
    "这车",
    "这个车",
    "那辆",
    "那台",
    "那款",
    "那车",
    "那一个",
    "刚才",
    "上面",
    "前面",
    "它",
)

CONTEXT_PRODUCT_DETAIL_TERMS = (
    "报价",
    "什么价",
    "多少钱",
    "价格",
    "车况",
    "配置",
    "公里",
    "贷款",
    "置换",
)

GENERIC_PRODUCT_REFERENCE_TERMS = {
    "车",
    "车子",
    "二手车",
    "车型",
    "这辆",
    "这台",
    "这个",
    "这款",
    "这车",
    "这个车",
    "那辆",
    "那台",
    "那款",
    "那车",
    "刚才",
    "上面",
    "前面",
    "它",
    "你们",
    "你这",
    "你家",
}

RELATIVE_CONTEXT_PREFIX_FILLERS = {
    "",
    "什么",
    "多少",
    "大概",
    "大约",
    "具体",
    "现在",
    "目前",
    "这个",
    "那个",
    "这车",
    "那车",
    "车",
}


def build_reply_evidence_pack(
    *,
    config: dict[str, Any],
    target_name: str,
    target_state: dict[str, Any],
    batch: list[dict[str, Any]],
    combined: str,
    decision: Any,
    reply_text: str,
    intent_assist: dict[str, Any],
    rag_reply: dict[str, Any],
    llm_reply: dict[str, Any],
    product_knowledge: dict[str, Any],
    data_capture: dict[str, Any],
    raw_capture: dict[str, Any],
    customer_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    settings = config.get("llm_reply_synthesis", {}) or {}
    context = dict(target_state.get("conversation_context", {}) or {})
    try:
        knowledge_pack = build_evidence_pack(combined, context=context)
        knowledge_error = ""
    except Exception as exc:
        knowledge_pack = {}
        knowledge_error = repr(exc)

    compact_knowledge = compact_knowledge_pack(
        combined,
        knowledge_pack,
        max_rag_hits=int(settings.get("max_rag_hits", DEFAULT_MAX_RAG_HITS) or DEFAULT_MAX_RAG_HITS),
        max_rag_text_chars=int(settings.get("max_rag_text_chars", DEFAULT_MAX_TEXT_CHARS) or DEFAULT_MAX_TEXT_CHARS),
        max_catalog_candidates=int(settings.get("max_catalog_candidates", 8) or 8),
    )
    common_sense = common_sense_prompt_fragment(
        build_common_sense_guidance(
            customer_message=combined,
            conversation_context=context,
        )
    )
    relax_soft_synthesis_safety(compact_knowledge, text=combined)
    history = recent_history(
        raw_capture=raw_capture,
        batch=batch,
        max_messages=int(settings.get("max_history_messages", DEFAULT_MAX_HISTORY_MESSAGES) or DEFAULT_MAX_HISTORY_MESSAGES),
        char_budget=int(settings.get("history_char_budget", DEFAULT_HISTORY_CHAR_BUDGET) or DEFAULT_HISTORY_CHAR_BUDGET),
    )

    history_text_pack = assemble_conversation_history(
        target_name=target_name,
        conversation_id=raw_conversation_id(raw_capture),
        current_batch=batch,
        config=config,
    )
    if settings.get("foreground_realtime"):
        history_text_pack = dict(history_text_pack)
        history_limit = max(300, int(settings.get("history_char_budget", DEFAULT_HISTORY_CHAR_BUDGET) or DEFAULT_HISTORY_CHAR_BUDGET))
        history_text_pack["history_text"] = truncate_text(str(history_text_pack.get("history_text") or ""), history_limit)
        history_text_pack["conversation_summary"] = truncate_text(str(history_text_pack.get("summary") or ""), 500)
        history_text_pack["current_batch_text"] = truncate_text(str(history_text_pack.get("current_batch_text") or ""), 600)

    evidence_ids = collect_evidence_ids(compact_knowledge)
    return {
        "schema_version": 1,
        "target": target_name,
        "current_message": truncate_text(combined, 2000),
        "current_batch": [compact_message(item) for item in batch],
        "conversation": {
            "context": context,
            "history": history,
            "history_count": len(history),
            "history_text": history_text_pack.get("history_text", ""),
            "current_batch_text": history_text_pack.get("current_batch_text", ""),
            "conversation_summary": history_text_pack.get("summary", ""),
            "raw_conversation_id": raw_conversation_id(raw_capture),
        },
        "existing_reply": {
            "decision": compact_decision(decision),
            "reply_text": truncate_text(reply_text, 1000),
            "rag_reply": compact_mapping(rag_reply, max_text_chars=500),
            "llm_reply": compact_mapping(llm_reply, max_text_chars=500),
        },
        "product_knowledge": compact_mapping(product_knowledge, max_text_chars=900),
        "data_capture": compact_mapping(data_capture, max_text_chars=500),
        "intent_assist": compact_mapping(intent_assist, max_text_chars=900),
        "knowledge": compact_knowledge,
        "authority_order": authority_order_payload(),
        "common_sense": common_sense,
        "knowledge_error": knowledge_error,
        "evidence_ids": evidence_ids,
        "safety": compact_knowledge.get("safety", {}),
        "intent_tags": compact_knowledge.get("intent_tags", []),
        "customer_profile": _compact_profile(customer_profile),
        "ai_experience_pool": compact_knowledge.get("ai_experience_pool", {}),
        "rag": compact_knowledge.get("rag_evidence", {}),
        "audit_summary": {
            "structured_evidence_count": structured_evidence_count(compact_knowledge),
            "runtime_rag_hit_count": len((compact_knowledge.get("rag_evidence", {}) or {}).get("hits", []) or []),
            "rag_hit_count": len((compact_knowledge.get("rag_evidence", {}) or {}).get("hits", []) or []),
            "excluded_ai_experience_pool_hit_count": int((compact_knowledge.get("ai_experience_pool", {}) or {}).get("excluded_hit_count") or 0),
            "rag_chunk_ids": [
                str(item.get("chunk_id") or "")
                for item in (compact_knowledge.get("rag_evidence", {}) or {}).get("hits", []) or []
                if item.get("chunk_id")
            ],
            "evidence_ids": evidence_ids,
        },
    }


def recent_history(
    *,
    raw_capture: dict[str, Any],
    batch: list[dict[str, Any]],
    max_messages: int,
    char_budget: int,
) -> list[dict[str, Any]]:
    conversation_id = raw_conversation_id(raw_capture)
    messages: list[dict[str, Any]] = []
    if conversation_id:
        try:
            messages = RawMessageStore().list_messages(conversation_id=conversation_id, limit=max_messages)
        except Exception:
            messages = []
    if not messages:
        messages = list(batch)
    compacted = [compact_message(item) for item in reversed(messages[:max_messages])]
    return trim_history(compacted, char_budget=max(500, char_budget))


def raw_conversation_id(raw_capture: dict[str, Any]) -> str:
    conversation = raw_capture.get("conversation", {}) or {}
    return str(conversation.get("conversation_id") or raw_capture.get("conversation_id") or "")


def compact_message(message: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(message.get("id") or message.get("message_id") or message.get("raw_message_id") or ""),
        "sender": str(message.get("sender") or ""),
        "time": str(message.get("time") or message.get("message_time") or message.get("observed_at") or ""),
        "content": truncate_text(str(message.get("content") or ""), 600),
    }


def _compact_profile(profile: dict[str, Any] | None) -> dict[str, Any]:
    if not profile:
        return {}
    basic = profile.get("basic_info") if isinstance(profile.get("basic_info"), dict) else {}
    tags = profile.get("tags") if isinstance(profile.get("tags"), dict) else {}
    return {
        "display_name": str(profile.get("display_name") or ""),
        "status": str(profile.get("status") or "active"),
        "gender": str(basic.get("gender") or ""),
        "gender_confidence": float(basic.get("gender_confidence") or 0.0),
        "region": str(basic.get("region") or ""),
        "total_messages": int(basic.get("total_messages", 0) or 0),
        "total_replies": int(basic.get("total_replies", 0) or 0),
        "conversation_summary": str(profile.get("conversation_summary") or ""),
        "tags": {k: str(v) for k, v in tags.items()},
    }


def trim_history(history: list[dict[str, Any]], *, char_budget: int) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    used = 0
    for item in reversed(history):
        content = str(item.get("content") or "")
        cost = len(content)
        if result and used + cost > char_budget:
            break
        result.append(item)
        used += cost
    return list(reversed(result))


def compact_knowledge_pack(
    text: str,
    pack: dict[str, Any],
    *,
    max_rag_hits: int,
    max_rag_text_chars: int,
    max_catalog_candidates: int,
) -> dict[str, Any]:
    evidence = pack.get("evidence", {}) or {}
    rag_evidence = pack.get("rag_evidence", {}) or {}
    context = pack.get("conversation_context") if isinstance(pack.get("conversation_context"), dict) else {}
    catalog_candidates = catalog_product_candidates(text, limit=max_catalog_candidates, context=context)
    item_limit = max(1, max_catalog_candidates)
    products = [
        annotate_authority(compact_mapping(item, max_text_chars=420), category_id=PRODUCT_MASTER_CATEGORY_ID)
        for item in (evidence.get("products", []) or [])[:item_limit]
    ]
    catalog_candidates = [
        annotate_authority(item, category_id=PRODUCT_MASTER_CATEGORY_ID)
        for item in catalog_candidates
        if isinstance(item, dict)
    ]
    if any(is_explicit_catalog_candidate(item) for item in catalog_candidates):
        products_for_merge = [item for item in products if not is_context_only_product_candidate(item)]
        product_master = dedupe_authoritative_products(catalog_candidates, products_for_merge)[:item_limit]
    else:
        product_master = dedupe_authoritative_products(products, catalog_candidates)[:item_limit]
    faq = [
        annotate_authority(compact_mapping(item, max_text_chars=360), category_id="faq")
        for item in (evidence.get("faq", []) or [])[:item_limit]
    ]
    product_scoped = [
        annotate_authority(compact_mapping(item, max_text_chars=360), category_id=str(item.get("category_id") or "product_faq"))
        for item in (evidence.get("product_scoped", []) or [])[:item_limit]
        if isinstance(item, dict)
    ]
    policies = compact_mapping(evidence.get("policies", {}) or {}, max_text_chars=700)
    rag_evidence = compact_rag_evidence(rag_evidence, max_hits=max_rag_hits, max_text_chars=max_rag_text_chars)
    return {
        "authority_order": authority_order_payload(),
        "intent_tags": list(pack.get("intent_tags", []) or []),
        "selected_items": [
            compact_mapping(item, max_text_chars=400)
            for item in (pack.get("selected_items", []) or [])[:item_limit]
            if isinstance(item, dict)
        ],
        "evidence": {
            "products": product_master,
            "faq": faq,
            "policies": policies,
            "product_scoped": product_scoped,
            "catalog_candidates": catalog_candidates,
            "style_examples": [
                compact_mapping(item, max_text_chars=260)
                for item in (evidence.get("style_examples", []) or [])[: min(item_limit, 2)]
            ],
        },
        "product_master": {
            "authority_level": "product_master",
            "can_authorize_product_facts": True,
            "items": product_master,
        },
        "formal_knowledge": {
            "authority_level": "formal_knowledge",
            "can_authorize_product_facts": False,
            "faq": faq,
            "policies": policies,
            "product_scoped": product_scoped,
        },
        "ai_experience_pool": {
            "authority_level": "ai_experience_pool",
            "can_authorize_product_facts": False,
            "can_authorize_reply_content": False,
            "usage": "governance_and_distribution_only",
            "excluded_hit_count": int(rag_evidence.get("excluded_hit_count") or 0),
            "source": {
                "enabled": rag_evidence.get("enabled", True),
                "reason": rag_evidence.get("reason") or "ai_experience_pool_not_runtime_content_basis",
                "hits": [],
            },
        },
        "rag_evidence": rag_evidence,
        "safety": compact_mapping(pack.get("safety", {}) or {}, max_text_chars=700),
        "matched_categories": list(pack.get("matched_categories", []) or []),
    }


def compact_rag_evidence(rag_evidence: dict[str, Any], *, max_hits: int, max_text_chars: int = DEFAULT_MAX_TEXT_CHARS) -> dict[str, Any]:
    hits = []
    excluded_hit_count = 0
    for item in rag_evidence.get("hits", []) or []:
        if not isinstance(item, dict):
            continue
        if not can_authorize_reply_content(item, category_id=str(item.get("category") or ""), source_type=str(item.get("source_type") or "")):
            excluded_hit_count += 1
            continue
        hits.append(
            {
                "chunk_id": item.get("chunk_id"),
                "source_id": item.get("source_id"),
                "score": item.get("score"),
                "category": item.get("category"),
                "source_type": item.get("source_type"),
                "product_id": item.get("product_id"),
                "retrieval_mode": item.get("retrieval_mode"),
                "risk_terms": item.get("risk_terms", []),
                "text": truncate_text(str(item.get("text") or ""), max(120, max_text_chars)),
            }
        )
        if len(hits) >= max(1, max_hits):
            break
    return {
        "enabled": rag_evidence.get("enabled", True),
        "ok": rag_evidence.get("ok"),
        "skipped": rag_evidence.get("skipped"),
        "reason": rag_evidence.get("reason"),
        "confidence": rag_evidence.get("confidence", 0.0),
        "rag_can_authorize": bool(rag_evidence.get("rag_can_authorize", False)),
        "structured_priority": rag_evidence.get("structured_priority", True),
        "excluded_hit_count": excluded_hit_count,
        "hits": hits,
    }


def collect_evidence_ids(pack: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    evidence = pack.get("evidence", {}) or {}
    for item in evidence.get("products", []) or []:
        append_id(ids, "product", item.get("id"))
    for item in evidence.get("faq", []) or []:
        append_id(ids, "faq", item.get("intent") or item.get("id"))
    for key in (evidence.get("policies", {}) or {}).keys():
        append_id(ids, "policy", key)
    for item in evidence.get("product_scoped", []) or []:
        append_id(ids, "product_scoped", item.get("id"))
    for item in evidence.get("catalog_candidates", []) or []:
        append_id(ids, "catalog_product", item.get("id"))
    for item in (pack.get("rag_evidence", {}) or {}).get("hits", []) or []:
        if can_authorize_reply_content(item, category_id=str(item.get("category") or ""), source_type=str(item.get("source_type") or "")):
            append_id(ids, "rag", item.get("chunk_id") or item.get("source_id"))
    return ids


def append_id(items: list[str], prefix: str, value: Any) -> None:
    text = str(value or "").strip()
    if text:
        marker = f"{prefix}:{text}"
        if marker not in items:
            items.append(marker)


def structured_evidence_count(pack: dict[str, Any]) -> int:
    evidence = pack.get("evidence", {}) or {}
    return (
        len(evidence.get("products", []) or [])
        + len(evidence.get("faq", []) or [])
        + len(evidence.get("policies", {}) or {})
        + len(evidence.get("product_scoped", []) or [])
        + len(evidence.get("catalog_candidates", []) or [])
    )


def relax_soft_synthesis_safety(pack: dict[str, Any], *, text: str = "") -> None:
    """Let the additive synthesis layer use catalog and allowed retrieval evidence for soft scenes.

    The base safety layer may mark a broad natural-language question as
    `no_relevant_business_evidence` before catalog candidates are attached. For
    soft selection questions this module can now provide formal catalog
    candidates plus runtime-allowed retrieval evidence. We only relax that narrow no-evidence marker;
    authority, price, finance, after-sales, or policy reasons remain untouched.
    """
    intent_tags = {str(item) for item in pack.get("intent_tags", []) or [] if str(item)}
    hard_authority_tags = intent_group("rag_authority_block") - {"quote"}
    if intent_tags & hard_authority_tags:
        return
    safety = pack.get("safety", {}) or {}
    if not isinstance(safety, dict) or not safety.get("must_handoff"):
        return
    reasons = {str(item) for item in safety.get("reasons", []) or [] if str(item)}
    if relax_product_master_grounded_quote_safety(pack, text=text, reasons=reasons):
        safety["must_handoff"] = False
        safety["allowed_auto_reply"] = True
        safety["reasons"] = []
        safety["llm_synthesis_product_master_quote_override"] = True
        return
    if not reasons or not reasons <= {"no_relevant_business_evidence"}:
        return
    if structured_evidence_count(pack) <= 0 and not ((pack.get("rag_evidence", {}) or {}).get("hits")):
        return
    safety["must_handoff"] = False
    safety["allowed_auto_reply"] = True
    safety["reasons"] = []
    safety["llm_synthesis_soft_evidence_override"] = True


def relax_product_master_grounded_quote_safety(pack: dict[str, Any], *, text: str, reasons: set[str]) -> bool:
    """Do not let broad shared price-risk FAQs block product-master-grounded quotes.

    Product master remains the only authority for product price/stock. Formal
    risk rules still win for true hard boundaries such as discounts, guarantees,
    deposits, financing approval, or condition commitments.
    """
    if not reasons or not reasons <= {"matched_faq_requires_handoff", "shared_risk_control", "missing_authoritative_evidence"}:
        return False
    intent_tags = {str(item) for item in pack.get("intent_tags", []) or [] if str(item)}
    if not ({"quote", "product"} & intent_tags):
        return False
    compact_text = compact_match_text(text)
    if any(compact_match_text(term) in compact_text for term in QUOTE_HARD_BOUNDARY_TERMS):
        return False
    evidence = pack.get("evidence", {}) if isinstance(pack.get("evidence"), dict) else {}
    product_items = [item for item in evidence.get("products", []) or [] if isinstance(item, dict)]
    catalog_items = [item for item in evidence.get("catalog_candidates", []) or [] if isinstance(item, dict)]
    if not product_items and not catalog_items:
        return False
    return any(product_has_price_or_stock(item) for item in [*product_items, *catalog_items])


def product_has_price_or_stock(item: dict[str, Any]) -> bool:
    if item.get("price") not in (None, ""):
        return True
    if item.get("stock") not in (None, ""):
        return True
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    return data.get("price") not in (None, "") or data.get("inventory") not in (None, "")


def catalog_product_candidates(text: str, *, limit: int, context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    try:
        runtime = KnowledgeRuntime()
        items = runtime.list_items("products")
    except Exception:
        return []
    context = context if isinstance(context, dict) else {}
    context_product = context_product_candidate(runtime, context, text, items=items)
    scored = []
    normalized = str(text or "").lower()
    catalog_request_mode = detect_catalog_request_mode(normalized)
    for item in items:
        if not isinstance(item, dict):
            continue
        data = item.get("data", {}) or {}
        if str(item.get("status") or "active") not in {"active", "approved", "published"}:
            continue
        matched_aliases = collect_catalog_product_aliases(data, normalized)
        searchable = product_searchable_text(data)
        score = catalog_alias_match_score(matched_aliases)
        for token in tokenize_for_catalog(normalized):
            if token and token in searchable:
                score += 2 if len(token) >= 2 else 1
        if score <= 0:
            score = fallback_catalog_score(data, normalized)
        payload = catalog_product_payload(item)
        if matched_aliases:
            payload["matched_aliases"] = matched_aliases[:8]
            payload["match_reason"] = "product_name_alias_or_semantic_match"
        scored.append((score, max_catalog_alias_length(matched_aliases), payload))
    scored.sort(key=lambda pair: (pair[0], pair[1]), reverse=True)
    ranked = [payload for score, _alias_len, payload in scored[: max(0, limit)] if score > 0]
    if catalog_request_mode == "price_desc":
        ranked = catalog_request_candidates(items, limit=limit, mode=catalog_request_mode)
    elif catalog_request_mode == "price_list" and not any(is_explicit_catalog_candidate(item) for item in ranked):
        ranked = catalog_request_candidates(items, limit=limit, mode=catalog_request_mode)
    budget_upper = extract_catalog_budget_upper(normalized)
    if budget_upper is not None and should_attach_budget_alternatives(normalized, ranked):
        ranked = merge_catalog_ranked_candidates(
            ranked,
            budget_alternative_catalog_candidates(
                items,
                limit=limit,
                budget_upper=budget_upper,
                target=ranked[0] if ranked else None,
            ),
            limit=limit,
        )
    if context_product:
        context_id = str(context_product.get("id") or "")
        ranked = [context_product, *[item for item in ranked if str(item.get("id") or "") != context_id]]
        if should_focus_context_product(text):
            ranked = ranked[:1]
    return ranked[: max(0, limit)]


def should_attach_budget_alternatives(normalized_text: str, ranked: list[dict[str, Any]]) -> bool:
    if not ranked or not any(is_explicit_catalog_candidate(item) for item in ranked):
        return False
    compact = compact_match_text(normalized_text)
    return any(compact_match_text(term) in compact for term in ("预算", "替代", "备选", "够不到", "超预算"))


def budget_alternative_catalog_candidates(
    items: list[dict[str, Any]],
    *,
    limit: int,
    budget_upper: float,
    target: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    target_id = str((target or {}).get("id") or "").strip()
    target_category = catalog_category_label(target or {})
    candidates: list[tuple[int, float, float, dict[str, Any]]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if str(item.get("status") or "active") not in {"active", "approved", "published"}:
            continue
        payload = catalog_product_payload(item)
        if str(payload.get("id") or "") == target_id:
            continue
        price = catalog_price_value(payload)
        if price <= 0 or price > budget_upper + 0.03:
            continue
        same_category_rank = 0 if target_category and catalog_category_label(payload) == target_category else 1
        payload["matched_aliases"] = ["budget_alternative"]
        payload["match_reason"] = "budget_alternative_price_fit"
        candidates.append((same_category_rank, abs(budget_upper - price), -price, payload))
    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    return [payload for _same_rank, _gap, _neg_price, payload in candidates[: max(0, int(limit or 0))]]


def merge_catalog_ranked_candidates(primary: list[dict[str, Any]], additions: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in [*(primary[:1] if primary else []), *additions, *(primary[1:] if len(primary) > 1 else [])]:
        item_id = str(item.get("id") or "")
        if item_id and item_id in seen:
            continue
        if item_id:
            seen.add(item_id)
        merged.append(item)
        if len(merged) >= max(0, int(limit or 0)):
            break
    return merged


def catalog_category_label(item: dict[str, Any]) -> str:
    category = str(item.get("category") or "").strip()
    if "/" in category:
        category = category.rsplit("/", 1)[-1]
    return category.strip()


def extract_catalog_budget_upper(text: str) -> float | None:
    raw = str(text or "")
    range_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:到|-|~|至|—|－)\s*(\d+(?:\.\d+)?)\s*万", raw)
    if range_match:
        return max(float(range_match.group(1)), float(range_match.group(2)))
    matches = [float(item) for item in re.findall(r"(\d+(?:\.\d+)?)\s*(?:万|w|W)", raw)]
    if matches:
        return max(matches)
    return None


def detect_catalog_request_mode(normalized_text: str) -> str:
    compact = compact_match_text(normalized_text)
    if not compact:
        return ""
    if any(compact_match_text(term) in compact for term in CATALOG_PRICE_SUPERLATIVE_TERMS):
        return "price_desc"
    if any(compact_match_text(term) in compact for term in CATALOG_LIST_REQUEST_TERMS):
        return "price_list"
    return ""


def catalog_request_candidates(items: list[dict[str, Any]], *, limit: int, mode: str) -> list[dict[str, Any]]:
    candidates: list[tuple[float, dict[str, Any]]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if str(item.get("status") or "active") not in {"active", "approved", "published"}:
            continue
        payload = catalog_product_payload(item)
        price = catalog_price_value(payload)
        if price <= 0:
            continue
        payload["matched_aliases"] = ["catalog_price_superlative" if mode == "price_desc" else "catalog_price_list"]
        payload["match_reason"] = "catalog_price_superlative" if mode == "price_desc" else "catalog_price_list_request"
        candidates.append((price, payload))
    candidates.sort(key=lambda pair: pair[0], reverse=True)
    return [payload for _price, payload in candidates[: max(0, int(limit or 0))]]


def catalog_price_value(item: dict[str, Any]) -> float:
    raw = item.get("price")
    try:
        return float(raw)
    except (TypeError, ValueError):
        digits = re.sub(r"[^0-9.]+", "", str(raw or ""))
        try:
            return float(digits) if digits else 0.0
        except ValueError:
            return 0.0


def collect_catalog_product_aliases(data: dict[str, Any], query_text: str) -> list[str]:
    aliases = [
        str(data.get("name") or ""),
        str(data.get("sku") or ""),
        *[str(alias) for alias in data.get("aliases", []) or []],
    ]
    matched = collect_matched_aliases(aliases, query_text)
    # Keep concrete model aliases first so "秦PLUS" beats generic "新能源/混动",
    # while still leaving generic hits available as weak recall signals.
    concrete = [alias for alias in matched if is_concrete_catalog_alias(alias)]
    generic = [alias for alias in matched if alias not in concrete]
    return [*concrete, *generic]


def catalog_alias_match_score(matched_aliases: list[str]) -> int:
    if not matched_aliases:
        return 0
    concrete = [alias for alias in matched_aliases if is_concrete_catalog_alias(alias)]
    if concrete:
        return 1000 + max_catalog_alias_length(concrete) * 10 + len(concrete)
    return 20 + max_catalog_alias_length(matched_aliases)


def max_catalog_alias_length(aliases: list[str]) -> int:
    lengths = [len(compact_match_text(alias)) for alias in aliases if compact_match_text(alias)]
    return max(lengths, default=0)


def is_concrete_catalog_alias(alias: str) -> bool:
    compact = compact_match_text(alias)
    if len(compact) < 2:
        return False
    if compact in {compact_match_text(item) for item in GENERIC_CATALOG_ALIAS_TERMS}:
        return False
    return True


def is_explicit_catalog_candidate(item: dict[str, Any]) -> bool:
    aliases = [str(alias) for alias in item.get("matched_aliases", []) or [] if str(alias)]
    if not aliases or item.get("context_used") is True:
        return False
    return any(alias != "conversation_context" and is_concrete_catalog_alias(alias) for alias in aliases)


def is_context_only_product_candidate(item: dict[str, Any]) -> bool:
    aliases = [str(alias) for alias in item.get("matched_aliases", []) or [] if str(alias)]
    return bool(aliases) and set(aliases) <= {"conversation_context"}


def context_product_candidate(
    runtime: KnowledgeRuntime,
    context: dict[str, Any],
    text: str,
    *,
    items: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    product_id = str(context.get("last_product_id") or "").strip()
    if not product_id or not should_focus_context_product(text):
        return None
    if text_has_explicit_other_catalog_product_reference(text, items=items, exclude_product_id=product_id):
        return None
    if text_has_unresolved_explicit_product_reference(text, items=items):
        return None
    try:
        item = runtime.get_item("products", product_id)
    except Exception:
        return None
    if not isinstance(item, dict):
        return None
    payload = catalog_product_payload(item)
    payload["matched_aliases"] = ["conversation_context"]
    payload["context_used"] = True
    return payload


def text_has_explicit_other_catalog_product_reference(
    text: str,
    *,
    items: list[dict[str, Any]] | None,
    exclude_product_id: str,
) -> bool:
    normalized = str(text or "").lower()
    if not normalized:
        return False
    exclude = str(exclude_product_id or "").strip()
    for item in items or []:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "").strip()
        if not item_id or item_id == exclude:
            continue
        if str(item.get("status") or "active") not in {"active", "approved", "published"}:
            continue
        data = item.get("data", {}) or {}
        matched_aliases = collect_catalog_product_aliases(data, normalized)
        if any(is_concrete_catalog_alias(alias) for alias in matched_aliases):
            return True
    return False


def text_has_unresolved_explicit_product_reference(text: str, *, items: list[dict[str, Any]] | None) -> bool:
    """Detect product-like direct references that should not inherit old context.

    If the current catalog can match the reference, `text_has_explicit_other_catalog_product_reference`
    handles it. This fallback is for user typos or out-of-stock names such as
    "塞纳多少钱" when the active tenant has no Sienna item: replying with the last
    context product would be worse than asking the Brain to clarify.
    """
    if text_has_any_catalog_product_reference(text, items=items):
        return False
    return text_has_product_like_reference_near_detail_term(text)


def text_has_any_catalog_product_reference(text: str, *, items: list[dict[str, Any]] | None) -> bool:
    normalized = str(text or "").lower()
    if not normalized:
        return False
    for item in items or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("status") or "active") not in {"active", "approved", "published"}:
            continue
        data = item.get("data", {}) or {}
        matched_aliases = collect_catalog_product_aliases(data, normalized)
        if any(is_concrete_catalog_alias(alias) for alias in matched_aliases):
            return True
    return False


def text_has_product_like_reference_near_detail_term(text: str) -> bool:
    compact = compact_match_text(text)
    if not compact:
        return False
    detail_terms = tuple(compact_match_text(term) for term in CONTEXT_PRODUCT_DETAIL_TERMS)
    relative_terms = tuple(compact_match_text(term) for term in RELATIVE_CONTEXT_PRODUCT_TERMS)
    for term in detail_terms:
        if not term:
            continue
        index = compact.find(term)
        if index <= 0:
            continue
        prefix = compact[:index]
        if not prefix or prefix_is_relative_context_reference(prefix):
            continue
        if prefix in {compact_match_text(item) for item in GENERIC_PRODUCT_REFERENCE_TERMS}:
            continue
        # A short brand/model token before "多少钱/价格/配置" is an explicit entity cue.
        if re.search(r"[a-z0-9]{2,}$", prefix, flags=re.IGNORECASE):
            return True
        chinese_tail = re.search(r"[\u4e00-\u9fff]{2,}$", prefix)
        if chinese_tail and chinese_tail.group(0) not in {compact_match_text(item) for item in GENERIC_PRODUCT_REFERENCE_TERMS}:
            return True
    return False


def prefix_is_relative_context_reference(prefix: str) -> bool:
    compact_prefix = compact_match_text(prefix)
    if not compact_prefix:
        return True
    relative_terms = tuple(compact_match_text(term) for term in RELATIVE_CONTEXT_PRODUCT_TERMS)
    filler_terms = {compact_match_text(item) for item in RELATIVE_CONTEXT_PREFIX_FILLERS}
    generic_terms = {compact_match_text(item) for item in GENERIC_PRODUCT_REFERENCE_TERMS}
    if compact_prefix in generic_terms:
        return True
    for relative in relative_terms:
        if not relative:
            continue
        if compact_prefix == relative or compact_prefix.endswith(relative):
            return True
        if compact_prefix.startswith(relative):
            tail = compact_prefix[len(relative) :]
            if tail in filler_terms or tail in generic_terms:
                return True
    return False


def should_focus_context_product(text: str) -> bool:
    normalized = re.sub(r"\s+", "", str(text or "").lower())
    if not normalized:
        return False
    relative_terms = (*RELATIVE_CONTEXT_PRODUCT_TERMS, *CONTEXT_PRODUCT_DETAIL_TERMS)
    return any(term in normalized for term in relative_terms)


def tokenize_for_catalog(text: str) -> list[str]:
    tokens = []
    for run in re.findall(r"[a-z0-9][a-z0-9_.-]{1,}|[\u4e00-\u9fff]{2,}", text, flags=re.IGNORECASE):
        normalized = run.lower()
        if len(normalized) <= 18:
            tokens.append(normalized)
        if re.search(r"[\u4e00-\u9fff]", normalized):
            for size in (2, 3, 4, 5, 6):
                if len(normalized) >= size:
                    tokens.extend(normalized[index : index + size] for index in range(0, len(normalized) - size + 1))
    return sorted(set(token for token in tokens if token.strip()), key=lambda item: (-len(item), item))


def fallback_catalog_score(data: dict[str, Any], query_text: str = "") -> int:
    query_tokens = set(tokenize_for_catalog(query_text))
    if not query_tokens:
        return 0
    product_tokens = set(tokenize_for_catalog(product_searchable_text(data)))
    if query_tokens & product_tokens:
        return 1
    return 0


def product_searchable_text(data: dict[str, Any]) -> str:
    parts = [
        str(data.get("name") or ""),
        str(data.get("sku") or ""),
        str(data.get("category") or ""),
        str(data.get("specs") or ""),
        " ".join(str(alias) for alias in data.get("aliases", []) or []),
        " ".join(str(rule) for rule in data.get("risk_rules", []) or []),
        " ".join(str(value) for value in (data.get("reply_templates", {}) or {}).values()),
        " ".join(str(value) for value in flatten_text_values(data.get("additional_details"))),
    ]
    return " ".join(part for part in parts if part).lower()


def flatten_text_values(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, (str, int, float, bool)):
        return [str(value)]
    if isinstance(value, list):
        values: list[str] = []
        for item in value:
            values.extend(flatten_text_values(item))
        return values
    if isinstance(value, dict):
        values = []
        for item in value.values():
            values.extend(flatten_text_values(item))
        return values
    return [str(value)]


def catalog_product_payload(item: dict[str, Any]) -> dict[str, Any]:
    data = item.get("data", {}) or {}
    return {
        "id": item.get("id"),
        "category_id": PRODUCT_MASTER_CATEGORY_ID,
        "authority_level": "product_master",
        "name": data.get("name"),
        "sku": data.get("sku"),
        "category": data.get("category"),
        "aliases": list(data.get("aliases", []) or [])[:10],
        "specs": truncate_text(str(data.get("specs") or ""), 260),
        "price": data.get("price"),
        "unit": data.get("unit"),
        "stock": data.get("inventory"),
        "shipping": truncate_text(str(data.get("shipping_policy") or ""), 220),
        "warranty": truncate_text(str(data.get("warranty_policy") or ""), 220),
        "reply_templates": compact_mapping(data.get("reply_templates", {}) or {}, max_text_chars=260),
        "risk_rules": list(data.get("risk_rules", []) or [])[:8],
    }


def compact_decision(decision: Any) -> dict[str, Any]:
    return {
        "reply_text": truncate_text(str(getattr(decision, "reply_text", "") or ""), 500),
        "rule_name": str(getattr(decision, "rule_name", "") or ""),
        "matched": bool(getattr(decision, "matched", False)),
        "need_handoff": bool(getattr(decision, "need_handoff", False)),
        "reason": str(getattr(decision, "reason", "") or ""),
    }


def compact_mapping(value: Any, *, max_text_chars: int = DEFAULT_MAX_TEXT_CHARS) -> Any:
    if isinstance(value, dict):
        return {
            str(key): compact_mapping(item, max_text_chars=max_text_chars)
            for key, item in value.items()
            if item not in (None, "", [], {})
        }
    if isinstance(value, list):
        return [compact_mapping(item, max_text_chars=max_text_chars) for item in value[:20]]
    if isinstance(value, str):
        return truncate_text(value, max_text_chars)
    return value


def truncate_text(text: str, max_chars: int) -> str:
    clean = " ".join(str(text or "").split())
    if len(clean) <= max_chars:
        return clean
    return clean[: max(1, max_chars - 1)].rstrip() + "..."
