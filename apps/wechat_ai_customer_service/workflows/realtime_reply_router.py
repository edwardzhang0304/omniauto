"""Fast foreground routing for WeChat customer-service replies.

The real-time path should only call an LLM when the current customer-visible
reply genuinely needs semantic composition. Deterministic facts, handoff
boundaries, greetings, and high-frequency recommendation patterns stay local.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from knowledge_runtime import KnowledgeRuntime


DEFAULT_MAX_PROMPT_TOKENS = 3000
DEFAULT_MAX_COMPLETION_TOKENS = 500

GREETING_TERMS = ("你好", "您好", "在吗", "在么", "有人吗", "哈喽", "嗨")
DATA_TERMS = ("电话", "手机号", "联系方式", "我叫", "姓名", "地址")
RECOMMEND_TERMS = (
    "预算",
    "推荐",
    "车源",
    "代步",
    "通勤",
    "家用",
    "省油",
    "自动挡",
    "上下班",
    "接娃",
    "买菜",
    "练手",
    "新手",
    "刚拿驾照",
    "跑高速",
    "后排",
    "空间",
    "舒服",
    "年限",
    "爸妈",
    "父母",
    "看车",
    "到店",
    "周末",
    "周六",
    "周日",
    "上午",
    "下午",
    "过去",
    "预约",
    "车还在",
    "安排",
    "suv",
    "皮实",
    "耐造",
    "工地",
)
APPOINTMENT_TERMS = ("看车", "能看", "去看", "到店", "试驾", "周末", "周六", "周日", "上午", "下午", "几点", "安排", "过去", "来店", "留车")
SAME_DAY_DELIVERY_TERMS = ("办手续", "直接办", "当天办", "提车", "直接提", "当天提", "临牌", "过户", "交车")
STORE_ARRIVAL_HANDOFF_TERMS = ("店地址", "门店地址", "地址", "位置", "导航", "在哪", "哪里", "找谁", "联系人")
FOLLOWUP_TERMS = ("刚才", "你刚才", "那台", "这个", "这台", "上一台", "前面", "前面说的", "按这个", "就按这个")
FOLLOWUP_SOURCE_TERMS = ("具体", "哪台", "哪款", "两台", "几台", "车源", "发我", "看看", "推荐", "直接", "合适", "方向", "挑", "筛", "别再问预算", "不用再问预算")
EXPLICIT_SOURCE_TERMS = ("哪台", "哪款", "两台", "几台", "车源", "发我", "挑两", "挑几", "挑两台", "挑几台", "直接挑", "给我挑", "给我两台", "给我几台", "推荐两", "推荐几", "两三个方向", "几个方向")
RECENT_GUIDANCE_TERMS = ("预算", "用途", "车况", "缩到", "筛", "两三台", "省心")
VALUE_RETENTION_TERMS = ("保值", "再卖", "卖掉", "亏得少", "残值", "二手行情")
VEHICLE_COMPARE_TERMS = ("哪个更适合", "哪台更适合", "哪个更好", "哪台更好", "哪个更贴近", "哪台更贴近", "更贴近", "怎么选", "更适合", "更偏哪台", "更偏哪个", "更偏哪款", "好开", "好停", "少操心")
TRADE_IN_TERMS = (
    "置换",
    "抵车款",
    "抵多少",
    "抵扣",
    "抵一点",
    "卖车",
    "收车",
    "旧车",
    "估价",
    "估个",
    "估一下",
    "估一",
    "现场估",
    "现场评估",
    "开过去",
    "老车",
    "剐蹭",
    "怎么估",
    "大概区间",
    "准备哪些东西",
    "准备什么东西",
    "准备什么材料",
)
NEW_ENERGY_CHECK_TERMS = ("电池", "三电", "插混", "混动", "新能源", "dmi", "dm-i", "DM-i", "DMI")
INSPECTION_GUIDANCE_TERMS = ("检测报告", "维保记录", "车况", "公里数", "事故", "事故车", "水泡", "火烧", "第三方检测", "出险", "补漆", "换件", "披露", "说清楚", "把关")
FEATURE_GUIDANCE_TERMS = ("安全配置", "倒车影像", "倒车雷达", "雷达", "360", "高速", "气囊", "ESP", "辅助驾驶")
FINANCE_GUIDANCE_TERMS = ("贷款", "分期", "按揭", "首付", "月供", "金融", "征信", "利率", "审批")
FEE_GUIDANCE_TERMS = ("过户", "保险", "上牌", "费用", "收费", "杂费", "加费用", "费用明细", "提前说清楚")
TESTDRIVE_MATERIAL_TERMS = ("试驾", "试车", "身份证", "驾驶证", "材料", "带什么", "需要带", "准备什么")
PRICE_NEGOTIATION_TERMS = ("价格", "优惠", "贵", "谈一点", "少一点", "便宜点", "还能谈", "再谈", "让点")
WARRANTY_GUIDANCE_TERMS = ("质保", "保修", "售后", "买完", "核心部件", "出问题", "维修")
COMFORT_HIGHWAY_TERMS = ("后排", "孩子", "老人", "父母", "高速", "回老家", "颠", "舒适", "舒服", "隔音", "胎噪", "底盘")
CARGO_SPACE_GUIDANCE_TERMS = (
    "第二排",
    "二排",
    "座椅放倒",
    "放倒",
    "后备厢",
    "后备箱",
    "装东西",
    "拉东西",
    "装得下",
    "放得下",
    "灯架",
    "背景架",
    "展架",
    "音响架",
    "物料",
    "折叠桌",
    "箱子",
    "尺寸",
    "容积",
)
VEHICLE_TYPE_GUIDANCE_TERMS = ("轿车", "suv", "mpv", "七座", "车型", "方向", "太大", "停车", "油耗")
MAINTENANCE_COST_TERMS = ("保养成本", "后期成本", "养车成本", "用车成本", "维修成本", "维护成本", "维护", "后期保养", "后期维修", "小毛病", "少操心", "豪华品牌", "mpv", "油车", "油耗")
NO_DEPOSIT_VISIT_TERMS = (
    "不交定金",
    "先不交定金",
    "不想先交定金",
    "不想交定金",
    "不用定金",
    "不付定金",
    "不交订金",
    "先不交订金",
    "不用订金",
    "合适再谈定金",
    "满意再谈定金",
    "满意了再决定",
    "满意再决定",
    "看完满意再决定",
    "先看车再谈定金",
    "先看车和报告",
    "先看车试驾",
    "不想一上来就被催",
    "不想一上来就付",
    "不想一上来就交",
    "不被催付钱",
)
STRICT_BUDGET_CAP_TERMS = (
    "别超过",
    "别超",
    "不超过",
    "不超",
    "不能超过",
    "不要超过",
    "不高于",
    "别高于",
    "以内",
    "万内",
    "预算内",
    "以下",
    "控制在",
    "最多",
    "上限",
    "封顶",
)
IDENTITY_PROBE_TERMS = (
    "是不是ai",
    "是不是AI",
    "ai吗",
    "AI吗",
    "ai自动",
    "AI自动",
    "真人吗",
    "是真人",
    "机器人",
    "自动回复",
    "机器客服",
    "智能客服",
)
DETAILED_NEED_SOURCE_TERMS = (
    "帮我看个车",
    "看个车",
    "想买",
    "换台",
    "换车",
    "推荐",
    "挑",
    "筛",
    "车源",
    "什么车",
    "哪台",
    "哪款",
)
DETAILED_NEED_USE_TERMS = (
    "通勤",
    "代步",
    "家用",
    "接娃",
    "买菜",
    "周末",
    "全家",
    "孙子",
    "退休",
    "老婆开",
    "媳妇开",
    "女士开",
    "女司机",
    "新手",
    "练手",
    "停车",
    "跑高速",
    "后排",
    "空间",
    "摄影",
    "工作室",
    "活动策划",
    "外拍",
    "接客户",
    "甲方客户",
    "客户接待",
    "商务接待",
    "公司用",
    "拉器材",
    "拉东西",
    "物料",
    "展架",
    "爸妈",
    "父母",
    "孩子",
)
DETAILED_NEED_PREFERENCE_TERMS = (
    "自动挡",
    "手动挡",
    "倒车",
    "影像",
    "雷达",
    "360",
    "小一点",
    "小巧",
    "省油",
    "别太费油",
    "省心",
    "别太费心",
    "舒服",
    "舒适",
    "空间大",
    "后备厢",
    "后备箱",
    "器材",
    "灯架",
    "展架",
    "物料",
    "音响架",
    "折叠桌",
    "相机箱",
    "背景架",
    "能拉",
    "装东西",
    "拉东西",
    "suv",
    "皮实",
    "耐造",
)
USED_CAR_EXPLICIT_QUERY_TERMS = (
    "车",
    "车型",
    "车源",
    "二手车",
    "自动挡",
    "手动挡",
    "看车",
    "到店",
    "试驾",
    "上牌",
    "公里",
    "后备厢",
    "后备箱",
    "空间",
    "器材",
    "灯架",
    "相机箱",
    "置换",
    "收车",
)
USED_CAR_SCENE_QUERY_TERMS = (
    "通勤",
    "代步",
    "家用",
    "接娃",
    "省油",
    "油耗",
    "老婆开",
    "女士开",
    "哪台",
    "挑两",
    "挑几",
    "摄影",
    "工作室",
    "活动策划",
    "外拍",
    "接客户",
    "甲方客户",
    "客户接待",
    "商务接待",
    "公司用",
    "后备厢",
    "后备箱",
    "器材",
    "拉东西",
    "物料",
    "展架",
    "装东西",
    "suv",
    "皮实",
    "耐造",
    "工地",
)
USED_CAR_PRODUCT_TERMS = (
    "二手车",
    "轿车",
    "suv",
    "mpv",
    "新能源",
    "上牌",
    "表显",
    "公里",
    "自动挡",
    "手动挡",
    "现车",
    "车况",
    "检测报告",
    "检测",
    "内饰",
    "外观",
    "补漆",
    "一手车",
    "凯美瑞",
    "思域",
    "秦plus",
    "马自达",
    "高尔夫",
    "奇骏",
    "途观",
    "宝马",
    "别克",
    "gl8",
    "大众",
    "丰田",
    "本田",
    "比亚迪",
)
CONCRETE_USED_CAR_MODEL_TERMS = (
    "凯美瑞",
    "思域",
    "秦plus",
    "马自达",
    "高尔夫",
    "奇骏",
    "途观",
    "宝马",
    "别克",
    "gl8",
    "大众",
    "丰田",
    "本田",
    "比亚迪",
)
HIGH_RISK_TERMS = (
    "最低价",
    "底价",
    "绝对",
    "保证",
    "包过",
    "赔",
    "赔偿",
    "事故",
    "水泡",
    "火烧",
    "定金",
    "订金",
    "锁车",
    "少开",
    "合同",
    "发票",
    "电池",
    "三电",
    "迁入政策",
)
STRICT_HIGH_RISK_TERMS = (
    "最低价",
    "底价",
    "绝对",
    "保证",
    "包过",
    "赔",
    "赔偿",
    "定金",
    "订金",
    "锁车",
    "少开",
    "合同",
    "发票",
    "迁入政策",
)
CONDITION_SENSITIVE_RISK_TERMS = ("事故", "水泡", "火烧", "电池", "三电")
GUARANTEE_CONTEXT_TERMS = ("保证", "绝对", "肯定", "包", "赔", "赔偿", "负责", "出问题", "没问题", "有没有问题")
OFF_TOPIC_OR_SECURITY_TERMS = (
    "外挂",
    "破解",
    "脚本",
    "系统提示词",
    "内部规则",
    "api密钥",
    "api key",
    "密钥",
    "prompt",
)


def decide_realtime_reply_route(
    *,
    config: dict[str, Any],
    combined: str,
    decision: Any,
    intent_result: Any,
    intent_assist: dict[str, Any],
    rag_reply: dict[str, Any],
    llm_reply: dict[str, Any],
    product_knowledge: dict[str, Any] | None,
    data_capture: dict[str, Any],
    evidence_pack: dict[str, Any],
    recent_reply_texts: list[str] | None = None,
) -> dict[str, Any]:
    settings = config.get("realtime_reply", {}) or {}
    enabled = settings.get("enabled", True) is not False
    route: dict[str, Any] = {
        "enabled": enabled,
        "level": "legacy",
        "reason": "realtime_reply_disabled",
        "foreground_llm_allowed": bool((config.get("llm_reply_synthesis", {}) or {}).get("enabled", False)),
        "max_prompt_tokens": int(settings.get("max_prompt_tokens", DEFAULT_MAX_PROMPT_TOKENS) or DEFAULT_MAX_PROMPT_TOKENS),
        "max_completion_tokens": int(settings.get("max_completion_tokens", DEFAULT_MAX_COMPLETION_TOKENS) or DEFAULT_MAX_COMPLETION_TOKENS),
        "background_jobs": [],
    }
    if not enabled:
        return route

    current_combined = current_customer_text(combined)
    contextual_combined = realtime_contextual_customer_text(
        combined,
        recent_reply_texts=recent_reply_texts or [],
    )
    text = normalize_text(current_combined)
    source_text = normalize_text(contextual_combined)
    if is_identity_probe(text) and not contains_any(text, HIGH_RISK_TERMS):
        return {
            **route,
            "level": "L1",
            "reason": "identity_probe_can_use_local_style",
            "foreground_llm_allowed": False,
            "background_jobs": ["reply_quality_review"],
        }
    intent = str(getattr(intent_result, "intent", "") or intent_assist.get("intent") or "")
    safety = ((intent_assist.get("evidence", {}) or {}).get("safety", {}) or {})
    safety_reasons = {str(item) for item in safety.get("reasons", []) or [] if str(item)}
    soft_missing_evidence = bool(safety.get("must_handoff")) and bool(safety_reasons) and safety_reasons <= {"no_relevant_business_evidence", "auto_reply_disabled"}
    decision_requires_handoff = bool(getattr(decision, "need_handoff", False)) and str(getattr(decision, "reason", "") or "") != "no_rule_matched"
    must_handoff = (bool(safety.get("must_handoff")) and not soft_missing_evidence) or decision_requires_handoff
    product_block = bool(product_knowledge and (product_knowledge.get("needs_handoff") or product_knowledge.get("auto_reply_allowed") is False))

    if requires_high_risk_boundary(text) or contains_any(text, OFF_TOPIC_OR_SECURITY_TERMS):
        return {
            **route,
            "level": "L0",
            "reason": "deterministic_handoff_or_high_risk_boundary",
            "foreground_llm_allowed": False,
            "background_jobs": ["reply_quality_review"],
        }
    if product_block:
        return {
            **route,
            "level": "L0",
            "reason": "deterministic_handoff_or_high_risk_boundary",
            "foreground_llm_allowed": False,
            "background_jobs": ["reply_quality_review"],
        }
    if intent == "customer_data_provide" or is_actual_customer_data_message(text):
        return {
            **route,
            "level": "L0",
            "reason": "customer_data_or_contact_message",
            "foreground_llm_allowed": False,
            "background_jobs": ["customer_profile_update"],
        }
    current_priority_guidance = current_turn_preempts_vehicle_candidate_reply(text, recent_reply_texts or [])
    if not current_priority_guidance and (
        is_followup_vehicle_source_request(text, recent_reply_texts or [])
        or is_followup_vehicle_source_request(source_text, recent_reply_texts or [])
    ):
        return {
            **route,
            "level": "L1",
            "reason": "followup_ready_for_vehicle_candidates",
            "foreground_llm_allowed": False,
            "background_jobs": ["reply_quality_review"],
        }
    if not current_priority_guidance and (is_explicit_vehicle_source_request(text) or is_explicit_vehicle_source_request(source_text)):
        return {
            **route,
            "level": "L1",
            "reason": "explicit_vehicle_candidates_requested",
            "foreground_llm_allowed": False,
            "background_jobs": ["reply_quality_review"],
        }
    if not current_priority_guidance and (is_detailed_vehicle_need_ready(text) or is_detailed_vehicle_need_ready(source_text)):
        return {
            **route,
            "level": "L1",
            "reason": "detailed_vehicle_need_ready_for_candidates",
            "foreground_llm_allowed": False,
            "background_jobs": ["reply_quality_review"],
        }
    if is_vehicle_compare_question(text, recent_reply_texts or []):
        return {
            **route,
            "level": "L1",
            "reason": "common_vehicle_compare_can_use_local_style",
            "foreground_llm_allowed": False,
            "background_jobs": ["reply_quality_review"],
        }
    if is_vehicle_type_guidance_question(text):
        return {
            **route,
            "level": "L1",
            "reason": "common_vehicle_type_guidance_can_use_local_style",
            "foreground_llm_allowed": False,
            "background_jobs": ["reply_quality_review"],
        }
    if is_maintenance_cost_question(text):
        return {
            **route,
            "level": "L1",
            "reason": "common_maintenance_cost_can_use_local_style",
            "foreground_llm_allowed": False,
            "background_jobs": ["reply_quality_review"],
        }
    if is_fee_transparency_question(text):
        return {
            **route,
            "level": "L1",
            "reason": "common_fee_guidance_can_use_local_style",
            "foreground_llm_allowed": False,
            "background_jobs": ["reply_quality_review"],
        }
    if is_finance_guidance_question(text):
        return {
            **route,
            "level": "L1",
            "reason": "common_finance_guidance_can_use_local_style",
            "foreground_llm_allowed": False,
            "background_jobs": ["reply_quality_review"],
        }
    if is_specific_testdrive_appointment_question(text):
        return {
            **route,
            "level": "L0",
            "reason": "deterministic_handoff_or_high_risk_boundary",
            "foreground_llm_allowed": False,
            "background_jobs": ["reply_quality_review"],
        }
    if is_testdrive_material_question(text):
        return {
            **route,
            "level": "L1",
            "reason": "common_testdrive_materials_can_use_local_style",
            "foreground_llm_allowed": False,
            "background_jobs": ["reply_quality_review"],
        }
    if is_visit_report_prep_question(text):
        return {
            **route,
            "level": "L1",
            "reason": "common_visit_timing_can_use_local_style",
            "foreground_llm_allowed": False,
            "background_jobs": ["reply_quality_review"],
        }
    if (
        contains_any(text, TRADE_IN_TERMS)
        and contains_any(text, ("现场估", "现场评估", "开过去", "老车", "估价", "估一下"))
        and not contains_any(text, EXPLICIT_SOURCE_TERMS + ("推荐", "优先看", "值得看", "更想看", "想看", "备选", "当备选"))
    ):
        return {
            **route,
            "level": "L1",
            "reason": "common_trade_in_collect_can_use_local_style",
            "foreground_llm_allowed": False,
            "background_jobs": ["customer_profile_update", "reply_quality_review"],
        }
    if is_inspection_guidance_question(text):
        return {
            **route,
            "level": "L1",
            "reason": "common_inspection_guidance_can_use_local_style",
            "foreground_llm_allowed": False,
            "background_jobs": ["reply_quality_review"],
        }
    if is_cargo_space_guidance_question(text):
        return {
            **route,
            "level": "L1",
            "reason": "common_cargo_space_guidance_can_use_local_style",
            "foreground_llm_allowed": False,
            "background_jobs": ["reply_quality_review"],
        }
    if is_comfort_highway_question(text):
        return {
            **route,
            "level": "L1",
            "reason": "common_comfort_highway_guidance_can_use_local_style",
            "foreground_llm_allowed": False,
            "background_jobs": ["reply_quality_review"],
        }
    if is_feature_guidance_question(text):
        return {
            **route,
            "level": "L1",
            "reason": "common_feature_guidance_can_use_local_style",
            "foreground_llm_allowed": False,
            "background_jobs": ["reply_quality_review"],
        }
    if is_price_negotiation_question(text):
        return {
            **route,
            "level": "L1",
            "reason": "common_price_negotiation_can_use_local_style",
            "foreground_llm_allowed": False,
            "background_jobs": ["reply_quality_review"],
        }
    if is_warranty_guidance_question(text):
        return {
            **route,
            "level": "L1",
            "reason": "common_warranty_guidance_can_use_local_style",
            "foreground_llm_allowed": False,
            "background_jobs": ["reply_quality_review"],
        }
    if is_visit_timing_question(text):
        return {
            **route,
            "level": "L1",
            "reason": "common_visit_timing_can_use_local_style",
            "foreground_llm_allowed": False,
            "background_jobs": ["reply_quality_review"],
        }
    if is_no_deposit_visit_question(text):
        return {
            **route,
            "level": "L1",
            "reason": "common_no_deposit_visit_can_use_local_style",
            "foreground_llm_allowed": False,
            "background_jobs": ["reply_quality_review"],
        }
    if must_handoff:
        return {
            **route,
            "level": "L0",
            "reason": "deterministic_handoff_or_high_risk_boundary",
            "foreground_llm_allowed": False,
            "background_jobs": ["reply_quality_review"],
        }
    if is_short_greeting(text) or (intent == "greeting" and not has_business_signal(text)):
        return {
            **route,
            "level": "L0",
            "reason": "simple_greeting",
            "foreground_llm_allowed": False,
        }
    if product_knowledge and product_knowledge.get("matched") and not product_knowledge.get("needs_handoff"):
        return {
            **route,
            "level": "L0",
            "reason": "structured_product_fact_available",
            "foreground_llm_allowed": False,
        }
    if is_followup_vehicle_source_request(text, recent_reply_texts or []) or is_followup_vehicle_source_request(source_text, recent_reply_texts or []):
        return {
            **route,
            "level": "L1",
            "reason": "followup_ready_for_vehicle_candidates",
            "foreground_llm_allowed": False,
            "background_jobs": ["reply_quality_review"],
        }
    if is_explicit_vehicle_source_request(text) or is_explicit_vehicle_source_request(source_text):
        return {
            **route,
            "level": "L1",
            "reason": "explicit_vehicle_candidates_requested",
            "foreground_llm_allowed": False,
            "background_jobs": ["reply_quality_review"],
        }
    if is_detailed_vehicle_need_ready(text) or is_detailed_vehicle_need_ready(source_text):
        return {
            **route,
            "level": "L1",
            "reason": "detailed_vehicle_need_ready_for_candidates",
            "foreground_llm_allowed": False,
            "background_jobs": ["reply_quality_review"],
        }
    if contains_any(text, VALUE_RETENTION_TERMS):
        return {
            **route,
            "level": "L1",
            "reason": "common_value_retention_followup_can_use_local_style",
            "foreground_llm_allowed": False,
            "background_jobs": ["reply_quality_review"],
        }
    if contains_any(text, NEW_ENERGY_CHECK_TERMS):
        return {
            **route,
            "level": "L1",
            "reason": "common_new_energy_check_can_use_local_style",
            "foreground_llm_allowed": False,
            "background_jobs": ["reply_quality_review"],
        }
    if contains_any(text, TRADE_IN_TERMS):
        return {
            **route,
            "level": "L1",
            "reason": "common_trade_in_collect_can_use_local_style",
            "foreground_llm_allowed": False,
            "background_jobs": ["customer_profile_update", "reply_quality_review"],
        }
    if is_appointment_context_query(text):
        return {
            **route,
            "level": "L1",
            "reason": "common_visit_timing_can_use_local_style",
            "foreground_llm_allowed": False,
            "background_jobs": ["reply_quality_review"],
        }
    if contains_any(text, FOLLOWUP_TERMS) and len(text) >= 8:
        return {
            **route,
            "level": "L2",
            "reason": "multi_turn_reference_needs_light_synthesis",
            "foreground_llm_allowed": bool(settings.get("allow_foreground_llm", True)),
            "background_jobs": ["conversation_summary"],
        }
    if contains_any(text, RECOMMEND_TERMS):
        return {
            **route,
            "level": "L1",
            "reason": "common_recommendation_can_use_local_candidates",
            "foreground_llm_allowed": False,
            "background_jobs": ["reply_quality_review"],
        }
    if not soft_missing_evidence and (rag_reply.get("applied") or bool((evidence_pack.get("rag_evidence", {}) or {}).get("hits"))):
        return {
            **route,
            "level": "L1",
            "reason": "rag_or_style_experience_available",
            "foreground_llm_allowed": False,
            "background_jobs": ["rag_experience_audit"],
        }

    return {
        **route,
        "level": "L2",
        "reason": "uncertain_message_light_synthesis_allowed",
        "foreground_llm_allowed": bool(settings.get("allow_foreground_llm", True)),
        "background_jobs": ["reply_quality_review"],
    }


def requires_high_risk_boundary(text: str) -> bool:
    clean = normalize_text(text)
    if not clean:
        return False
    if contains_any(clean, ("不要求你保证", "不用保证", "不需要保证", "不是让你保证")):
        clean = clean.replace("保证", "")
    if contains_any(clean, NO_DEPOSIT_VISIT_TERMS):
        clean = clean.replace("定金", "").replace("订金", "")
    if contains_any(clean, STRICT_HIGH_RISK_TERMS):
        return True
    if is_store_arrival_contact_question(clean):
        return True
    if is_same_day_delivery_or_transaction_question(clean):
        return True
    if is_specific_price_approval_question(clean):
        return True
    if not contains_any(clean, CONDITION_SENSITIVE_RISK_TERMS):
        return False
    if contains_any(clean, ("检测", "检测报告", "记录", "三电记录", "怎么看", "怎么查", "一般怎么看")) and not contains_any(clean, ("保证", "绝对", "肯定", "负责", "赔", "赔偿")):
        return False
    return contains_any(clean, GUARANTEE_CONTEXT_TERMS)


def is_specific_price_approval_question(text: str) -> bool:
    clean = normalize_text(text)
    if not clean or not contains_any(clean, PRICE_NEGOTIATION_TERMS + ("报价", "成交价")):
        return False
    has_specific_target = bool(re.search(r"\d+(?:\.\d+)?\s*(?:万|整)", clean))
    if not has_specific_target:
        return False
    return contains_any(clean, ("帮我问", "问问", "能不能谈", "谈到", "能不能给", "给到", "最低", "现在定", "今天定", "直接定", "马上定"))


def is_same_day_delivery_or_transaction_question(text: str) -> bool:
    clean = normalize_text(text)
    if not clean or not contains_any(clean, SAME_DAY_DELIVERY_TERMS):
        return False
    transaction_context = (
        "当天",
        "今天",
        "马上",
        "直接",
        "能不能",
        "可以吗",
        "行不行",
        "试驾没问题",
        "看完",
        "办手续",
        "资料齐",
    )
    return contains_any(clean, transaction_context)


def is_store_arrival_contact_question(text: str) -> bool:
    clean = normalize_text(text)
    if not clean or not contains_any(clean, STORE_ARRIVAL_HANDOFF_TERMS):
        return False
    visit_context = ("你们店", "门店", "店里", "到店", "到了", "过去", "看车", "试驾", "跑错", "导航")
    return contains_any(clean, visit_context)


def is_actual_customer_data_message(text: str) -> bool:
    clean = normalize_text(text)
    if not clean:
        return False
    if re.search(r"(?<!\d)1[3-9]\d{9}(?!\d)", clean):
        return True
    if re.search(r"(?:我叫|我姓|本人|联系人|姓名)\s*[\u4e00-\u9fff·]{1,8}", clean):
        return True
    return contains_any(clean, ("客户资料", "客户信息", "收货信息", "联系电话", "手机号"))


def is_vehicle_compare_question(text: str, recent_reply_texts: list[str]) -> bool:
    clean = normalize_text(text)
    if not clean or not contains_any(clean, VEHICLE_COMPARE_TERMS):
        return False
    if contains_any(clean, STRICT_HIGH_RISK_TERMS) or contains_any(clean, OFF_TOPIC_OR_SECURITY_TERMS):
        return False
    # Category tradeoffs like "sedan vs SUV for a two-child family" should be
    # answered as vehicle-type guidance, not hijacked by previously mentioned
    # concrete candidates.
    if contains_any(clean, ("轿车", "suv", "mpv", "七座", "车型")) and not contains_any(clean, CONCRETE_USED_CAR_MODEL_TERMS):
        return False
    recent = normalize_text(" ".join(recent_reply_texts[-4:]))
    return contains_any(clean, USED_CAR_SCENE_QUERY_TERMS + USED_CAR_EXPLICIT_QUERY_TERMS + USED_CAR_PRODUCT_TERMS) or contains_any(recent, USED_CAR_PRODUCT_TERMS)


def is_vehicle_type_guidance_question(text: str) -> bool:
    clean = normalize_text(text)
    if not clean or not contains_any(clean, VEHICLE_TYPE_GUIDANCE_TERMS):
        return False
    if contains_any(clean, EXPLICIT_SOURCE_TERMS + ("哪两台", "哪台", "推荐", "具体车源", "锁定两台")):
        return False
    if requires_high_risk_boundary(clean) or contains_any(clean, OFF_TOPIC_OR_SECURITY_TERMS):
        return False
    guidance_markers = (
        "怎么选",
        "怎么建议",
        "哪类",
        "哪种",
        "哪个方向",
        "哪个更",
        "会不会",
        "大不大",
        "压力",
        "太大",
        "适合",
        "纠结",
        "取舍",
    )
    return contains_any(clean, guidance_markers)


def is_maintenance_cost_question(text: str) -> bool:
    clean = normalize_text(text)
    if not clean or not contains_any(clean, MAINTENANCE_COST_TERMS):
        return False
    if contains_any(clean, EXPLICIT_SOURCE_TERMS + ("哪两台", "哪台", "推荐", "具体车源", "锁定两台")):
        return False
    if requires_high_risk_boundary(clean) or contains_any(clean, OFF_TOPIC_OR_SECURITY_TERMS):
        return False
    return contains_any(clean, ("差多少", "差别", "贵不贵", "成本", "保养", "维修", "后期", "养车", "费用", "油耗", "小毛病", "少操心"))


def is_inspection_guidance_question(text: str) -> bool:
    clean = normalize_text(text)
    if not clean or not contains_any(clean, INSPECTION_GUIDANCE_TERMS):
        return False
    if requires_high_risk_boundary(clean):
        return False
    return contains_any(clean, ("怎么", "怎么看", "把关", "报告", "记录", "能不能看", "能不能带", "一起看", "第三方", "不踏实", "只听", "有没有", "实际", "只听口头", "具体", "怕", "补漆", "换件", "说清楚", "披露", "事故车"))


def is_feature_guidance_question(text: str) -> bool:
    clean = normalize_text(text)
    if not clean or not contains_any(clean, FEATURE_GUIDANCE_TERMS):
        return False
    if is_comfort_highway_question(clean):
        return False
    if contains_any(clean, EXPLICIT_SOURCE_TERMS + ("哪两台", "哪台", "推荐", "具体车源")):
        return False
    if requires_high_risk_boundary(clean):
        return False
    return contains_any(clean, ("安全配置", "倒车影像", "倒车雷达", "雷达", "360", "气囊", "esp", "辅助驾驶", "重点看", "是不是", "要不要", "安全", "配置"))


def is_comfort_highway_question(text: str) -> bool:
    clean = normalize_text(text)
    if not clean or not contains_any(clean, COMFORT_HIGHWAY_TERMS):
        return False
    if contains_any(clean, EXPLICIT_SOURCE_TERMS + ("哪两台", "哪台", "推荐", "具体车源", "锁定两台")):
        return False
    if requires_high_risk_boundary(clean) or contains_any(clean, OFF_TOPIC_OR_SECURITY_TERMS):
        return False
    return contains_any(clean, ("重点看", "应该看", "怎么看", "会不会", "颠", "舒服", "舒适", "隔音", "胎噪", "高速", "后排"))


def is_cargo_space_guidance_question(text: str) -> bool:
    clean = normalize_text(text)
    if not clean or not contains_any(clean, CARGO_SPACE_GUIDANCE_TERMS):
        return False
    if contains_any(clean, EXPLICIT_SOURCE_TERMS + ("哪两台", "哪台", "推荐", "具体车源", "锁定两台")):
        return False
    if requires_high_risk_boundary(clean) or contains_any(clean, OFF_TOPIC_OR_SECURITY_TERMS):
        return False
    return contains_any(clean, ("能不能", "能装", "装", "放", "尺寸", "容积", "够不够", "够用", "实用", "现场", "实车", "第二排", "二排", "后备"))


def is_finance_guidance_question(text: str) -> bool:
    clean = normalize_text(text)
    if not clean or not contains_any(clean, FINANCE_GUIDANCE_TERMS):
        return False
    if contains_any(clean, ("不要求你保证", "不用保证", "不需要保证", "不是让你保证")):
        clean = clean.replace("保证", "")
    if contains_any(clean, ("包过", "保证", "肯定能批", "一定能批", "最低首付", "零首付")):
        return False
    return contains_any(clean, ("大概", "范围", "流程", "多久", "麻烦", "怎么算", "准备", "手续", "首付", "月供", "征信"))


def is_fee_transparency_question(text: str) -> bool:
    clean = normalize_text(text)
    if not clean or not contains_any(clean, FEE_GUIDANCE_TERMS):
        return False
    if contains_any(clean, ("少开", "低开", "合同", "发票")):
        return False
    return contains_any(clean, ("费用", "提前", "说清楚", "明细", "上牌", "过户", "保险", "加费用", "收费"))


def is_testdrive_material_question(text: str) -> bool:
    clean = normalize_text(text)
    if not clean or not contains_any(clean, TESTDRIVE_MATERIAL_TERMS):
        return False
    if contains_any(clean, ("押金", "定金", "订金", "锁车", "保证")):
        return False
    if contains_any(clean, ("几点", "时间", "白跑", "稳", "周日", "周六", "下午", "上午")):
        return False
    return contains_any(clean, ("带", "材料", "身份证", "驾驶证", "证件", "需要带", "准备什么", "什么资料"))


def is_specific_testdrive_appointment_question(text: str) -> bool:
    clean = normalize_text(text)
    if not clean or not contains_any(clean, ("试驾", "试车")):
        return False
    if is_testdrive_material_question(clean):
        return False
    return contains_any(clean, ("今天", "明天", "周六", "周日", "上午", "下午", "晚上", "几点", "时间", "到店", "过去", "预约", "安排", "能看", "能不能看"))


def is_visit_timing_question(text: str) -> bool:
    clean = normalize_text(text)
    if not clean or not contains_any(clean, APPOINTMENT_TERMS):
        return False
    if contains_any(clean, ("定金", "订金", "锁车", "留车")) or is_actual_customer_data_message(clean):
        return False
    if is_visit_report_prep_question(clean):
        return True
    return contains_any(clean, ("几点", "时间", "白跑", "稳", "一次看", "对比", "试驾", "试车"))


def is_visit_report_prep_question(text: str) -> bool:
    clean = normalize_text(text)
    if not clean or not contains_any(clean, APPOINTMENT_TERMS):
        return False
    if requires_high_risk_boundary(clean):
        return False
    return contains_any(clean, ("检测报告", "车准备好", "准备好", "提前把", "提前准备", "车源状态"))


def is_no_deposit_visit_question(text: str) -> bool:
    clean = normalize_text(text)
    if not clean or not contains_any(clean, NO_DEPOSIT_VISIT_TERMS):
        return False
    if contains_any(clean, ("最低价", "底价", "包过", "保证", "赔偿", "合同", "发票", "少开", "迁入政策")):
        return False
    return contains_any(clean, ("先看车", "看车", "报告", "检测", "满意", "再谈", "流程", "可以吧", "行不行"))


def is_price_negotiation_question(text: str) -> bool:
    clean = normalize_text(text)
    if not clean or not contains_any(clean, PRICE_NEGOTIATION_TERMS):
        return False
    if contains_any(clean, NO_DEPOSIT_VISIT_TERMS):
        return False
    if contains_any(clean, ("最低价", "底价", "今天就定", "现在就定", "保证", "绝对", "包过")):
        return False
    return contains_any(clean, ("能不能", "还能", "谈", "优惠", "贵", "少", "便宜", "现场", "合适"))


def is_warranty_guidance_question(text: str) -> bool:
    clean = normalize_text(text)
    if not clean or not contains_any(clean, WARRANTY_GUIDANCE_TERMS):
        return False
    if contains_any(clean, ("赔偿", "退车", "退款", "维权", "投诉", "保证", "绝对")):
        return False
    return contains_any(clean, ("怎么", "具体", "理解", "找谁", "买完", "售后", "质保", "保修", "出问题"))


def is_service_guidance_question(text: str) -> bool:
    return any(
        checker(text)
        for checker in (
            is_fee_transparency_question,
            is_finance_guidance_question,
            is_testdrive_material_question,
            is_inspection_guidance_question,
            is_feature_guidance_question,
            is_comfort_highway_question,
            is_vehicle_type_guidance_question,
            is_maintenance_cost_question,
            is_no_deposit_visit_question,
            is_price_negotiation_question,
            is_warranty_guidance_question,
            is_visit_timing_question,
        )
    )


def maybe_build_realtime_reply(
    *,
    config: dict[str, Any],
    route: dict[str, Any],
    combined: str,
    evidence_pack: dict[str, Any],
    current_reply_text: str,
    recent_reply_texts: list[str] | None = None,
) -> dict[str, Any]:
    if route.get("enabled") is False or route.get("level") != "L1":
        return {"applied": False, "reason": "route_not_l1"}
    current_combined = current_customer_text(combined)
    contextual_combined = realtime_contextual_customer_text(
        combined,
        recent_reply_texts=recent_reply_texts or [],
    )
    text = normalize_text(current_combined)
    source_text = normalize_text(contextual_combined)
    recent_reply_texts = recent_reply_texts or []
    if is_identity_probe(text):
        reply, variant_index = build_identity_probe_reply(
            config,
            query=current_combined,
            recent_reply_texts=recent_reply_texts,
        )
        return {
            "applied": True,
            "rule_name": "realtime_identity_probe",
            "reason": "local_identity_guard_reply",
            "raw_reply_text": reply,
            "reply_text": reply,
            "variant_index": variant_index,
            "used_product_ids": [],
            "saved_reason": "foreground_llm_skipped_for_identity_probe",
        }
    route_reason = str(route.get("reason") or "")
    if route_reason == "common_vehicle_compare_can_use_local_style":
        reply, variant_index = build_vehicle_compare_reply(current_combined, recent_reply_texts=recent_reply_texts)
        return {
            "applied": True,
            "rule_name": "realtime_vehicle_compare_guidance",
            "reason": "local_vehicle_compare_guidance",
            "raw_reply_text": reply,
            "reply_text": reply,
            "variant_index": variant_index,
            "used_product_ids": [],
            "saved_reason": "foreground_llm_skipped_for_vehicle_compare",
        }
    if route_reason == "common_vehicle_type_guidance_can_use_local_style":
        reply, variant_index = build_vehicle_type_guidance_reply(current_combined, recent_reply_texts=recent_reply_texts)
        return {
            "applied": True,
            "rule_name": "realtime_vehicle_type_guidance",
            "reason": "local_vehicle_type_guidance",
            "raw_reply_text": reply,
            "reply_text": reply,
            "variant_index": variant_index,
            "used_product_ids": [],
            "saved_reason": "foreground_llm_skipped_for_vehicle_type_guidance",
        }
    if route_reason == "common_maintenance_cost_can_use_local_style":
        reply, variant_index = build_maintenance_cost_reply(current_combined, recent_reply_texts=recent_reply_texts)
        return {
            "applied": True,
            "rule_name": "realtime_maintenance_cost_guidance",
            "reason": "local_maintenance_cost_guidance",
            "raw_reply_text": reply,
            "reply_text": reply,
            "variant_index": variant_index,
            "used_product_ids": [],
            "saved_reason": "foreground_llm_skipped_for_maintenance_cost_guidance",
        }
    if route_reason == "common_inspection_guidance_can_use_local_style":
        reply, variant_index = build_inspection_guidance_reply(current_combined, recent_reply_texts=recent_reply_texts)
        return {
            "applied": True,
            "rule_name": "realtime_inspection_guidance",
            "reason": "local_inspection_guidance",
            "raw_reply_text": reply,
            "reply_text": reply,
            "variant_index": variant_index,
            "used_product_ids": [],
            "saved_reason": "foreground_llm_skipped_for_inspection_guidance",
        }
    if route_reason == "common_cargo_space_guidance_can_use_local_style":
        reply, variant_index = build_cargo_space_guidance_reply(current_combined, recent_reply_texts=recent_reply_texts)
        return {
            "applied": True,
            "rule_name": "realtime_cargo_space_guidance",
            "reason": "local_cargo_space_guidance",
            "raw_reply_text": reply,
            "reply_text": reply,
            "variant_index": variant_index,
            "used_product_ids": [],
            "saved_reason": "foreground_llm_skipped_for_cargo_space_guidance",
        }
    if route_reason == "common_feature_guidance_can_use_local_style":
        reply, variant_index = build_feature_guidance_reply(current_combined, recent_reply_texts=recent_reply_texts)
        return {
            "applied": True,
            "rule_name": "realtime_feature_guidance",
            "reason": "local_feature_guidance",
            "raw_reply_text": reply,
            "reply_text": reply,
            "variant_index": variant_index,
            "used_product_ids": [],
            "saved_reason": "foreground_llm_skipped_for_feature_guidance",
        }
    if route_reason == "common_comfort_highway_guidance_can_use_local_style":
        reply, variant_index = build_comfort_highway_reply(current_combined, recent_reply_texts=recent_reply_texts)
        return {
            "applied": True,
            "rule_name": "realtime_comfort_highway_guidance",
            "reason": "local_comfort_highway_guidance",
            "raw_reply_text": reply,
            "reply_text": reply,
            "variant_index": variant_index,
            "used_product_ids": [],
            "saved_reason": "foreground_llm_skipped_for_comfort_highway_guidance",
        }
    if route_reason == "common_finance_guidance_can_use_local_style":
        reply, variant_index = build_finance_guidance_reply(current_combined, recent_reply_texts=recent_reply_texts)
        return {
            "applied": True,
            "rule_name": "realtime_finance_guidance",
            "reason": "local_finance_guidance",
            "raw_reply_text": reply,
            "reply_text": reply,
            "variant_index": variant_index,
            "used_product_ids": [],
            "saved_reason": "foreground_llm_skipped_for_finance_guidance",
        }
    if route_reason == "common_fee_guidance_can_use_local_style":
        reply, variant_index = build_fee_guidance_reply(current_combined, recent_reply_texts=recent_reply_texts)
        return {
            "applied": True,
            "rule_name": "realtime_fee_guidance",
            "reason": "local_fee_guidance",
            "raw_reply_text": reply,
            "reply_text": reply,
            "variant_index": variant_index,
            "used_product_ids": [],
            "saved_reason": "foreground_llm_skipped_for_fee_guidance",
        }
    if route_reason == "common_testdrive_materials_can_use_local_style":
        reply, variant_index = build_testdrive_material_reply(current_combined, recent_reply_texts=recent_reply_texts)
        return {
            "applied": True,
            "rule_name": "realtime_testdrive_materials",
            "reason": "local_testdrive_material_guidance",
            "raw_reply_text": reply,
            "reply_text": reply,
            "variant_index": variant_index,
            "used_product_ids": [],
            "saved_reason": "foreground_llm_skipped_for_testdrive_materials",
        }
    if route_reason == "common_visit_timing_can_use_local_style":
        reply, variant_index = build_visit_timing_reply(current_combined, recent_reply_texts=recent_reply_texts)
        return {
            "applied": True,
            "rule_name": "realtime_visit_timing",
            "reason": "local_visit_timing_guidance",
            "raw_reply_text": reply,
            "reply_text": reply,
            "variant_index": variant_index,
            "used_product_ids": [],
            "saved_reason": "foreground_llm_skipped_for_visit_timing",
        }
    if route_reason == "common_no_deposit_visit_can_use_local_style":
        reply, variant_index = build_no_deposit_visit_reply(current_combined, recent_reply_texts=recent_reply_texts)
        return {
            "applied": True,
            "rule_name": "realtime_no_deposit_visit_guidance",
            "reason": "local_no_deposit_visit_guidance",
            "raw_reply_text": reply,
            "reply_text": reply,
            "variant_index": variant_index,
            "used_product_ids": [],
            "saved_reason": "foreground_llm_skipped_for_no_deposit_visit",
        }
    if route_reason == "common_price_negotiation_can_use_local_style":
        reply, variant_index = build_price_negotiation_reply(current_combined, recent_reply_texts=recent_reply_texts)
        return {
            "applied": True,
            "rule_name": "realtime_price_negotiation",
            "reason": "local_price_negotiation_guidance",
            "raw_reply_text": reply,
            "reply_text": reply,
            "variant_index": variant_index,
            "used_product_ids": [],
            "saved_reason": "foreground_llm_skipped_for_price_negotiation",
        }
    if route_reason == "common_warranty_guidance_can_use_local_style":
        reply, variant_index = build_warranty_guidance_reply(current_combined, recent_reply_texts=recent_reply_texts)
        return {
            "applied": True,
            "rule_name": "realtime_warranty_guidance",
            "reason": "local_warranty_guidance",
            "raw_reply_text": reply,
            "reply_text": reply,
            "variant_index": variant_index,
            "used_product_ids": [],
            "saved_reason": "foreground_llm_skipped_for_warranty_guidance",
        }
    if contains_any(text, VALUE_RETENTION_TERMS):
        reply, variant_index = build_value_retention_reply(current_combined, recent_reply_texts=recent_reply_texts)
        return {
            "applied": True,
            "rule_name": "realtime_value_retention_followup",
            "reason": "local_value_retention_general_guidance",
            "raw_reply_text": reply,
            "reply_text": reply,
            "variant_index": variant_index,
            "used_product_ids": [],
            "saved_reason": "foreground_llm_skipped_for_common_value_retention_followup",
        }
    if contains_any(text, NEW_ENERGY_CHECK_TERMS):
        reply, variant_index = build_new_energy_check_reply(current_combined, recent_reply_texts=recent_reply_texts)
        return {
            "applied": True,
            "rule_name": "realtime_new_energy_check",
            "reason": "local_new_energy_check_guidance",
            "raw_reply_text": reply,
            "reply_text": reply,
            "variant_index": variant_index,
            "used_product_ids": [],
            "saved_reason": "foreground_llm_skipped_for_common_new_energy_check",
        }
    if route_reason == "common_trade_in_collect_can_use_local_style":
        reply, variant_index = build_trade_in_collect_reply(current_combined, recent_reply_texts=recent_reply_texts)
        return {
            "applied": True,
            "rule_name": "realtime_trade_in_collect",
            "reason": "local_trade_in_information_collection",
            "raw_reply_text": reply,
            "reply_text": reply,
            "variant_index": variant_index,
            "used_product_ids": [],
            "saved_reason": "foreground_llm_skipped_for_common_trade_in_collect",
        }
    followup_source_request = is_followup_vehicle_source_request(text, recent_reply_texts) or is_followup_vehicle_source_request(source_text, recent_reply_texts)
    explicit_source_request = is_explicit_vehicle_source_request(text) or is_explicit_vehicle_source_request(source_text)
    detailed_source_request = is_detailed_vehicle_need_ready(text) or is_detailed_vehicle_need_ready(source_text)
    if not contains_any(text, RECOMMEND_TERMS) and not followup_source_request and not explicit_source_request and not detailed_source_request:
        return {"applied": False, "reason": "not_recommendation_scene"}
    if current_reply_text and not can_override_current_reply(current_reply_text):
        return {"applied": False, "reason": "current_rule_reply_has_priority"}
    if not followup_source_request and not explicit_source_request and not detailed_source_request:
        reply, variant_index = build_generic_recommendation_reply(combined, recent_reply_texts=recent_reply_texts)
        return {
            "applied": True,
            "rule_name": "realtime_local_recommendation",
            "reason": "first_broad_recommendation_stays_consultative",
            "raw_reply_text": reply,
            "reply_text": reply,
            "variant_index": variant_index,
            "used_product_ids": [],
            "saved_reason": "foreground_llm_skipped_for_first_broad_recommendation",
        }
    recommendation_query = query_with_recent_requirement_context(combined, recent_reply_texts)
    candidates = rank_product_candidates(
        recommendation_query,
        evidence_pack,
        allow_catalog_fallback=followup_source_request or explicit_source_request or detailed_source_request,
        allow_broad_fallback=followup_source_request or explicit_source_request or detailed_source_request,
    )
    if not candidates:
        reply, variant_index = build_generic_recommendation_reply(combined, recent_reply_texts=recent_reply_texts)
        return {
            "applied": True,
            "rule_name": "realtime_local_recommendation",
            "reason": "local_recommendation_clarifying_fallback",
            "raw_reply_text": reply,
            "reply_text": reply,
            "variant_index": variant_index,
            "used_product_ids": [],
            "saved_reason": "foreground_llm_skipped_for_common_recommendation",
        }
    reply, variant_index = build_recommendation_reply(recommendation_query, candidates[:2], recent_reply_texts=recent_reply_texts)
    if not reply:
        return {"applied": False, "reason": "empty_realtime_reply"}
    return {
        "applied": True,
        "rule_name": "realtime_local_recommendation",
        "reason": "local_product_candidates_with_service_style",
        "raw_reply_text": reply,
        "reply_text": reply,
        "variant_index": variant_index,
        "used_product_ids": [str(item.get("id") or "") for item in candidates[:2] if item.get("id")],
        "saved_reason": "foreground_llm_skipped_for_common_recommendation",
    }


def query_with_recent_requirement_context(query: str, recent_reply_texts: list[str] | None = None) -> str:
    current = str(query or "").strip()
    if extract_budget_wan(current) > 0:
        return current
    context = recent_requirement_context(recent_reply_texts or [])
    if not context:
        return current
    return f"近期已确认需求：{context}\n当前客户问题：{current}"


def recent_requirement_context(recent_reply_texts: list[str]) -> str:
    for reply in reversed(recent_reply_texts[-4:]):
        text = re.sub(r"\s+", " ", str(reply or "")).strip()
        if not text or extract_budget_wan(text) <= 0:
            continue
        for pattern in (
            r"需求这块[^。；;]*",
            r"从\d+(?:\.\d+)?万(?:以内|以下|内|左右)?[^。；;]*",
            r"按您说的\d+(?:\.\d+)?万(?:以内|以下|内|左右)?[^。；;]*",
            r"\d+(?:\.\d+)?万(?:以内|以下|内|左右)[^。；;]*",
        ):
            match = re.search(pattern, text)
            if match:
                return match.group(0)[:180]
    return ""


def build_generic_recommendation_reply(query: str, *, recent_reply_texts: list[str] | None = None) -> tuple[str, int]:
    summary = build_need_summary(query)
    budget_known = extract_budget_wan(query) > 0
    if is_appointment_context_query(query):
        visit_time = extract_visit_time_label(query)
        if visit_time:
            return choose_natural_reply_variant(
                [
                    f"可以，我先按{visit_time}帮您核车源和门店排期，确认车还在、能不能试驾、能不能一次看两台，尽量别让您白跑。",
                    f"{visit_time}这个时间我先记下，接下来主要确认车源状态、排期和试驾安排；确认没问题再让您过去更稳。",
                    f"行，我按{visit_time}去核一下现车和排期。到店前把车源还在不在、能不能一起看、试驾怎么排确认清楚，省得您多跑。",
                ],
                key_text=query,
                recent_reply_texts=recent_reply_texts,
            )
        return choose_natural_reply_variant(
            [
                "可以的，您来之前跟我说一下大概时间和想看的车型，我帮您确认一下车源还在不在、门店排期和能不能一次安排两三台一起看，尽量别让您白跑。",
                "行，您把大概到店时间和想看的方向发我，我确认车源、门店排期和能不能集中安排几台一起看，省得您跑空。",
                "可以安排，您先说下周末大概几点到、想看轿车还是SUV。我这边把现车和排期核一下，尽量让您一次看得完整点。",
            ],
            key_text=query,
            recent_reply_texts=recent_reply_texts,
        )
    if budget_known and summary:
        followup = build_next_info_prompt(query, recent_reply_texts=recent_reply_texts)
        return choose_natural_reply_variant(
            [
                f"按您说的{summary}，先看车况、好不好上手和后期成本，不只看车名。{followup}",
                f"信息已经够先筛了：{summary}。接下来按这个方向看现车和车况记录，{followup}",
                f"这个需求比较明确了，{summary}。先把不合适的排掉，重点看车况透明、驾驶好上手、后期费用别太高的。{followup}",
                f"那就不从大方向绕了，先按{summary}往下缩范围。车况、公里数和配置适配度放前面看，{followup}",
            ],
            key_text=query,
            recent_reply_texts=recent_reply_texts,
        )
    if any(term in query for term in ("露营", "钓鱼", "郊外", "后备箱", "底盘高", "通过性")):
        return choose_natural_reply_variant(
            [
                "您这个更像周末户外用车场景，重点看SUV空间、后备箱、底盘通过性、油耗和底盘车况。先别只看外观配置，预算和是否置换确认后，我按现车把更适合露营钓鱼的几台缩出来。",
                "露营钓鱼的话，方向可以先放在空间够用、底盘别太低、后备箱规整、油耗别太夸张的SUV上。您把预算上限和能不能接受置换/贷款说一下，我再往具体车源上靠。",
                "这个用途我理解，车不能太娇气，后备箱和底盘状态也要看。先按SUV、空间、油耗、检测报告和后期保养成本筛，后面再给您缩到两台更稳的。",
            ],
            key_text=query,
            recent_reply_texts=recent_reply_texts,
        )
    if any(term in query for term in ("工地", "皮实", "耐造")):
        return choose_natural_reply_variant(
            [
                "可以，这类需求我会按预算、底盘耐用度、车况透明和后期维修成本来筛，SUV也要看年份和公里数，不能只图便宜。您方便的话我帮您把四五万左右能看的方向捋一下。",
                "明白，跑工地更要看皮实耐造和车况，不建议只看外观和配置。按四五万左右、SUV、维修成本别太高的方向筛，具体还是以检测报告为准。",
                "这个预算可以先筛耐用、省心、维修不贵的SUV方向，车况比年份更关键。我帮您看有没有合适现车，再确认检测和公里数。",
            ],
            key_text=query,
            recent_reply_texts=recent_reply_texts,
        )
    if any(term in query for term in ("跑高速", "后排", "空间", "舒服", "年限", "爸妈", "父母")):
        return choose_natural_reply_variant(
            [
                "明白，您这个方向就不能只看价格了，我会优先按后排舒适、年限公里数、车况记录和高速稳定性来筛，具体还是以检测报告和实车情况为准。",
                "这个需求我理解，重点放在后排空间、底盘稳定、年限别太老和车况透明上，不会只按便宜来推。您后面如果方便到店，我可以先把适合的几台排出来。",
                "可以，您这个更偏家庭舒适和长途稳定，按车况干净、公里数合理、后排坐着不累的方向筛，别只看车名。",
            ],
            key_text=query,
            recent_reply_texts=recent_reply_texts,
        )
    if any(term in query for term in ("接娃", "家用", "通勤", "省油", "代步")):
        return choose_natural_reply_variant(
            [
                "您这个需求我建议先按预算、用途和车况筛，不要只看年份。家用通勤优先看省心、省油、维修成本低的车，具体车况还是以检测报告为准。您预算大概卡在多少，能不能接受贷款或置换？我再帮您缩到两三台。",
                "家用通勤的话，重点看省心、省油、后期维修成本低不低。您把预算和能不能贷款/置换说一下，我就能直接帮您缩小到两三台。",
                "这种需求重点不是年份越新越好，而是车况干净、公里数合理、后期好养。您预算大概卡在哪个区间？我按这个思路给您挑几台更稳的。",
            ],
            key_text=query,
            recent_reply_texts=recent_reply_texts,
        )
    return choose_natural_reply_variant(
        [
            "可以，先从预算、用途和偏好的车型入手。您把预算范围、主要用途、能否贷款或置换发我，我再给您缩到两三台合适的。",
            "没问题，预算、用途、偏轿车还是SUV、是否考虑贷款/置换，这几项说清楚后，我按条件给您筛几台更贴近的。",
            "可以先筛一轮。您把预算上限、用车场景和有没有置换发我，后面按车况和养车成本一起看，不只看车名。",
            "行，先别铺太大范围。您说下预算、主要怎么用车、有没有置换，我按这些条件直接往合适车源上靠。",
        ],
        key_text=query,
        recent_reply_texts=recent_reply_texts,
    )


def build_value_retention_reply(query: str, *, recent_reply_texts: list[str] | None = None) -> tuple[str, int]:
    return choose_natural_reply_variant(
        [
            "实际一点说，保值主要看品牌口碑、年份里程、车况和后面市场行情。家用车里同级别一般日系更稳一些，但最终不能只看车名，还是要结合检测报告、出险记录和成交价。您如果就是想以后少亏点，我建议优先选车况透明、公里数正常、后期好卖的那台。",
            "如果考虑以后再卖，别只盯车名，重点看公里数、车况透明度、保养记录和市场流通量。车况干净、后面好出手的，一般亏得少；具体还得看检测报告和当时行情。",
            "换个说法，二手车想少亏，核心是选好卖的车型和干净的车况。品牌是一方面，出险、公里数、保养记录更影响后面卖价；您可以优先挑车况透明、受众广的那台。",
        ],
        key_text=query,
        recent_reply_texts=recent_reply_texts,
    )


def build_vehicle_compare_reply(query: str, *, recent_reply_texts: list[str] | None = None) -> tuple[str, int]:
    normalized_query = normalize_text(query)
    recent = normalize_text(" ".join((recent_reply_texts or [])[-3:]))
    context = normalized_query + recent
    spouse_or_new_driver_context = contains_any(
        context,
        ("老婆", "媳妇", "爱人", "女士", "女司机", "给她开", "她停车", "停车不熟", "新手"),
    )
    business_or_cargo_context = contains_any(
        context,
        ("公司用", "接客户", "甲方", "活动策划", "商务", "物料", "展架", "音响架", "折叠桌", "器材", "后备厢", "后备箱"),
    )
    has_h6_xtrail = contains_any(context, ("哈弗h6", "h6")) and contains_any(context, ("奇骏", "xtrail"))
    has_xtrail_tiguan = contains_any(context, ("奇骏", "xtrail")) and contains_any(context, ("途观l", "途观"))
    has_mazda_golf = contains_any(context, ("马自达3", "昂克赛拉", "高尔夫"))
    if has_mazda_golf:
        if spouse_or_new_driver_context:
            variants = [
                "这俩里如果重点是新手好开、好停，我会把高尔夫放前面，车身更紧凑，城市停车压力小一点；昂克赛拉驾驶感更好，但后排和视野要实际坐一下。最终还是看检测报告、车况和试开感受。",
                "按好上手、停车压力小这个前提，高尔夫会更偏稳妥，昂克赛拉更偏驾驶质感。不是说哪台绝对好，关键看车况记录、倒车辅助配置和坐进去顺不顺手。",
                "如果只按好开好停排序，我会先看高尔夫，再看昂克赛拉；如果更在意开起来的质感，昂克赛拉也可以留着对比。到店最好两台都坐一下，方向盘、视野和倒车影像一试就明显。",
            ]
        else:
            variants = [
                "高尔夫更偏均衡和好停，城市通勤、后期维护压力相对好控；昂克赛拉更偏驾驶质感和外观。两台都能看，但我会先按车况、公里数和检测报告把优先级排出来。",
                "这两台方向不太一样：高尔夫实用、省心一点，昂克赛拉开起来更有质感。二手车别只看车名，先看检测报告、保养记录和实际试驾感受。",
                "如果您想稳一点，高尔夫更像均衡选择；如果更在意操控和颜值，昂克赛拉可以留着对比。最终还是看哪台车况更干净、价格更合适。",
            ]
    elif has_h6_xtrail:
        if business_or_cargo_context:
            variants = [
                "公司用、还要装物料的话，奇骏会更偏稳妥，空间、四驱和接待观感都还可以；H6预算压力小、配置通常也够用，但重点要核车况和油耗。您这个场景我会先看奇骏，H6当性价比备选。",
                "这两台都能往SUV方向看：奇骏更适合兼顾客户接待和物料装载，H6胜在价格压力低。接下来主要比后备厢实装、车况记录、底盘和试驾感受。",
                "如果公司形象和接待也要顾到，奇骏会比H6更稳一点；如果更看重预算和日常工具属性，H6也可以放备选。最终还是看检测报告、公里数和实际装载空间。",
            ]
        elif spouse_or_new_driver_context:
            variants = [
                "H6和奇骏这类SUV空间更占优，但对停车不熟的人来说车身尺寸要实际感受一下。这个场景我会优先看带倒车影像、雷达更全、坐姿视野好的那台，不只看空间。",
                "SUV优势是空间和视野，缺点是停车压力比小车大一点。重点看倒车影像、雷达、转弯半径和车身盲区，试开一下比我口头说更准。",
                "SUV不是不能选，但别选得只图大。H6、奇骏这类要重点看车况、油耗和停车辅助配置，谁更适合还是要实际试一下。",
            ]
        else:
            variants = [
                "奇骏和H6都属于实用SUV方向，奇骏更偏合资、空间和通过性，H6优势是预算压力小、配置看着更足。具体我会先看车况记录、公里数、底盘和油耗，再判断哪台更值。",
                "如果预算更紧，H6可以作为性价比备选；如果想兼顾质感、空间和后期流通，奇骏会更稳一点。二手车最后还是看检测报告和实车状态。",
                "这两台不建议只按品牌拍板。奇骏偏稳，H6偏实惠；您如果更重视装载和接待，我会把奇骏放前面，如果更重视价格，就把H6留着对比。",
            ]
    elif has_xtrail_tiguan:
        variants = [
            "奇骏更偏实用、空间和后期成本好控；途观L质感、动力和接待观感会更强一些，但价格和后期成本一般也更高。最后还是看具体车况、里程、底盘和试驾感受。",
            "这两个方向不一样：奇骏偏省心实用，途观L偏质感和动力。您如果想控制预算和维护成本，我会先看奇骏；如果更看重质感，再把途观L作为品质备选。",
            "如果按综合成本和实用性排序，奇骏可以放前面；途观L也能看，但要确认价格、底盘状态和后期保养成本。两台都建议看后备厢、试坐后排，再看检测报告。",
        ]
    else:
        if spouse_or_new_driver_context:
            variants = [
                "按新手、好停、省心这个排序，我会优先看车身不太大、自动挡、倒车影像/雷达齐、后期维修成本低的车。具体到哪台，还是把检测报告、公里数和试开感受放一起判断。",
                "这个场景别只看品牌名。好上手、视野、倒车辅助和车况透明度更重要；车身太大的SUV我会谨慎一点，除非实际试开觉得没压力。",
                "如果让我按优先级排：先看好不好停，再看车况和公里数，最后看配置和保值。新手用车，实际试坐试开很关键，光看参数容易偏。",
            ]
        else:
            variants = [
                "这类对比别只看车名，我会先看预算、用途、车况记录和后期成本。哪台更适合，要把检测报告、公里数、配置和实际试驾放一起判断。",
                "如果两台都能接受，我建议先按使用场景排优先级：装载、通勤、接待、停车压力分别看，再用车况和价格把范围收窄。",
                "二手车对比核心不是谁名气更大，而是哪台车况更干净、成本更可控、用起来更贴近您的场景。先看检测和实车，再谈优先级更稳。",
            ]
    return choose_natural_reply_variant(variants, key_text=query + recent, recent_reply_texts=recent_reply_texts)


def build_vehicle_type_guidance_reply(query: str, *, recent_reply_texts: list[str] | None = None) -> tuple[str, int]:
    normalized = normalize_text(query)
    spouse_or_new_driver_context = contains_any(
        normalized,
        ("老婆", "媳妇", "爱人", "女士", "女司机", "给她开", "她停车", "停车不熟", "新手"),
    )
    if contains_any(normalized, ("二胎", "全家", "老人孩子", "家庭")) and contains_any(normalized, ("轿车", "suv", "mpv", "车型")):
        return choose_natural_reply_variant(
            [
                "您这个二胎家庭场景，我会把空间、后备箱、后排舒适和停车压力放一起看。轿车更好开好停、油耗通常稳一点；SUV后备箱和坐姿视野更占优，老人孩子上下车也要实际试；MPV最舒服但车身大。您如果没有七座刚需，我会先看中型SUV或空间大的轿车，再到店试一下停车压力。",
                "二胎家用别只按车名选，核心是后排、后备箱、儿童座椅空间和家里人能不能轻松停车。轿车省心好开，SUV更全能，MPV舒服但尺寸压力大；您这个预算我会先把中型SUV和空间好的轿车并排看，最后以车况和试坐试驾为准。",
                "按您家里两个孩子、老人偶尔坐的情况，SUV的空间和后备箱会更实用，但停车和车身尺寸必须试。轿车适合通勤省心，MPV适合七座刚需；目前更建议先看尺寸别太夸张、车况透明的SUV/大空间轿车。",
            ],
            key_text=query,
            recent_reply_texts=recent_reply_texts,
        )
    if contains_any(normalized, ("suv", "停车", "老婆", "爱人", "偶尔也会开", "市区")):
        if spouse_or_new_driver_context:
            variants = [
                "SUV不是不能选，但市区停车确实比小车更考验车身尺寸和视野。到店重点试倒车影像、雷达、转弯半径和坐姿盲区；如果实际开着没压力，再看空间和通过性就更稳。",
                "这类SUV城市里能开，但别只看空间大。重点看车身大小、倒车辅助、方向轻不轻和停车视野；最好实际倒一把车，比我口头说更准。",
                "市区停车压力主要看车身尺寸、雷达影像、坐姿视野和方向手感。如果需要SUV空间，也要优先选尺寸别太夸张、辅助配置齐、车况透明的那台。",
            ]
        else:
            variants = [
                "SUV市区能开，但要把停车压力、油耗和装载需求一起看。您如果经常跑展会、拉物料，我会优先看后备厢开口、第二排放倒、雷达影像和底盘状态。",
                "公司用车不能只看空间大。市区跑得多的话，车身尺寸、油耗、后备厢实用性和接待观感都要平衡；奇骏、H6这类SUV可以看，但必须结合实车车况筛。",
                "市区用SUV，重点是好不好停、装卸顺不顺、油耗和维护成本能不能接受。装载需求明确的话，我会把空间和车况放前面，不会只看配置表。",
            ]
        return choose_natural_reply_variant(variants, key_text=query, recent_reply_texts=recent_reply_texts)
    return choose_natural_reply_variant(
        [
            "这个要按使用比例来取舍。轿车开起来更稳、接待也体面；SUV视野和通过性好，但停车和油耗压力通常大一点；MPV二排舒服，适合多人和老人孩子，只是车身尺寸要试一下。您如果接待和家用都要兼顾，我会先看中型SUV/舒适轿车，七座刚需再重点看MPV。",
            "不建议只按车型名定。市区停车多、家里人偶尔坐，轿车或中型SUV更均衡；经常带父母孩子长途，MPV舒服，但车大、油耗和停车都要实际感受。到店最好把坐姿、二排、倒车压力一起试。",
            "按实用角度说：轿车省心、稳；SUV更全能；MPV是舒适和七座取向。您如果只是偶尔七座，别急着上MPV；如果接待和家用频率都高，再把MPV放进备选，最后看车况和试驾感受。",
        ],
        key_text=query,
        recent_reply_texts=recent_reply_texts,
    )


def build_maintenance_cost_reply(query: str, *, recent_reply_texts: list[str] | None = None) -> tuple[str, int]:
    normalized = normalize_text(query)
    if contains_any(normalized, ("mpv", "商务车", "七座", "7座", "多人")):
        variants = [
            "后期成本大体可以这么看：豪华品牌保养、轮胎、易损件和维修单价通常更高；本田丰田这类保有量大的车，维护会更友好。MPV还要额外看电动门、座椅滑轨、底盘件和混动系统状态，具体到某台车还是以里程、保养记录和检测报告为准。",
            "如果您想后面少操心，别只看车价。豪华品牌开着有质感，但保养和维修成本一般更高；MPV则要重点看空间机构、电动门、悬挂和保养记录。最终我会把车况干净、保养连续的放前面。",
            "养车成本这块我会先分两层看：品牌零整比和这台车自己的车况。豪华品牌正常会贵一些，本田丰田体系相对好养；MPV还要看有没有长期商用痕迹、内饰磨损、底盘和保养记录，不能只按年份判断。",
        ]
    else:
        variants = [
            "后期成本我会先看品牌零整比、里程、保养记录和这台车自己的车况。豪华品牌通常保养维修贵一些，保有量大的日系或主流合资车一般更好养；具体还是以检测报告和维保记录为准。",
            "如果您想后面少操心，别只看车价。重点看发动机变速箱状态、底盘件、轮胎刹车、保养是否连续，还有这台车有没有明显维修隐患；车况干净的通常比配置高但记录乱的更稳。",
            "养车成本不能只按车名判断，我会把品牌维修单价、公里数、保养记录、易损件状态和检测报告一起看。能选的话，优先放车况透明、后期配件好找、保养记录连续的那台。",
        ]
    return choose_natural_reply_variant(
        variants,
        key_text=query,
        recent_reply_texts=recent_reply_texts,
    )


def build_inspection_guidance_reply(query: str, *, recent_reply_texts: list[str] | None = None) -> tuple[str, int]:
    return choose_natural_reply_variant(
        [
            "车况这块不能只听口头说。正常我会看检测报告、维保/出险记录、漆膜和结构件情况；补漆、换件、事故水泡火烧这些要分清楚说，重大问题必须以报告和实车为准。",
            "看二手车我建议抓几个硬点：检测报告、出险记录、保养记录、公里数逻辑、底盘和结构件。小补漆和重大事故不是一回事，能看到的补漆换件我会提醒您结合报告一起看。",
            "实际把关就是别只看外观。先看检测报告和维保出险，再看结构件、底盘、发动机变速箱工况；涉及事故、水泡、火烧或关键部位换件，必须以检测和记录为准，不靠一句口头承诺。",
        ],
        key_text=query,
        recent_reply_texts=recent_reply_texts,
    )


def build_cargo_space_guidance_reply(query: str, *, recent_reply_texts: list[str] | None = None) -> tuple[str, int]:
    return choose_natural_reply_variant(
        [
            "这个要看实车空间，不能只按参数拍板。到店我建议把第二排放倒试一下，量后备厢进深和开口高度，展架、音响架、折叠桌和箱子最好按实际尺寸比一遍；能装下还要看固定稳不稳、会不会挡视线。",
            "装物料这块得实测。SUV一般比轿车更合适，但具体还是要看第二排放倒后的地台、后备厢开口、箱子高度和装卸方便程度。您可以把最大那件器材尺寸发我，我先帮您对一遍方向。",
            "您问得很细，这个场景我会把后备厢开口、第二排能不能放平、地台高不高、箱子放进去是否晃动一起看。最好带一两个常用箱子到现场试装，光看图片容易误判。",
        ],
        key_text=query,
        recent_reply_texts=recent_reply_texts,
    )


def build_feature_guidance_reply(query: str, *, recent_reply_texts: list[str] | None = None) -> tuple[str, int]:
    return choose_natural_reply_variant(
        [
            "您这个关注点对。倒车影像、雷达、车身尺寸、视野和刹车脚感都要看；偶尔高速的话，再看胎况、制动、ESP/气囊这些基础安全配置，别只看屏幕配置。",
            "重点可以这么看：城市停车看倒车影像、雷达和车身大小；高速通勤看轮胎、刹车、底盘稳定和基础安全配置。到店实际试坐试开一下，比参数更直观。",
            "这些配置建议重点看，尤其是停车场景多的话，影像和雷达很实用。但最终还得结合车况、检测报告和开起来顺不顺手，配置多不代表一定适合。",
        ],
        key_text=query,
        recent_reply_texts=recent_reply_texts,
    )


def build_comfort_highway_reply(query: str, *, recent_reply_texts: list[str] | None = None) -> tuple[str, int]:
    return choose_natural_reply_variant(
        [
            "后排孩子坐、偶尔跑高速的话，重点看底盘稳定性、座椅支撑、轮胎胎况、隔音胎噪和悬挂有没有松散异响。SUV不是只看空间，试驾时过减速带、烂路和高速巡航感受都要一起看，检测报告里底盘件和轮胎也要核。",
            "这个问题问得细。别只看后排大不大，还要看座椅角度、悬挂支撑、胎噪、风噪和底盘有没有松旷；孩子坐得舒服不舒服，试驾一圈比参数更准。车况、轮胎和避震状态也会明显影响舒适度。",
            "如果想长途舒服一点，我会把后排坐姿、底盘滤震、隔音、轮胎和车况记录放前面看。尤其二手SUV，里程和底盘保养很关键，不是配置高就一定坐着舒服。",
        ],
        key_text=query,
        recent_reply_texts=recent_reply_texts,
    )


def build_finance_guidance_reply(query: str, *, recent_reply_texts: list[str] | None = None) -> tuple[str, int]:
    return choose_natural_reply_variant(
        [
            "分期可以先按车价、首付比例和贷款年限做大概测算，但月供和利率要看车型、首付和资方审批。您征信没问题的话流程一般不会太复杂，材料齐了再让金融那边给准方案。",
            "贷款流程通常是先定车型和车价，再看首付、年限、征信和资方方案。大概范围我可以先帮您算方向，但不能口头保证审批结果；到店前先把方案核清楚，避免您白跑。",
            "首付月供这块能先聊大概逻辑：车价越高、首付越低，月供压力就越大；具体利率、期数和能不能批，要金融审核后才准。您先不用急着定，我可以按目标预算帮您控制总成本。",
        ],
        key_text=query,
        recent_reply_texts=recent_reply_texts,
    )


def build_fee_guidance_reply(query: str, *, recent_reply_texts: list[str] | None = None) -> tuple[str, int]:
    return choose_natural_reply_variant(
        [
            "这个您提前问是对的。车价、过户、保险、上牌、金融相关费用这些都应该提前列清楚，能确认的我会让您看明细；如果哪项没说清楚，不建议您急着定。",
            "费用这块我建议到店前先核一遍：裸车价、过户/上牌、保险、金融或服务相关费用分别是多少。别到现场才发现多一块少一块，确认清楚再看车更稳。",
            "可以提前说清楚的，您关心的就是总落地成本。我这边会按车价、过户、保险、上牌和金融费用分开核，能列明细就列明细，避免后面产生误会。",
        ],
        key_text=query,
        recent_reply_texts=recent_reply_texts,
    )


def build_testdrive_material_reply(query: str, *, recent_reply_texts: list[str] | None = None) -> tuple[str, int]:
    return choose_natural_reply_variant(
        [
            "试驾一般带身份证和驾驶证就行，最好提前约时间。置换的话，旧车行驶证、登记证书、车主身份证、保单和车况照片能带就带，资料越全，估价越快。",
            "试驾的话，身份证、驾驶证先带着；旧车置换准备行驶证、登记证书、保单、车主身份证，再拍几张外观内饰照片。到店前我先确认车源和试驾排期，省得白跑。",
            "材料不复杂：看车试驾带身份证、驾驶证；置换旧车带行驶证、登记证书、保单和车主证件。照片提前发也行，我先帮您把置换和看车安排捋顺。",
        ],
        key_text=query,
        recent_reply_texts=recent_reply_texts,
    )


def build_visit_timing_reply(query: str, *, recent_reply_texts: list[str] | None = None) -> tuple[str, int]:
    visit_time = extract_visit_time_label(query)
    if contains_any(normalize_text(query), ("检测报告", "车准备好", "准备好", "提前把", "提前准备", "车源状态")):
        label = visit_time or "到店前"
        return choose_natural_reply_variant(
            [
                f"可以，我按{label}帮您核车源和排期，检测报告也提前一起确认，确认没问题再让您过去。",
                f"{label}我先记下，车源状态、检测报告和试驾安排我这边一起核，避免您到店后白等。",
                f"行，我按{label}去确认。到店前把现车、检测报告和试驾排期都核清楚，再给您准话。",
            ],
            key_text=query,
            recent_reply_texts=recent_reply_texts,
        )
    if visit_time:
        return choose_natural_reply_variant(
            [
                f"可以，我先按{visit_time}帮您确认车源、排期和试驾情况，确认没问题再让您过去，尽量别白跑。",
                f"{visit_time}我先记下，接下来核车源还在不在、能不能一次看两台、试驾怎么排，确认好再给您准话。",
                f"行，我按{visit_time}去核排期。到店前把现车、试驾和资料一起确认清楚，这样您过去效率高一点。",
            ],
            key_text=query,
            recent_reply_texts=recent_reply_texts,
        )
    return choose_natural_reply_variant(
        [
            "可以，周末建议先按下午两点到四点这个区间看，时间相对好排一点。您确定来之前我再核车源还在不在、能不能试驾和能否一次看两三台，尽量别让您白跑。",
            "能一次对比最好，我会先按您说的方向核两三台现车。周六下午一般三点左右比较稳，但最终还是要看门店排期和车源状态，我确认好再跟您说准。",
            "可以安排成对比看车，不建议只看一台就下判断。您周六下午来的话，我先按三点左右去核排期和试驾情况，确认没问题再让您过去。",
        ],
        key_text=query,
        recent_reply_texts=recent_reply_texts,
    )


def build_no_deposit_visit_reply(query: str, *, recent_reply_texts: list[str] | None = None) -> tuple[str, int]:
    return choose_natural_reply_variant(
        [
            "可以，先看实车和检测报告，不用一上来就急着交定金。您看完车况、试驾感受和费用明细都满意了，再谈价格和手续会更稳；我这边先把车源状态和看车排期核清楚。",
            "这个流程没问题。先看车、看报告、试驾，觉得合适再确认价格、手续和是否留车；没看明白之前不建议急着付定金，这样您心里也踏实。",
            "可以按这个节奏来。先把实车、检测报告、费用和试驾感受看清楚，满意后再谈成交和留车，不需要一开始就被定金绑住；我先帮您把要看的车和排期确认好。",
        ],
        key_text=query,
        recent_reply_texts=recent_reply_texts,
    )


def build_price_negotiation_reply(query: str, *, recent_reply_texts: list[str] | None = None) -> tuple[str, int]:
    return choose_natural_reply_variant(
        [
            "价格这块可以帮您争取，但我不建议还没看车就只盯最低。先把车况、检测报告和付款方式看清楚，现场如果确实合适，再按实际成交方案去谈会更靠谱。",
            "能谈的空间一般要结合车源、车况、付款方式和当天政策看。我可以先帮您把方向记下，但不随口报最低，免得到店前后说法对不上。",
            "您关注价格很正常。我的建议是先确认这台车值不值得看，再谈成交空间；如果车况和试驾都满意，我再帮您按付款方式和置换情况去争取。",
        ],
        key_text=query,
        recent_reply_texts=recent_reply_texts,
    )


def build_warranty_guidance_reply(query: str, *, recent_reply_texts: list[str] | None = None) -> tuple[str, int]:
    return choose_natural_reply_variant(
        [
            "售后这块要看合同约定和具体车源政策。一般会重点说清楚质保范围、期限、哪些部件覆盖、哪些属于易损件；真遇到问题先按合同和检测记录处理，不建议只听口头承诺。",
            "质保可以提前问清楚，尤其是发动机、变速箱这些核心部件怎么保、保多久、哪些情况不保。到店我建议把条款写清楚再定，这样后面不扯皮。",
            "买完以后如果有问题，先看合同质保条款和检测报告。能覆盖的按流程处理，易损件或人为使用问题通常另算；这块到店前我也会建议您问清楚。",
        ],
        key_text=query,
        recent_reply_texts=recent_reply_texts,
    )


def build_new_energy_check_reply(query: str, *, recent_reply_texts: list[str] | None = None) -> tuple[str, int]:
    return choose_natural_reply_variant(
        [
            "三电这块可以先看检测报告、电池状态、维保记录和实际用车强度。具体到某台车，我会重点核电池健康、充放电表现和有没有异常维修记录，别只听一句口头说没问题。",
            "您这个问法很对，插混/新能源不能只看年份和公里数。先看三电检测、电池状态、维保记录，再结合您的实际使用场景判断合不合适；具体到某台车，我再按检测记录帮您核。",
            "新能源这块我会先看三点：电池状态、三电检测记录、之前有没有异常维修。日常用车强度只是参考，具体适不适合还得落到这台车的检测和使用记录上。",
        ],
        key_text=query,
        recent_reply_texts=recent_reply_texts,
    )


def build_trade_in_collect_reply(query: str = "trade_in_collect", *, recent_reply_texts: list[str] | None = None) -> tuple[str, int]:
    normalized = normalize_text(query)
    if contains_any(normalized, ("准价", "别给区间", "准确价格", "能抵多少", "抵多少")):
        return choose_natural_reply_variant(
            [
                "置换不能只凭一句话给准价，我先按车型、年份、公里数、上牌地和车况给大概区间；最终还要核实行情和实车检测，确认后再说能抵多少车款。",
                "这个我不建议直接报死价，旧车要看手续、漆面、换件、事故水泡火烧和市场行情。您把基础信息和照片发我，我先核实一个区间，现场检测后再定准价。",
                "可以先估方向，但准价要等实车检测和行情核实。您先发车型年份、公里数、城市、配置和车况照片，我按这些给您看区间，再到店确认能抵多少。",
            ],
            key_text=query,
            recent_reply_texts=recent_reply_texts,
        )
    if contains_any(normalized, ("现场估", "现场评估", "开过去", "老车", "剐蹭")):
        recent_trade_in_context = normalize_text("\n".join(recent_reply_texts or []))
        if contains_any(recent_trade_in_context, ("基础信息够", "关键信息已经", "年份公里数", "年份、公里数", "上牌地")):
            return choose_natural_reply_variant(
                [
                    "可以，开过来现场看会更准。您这台基础信息已经有了，接下来主要补外观内饰照片、配置版本、手续和事故水泡火烧情况；到店再结合实车检测和行情定准价。",
                    "能现场评估。既然年份、公里数和上牌地前面已经说了，我这边再看照片、配置、手续和具体车况瑕疵，先估区间，到店后再按实车核准。",
                    "可以带过来估，旧车最终还是看实车。您这台我先按已给的基础信息建个底，再补照片、配置和事故水泡火烧情况，现场看漆面、结构件和行情后定准一点。",
                ],
                key_text=query,
                recent_reply_texts=recent_reply_texts,
            )
        return choose_natural_reply_variant(
            [
                "可以，开过来现场看会更准。外观剐蹭、公里数、手续和实车检测都会影响置换价；您也可以先发外观内饰照片、行驶证信息和大概车况，我先按行情给个粗区间，到店再结合检测确认。",
                "能现场评估，旧车这块最终还是看实车。您这台如果只是外观剐蹭、没有大事故，先把照片、公里数、配置和手续情况发我，我按行情估一版；到店再看漆面、结构件和车况细节。",
                "可以带过来估。现场主要看外观内饰、漆面换件、底盘、手续和当时行情；您先发几张车身四角和内饰照片，我可以先给大概方向，最终价以实车检测为准。",
            ],
            key_text=query,
            recent_reply_texts=recent_reply_texts,
        )
    has_year = bool(re.search(r"(?:19|20)\d{2}", normalized))
    has_mileage = contains_any(normalized, ("公里", "万公里", "公里数", "万多公里"))
    has_city_or_plate = contains_any(normalized, ("牌", "上牌", "南京", "苏州", "上海", "杭州", "无锡", "常州", "合肥"))
    has_vehicle_hint = contains_any(
        normalized,
        ("旧车", "老车", "这台", "朗逸", "马自达", "cx", "途观", "奇骏", "卡罗拉", "轩逸", "雅阁", "天籁", "帕萨特", "车"),
    )
    if has_year and has_mileage and has_city_or_plate and has_vehicle_hint:
        return choose_natural_reply_variant(
            [
                "您这台旧车的基础信息够先估一版了。我这边还要再看有没有事故水泡火烧、配置版本、手续是否齐，再加几张外观内饰照片；这些齐了我先按行情给您粗区间，最终以实车检测为准。",
                "可以，年份、公里数和上牌地这些关键信息已经有了。接下来您再补一下配置、有没有事故水泡火烧、外观内饰照片和手续情况，我先给您做个置换区间，到店再核准价。",
                "这个信息已经比空问好判断多了。先按您给的年份、公里数和牌照地做初筛，再补车况照片、配置和事故/水泡/火烧情况，我就能先估一个大概区间；最终还是看实车和行情。",
            ],
            key_text=query or "trade_in_collect",
            recent_reply_texts=recent_reply_texts,
        )
    return choose_natural_reply_variant(
        [
            "可以估，您先把车型年份、上牌城市、公里数、排量配置、有没有事故水泡火烧、外观内饰大概成色发我。有行驶证照片和车身四角照片更好，我帮您做个大概区间；最终价还是要看实车检测和当时行情。",
            "置换可以先做个大概区间。您发我车型、哪年上牌、公里数、在哪个城市、有没有事故水泡火烧，再加几张外观内饰照片，我按行情粗估一下。",
            "可以先估一版，您这个思路没问题。您把车龄、公里数、配置、上牌地、车况大概情况发我，我核实行情给您看区间；最后还是要结合实车检测。",
        ],
        key_text=query or "trade_in_collect",
        recent_reply_texts=recent_reply_texts,
    )


def build_synthesis_config_for_route(config: dict[str, Any], route: dict[str, Any]) -> dict[str, Any]:
    next_config = dict(config)
    settings = dict(next_config.get("llm_reply_synthesis", {}) or {})
    realtime = dict(next_config.get("realtime_reply", {}) or {})
    max_tokens = int(route.get("max_completion_tokens") or realtime.get("max_completion_tokens") or DEFAULT_MAX_COMPLETION_TOKENS)
    max_history_messages = int(realtime.get("max_history_messages", 6) or 6)
    history_char_budget = int(realtime.get("history_char_budget", 1200) or 1200)
    max_rag_hits = int(realtime.get("max_rag_hits", 2) or 2)
    max_rag_text_chars = int(realtime.get("max_rag_text_chars", 180) or 180)
    max_catalog_candidates = int(realtime.get("max_catalog_candidates", 3) or 3)
    settings["timeout_seconds"] = int(realtime.get("foreground_llm_timeout_seconds", 8) or 8)
    settings["retry_count"] = int(realtime.get("foreground_llm_retry_count", 0) or 0)
    settings["max_tokens"] = max_tokens
    settings["max_history_messages"] = max_history_messages
    settings["history_char_budget"] = history_char_budget
    settings["max_rag_hits"] = max_rag_hits
    settings["max_rag_text_chars"] = max_rag_text_chars
    settings["max_catalog_candidates"] = max_catalog_candidates
    profiles = settings.get("profiles") if isinstance(settings.get("profiles"), dict) else {}
    capped_profiles: dict[str, Any] = {}
    for name, profile in profiles.items():
        if not isinstance(profile, dict):
            capped_profiles[name] = profile
            continue
        capped = dict(profile)
        capped["max_history_messages"] = min(int(capped.get("max_history_messages") or max_history_messages), max_history_messages)
        capped["history_char_budget"] = min(int(capped.get("history_char_budget") or history_char_budget), history_char_budget)
        capped["max_rag_hits"] = min(int(capped.get("max_rag_hits") or max_rag_hits), max_rag_hits)
        capped["max_rag_text_chars"] = min(int(capped.get("max_rag_text_chars") or max_rag_text_chars), max_rag_text_chars)
        capped["max_catalog_candidates"] = min(int(capped.get("max_catalog_candidates") or max_catalog_candidates), max_catalog_candidates)
        capped["max_tokens"] = min(int(capped.get("max_tokens") or max_tokens), max_tokens)
        capped_profiles[name] = capped
    if capped_profiles:
        settings["profiles"] = capped_profiles
    settings["foreground_realtime"] = True
    next_config["llm_reply_synthesis"] = settings
    return next_config


def initial_token_budget(route: dict[str, Any]) -> dict[str, Any]:
    return {
        "max_prompt_tokens": int(route.get("max_prompt_tokens") or DEFAULT_MAX_PROMPT_TOKENS),
        "max_completion_tokens": int(route.get("max_completion_tokens") or DEFAULT_MAX_COMPLETION_TOKENS),
        "actual_prompt_tokens": 0,
        "actual_completion_tokens": 0,
        "actual_total_tokens": 0,
        "saved_reason": "" if route.get("foreground_llm_allowed") else str(route.get("reason") or "foreground_llm_not_allowed"),
    }


def update_token_budget_from_synthesis(budget: dict[str, Any], llm_synthesis: dict[str, Any]) -> dict[str, Any]:
    next_budget = dict(budget)
    usage = llm_synthesis.get("llm_usage") if isinstance(llm_synthesis.get("llm_usage"), dict) else {}
    prompt_estimate = llm_synthesis.get("prompt_estimate") if isinstance(llm_synthesis.get("prompt_estimate"), dict) else {}
    prompt_tokens = int(usage.get("prompt_tokens") or prompt_estimate.get("rough_prompt_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or 0)
    total_tokens = int(usage.get("total_tokens") or (prompt_tokens + completion_tokens))
    next_budget.update(
        {
            "actual_prompt_tokens": prompt_tokens,
            "actual_completion_tokens": completion_tokens,
            "actual_total_tokens": total_tokens,
            "token_budget_exceeded": bool(total_tokens and total_tokens > int(next_budget.get("max_prompt_tokens", DEFAULT_MAX_PROMPT_TOKENS)) + int(next_budget.get("max_completion_tokens", DEFAULT_MAX_COMPLETION_TOKENS))),
        }
    )
    if total_tokens:
        next_budget["saved_reason"] = ""
    return next_budget


def is_followup_vehicle_source_request(text: str, recent_reply_texts: list[str]) -> bool:
    if not text or not recent_reply_texts:
        return False
    if is_service_guidance_question(text):
        return False
    recent_text = normalize_text(" ".join(recent_reply_texts[-3:]))
    if not contains_any(recent_text, RECENT_GUIDANCE_TERMS):
        return False
    if contains_any(text, VALUE_RETENTION_TERMS):
        return False
    if contains_any(text, TRADE_IN_TERMS) and not contains_any(text, FOLLOWUP_SOURCE_TERMS + EXPLICIT_SOURCE_TERMS + ("更想看", "想看", "备选", "当备选")):
        return False
    if requires_high_risk_boundary(text) or contains_any(text, OFF_TOPIC_OR_SECURITY_TERMS):
        return False
    if contains_any(text, APPOINTMENT_TERMS):
        return False
    return contains_any(text, FOLLOWUP_SOURCE_TERMS) or bool(re.search(r"\d+(?:\.\d+)?万", text))


def is_explicit_vehicle_source_request(text: str) -> bool:
    if not text:
        return False
    if is_service_guidance_question(text):
        return False
    if contains_any(text, VALUE_RETENTION_TERMS):
        return False
    if contains_any(text, TRADE_IN_TERMS) and not contains_any(text, EXPLICIT_SOURCE_TERMS + ("推荐", "优先看", "值得看", "更想看", "想看", "备选", "当备选")):
        return False
    if requires_high_risk_boundary(text) or contains_any(text, OFF_TOPIC_OR_SECURITY_TERMS):
        return False
    if contains_any(text, ("更想看", "想看", "备选", "当备选")) and contains_any(text, CONCRETE_USED_CAR_MODEL_TERMS):
        return True
    if contains_any(text, EXPLICIT_SOURCE_TERMS):
        return True
    if is_direction_candidate_request(text):
        return True
    return "具体" in text and contains_any(text, ("推荐", "车源", "给我", "挑", "看哪", "哪台", "哪款"))


def is_direction_candidate_request(text: str) -> bool:
    normalized = normalize_text(text)
    if not normalized or "方向" not in normalized:
        return False
    if not contains_any(normalized, ("给我", "推荐", "挑", "筛", "先按", "缩到", "两三", "几个", "具体")):
        return False
    return is_used_car_query(normalized) or extract_budget_wan(normalized) > 0


def is_detailed_vehicle_need_ready(text: str) -> bool:
    normalized = normalize_text(text)
    if not normalized:
        return False
    if contains_any(normalized, VALUE_RETENTION_TERMS):
        return False
    if contains_any(normalized, TRADE_IN_TERMS) and not contains_any(normalized, ("推荐", "哪台", "哪款", "两台", "几台", "优先看")):
        return False
    if requires_high_risk_boundary(normalized) or contains_any(normalized, OFF_TOPIC_OR_SECURITY_TERMS):
        return False
    if extract_budget_wan(normalized) <= 0:
        return False
    if not is_used_car_query(normalized):
        return False
    detail_score = 0
    if contains_any(normalized, DETAILED_NEED_SOURCE_TERMS):
        detail_score += 1
    if contains_any(normalized, DETAILED_NEED_USE_TERMS):
        detail_score += 1
    if contains_any(normalized, DETAILED_NEED_PREFERENCE_TERMS):
        detail_score += 1
    return detail_score >= 2


def is_identity_probe(text: str) -> bool:
    normalized = normalize_text(text)
    return contains_any(normalized, IDENTITY_PROBE_TERMS)


def identity_guard_enabled(config: dict[str, Any]) -> bool:
    synthesis = config.get("llm_reply_synthesis") if isinstance(config.get("llm_reply_synthesis"), dict) else {}
    if "identity_guard_enabled" in synthesis:
        return synthesis.get("identity_guard_enabled") is not False
    style = config.get("reply_style_adapter") if isinstance(config.get("reply_style_adapter"), dict) else {}
    if "identity_guard_enabled" in style:
        return style.get("identity_guard_enabled") is not False
    return True


def build_identity_probe_reply(
    config: dict[str, Any],
    *,
    query: str = "",
    recent_reply_texts: list[str] | None = None,
) -> tuple[str, int]:
    if identity_guard_enabled(config):
        return choose_natural_reply_variant(
            [
                "不是AI，也不是机器人哈。内部规则这些不对外说，您别介意；咱们还是回到具体需求上，您关心哪块我按实际情况帮您确认。",
                "不是机器人哈，这类内部信息不方便外发。您要是担心回复准不准，可以直接问具体车况、报价或者手续，我按实际情况给您核。",
                "不是自动回复，也不是AI。提示词、内部规则这些肯定不能往外发；您关心哪台车、费用还是置换，我继续帮您确认。",
                "不是机器客服哈，内部规则就不展开说了。咱们直接聊车就行，车源、车况、价格这些我按能核实的给您回。",
            ],
            key_text=query or "identity_probe_guarded",
            recent_reply_texts=recent_reply_texts,
        )
    return choose_natural_reply_variant(
        [
            "是智能客服助手在协助回复，能直接确认的我会先答；涉及价格、车况、合同这些关键细节，还是会按门店实际情况核实。",
            "当前是智能客服先帮您接待，车源、需求和基础问题我可以先整理；关键承诺类信息会以门店核实结果为准。",
            "我是智能客服助手，可以先帮您查车源、梳理需求和记录重点；价格、合同、车况承诺这些还是按门店确认结果来。",
        ],
        key_text=query or "identity_probe_open",
        recent_reply_texts=recent_reply_texts,
    )


def choose_reply_variant(
    variants: list[str],
    *,
    key_text: str = "",
    recent_reply_texts: list[str] | None = None,
) -> tuple[str, int]:
    candidates = [str(item).strip() for item in variants if str(item).strip()]
    if not candidates:
        return "", 0
    recent_reply_texts = recent_reply_texts or []
    if not recent_reply_texts:
        index = stable_variant_index(key_text, len(candidates))
        return candidates[index], index
    scored: list[tuple[float, int, str]] = []
    for index, candidate in enumerate(candidates):
        max_similarity = max((reply_similarity(candidate, recent) for recent in recent_reply_texts[-5:]), default=0.0)
        scored.append((max_similarity, index, candidate))
    scored.sort(key=lambda item: (item[0], stable_variant_tiebreak(key_text, item[1])))
    _, index, candidate = scored[0]
    return candidate, index


def choose_natural_reply_variant(
    variants: list[str],
    *,
    key_text: str = "",
    recent_reply_texts: list[str] | None = None,
) -> tuple[str, int]:
    reply, index = choose_reply_variant(variants, key_text=key_text, recent_reply_texts=recent_reply_texts)
    return de_template_reply_text(reply, key_text=key_text, recent_reply_texts=recent_reply_texts), index


def de_template_reply_text(
    reply: str,
    *,
    key_text: str = "",
    recent_reply_texts: list[str] | None = None,
) -> str:
    """Reduce overused local-template phrases before a customer sees them."""
    text = str(reply or "").strip()
    if not text:
        return text
    recent_reply_texts = recent_reply_texts or []
    replacements: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("我先不乱推", ("先按您说的条件筛一下", "我按您这几个条件往下看", "先把范围收窄一点")),
        ("尽量别给您乱推荐", ("尽量把范围缩准一点", "避免范围越聊越散", "尽量筛得更贴近一点")),
        ("我先帮您记录", ("我把这点记下", "这块我记下", "信息我先留好")),
        ("我先记录", ("我把这点记下", "这块我记下", "信息我先留好")),
        ("我先帮您看", ("我帮您看", "这边帮您看", "我来帮您看")),
        ("我先帮您核", ("我帮您核", "这边帮您核", "我来核一下")),
        ("我先确认", ("我确认", "这边确认", "我来确认")),
        ("我先核实", ("我核实", "这边核实", "我来核一下")),
        ("我会重点看", ("重点看", "我主要看", "这边先核")),
        ("我会优先看", ("优先看", "我主要看", "这边先看")),
        ("我会按", ("我按", "这边按", "先按")),
        ("我会先", ("我会", "这边会", "先")),
        ("这个需求已经比较明确了", ("条件已经比较清楚了", "这个方向挺明确了", "需求这块已经不算泛了")),
        ("客户资料已记录", ("资料我收到了", "资料这边已经记下", "信息已经记下")),
        ("我会尽快为您继续处理", ("后面按这个继续跟进", "接下来按这个处理", "我这边继续往下跟")),
        ("我看到了客户资料，但还缺少", ("资料我看到了，还差", "信息收到了，还缺", "这边看到了，还需要补一下")),
        ("请补充后我再记录", ("您补一下我就接着处理", "您发我一下，我这边补齐", "补齐后我继续往下跟")),
        ("请您稍等片刻", ("您稍等一下", "您等我一下", "稍等我确认下")),
        ("请稍等我回复您", ("稍等我回复您", "等我确认后回您", "我核一下再回您")),
        ("稍等我回复您", ("等我确认后回您", "我核一下再回您", "确认后回您")),
        ("再给您准确处理意见", ("再跟您说怎么处理", "再把处理意见跟您说清楚", "再给您明确处理意见")),
        ("再给您准确说法", ("再跟您说清楚", "再给您明确说法", "再把情况讲清楚")),
        ("给您准确处理意见", ("给您明确处理意见", "把处理意见跟您说清楚", "再跟您说怎么处理")),
        ("给您准确说法", ("跟您说清楚", "给您明确说法", "再把情况讲清楚")),
        ("不能直接拍板", ("不能随口定", "不能直接定", "得按实际情况确认")),
        ("不随口答复", ("不直接乱说", "不能凭一句话定", "得看实际情况")),
        ("不随口承诺", ("不直接乱承诺", "不能凭一句话承诺", "得按实际情况确认")),
        ("确认后第一时间回复您", ("弄清楚后回您", "确认好就回您", "核完再回您")),
        ("确认后马上回您", ("确认好就回您", "核完再回您", "弄清楚后回您")),
        ("确认清楚后马上给您准话", ("核清楚再跟您说准", "确认好再给您明确答复", "弄清楚后再回您")),
        ("确认清楚后马上回复您", ("核清楚再回您", "确认好再给您明确答复", "弄清楚后再回您")),
        ("核实清楚后第一时间回复您", ("核清楚后回您", "弄清楚后再回您", "确认好再给您明确答复")),
        ("核清楚后给您准话", ("核清楚再跟您说准", "确认好再给您明确答复", "弄清楚后再回您")),
        ("再给您准话", ("再跟您说准", "再给您明确答复", "再把结果告诉您")),
        ("给您准话", ("跟您说准", "给您明确答复", "把结果告诉您")),
    )
    for old, variants in replacements:
        if old not in text:
            continue
        replacement, _ = choose_reply_variant(
            list(variants),
            key_text=f"{key_text}|{old}",
            recent_reply_texts=recent_reply_texts,
        )
        text = text.replace(old, replacement, 1)
    text = text.replace("再再", "再")
    return text


def stable_variant_index(key_text: str, count: int) -> int:
    if count <= 1:
        return 0
    digest = hashlib.sha256(str(key_text or "").encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % count


def stable_variant_tiebreak(key_text: str, index: int) -> int:
    digest = hashlib.sha256(f"{key_text}|{index}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def reply_similarity(left: str, right: str) -> float:
    left_tokens = char_bigrams(normalize_text(left))
    right_tokens = char_bigrams(normalize_text(right))
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens))


def char_bigrams(text: str) -> set[str]:
    if len(text) <= 1:
        return {text} if text else set()
    return {text[index : index + 2] for index in range(len(text) - 1)}


def normalize_text(text: str) -> str:
    return "".join(str(text or "").split()).lower()


def current_customer_text(text: str) -> str:
    raw = str(text or "")
    marker = "当前客户问题："
    if marker in raw:
        return raw.rsplit(marker, 1)[-1].strip()
    return raw.strip()


def has_realtime_context_prefix(text: str) -> bool:
    raw = str(text or "")
    return "近期客户需求：" in raw and "当前客户问题：" in raw


def realtime_contextual_customer_text(text: str, *, recent_reply_texts: list[str] | None = None) -> str:
    """Return current text plus compact history only when the current turn asks for it.

    File Transfer Assistant is often used for chaotic self-tests, so the router
    must not blindly let old messages steer every new turn. The history prefix is
    only trusted for follow-up recommendation/comparison scenes where customers
    naturally say things like "按前面说的挑两台".
    """
    raw = str(text or "").strip()
    current = current_customer_text(raw)
    if not raw or not current or not has_realtime_context_prefix(raw):
        return current
    normalized_current = normalize_text(current)
    if (
        requires_high_risk_boundary(normalized_current)
        or contains_any(normalized_current, OFF_TOPIC_OR_SECURITY_TERMS)
        or is_identity_probe(normalized_current)
        or is_actual_customer_data_message(normalized_current)
    ):
        return current
    context_candidate_markers = (
        FOLLOWUP_TERMS
        + FOLLOWUP_SOURCE_TERMS
        + EXPLICIT_SOURCE_TERMS
        + VEHICLE_COMPARE_TERMS
        + (
            "别再问",
            "不用再问",
            "按这个",
            "就按这个",
            "按前面",
            "前面说的",
            "刚说的",
            "这俩",
            "它俩",
            "哪个更适合",
            "哪台更适合",
            "好停",
            "好开",
        )
    )
    if contains_any(normalized_current, context_candidate_markers):
        return raw
    if contains_any(normalized_current, RECOMMEND_TERMS) and has_business_signal(normalize_text(raw)):
        return raw
    if recent_reply_texts and contains_any(normalized_current, ("具体", "怎么选", "哪个", "哪台", "合适")):
        return raw
    return current


def extract_visit_time_label(text: str) -> str:
    raw = str(text or "")
    if not raw:
        return ""
    normalized = normalize_text(raw)
    day = ""
    for marker in ("周一", "周二", "周三", "周四", "周五", "周六", "周日", "今天", "明天", "后天"):
        if normalize_text(marker) in normalized:
            day = marker
            break
    period = ""
    for marker in ("上午", "中午", "下午", "晚上"):
        if marker in raw:
            period = marker
            break
    clock = ""
    match = re.search(r"([一二三四五六七八九十两\d]{1,3}点(?:半)?)", raw)
    if match:
        clock = match.group(1)
    label = f"{day}{period}{clock}".strip()
    return label


def contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term.lower() in text for term in terms if term)


def is_short_greeting(text: str) -> bool:
    return len(text) <= 10 and contains_any(text, GREETING_TERMS)


def has_business_signal(text: str) -> bool:
    if contains_any(text, RECOMMEND_TERMS + APPOINTMENT_TERMS + FOLLOWUP_SOURCE_TERMS + EXPLICIT_SOURCE_TERMS + VALUE_RETENTION_TERMS + TRADE_IN_TERMS + HIGH_RISK_TERMS):
        return True
    if re.search(r"\d+(?:\.\d+)?万", text):
        return True
    return contains_any(text, ("车", "预算", "通勤", "家用", "接娃", "贷款", "置换", "到店", "看车"))


def can_override_current_reply(text: str) -> bool:
    normalized = normalize_text(text)
    if not normalized:
        return True
    generic_markers = (
        "收到我先记录",
        "我先记录一下",
        "涉及车况价格金融或到店安排",
        "暂时没匹配到",
        "稍后确认",
        "需要负责人确认",
        "请示负责人",
        "问清楚后",
        "内部确认",
        "我把情况记下",
    )
    return any(marker in normalized for marker in generic_markers)


def current_turn_preempts_vehicle_candidate_reply(text: str, recent_reply_texts: list[str]) -> bool:
    """Keep an explicit current-turn service question from being hijacked by older needs."""
    clean = normalize_text(text)
    if not clean:
        return False
    if is_vehicle_compare_question(clean, recent_reply_texts):
        return True
    if any(
        checker(clean)
        for checker in (
            is_fee_transparency_question,
            is_finance_guidance_question,
            is_testdrive_material_question,
            is_visit_report_prep_question,
            is_visit_timing_question,
            is_no_deposit_visit_question,
            is_price_negotiation_question,
            is_warranty_guidance_question,
        )
    ):
        return True
    if (
        is_followup_vehicle_source_request(clean, recent_reply_texts)
        or is_explicit_vehicle_source_request(clean)
        or is_detailed_vehicle_need_ready(clean)
    ):
        return False
    return any(
        checker(clean)
        for checker in (
            is_vehicle_type_guidance_question,
            is_maintenance_cost_question,
            is_inspection_guidance_question,
            is_cargo_space_guidance_question,
            is_feature_guidance_question,
            is_comfort_highway_question,
        )
    )


def is_appointment_context_query(text: str) -> bool:
    clean = normalize_text(text)
    if not clean:
        return False
    if contains_any(clean, ("周末经常", "平时周末", "每周末", "周末带", "周末用")):
        return False
    action_terms = ("看车", "能看", "去看", "到店", "试驾", "试车", "安排", "过去", "预约", "车还在", "来店")
    time_terms = ("周末", "周六", "周日", "上午", "下午", "今天", "明天", "几点", "时间")
    return contains_any(clean, action_terms) and (
        contains_any(clean, time_terms)
        or contains_any(clean, ("别白跑", "白跑", "排期", "一次看", "对比"))
    )


def rank_product_candidates(
    query: str,
    evidence_pack: dict[str, Any],
    *,
    allow_catalog_fallback: bool = False,
    allow_broad_fallback: bool = False,
) -> list[dict[str, Any]]:
    products = (evidence_pack.get("evidence", {}) or {}).get("products", []) or []
    if allow_catalog_fallback and not products:
        products = load_catalog_product_candidates()
    budget = extract_budget_wan(query)
    strict_budget_cap = has_strict_budget_cap(query)
    used_car_query = is_used_car_query(query)
    scored: list[tuple[float, dict[str, Any]]] = []
    score_product_items(
        query=query,
        items=products,
        budget=budget,
        strict_budget_cap=strict_budget_cap,
        used_car_query=used_car_query,
        scored=scored,
        allow_broad_fallback=allow_broad_fallback,
    )
    if allow_catalog_fallback and not scored:
        # Evidence retrieval can return a semantically relevant but over-budget
        # vehicle. In that case, fall back to the authoritative catalog instead
        # of asking the customer to repeat requirements that were already clear.
        evidence_ids = {str(item.get("id") or "") for item in products if isinstance(item, dict)}
        catalog_products = [
            item
            for item in load_catalog_product_candidates()
            if str(item.get("id") or "") not in evidence_ids
        ]
        score_product_items(
            query=query,
            items=catalog_products,
            budget=budget,
            strict_budget_cap=strict_budget_cap,
            used_car_query=used_car_query,
            scored=scored,
            allow_broad_fallback=True,
        )
    scored.sort(key=lambda pair: (pair[0], float(pair[1].get("price") or 0)), reverse=True)
    return [item for _, item in scored]


def score_product_items(
    *,
    query: str,
    items: list[dict[str, Any]],
    budget: float,
    strict_budget_cap: bool,
    used_car_query: bool,
    scored: list[tuple[float, dict[str, Any]]],
    allow_broad_fallback: bool,
) -> None:
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            price = float(item.get("price"))
        except (TypeError, ValueError):
            price = 0.0
        # Used-car conversations commonly tolerate a small upward stretch when
        # the match is stronger, especially around "8万/10万预算" shorthand.
        if budget and price and strict_budget_cap and price > budget:
            continue
        if budget and price and not strict_budget_cap and price > max(budget * 1.15, budget + 0.8):
            continue
        searchable = product_search_text(item)
        if used_car_query and not is_used_car_product_search_text(searchable):
            continue
        score = product_query_score(query, searchable)
        if budget and price:
            score += max(0.0, 4.0 - abs(budget - price) / max(budget, 1.0) * 4.0)
            score += budget_position_score(query, price=price, budget=budget, strict_budget_cap=strict_budget_cap)
        if price and price <= 10:
            score += 0.8
        score += persona_fit_score(query, searchable)
        if int(item.get("stock") or 0) > 0:
            score += 0.5
        if score > 0:
            scored.append((score, item))
        elif allow_broad_fallback:
            fallback_score = broad_product_fallback_score(item, budget=budget, strict_budget_cap=strict_budget_cap)
            if fallback_score > 0:
                scored.append((fallback_score, item))


def is_used_car_query(query: str) -> bool:
    normalized = normalize_text(query)
    if contains_any(normalized, USED_CAR_EXPLICIT_QUERY_TERMS):
        return True
    has_budget_signal = extract_budget_wan(normalized) > 0
    return has_budget_signal and contains_any(normalized, USED_CAR_SCENE_QUERY_TERMS)


def is_used_car_product_search_text(searchable: str) -> bool:
    return contains_any(normalize_text(searchable), USED_CAR_PRODUCT_TERMS)


def product_query_score(query: str, searchable: str) -> float:
    query_text = normalize_text(query)
    searchable_text = normalize_text(searchable)
    score = 0.0
    for token, weight in (
        ("通勤", 2.0),
        ("代步", 2.0),
        ("省油", 2.0),
        ("自动", 1.2),
        ("suv", 2.2),
        ("空间", 1.4),
        ("孩子", 0.8),
        ("后排", 1.0),
        ("家用", 1.5),
        ("上下班", 1.8),
        ("女士", 0.6),
        ("一手", 0.6),
        ("高速", 1.0),
        ("舒服", 1.0),
        ("舒适", 1.0),
        ("父母", 0.8),
        ("老人", 0.8),
        ("露营", 1.5),
        ("钓鱼", 1.2),
        ("后备箱", 1.4),
        ("后备厢", 1.4),
        ("摄影", 1.0),
        ("工作室", 1.0),
        ("活动策划", 1.0),
        ("接客户", 1.0),
        ("甲方客户", 1.0),
        ("器材", 1.3),
        ("灯架", 1.3),
        ("展架", 1.3),
        ("物料", 1.3),
        ("音响架", 1.3),
        ("折叠桌", 1.1),
        ("相机箱", 1.3),
        ("底盘高", 1.4),
        ("通过性", 1.4),
    ):
        if normalize_text(token) in query_text and normalize_text(token) in searchable_text:
            score += weight
    if "suv" in query_text and "suv" not in searchable_text:
        score -= 3.0
    if contains_any(query_text, ("露营", "钓鱼", "郊外", "后备箱", "底盘高", "通过性")):
        if contains_any(searchable_text, ("suv", "四驱", "空间", "后备箱", "底盘", "通过性", "2.0t", "2.5l")):
            score += 2.2
        if contains_any(searchable_text, ("紧凑型轿车", "小型轿车", "两厢", "轿车")) and "suv" in query_text:
            score -= 2.2
    if contains_any(query_text, ("摄影", "工作室", "活动策划", "接客户", "甲方客户", "客户接待", "商务接待", "器材", "灯架", "展架", "物料", "音响架", "折叠桌", "相机箱", "后备厢", "后备箱")):
        if contains_any(searchable_text, ("suv", "mpv", "空间", "后备", "电动尾门", "七座", "商务", "客户", "大空间")):
            score += 2.4
        if contains_any(searchable_text, ("小型轿车", "紧凑型轿车", "新能源轿车", "轿车", "两厢", "小巧", "练车")) and not contains_any(searchable_text, ("suv", "mpv")):
            score -= 2.4
    if contains_any(query_text, ("父母", "老人", "高速", "舒服", "舒适", "回老家")) and contains_any(
        searchable_text,
        ("豪华轿车", "中大型", "mpv", "suv", "空间", "舒适", "保养记录", "一手", "混动"),
    ):
        score += 1.8
    if contains_any(query_text, ("二胎", "全家", "老人孩子", "孩子", "老人", "回老家", "后排", "空间")):
        if contains_any(searchable_text, ("suv", "中型", "中大型", "空间", "后排", "后备箱", "2.0t", "2.5l", "凯美瑞", "奇骏", "哈弗h6", "皇冠")):
            score += 2.4
        if contains_any(searchable_text, ("小型轿车", "两厢", "小巧", "练车")):
            score -= 1.8
    if contains_any(query_text, ("后期小毛病", "小毛病", "省心", "少操心")) and contains_any(
        searchable_text,
        ("保养记录", "一手", "原版原漆", "日系", "丰田", "本田", "大众", "检测报告"),
    ):
        score += 1.2
    if contains_any(query_text, ("老婆开", "媳妇开", "给老婆", "我老婆", "老婆换", "老婆用", "老婆接送", "女士开", "女司机")) and contains_any(
        searchable_text,
        ("女士", "小巧", "好停车", "倒车", "影像", "雷达", "360"),
    ):
        score += 2.0
    if contains_any(query_text, ("停车", "倒车", "影像", "雷达")) and contains_any(
        searchable_text,
        ("倒车", "影像", "雷达", "360", "小巧", "好停车"),
    ):
        score += 2.6
    if contains_any(query_text, ("停车不太熟", "停车不熟", "倒车不熟")) and "suv" in searchable_text:
        score -= 1.2
    return score


def persona_fit_score(query: str, searchable: str) -> float:
    """Prefer candidates that fit the buyer's lived scenario, not just price."""
    query_text = normalize_text(query)
    searchable_text = normalize_text(searchable)
    score = 0.0
    new_driver_or_parking = contains_any(
        query_text,
        ("老婆开", "媳妇开", "给老婆", "我老婆", "老婆换", "老婆用", "老婆接送", "女士开", "女司机", "新手", "停车", "好停", "好开", "省心", "别太大", "不太大"),
    )
    explicit_suv_need = contains_any(query_text, ("想要suv", "要suv", "只看suv", "suv优先", "大空间suv"))
    if new_driver_or_parking:
        if contains_any(searchable_text, ("小型轿车", "紧凑型轿车", "两厢", "小巧", "好停车", "女士一手", "新手", "练车")):
            score += 1.8
        if contains_any(searchable_text, ("倒车影像", "倒车", "雷达", "360")):
            score += 0.8
        if contains_any(searchable_text, ("suv", "越野", "四驱")) and not explicit_suv_need:
            budget = extract_budget_wan(query_text)
            spouse_context = contains_any(query_text, ("老婆", "媳妇", "爱人", "女士", "女司机"))
            if contains_any(query_text, ("停车", "好停", "别太大", "不太大")):
                score -= 3.2
            elif spouse_context and budget and budget <= 9:
                score -= 5.0
            else:
                score -= 2.0
    if contains_any(query_text, ("省心", "少操心", "后期", "好养")):
        if contains_any(searchable_text, ("省油", "保值", "一手", "公里数少", "保养记录", "车况透明", "好开")):
            score += 1.0
        if contains_any(searchable_text, ("维修成本", "后期成本", "好养")):
            score += 0.8
    business_equipment_need = contains_any(
        query_text,
        (
            "摄影",
            "工作室",
            "外拍",
            "接客户",
            "客户接待",
            "商务接待",
            "公司用",
            "器材",
            "灯架",
            "相机箱",
            "背景架",
            "后备厢",
            "后备箱",
            "拉东西",
            "装东西",
        ),
    )
    if business_equipment_need:
        if contains_any(searchable_text, ("suv", "mpv", "空间大", "后备", "电动尾门", "七座", "商务", "客户", "大空间")):
            score += 2.2
        if contains_any(searchable_text, ("小型轿车", "紧凑型轿车", "新能源轿车", "轿车", "两厢", "小巧", "练车")) and not contains_any(searchable_text, ("suv", "mpv")):
            score -= 2.2
    return score


def budget_position_score(query: str, *, price: float, budget: float, strict_budget_cap: bool) -> float:
    """Avoid recommending much-cheaper cars just because they are below a loose cap."""
    if not price or not budget:
        return 0.0
    query_text = normalize_text(query)
    budget_limited = contains_any(query_text, ("预算有限", "越便宜越好", "便宜点", "练手", "代步就行", "几万"))
    ratio = price / max(budget, 1.0)
    if budget_limited:
        return 0.0
    if strict_budget_cap:
        if ratio < 0.45:
            return -1.2
        if 0.65 <= ratio <= 1.0:
            return 0.8
        if 0.5 <= ratio < 0.65:
            return 0.2
    else:
        if ratio < 0.45:
            return -0.8
        if 0.7 <= ratio <= 1.05:
            return 0.5
    return 0.0


def product_search_text(item: dict[str, Any]) -> str:
    parts = [
        str(item.get("name") or ""),
        str(item.get("category") or ""),
        str(item.get("spec") or item.get("specs") or ""),
        str(item.get("shipping") or item.get("shipping_policy") or ""),
        str(item.get("warranty") or ""),
        str(item.get("recommendation") or ""),
        " ".join(str(alias) for alias in item.get("aliases", []) or []),
        " ".join(str(alias) for alias in item.get("matched_aliases", []) or []),
    ]
    return " ".join(parts)


def load_catalog_product_candidates() -> list[dict[str, Any]]:
    try:
        items = KnowledgeRuntime().list_items("products")
    except Exception:
        return []
    products: list[dict[str, Any]] = []
    for item in items:
        data = item.get("data", {}) if isinstance(item.get("data"), dict) else {}
        runtime = item.get("runtime", {}) if isinstance(item.get("runtime"), dict) else {}
        if item.get("status") == "archived" or runtime.get("allow_auto_reply") is False:
            continue
        products.append(
            {
                "id": item.get("id"),
                "name": data.get("name"),
                "category": data.get("category"),
                "price": data.get("price"),
                "stock": data.get("inventory"),
                "spec": data.get("specs"),
                "shipping": data.get("shipping_policy"),
                "warranty": data.get("warranty_policy"),
                "recommendation": (data.get("reply_templates") or {}).get("recommendation") if isinstance(data.get("reply_templates"), dict) else "",
                "aliases": data.get("aliases", []) or [],
            }
        )
    return products


def broad_product_fallback_score(item: dict[str, Any], *, budget: float = 0.0, strict_budget_cap: bool = False) -> float:
    try:
        price = float(item.get("price") or 0)
    except (TypeError, ValueError):
        price = 0.0
    stock = int(item.get("stock") or 0)
    if stock <= 0:
        return 0.0
    if budget and price:
        if strict_budget_cap and price > budget:
            return 0.0
        if price > max(budget * 1.2, budget + 1.0):
            return 0.0
        return 2.0 + max(0.0, 3.0 - abs(budget - price) / max(budget, 1.0) * 3.0)
    if 5 <= price <= 12:
        return 2.0 + (12 - price) / 12
    if 12 < price <= 16:
        return 1.2
    return 0.5 if price else 0.0


def extract_budget_wan(text: str) -> float:
    compact = normalize_text(text)
    match = re.search(r"(\d+(?:\.\d+)?)\s*万", compact)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return 0.0
    chinese_ranges = {
        "三四万": 3.5,
        "四五万": 4.5,
        "五六万": 5.5,
        "六七万": 6.5,
        "七八万": 7.5,
        "八九万": 8.5,
        "十来万": 10.0,
        "十万出头": 10.5,
        "十万": 10.0,
        "十一二万": 11.5,
        "十二三万": 12.5,
        "十三四万": 13.5,
        "十四五万": 14.5,
        "十五六万": 15.5,
    }
    for marker, value in sorted(chinese_ranges.items(), key=lambda item: len(item[0]), reverse=True):
        if marker in compact:
            return value
    if "十来万" in compact or "十万" in compact:
        return 10.0
    if "八万" in compact:
        return 8.0
    if "七万" in compact:
        return 7.0
    if "六万" in compact:
        return 6.0
    if "五万" in compact:
        return 5.0
    if "四万" in compact:
        return 4.0
    if "三万" in compact:
        return 3.0
    return 0.0


def has_strict_budget_cap(text: str) -> bool:
    normalized = normalize_text(text)
    return extract_budget_wan(normalized) > 0 and contains_any(normalized, STRICT_BUDGET_CAP_TERMS)


def build_need_summary(query: str) -> str:
    normalized = normalize_text(query)
    parts: list[str] = []
    budget = extract_budget_wan(normalized)
    if budget:
        suffix = "以内" if has_strict_budget_cap(normalized) else "左右"
        parts.append(f"{budget:g}万{suffix}")
    if contains_any(normalized, ("老婆开", "媳妇开", "给老婆", "我老婆", "老婆换", "老婆用", "老婆接送")):
        parts.append("主要给您爱人开")
    elif contains_any(normalized, ("女士开", "女司机")):
        parts.append("女士开")
    if contains_any(normalized, ("停车不太熟", "停车不熟", "倒车不熟", "停车")):
        parts.append("停车要好上手")
    if "自动挡" in normalized:
        parts.append("自动挡")
    if contains_any(normalized, ("倒车影像", "影像", "雷达", "360")):
        parts.append("倒车/影像配置优先")
    if contains_any(normalized, ("摄影", "工作室", "活动策划", "外拍", "接客户", "甲方客户", "客户接待", "商务接待", "公司用")):
        parts.append("工作室用车/偶尔接客户")
    if contains_any(normalized, ("器材", "灯架", "展架", "物料", "音响架", "折叠桌", "相机箱", "背景架", "后备厢", "后备箱", "拉东西", "装东西")):
        parts.append("后备厢和装载实用")
    if contains_any(normalized, ("suv", "mpv", "七座")) and not any("SUV" in part or "MPV" in part for part in parts):
        if "mpv" in normalized:
            parts.append("MPV方向")
        elif "suv" in normalized:
            parts.append("SUV方向")
    if contains_any(normalized, ("通勤", "代步", "接娃", "买菜", "家用")) and not any("家用" in part for part in parts):
        parts.append("日常家用代步")
    return "、".join(parts)


def build_next_info_prompt(query: str, *, recent_reply_texts: list[str] | None = None) -> str:
    normalized = normalize_text(query)
    needs_finance = not contains_any(normalized, ("贷款", "按揭", "全款", "首付", "月供", "置换", "旧车"))
    needs_visit = not contains_any(normalized, ("南京", "苏州", "到店", "看车", "试驾", "周末", "周六", "周日", "今天", "明天"))
    prompts: list[str] = []
    if needs_finance:
        prompts.append("如果有贷款或置换，也可以顺手告诉我")
    if needs_visit:
        prompts.append("方便的话再说下看车城市或大概到店时间")
    if not prompts:
        return "我按这个方向继续核现车和车况。"
    if needs_finance and needs_visit:
        reply, _ = choose_reply_variant(
            [
                "贷款/置换情况、看车城市或大概到店时间，您方便时一起补一下，我再把优先级排细一点。",
                "您把贷款/置换情况、看车城市或大概到店时间发我，我好把顺序排清楚。",
                "这两点方便的话补一下：贷款/置换、看车城市或到店时间，我再往下细筛。",
            ],
            key_text=f"{query}|next-info-both",
            recent_reply_texts=recent_reply_texts,
        )
        return reply
    if needs_finance:
        reply, _ = choose_reply_variant(
            [
                "如果有贷款或置换，也可以顺手告诉我，我再把优先级排细一点。",
                "贷款/置换这块您方便时补一下，我好按总成本继续筛。",
                "全款、贷款或置换情况您说一下，我再帮您把范围收窄。",
            ],
            key_text=f"{query}|next-info-finance",
            recent_reply_texts=recent_reply_texts,
        )
        return reply
    reply, _ = choose_reply_variant(
        [
            "方便的话再说下看车城市或大概到店时间，我再把优先级排细一点。",
            "看车城市或大概到店时间您后面补一下，我好核现车和排期。",
            "如果准备到店，您说下城市和大概时间，我再按现车情况往下排。",
        ],
        key_text=f"{query}|next-info-visit",
        recent_reply_texts=recent_reply_texts,
    )
    return reply


def build_recommendation_reply(
    query: str,
    products: list[dict[str, Any]],
    *,
    recent_reply_texts: list[str] | None = None,
) -> tuple[str, int]:
    if not products:
        return "", 0
    segments = []
    for product in products:
        name = str(product.get("name") or "").strip()
        price = product.get("price")
        spec = brief_spec(str(product.get("spec") or product.get("specs") or ""))
        if not name:
            continue
        price_text = f"{price:g}万" if isinstance(price, (int, float)) else (f"{price}万" if price else "")
        detail = "，".join(part for part in (price_text, spec) if part)
        segments.append(f"{name}（{detail}）" if detail else name)
    if not segments:
        return "", 0
    if len(segments) == 1:
        product_text = segments[0]
        product_ref = "这台"
        product_lead = "如果先放一台更贴近的"
    else:
        product_text = "和".join(segments[:2])
        product_ref = "这两台"
        product_lead = "如果先缩到两台"
    summary = build_need_summary(query)
    followup = build_next_info_prompt(query, recent_reply_texts=recent_reply_texts)
    if summary:
        variants = [
            f"按您说的{summary}，可以先看{product_text}。重点看车况记录、公里数和实际好不好上手，具体还是以检测报告为准。{followup}",
            f"这个需求已经比较明确了：{summary}。先把{product_text}放前面看，方向是好开、停车辅助友好、车况透明，后面再结合实车检测细筛。{followup}",
            f"{product_lead}，先看{product_text}。{product_ref}更贴近您刚说的{summary}，下一步主要核车况、配置和到店安排。{followup}",
            f"从{summary}这个条件看，{product_text}可以先排在前面。别只看价格，车况记录、公里数和辅助配置要一起核，{followup}",
        ]
    else:
        variants = [
            f"您这个预算如果主要上下班通勤，可以先看{product_text}。这类车日常代步比较好上手，后续车况细节还是以检测报告为准。{followup}",
            f"如果先缩到两台，{product_text}可以放前面看。一个重点看省心和后期成本，一个重点看车况透明度；具体哪台更合适，还要再结合贷款或置换情况。",
            f"按您现在这个方向，我建议先从{product_text}里挑。别只看年份，先看公里数、车况记录和检测报告；后面我再帮您把优先级排清楚。",
            f"先给您缩小范围的话，{product_text}更值得优先看。后面主要比车况、公里数、检测报告和实际到店体验。",
        ]
    return choose_natural_reply_variant(variants, key_text=query + product_text, recent_reply_texts=recent_reply_texts)


def brief_spec(spec: str) -> str:
    clean = " ".join(str(spec or "").split())
    if not clean:
        return ""
    parts = re.split(r"[，,。；;]", clean)
    useful = [part.strip() for part in parts if part.strip()]
    return "，".join(useful[:3])[:80]
