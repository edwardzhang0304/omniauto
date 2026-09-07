"""Incident d85a414e: approved, redacted candidate text + artificial test context.

The two second-attempt candidate texts and cited guidance below came from the
approved incident inspection. IDs, history and customer input are test fixtures;
this is not a replay of the entire production conversation or Windows sending.
"""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
RUNTIME = ROOT
for path in (RUNTIME, RUNTIME / "apps/wechat_ai_customer_service", RUNTIME / "apps/wechat_ai_customer_service/workflows", RUNTIME / "apps/wechat_ai_customer_service/adapters"):
    sys.path.insert(0, str(path))

from customer_service_brain_contract import normalize_brain_plan, validate_brain_plan
from apps.wechat_ai_customer_service.workflows.customer_service_brain import brain_plan_allows_soft_evidence_override, validate_plan_against_evidence

CANDIDATES = [
    ["好嘞，欢迎您～", "您之前咨询过二手车，想看哪类车、有什么需求都可以直接发我，我帮您筛选合适车源。"],
    ["好嘞，欢迎您～", "您之前问过二手车，想先看哪类车或大概什么预算，都可以告诉我，我帮您找合适的车源。"],
]
GUIDANCE = [
    ("购车需求收集", "低风险购车咨询可收集预算范围、主要用途、车型或车身类型偏好、所在城市、贷款或全款、是否置换。每轮只询问一到两个最关键问题，不要一次连续追问全部信息；没有车辆证据时不得推荐具体车型。"),
    ("闲聊自然转入购车需求", "客户闲聊时先自然回应，再结合上下文询问一个购车相关问题；没有车辆证据时不得借机推荐具体车型。"),
]


def make_plan(*, reply=None, mode="soft_redirect_to_business", evidence=None):
    return normalize_brain_plan({
        "can_answer": True,
        "answer_mode": mode,
        "evidence_used": evidence if evidence is not None else {"formal_knowledge_ids": ["test-guidance-1", "test-guidance-2"]},
        "facts_claimed": [],
        "reply_segments": reply or CANDIDATES[0],
        "risk": {"risk_level": "low", "risk_tags": [], "needs_handoff": False},
        "recommended_action": "send_reply",
        "confidence": .9,
    })


@pytest.mark.parametrize("reply", CANDIDATES)
@pytest.mark.parametrize("mode", ["soft_social_reply", "soft_redirect_to_business", "ask_clarifying_question", "collect_customer_info", "direct_answer"])
def test_guidance_references_do_not_invent_factual_claims(reply, mode):
    plan = make_plan(reply=reply, mode=mode)
    original = deepcopy(plan)
    assert validate_brain_plan(plan, require_fact_claims=True)["ok"]
    assert brain_plan_allows_soft_evidence_override(plan)
    assert plan == original  # keep both knowledge references and the exact reply


@pytest.mark.parametrize("evidence", [{}, {"formal_knowledge_ids": ["test-guidance-1"]}])
@pytest.mark.parametrize("reply,mode", [
    (["这台售价8.68万。"], "soft_social_reply"),
    (["目前有现车库存。"], "ask_clarifying_question"),
    (["贷款审批一定通过。"], "direct_answer"),
    (["合同保证包退。"], "collect_customer_info"),
    (["累计行驶3万公里。"], "compare_options"),
    (["建议选择这款车。"], "recommend_from_catalog"),
    (["这是已经核实的车辆资料。"], "quote_product_fact"),
])
def test_labels_and_guidance_do_not_bypass_missing_fact_checks(evidence, reply, mode):
    plan = make_plan(reply=reply, mode=mode, evidence=evidence)
    assert "missing_fact_claims" in validate_brain_plan(plan, require_fact_claims=True)["errors"]
    assert not brain_plan_allows_soft_evidence_override(plan)


@pytest.mark.parametrize("mode", ["recommend_from_catalog", "quote_product_fact"])
def test_common_sense_label_cannot_exempt_factual_mode(mode):
    plan = make_plan(mode=mode, evidence={"common_sense_topics": ["测试常识"]})
    assert "missing_fact_claims" in validate_brain_plan(plan, require_fact_claims=True)["errors"]
    assert not brain_plan_allows_soft_evidence_override(plan)


def test_existing_common_sense_finance_question_remains_nonfactual():
    plan = make_plan(mode="collect_customer_info", reply=["您考虑贷款还是全款？"], evidence={"common_sense_topics": ["购车需求收集"]})
    assert validate_brain_plan(plan, require_fact_claims=True)["ok"]


@pytest.mark.parametrize("risk", [
    {"risk_level": "high", "risk_tags": ["policy_violation"], "needs_handoff": False},
    {"risk_level": "low", "risk_tags": [], "needs_handoff": True},
])
def test_guidance_does_not_override_hard_risk(risk):
    plan = make_plan()
    plan["risk"] = risk
    assert not brain_plan_allows_soft_evidence_override(plan)


@pytest.mark.parametrize("citation", ["test-guidance-1", "policy:test-guidance-1", "formal_knowledge:test-guidance-1"])
def test_fact_free_guidance_citation_must_exist_in_current_evidence(citation):
    plan = make_plan(evidence={"formal_knowledge_ids": [citation]})
    assert not validate_plan_against_evidence(plan, {})["ok"]
    assert validate_plan_against_evidence(plan, {"evidence_ids": ["policy:test-guidance-1"]})["ok"]
    assert not validate_plan_against_evidence(plan, {"evidence_ids": ["policy:other-turn-guidance"]})["ok"]




# Artificial review counterexamples, not text taken from the production batch.
PAYMENT_QUESTIONS = [
    "您考虑贷款还是全款？",
    "您是考虑全款还是分期？",
    "你打算分期还是全款呢？",
    "请问您更倾向全款还是贷款？",
    "您好，您准备全款还是贷款买车？",
    "您这边是打算全款购车还是分期购车？",
    "您考虑贷款还是全款",  # Grammar, not a question mark, establishes an inquiry.
]
PAYMENT_CLAIMS = [
    "贷款审批一定通过，您考虑贷款还是全款？",
    "您考虑贷款还是全款？审批包过。",
    "您考虑贷款还是全款，利率3%？",
    "您考虑贷款还是全款？这台售价8.68万。",
    "贷款包过，您要分期吗？",
    "您考虑贷款还是全款都能批？",
    "您考虑贷款还是全款？分期不需要审核。",
    "这台贷款月供2000元，您考虑贷款还是全款？",
    "您考虑贷款还是全款？现车库存充足。",
    "您考虑贷款还是全款？合同保证包退。",
    "您考虑零利率分期还是全款？",
    "您考虑贷款还是全款？我们保证没有利息。",
]


@pytest.mark.parametrize("question", PAYMENT_QUESTIONS)
@pytest.mark.parametrize("mode", ["collect_customer_info", "ask_clarifying_question", "direct_answer"])
def test_formal_guidance_payment_preference_is_not_a_fact(question, mode):
    plan = make_plan(reply=[question], mode=mode)
    original = deepcopy(plan)
    assert validate_brain_plan(plan, require_fact_claims=True)["ok"]
    assert brain_plan_allows_soft_evidence_override(plan)
    assert plan == original


@pytest.mark.parametrize("reply", PAYMENT_CLAIMS)
def test_payment_question_cannot_hide_an_authoritative_claim(reply):
    plan = make_plan(reply=[reply], mode="collect_customer_info")
    assert "missing_fact_claims" in validate_brain_plan(plan, require_fact_claims=True)["errors"]
    assert not brain_plan_allows_soft_evidence_override(plan)






# Artificial combinations of existing reply segments; do not concatenate them
# before exercising the production protocol or substitute the schema result.
SEGMENTED_QUESTIONS = [
    ["好嘞，欢迎您～", "您考虑贷款还是全款？"],
    ["收到，我们先了解下您的需求。", "您是考虑全款还是分期？"],
    ["您考虑贷款还是全款？", "您的预算大概多少？"],
    ["好嘞，欢迎您～", "您的预算大概多少？", "您考虑贷款还是全款？"],
    ["您考虑贷款还是全款？", "收到，我们先了解下您的需求。"],
]
SEGMENTED_CLAIMS = [
    ["贷款审批一定通过。", "您考虑贷款还是全款？"],
    ["您考虑贷款还是全款？", "贷款审批一定通过。"],
    ["好嘞，欢迎您～", "您考虑贷款还是全款？", "这台售价8.68万。"],
    ["这台售价8.68万。", "好嘞，欢迎您～", "您考虑贷款还是全款？"],
    ["您考虑贷款还是全款？", "审批包过。"],
    ["利率3%。", "您考虑贷款还是全款？"],
    ["您考虑贷款还是全款？", "月供2000元。"],
    ["您考虑贷款还是全款？", "肯定能批。"],
    ["您考虑贷款还是全款？", "保证通过。"],
    ["您考虑贷款还是全款？", "无息。"],
    ["您考虑贷款还是全款？审批包过。", "好嘞，欢迎您～"],
    ["好嘞，欢迎您～", "贷款包过，您考虑贷款还是全款？"],
]


@pytest.mark.parametrize("segments", SEGMENTED_QUESTIONS)
def test_segmented_payment_questions_preserve_every_segment(segments):
    plan = make_plan(reply=segments, mode="collect_customer_info")
    original = deepcopy(plan)
    assert plan["reply_segments"] == segments
    assert validate_brain_plan(plan, require_fact_claims=True)["ok"]
    assert brain_plan_allows_soft_evidence_override(plan)
    assert plan == original


@pytest.mark.parametrize("segments", SEGMENTED_CLAIMS)
def test_segmented_payment_question_never_hides_other_claims(segments):
    plan = make_plan(reply=segments, mode="collect_customer_info")
    original = deepcopy(plan)
    assert "missing_fact_claims" in validate_brain_plan(plan, require_fact_claims=True)["errors"]
    assert not brain_plan_allows_soft_evidence_override(plan)
    assert plan == original
