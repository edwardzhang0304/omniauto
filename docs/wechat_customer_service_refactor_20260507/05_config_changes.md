# 配置变更清单

## 一、意图识别超时（P0）

**文件**：`apps/wechat_ai_customer_service/configs/jiangsu_chejin_xucong_live.example.json`

```json
{
  "intent_router": {
    "llm": {
      "enabled": true,
      "timeout_seconds": 2,
      "max_tokens": 256,
      "model": "deepseek-v4-flash"
    },
    "cache_seconds": 60
  }
}
```

**注意**：如果该租户使用其他配置文件（如 `default.example.json` 或自定义文件），需同步修改。

---

## 二、模型路由策略（P0）

**文件**：所有租户配置文件

```json
{
  "llm_reply_synthesis": {
    "model_routing": {
      "enabled": true,
      "default_tier": "flash",
      "flash_model": "deepseek-v4-flash",
      "pro_model": "deepseek-v4-pro",
      "pro_intent_tags": ["payment", "invoice", "after_sales", "handoff", "customer_data"],
      "pro_safety_reasons": [
        "matched_faq_requires_handoff",
        "invoice_amount_entity",
        "contract_risk",
        "payment_boundary",
        "price_approval_required"
      ],
      "pro_when_must_handoff": true,
      "pro_when_rag_only_authority": false
    },
    "cost_controls": {
      "enabled": true,
      "skip_llm_when_deterministic_reply": false,
      "safe_deterministic_rule_names": []
    }
  }
}
```

**关键变更**：
- `pro_when_rag_only_authority`：从 `true` 改为 `false`
- `skip_llm_when_deterministic_reply`：保持 `false`（因用户要求不跳过 LLM 合成）

---

## 三、后台 Worker 配置（P1）

**新增配置段**（可放入各租户配置或全局默认配置）：

```json
{
  "background_worker": {
    "enabled": true,
    "queue": "customer_service",
    "poll_interval_seconds": 5,
    "max_concurrent_jobs": 3,
    "job_lock_seconds": 600,
    "auto_start": true
  }
}
```

---

## 四、拟人化规则（已完成）

**文件**：`apps/wechat_ai_customer_service/configs/platform_safety_rules.example.json`

**规则 ID**：`natural_reply_style`

**当前状态**：已强化，要求拟人化、避免机械化。

**同步要求**：如果租户使用自定义 safety rules 文件（非 example），需手动将该规则同步到其配置中。

---

## 五、后台任务开关（P1）

**新增配置段**：

```json
{
  "background_tasks": {
    "experience_interpretation": true,
    "rag_quality_audit": true,
    "knowledge_compile": true,
    "conversation_summary": false,
    "customer_data_sync": true,
    "raw_message_archive": true,
    "diagnostics_deep_check": false
  }
}
```

**说明**：
- `conversation_summary` 和 `diagnostics_deep_check` 默认关闭，因耗时长且非必需
- 其他任务默认开启
