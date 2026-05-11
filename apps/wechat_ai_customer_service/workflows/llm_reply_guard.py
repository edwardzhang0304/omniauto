"""Safety guard for LLM synthesized customer-service replies."""

from __future__ import annotations

import re
from typing import Any

from apps.wechat_ai_customer_service.platform_safety_rules import guard_term_set, load_platform_safety_rules


HARD_HANDOFF_RISK_TAGS = {"off_topic", "illegal_request", "prompt_injection", "policy_violation", "out_of_scope"}
HARD_HANDOFF_RISK_TAG_ALIASES = {
    "off_topic": "off_topic",
    "off-topic": "off_topic",
    "offtopic": "off_topic",
    "偏离话题": "off_topic",
    "离题": "off_topic",
    "不相关请求": "off_topic",
    "out_of_scope": "out_of_scope",
    "out-of-scope": "out_of_scope",
    "outofscope": "out_of_scope",
    "超出范围": "out_of_scope",
    "超出业务范围": "out_of_scope",
    "illegal_request": "illegal_request",
    "illegal": "illegal_request",
    "违规请求": "illegal_request",
    "违法请求": "illegal_request",
    "prompt_injection": "prompt_injection",
    "prompt-injection": "prompt_injection",
    "提示词注入": "prompt_injection",
    "越狱": "prompt_injection",
    "policy_violation": "policy_violation",
    "policy-violation": "policy_violation",
    "违反政策": "policy_violation",
    "违反规则": "policy_violation",
}


def guard_synthesized_reply(
    *,
    candidate: dict[str, Any],
    evidence_pack: dict[str, Any],
    settings: dict[str, Any],
) -> dict[str, Any]:
    platform_rules = load_platform_safety_rules(settings).get("item", {})
    normalized = normalize_candidate(candidate)
    if not normalized.get("ok"):
        return {"allowed": False, "action": "fallback", "reason": "candidate_invalid", "errors": normalized.get("errors", [])}

    candidate = normalized["candidate"]
    reply = str(candidate.get("reply") or "").strip()
    safety = evidence_pack.get("safety", {}) or {}
    if isinstance(safety, dict) and safety.get("must_handoff"):
        return handoff_decision("existing_safety_requires_handoff", candidate)

    risk_tags = normalize_risk_tags(candidate.get("risk_tags", []) or [])
    if risk_tags & HARD_HANDOFF_RISK_TAGS:
        enriched = dict(candidate)
        enriched["reply"] = risk_tag_handoff_reply(risk_tags)
        return handoff_decision("risk_tag_requires_handoff", enriched)

    if request_has_hard_boundary_signal(evidence_pack):
        return handoff_decision("customer_request_boundary_requires_handoff", candidate, include_candidate_reply=False)

    authority_tags = set(str(item) for item in evidence_pack.get("intent_tags", []) or []) & guard_term_set(platform_rules, "authority_tags")
    intent_tags = {str(item).strip().lower() for item in (evidence_pack.get("intent_tags", []) or []) if str(item).strip()}
    handoff_requested = bool(candidate.get("needs_handoff")) or candidate.get("recommended_action") in {"handoff", "handoff_for_approval"}
    soft_handoff_downgraded = False
    if handoff_requested:
        authority_handoff_tags = {"quote", "discount", "stock", "contract", "payment", "invoice", "after_sales", "handoff"}
        if not reply:
            return handoff_decision("llm_requested_handoff", candidate, include_candidate_reply=False)
        if authority_tags or intent_tags & authority_handoff_tags:
            return handoff_decision("llm_requested_handoff", candidate)
        if not candidate.get("can_answer", True) and settings.get("allow_soft_cannot_answer_downgrade", True) is False:
            return handoff_decision("llm_cannot_answer", candidate)
        if settings.get("allow_soft_handoff_downgrade", True) is False:
            return handoff_decision("llm_requested_handoff", candidate)
        soft_handoff_downgraded = True

    try:
        confidence = float(candidate.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    min_confidence = float(settings.get("min_confidence", 0.62) or 0.62)
    if confidence < min_confidence:
        return {
            "allowed": False,
            "action": "fallback",
            "reason": "confidence_below_threshold",
            "confidence": confidence,
            "min_confidence": min_confidence,
            "candidate": candidate,
        }

    if not reply:
        return {"allowed": False, "action": "fallback", "reason": "empty_reply", "candidate": candidate}

    has_structured = has_structured_evidence(evidence_pack)
    rag_used = bool(candidate.get("rag_used"))
    structured_used = bool(candidate.get("structured_used"))
    require_structured = settings.get("require_structured_for_authority", True) is not False

    if authority_tags and require_structured and not has_structured:
        return handoff_decision(
            "authority_topic_without_structured_evidence",
            candidate,
            authority_tags=sorted(authority_tags),
        )

    if authority_tags and rag_used and not structured_used and require_structured:
        return handoff_decision(
            "rag_only_cannot_authorize_authority_topic",
            candidate,
            authority_tags=sorted(authority_tags),
        )

    if intent_tags & {"quote", "discount", "contract", "payment"} and has_price_lock_commitment(reply):
        return handoff_decision("price_lock_commitment_requires_handoff", candidate)

    if has_unsafe_commitment(reply, platform_rules) and not has_caution(reply, platform_rules):
        return handoff_decision("unsafe_commitment_without_caution", candidate, include_candidate_reply=False)

    if has_uncertainty_reassurance_conflict(candidate, reply):
        return handoff_decision("uncertainty_conflicts_with_reassuring_reply", candidate, include_candidate_reply=False)

    if has_forbidden_private_payment_or_invoice_reply(reply, platform_rules):
        return handoff_decision("forbidden_payment_invoice_or_finance_boundary", candidate, include_candidate_reply=False)

    if has_direct_appointment_commitment(reply, platform_rules):
        return handoff_decision("appointment_or_reservation_commitment_requires_handoff", candidate, include_candidate_reply=False)

    if has_sales_followup_commitment(reply, platform_rules):
        return handoff_decision("sales_followup_requires_handoff", candidate)

    if settings.get("require_evidence", True) is not False:
        candidate = enrich_candidate_evidence(candidate=candidate, evidence_pack=evidence_pack)
    if settings.get("require_evidence", True) is not False and not candidate_evidence_declared(candidate):
        return {"allowed": False, "action": "fallback", "reason": "candidate_missing_used_evidence", "candidate": candidate}

    return {
        "allowed": True,
        "action": "send_reply",
        "reason": "llm_soft_handoff_downgraded" if soft_handoff_downgraded else "guard_passed",
        "reply": reply,
        "candidate": candidate,
        "authority_tags": sorted(authority_tags),
    }


def handoff_decision(
    reason: str,
    candidate: dict[str, Any],
    *,
    authority_tags: list[str] | None = None,
    include_candidate_reply: bool = True,
) -> dict[str, Any]:
    platform_rules = load_platform_safety_rules().get("item", {})
    payload: dict[str, Any] = {
        "allowed": True,
        "action": "handoff",
        "reason": reason,
        "candidate": candidate,
    }
    if authority_tags:
        payload["authority_tags"] = authority_tags
    reply = str(candidate.get("reply") or "").strip()
    if include_candidate_reply:
        payload["reply"] = reply if handoff_reply_safe(reply, platform_rules) else default_handoff_reply(platform_rules)
    return payload


def handoff_reply_safe(reply: str, platform_rules: dict[str, Any] | None = None) -> bool:
    platform_rules = platform_rules or load_platform_safety_rules().get("item", {})
    clean = str(reply or "").strip()
    if not clean:
        return False
    if len(clean) > 700:
        return False
    if has_formulaic_handoff(clean, platform_rules):
        return False
    if has_unqualified_commitment(clean, platform_rules):
        return False
    return has_caution(clean, platform_rules)


def default_handoff_reply(platform_rules: dict[str, Any] | None = None) -> str:
    platform_rules = platform_rules or load_platform_safety_rules().get("item", {})
    caution_terms = list(guard_term_set(platform_rules, "caution_terms"))
    caution = caution_terms[0] if caution_terms else "人工核实"
    return f"这个问题我不能直接给结论，我先转给人工同事{caution}后再回复您。"


def risk_tag_handoff_reply(risk_tags: set[str]) -> str:
    del risk_tags
    return "这个问题超出自动回复边界，我不能直接给结论；我先转给人工同事核实后再回复您。"


def normalize_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(candidate, dict):
        return {"ok": False, "errors": ["candidate_not_object"]}
    reply = str(candidate.get("reply") or "").strip()
    action = str(candidate.get("recommended_action") or "send_reply").strip() or "send_reply"
    if action not in {"send_reply", "handoff", "handoff_for_approval", "fallback_existing"}:
        errors.append("invalid_recommended_action")
    if action == "send_reply" and not reply:
        errors.append("missing_reply")
    try:
        confidence = float(candidate.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
        errors.append("invalid_confidence")
    confidence = max(0.0, min(1.0, confidence))
    used_evidence = [str(item) for item in candidate.get("used_evidence", []) or [] if str(item)]
    normalized = {
        "can_answer": candidate.get("can_answer", True) is not False,
        "reply": reply,
        "confidence": confidence,
        "recommended_action": action,
        "needs_handoff": bool(candidate.get("needs_handoff", False)),
        "used_evidence": used_evidence,
        "rag_used": bool(candidate.get("rag_used", any(item.startswith("rag:") for item in used_evidence))),
        "structured_used": bool(
            candidate.get(
                "structured_used",
                any(item.startswith(("product:", "faq:", "policy:", "product_scoped:")) for item in used_evidence),
            )
        ),
        "uncertain_points": [str(item) for item in candidate.get("uncertain_points", []) or [] if str(item)],
        "risk_tags": [str(item) for item in candidate.get("risk_tags", []) or [] if str(item)],
        "reason": str(candidate.get("reason") or ""),
    }
    return {"ok": not errors, "candidate": normalized, "errors": errors}


def has_structured_evidence(evidence_pack: dict[str, Any]) -> bool:
    knowledge = evidence_pack.get("knowledge", {}) or {}
    evidence = knowledge.get("evidence", {}) or {}
    return bool(
        evidence.get("products")
        or evidence.get("faq")
        or evidence.get("policies")
        or evidence.get("product_scoped")
        or evidence.get("catalog_candidates")
    )


def candidate_evidence_declared(candidate: dict[str, Any]) -> bool:
    if candidate.get("used_evidence"):
        return True
    return bool(candidate.get("rag_used") or candidate.get("structured_used"))


def enrich_candidate_evidence(*, candidate: dict[str, Any], evidence_pack: dict[str, Any]) -> dict[str, Any]:
    if candidate_evidence_declared(candidate):
        return candidate
    audit_summary = evidence_pack.get("audit_summary") if isinstance(evidence_pack.get("audit_summary"), dict) else {}
    used_evidence = [str(item) for item in (audit_summary.get("evidence_ids") or []) if str(item)]
    if not used_evidence:
        used_evidence = [
            str(item.get("id") or "")
            for item in (evidence_pack.get("selected_items") or [])
            if isinstance(item, dict) and str(item.get("id") or "")
        ]
    rag_used = int(audit_summary.get("rag_hit_count") or 0) > 0
    structured_used = int(audit_summary.get("structured_evidence_count") or 0) > 0
    if not used_evidence and not rag_used and not structured_used:
        return candidate
    enriched = dict(candidate)
    if used_evidence and not enriched.get("used_evidence"):
        enriched["used_evidence"] = used_evidence[:12]
    if rag_used and not bool(enriched.get("rag_used")):
        enriched["rag_used"] = True
    if structured_used and not bool(enriched.get("structured_used")):
        enriched["structured_used"] = True
    return enriched


def has_unsafe_commitment(reply: str, platform_rules: dict[str, Any] | None = None) -> bool:
    platform_rules = platform_rules or load_platform_safety_rules().get("item", {})
    normalized = re.sub(r"\s+", "", reply)
    return any(term in normalized for term in guard_term_set(platform_rules, "commitment_terms"))


def has_unqualified_commitment(reply: str, platform_rules: dict[str, Any] | None = None) -> bool:
    platform_rules = platform_rules or load_platform_safety_rules().get("item", {})
    normalized = re.sub(r"\s+", "", str(reply or ""))
    if not normalized:
        return False
    commitment_terms = [term for term in guard_term_set(platform_rules, "commitment_terms") if term]
    caution_terms = [term for term in guard_term_set(platform_rules, "caution_terms") if term]
    local_negation_markers = [
        "不能", "无法", "没法", "不敢", "不保证", "不能保证", "需核实", "要核实", "人工确认", "转人工",
    ]
    markers = [*caution_terms, *local_negation_markers]
    for term in commitment_terms:
        start = normalized.find(term)
        while start >= 0:
            window = normalized[max(0, start - 14) : start + len(term) + 22]
            if not any(marker and marker in window for marker in markers):
                return True
            start = normalized.find(term, start + len(term))
    return False


def has_price_lock_commitment(reply: str) -> bool:
    clean = re.sub(r"\s+", "", str(reply or ""))
    if not clean:
        return False
    patterns = (
        r"就是这个价",
        r"价格.*不会变",
        r"最低价.*保证",
        r"今天就能锁定",
        r"马上锁定",
        r"直接锁定",
        r"保价",
    )
    return any(re.search(pattern, clean) for pattern in patterns)


def has_forbidden_private_payment_or_invoice_reply(reply: str, platform_rules: dict[str, Any] | None = None) -> bool:
    platform_rules = platform_rules or load_platform_safety_rules().get("item", {})
    clean = re.sub(r"\s+", "", str(reply or ""))
    risky_terms = guard_term_set(platform_rules, "forbidden_reply_terms")
    safe_markers = guard_term_set(platform_rules, "forbidden_safe_markers")
    for term in risky_terms:
        start = clean.find(term)
        while start >= 0:
            window = clean[max(0, start - 12) : start + len(term) + 18]
            if not any(marker in window for marker in safe_markers):
                return True
            start = clean.find(term, start + len(term))
    return False


def has_caution(reply: str, platform_rules: dict[str, Any] | None = None) -> bool:
    platform_rules = platform_rules or load_platform_safety_rules().get("item", {})
    return any(term in reply for term in guard_term_set(platform_rules, "caution_terms"))


def has_formulaic_handoff(reply: str, platform_rules: dict[str, Any] | None = None) -> bool:
    platform_rules = platform_rules or load_platform_safety_rules().get("item", {})
    return any(term in reply for term in guard_term_set(platform_rules, "formulaic_handoff_terms"))


def has_uncertainty_reassurance_conflict(candidate: dict[str, Any], reply: str) -> bool:
    uncertain_points = [str(item) for item in candidate.get("uncertain_points", []) or [] if str(item)]
    if not uncertain_points:
        return False
    uncertainty_markers = ("人工确认", "需确认", "需要确认", "无法", "未知", "不确定", "核实")
    if not any(any(marker in point for marker in uncertainty_markers) for point in uncertain_points):
        return False
    reassurance_markers = ("不用担心", "放心", "没问题", "完全没问题", "肯定", "一定", "包过", "包赔")
    return any(marker in str(reply or "") for marker in reassurance_markers)


def has_direct_appointment_commitment(reply: str, platform_rules: dict[str, Any] | None = None) -> bool:
    platform_rules = platform_rules or load_platform_safety_rules().get("item", {})
    clean = re.sub(r"\s+", "", str(reply or ""))
    risky_terms = guard_term_set(platform_rules, "appointment_commitment_terms")
    local_caution = guard_term_set(platform_rules, "appointment_caution_terms")
    for term in risky_terms:
        start = clean.find(term)
        while start >= 0:
            window = clean[max(0, start - 18) : start + len(term) + 18]
            if not any(marker in window for marker in local_caution):
                return True
            start = clean.find(term, start + len(term))
    return False


def has_sales_followup_commitment(reply: str, platform_rules: dict[str, Any] | None = None) -> bool:
    platform_rules = platform_rules or load_platform_safety_rules().get("item", {})
    clean = re.sub(r"\s+", "", str(reply or ""))
    actors = guard_term_set(platform_rules, "sales_followup_actors")
    actions = guard_term_set(platform_rules, "sales_followup_actions")
    for actor in actors:
        start = clean.find(actor)
        while start >= 0:
            window = clean[start : start + 36]
            if any(action in window for action in actions):
                return True
            start = clean.find(actor, start + len(actor))
    return False


def normalize_risk_tags(raw_tags: list[Any]) -> set[str]:
    normalized: set[str] = set()
    for raw in raw_tags:
        text = str(raw or "").strip().lower()
        if not text:
            continue
        compact = re.sub(r"[\s_\-]+", "", text)
        direct = HARD_HANDOFF_RISK_TAG_ALIASES.get(text) or HARD_HANDOFF_RISK_TAG_ALIASES.get(compact)
        if direct:
            normalized.add(direct)
            continue
        if text in HARD_HANDOFF_RISK_TAGS:
            normalized.add(text)
            continue
        for alias, canonical in HARD_HANDOFF_RISK_TAG_ALIASES.items():
            if alias and (alias in text or alias in compact):
                normalized.add(canonical)
                break
    return normalized


def request_has_hard_boundary_signal(evidence_pack: dict[str, Any]) -> bool:
    text = re.sub(r"\s+", "", str(evidence_pack.get("current_message") or ""))
    if not text:
        return False
    intent_tags = {str(item).strip().lower() for item in (evidence_pack.get("intent_tags") or []) if str(item).strip()}
    if not (intent_tags & {"quote", "discount", "payment", "after_sales", "handoff"}):
        return False
    patterns = (
        r"最低价.{0,12}(保证|锁定|就是这个价|今天定)",
        r"(保证|包过).{0,10}(贷款|审批|通过|征信)",
        r"绝对.{0,8}(无事故|无水泡|无火烧)",
        r"(月结|账期|先发货|合同|赔偿|少开发票|虚开发票)",
    )
    return any(re.search(pattern, text, re.I) for pattern in patterns)
