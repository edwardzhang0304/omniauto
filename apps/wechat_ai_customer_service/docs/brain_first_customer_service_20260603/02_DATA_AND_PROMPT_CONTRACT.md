# Brain First 数据与 Prompt 合同

## 客户可见回复所有权硬基线

- 所有客户可见回复必须由 `customer_service_brain` 发出：只能是首个有效 BrainPlan、Brain repair 后的 BrainPlan，或 Brain 自己生成的硬边界/拒绝/转人工类说明。
- Guard、质量门、语义审稿、RAG、实时路由、本地模板、旧合成器、最终润色和任何兜底模块都不能生成、替换、拼接客户可见回复；它们只能提供证据、风险、审稿意见、返修指令或轻量表达校验。
- Brain 不可用、超时、不可采纳或返修失败时，不允许本地 safe fallback 代替 Brain 发客户可见话术；必须阻断发送、记录审计，并触发内部人工/告警接口。
- 后续所有客服相关开发文档必须引用 [customer_visible_reply_ownership_baseline.md](../customer_visible_reply_ownership_baseline.md)。

## 1. 合同目标

本合同定义 LLM 客服大脑的输入、输出、证据权威、guard 校验和审计字段，确保 LLM 拥有充分思考能力，同时不能越过商品库和正式知识库的事实边界。

## 2. 核心对象

### 2.0 客户可见回复 Owner 合同

`BrainPlan` 是客户可见回复的唯一上游来源。Guard、质量门、语义审稿、RAG、实时路由、本地模板、旧合成器、最终润色和兜底模块不得产生新的客户可见正文；它们只能返回审稿意见、证据、风险、返修指令或轻量自然化结果。Brain 不可用或不可采纳时，输出合同必须是“无客户可见回复 + 内部人工/告警”，而不是本地 fallback 文案。

### 2.1 BrainInput

`BrainInput` 是 LLM 客服大脑的唯一入口。

```json
{
  "schema_version": 1,
  "tenant_id": "chejin",
  "target": {
    "conversation_id": "wx_xxx",
    "target_name": "许聪",
    "chat_type": "private",
    "speaker_name": "许聪"
  },
  "current_message": {
    "raw_text": "许聪\n秦plus多少钱",
    "clean_text": "秦plus多少钱",
    "message_ids": ["msg_xxx"],
    "observed_at": "2026-06-03T20:00:00+08:00"
  },
  "conversation": {
    "history_text": "",
    "summary": "",
    "current_facts": {},
    "last_product_context": {}
  },
  "evidence": {},
  "runtime": {
    "route_level": "brain_first",
    "final_polish_required": true,
    "send_mode": "serial_rpa",
    "max_reply_segments": 3
  }
}
```

要求：

- `clean_text` 是 Brain 的主要输入。
- `raw_text` 仅供审计，不可让 LLM 把用户名当成客户正文。
- `speaker_name` 只表示身份，不表示客户问题内容。
- `conversation_id` 必须用于隔离多会话上下文。

### 2.2 EvidencePackV2

`EvidencePackV2` 是 Brain 的证据包。

```json
{
  "schema_version": 2,
  "content_basis": {
    "product_master": [],
    "formal_knowledge": [],
    "current_conversation_facts": []
  },
  "auxiliary": {
    "common_sense_guidance": {},
    "style_context": {},
    "ai_experience_pool_summary": {}
  },
  "candidate_only": {
    "review_candidates": [],
    "product_update_candidates": []
  },
  "authority_contract": {
    "product_facts_allowed_sources": ["product_master"],
    "policy_facts_allowed_sources": ["formal_knowledge"],
    "style_only_sources": ["style_context", "ai_experience_pool_summary"],
    "forbidden_runtime_content_sources": ["ai_experience_pool", "review_candidates", "raw_chat_history"]
  },
  "audit": {
    "content_basis_sources": [],
    "excluded_sources": [],
    "authority_conflicts": [],
    "matched_aliases": []
  }
}
```

### 2.3 BrainPlan

`BrainPlan` 是 LLM 客服大脑输出的结构化计划，不是最终可见文本。

```json
{
  "schema_version": 1,
  "can_answer": true,
  "understanding": {
    "user_intent": "询问具体车型报价",
    "normalized_entities": [
      {
        "raw": "秦plus",
        "normalized": "比亚迪秦PLUS",
        "entity_type": "product",
        "match_reason": "别名/大小写归一"
      }
    ],
    "context_resolution": {
      "used_last_product_context": false,
      "resolved_product_id": "chejin_qinplus_2022_dmi55"
    }
  },
  "answer_mode": "direct_answer",
  "reply_strategy": {
    "style": "concise_human",
    "business_goal": "直接报价并轻推进看车",
    "should_ask_clarifying_question": false,
    "should_soft_redirect": false
  },
  "evidence_used": {
    "product_ids": ["chejin_qinplus_2022_dmi55"],
    "formal_knowledge_ids": [],
    "conversation_fact_ids": [],
    "common_sense_topics": [],
    "style_ids": []
  },
  "facts_claimed": [
    {
      "fact_type": "price",
      "value": "x.xx万",
      "source_level": "product_master",
      "source_id": "chejin_qinplus_2022_dmi55"
    }
  ],
  "reply_segments": [
    "秦PLUS这台目前报价是 x.xx 万。",
    "如果您主要看通勤省油，这台方向是对的，可以再看下车况和到店时间。"
  ],
  "risk": {
    "risk_level": "low",
    "risk_tags": [],
    "needs_handoff": false,
    "handoff_reason": ""
  },
  "confidence": 0.86,
  "reason": "商品库命中具体车型和价格，问题可直接回答。"
}
```

### 2.4 GuardResult

`GuardResult` 是 Brain 输出后的强校验结果。

```json
{
  "allowed": true,
  "action": "send_reply",
  "reason": "guard_passed",
  "verified_segments": [],
  "rejected_facts": [],
  "required_handoff": false,
  "audit": {
    "product_fact_verified": true,
    "policy_fact_verified": true,
    "style_only_sources_not_used_as_facts": true,
    "answer_relevance_score": 0.9
  }
}
```

## 3. 权威合同

### 3.1 可以作为客户回复事实依据

```text
商品库
正式知识库
当前会话事实
```

### 3.2 只能作为辅助

```text
LLM常识层
话术风格层
AI经验池摘要
历史真实聊天
```

### 3.3 不能参与客户可见回复

```text
候选知识
未审核商品线索
原始历史聊天事实
运行日志
内部规则描述
Prompt
模型/API/密钥/系统路径
```

## 4. Prompt 合同

### 4.1 System 原则

Brain Prompt 必须明确：

```text
你是真人客服风格的销售助理。
你负责理解客户真实意图，并基于给定证据制定回复策略。
商品事实只能来自 product_master。
政策、流程、边界只能来自 formal_knowledge。
当前会话事实只能用于当前会话。
AI经验池、历史聊天、style_context 只能学习表达方式，不能当事实。
常识层只能做泛化分析，不能编造具体商品、价格、库存、车况、政策承诺。
输出必须是 JSON，不要直接输出客户可见文本以外的解释。
```

### 4.2 用户意图处理原则

Brain 必须具备以下能力：

- 对明确问题直接回答。
- 对错别字、音译、简称、别名做语义归一。
- 对“这辆 / 这台 / 刚才那个 / 报价 / 车况”做指代消解。
- 对客户质疑做回应，不重复旧模板。
- 对无害闲聊可以短暂自然回应，再轻柔引导业务。
- 对无关高风险问题转人工或婉拒。
- 对证据不足的问题，明确说明缺什么，不编。

### 4.3 回复风格原则

Brain 产出的 `reply_segments` 必须满足：

- 1-3 条。
- 每条都有完整意思。
- 不要“书接上文”式机械拆句。
- 不要长篇大段。
- 不要每条都称呼客户。
- 不要显得像知识库摘要。
- 不要暴露 AI 身份。
- 不要使用省略号截断。

### 4.4 事实声明原则

如果 Brain 输出以下内容，必须在 `facts_claimed` 里声明来源：

- 价格。
- 库存。
- 年份。
- 公里数。
- 车况。
- 门店/城市。
- 贷款、置换、售后、过户、检测、合同、发票等政策。

Guard 如果发现事实声明没有来源，必须拦截。

## 5. Answer Mode 枚举

```text
direct_answer
ask_clarifying_question
soft_social_reply
soft_redirect_to_business
recommend_from_catalog
compare_options
quote_product_fact
collect_customer_info
handoff
fallback_existing
```

要求：

- `soft_social_reply` 适用于你好、在吗、谢谢、再见、轻闲聊。
- `soft_redirect_to_business` 适用于无害但偏题内容。
- `recommend_from_catalog` 必须有商品库候选。
- `quote_product_fact` 必须命中商品库。
- `handoff` 只能在硬风险、事实缺失且必须人工、系统异常时使用。

## 6. 多会话隔离合同

BrainInput 必须包含：

- `conversation_id`
- `target_name`
- `speaker_name`
- `current_batch_id`
- `message_ids`

BrainPlan 必须回传：

- `conversation_id`
- `target_name`
- `current_batch_id`
- `source_message_ids`

发送前校验：

```text
ready_reply.conversation_id == current_window.conversation_id
ready_reply.target_name == current_window.target_name
ready_reply.source_message_ids 仍未被同会话更新覆盖
输入框为空或只包含本次草稿
```

## 7. 审计合同

每次回复必须记录：

- Brain 是否启用。
- 使用了哪些 product ids。
- 使用了哪些 formal knowledge ids。
- 是否使用当前会话事实。
- 是否使用 common sense。
- 是否使用 style context。
- 哪些 AI经验池内容被排除为事实依据。
- Guard 是否通过。
- Final polish 是否执行。
- 回复分段数量。
- 总耗时、LLM耗时、等待耗时、RPA发送耗时。

## 8. 兼容合同

历史兼容说明：以下旧灰度模式仅用于归档理解和离线对比，当前生产基线以 `customer_visible_reply_ownership_baseline.md` 为准。Brain First 下不允许 legacy fallback 生成客户可见回复：

```json
{
  "customer_service_brain": {
    "enabled": true,
    "mode": "hybrid_shadow",
    "fallback_to_legacy_on_error": false,
    "require_final_visible_polish": true,
    "allow_legacy_local_reply_for_hard_system_notice": true
  }
}
```

模式说明：

- `off`：完全旧链路。
- `shadow`：Brain 只审计，不改变回复。
- `hybrid_shadow`：历史灰度术语，仅用于离线比较；不得作为当前客户可见出口策略。
- `brain_first`：正常业务默认采纳 Brain。
- `legacy_safe_fallback`：已归档废弃。Brain 出错、超时、不可采纳或返修失败时必须阻断出站并触发内部告警，不回旧链路发客户可见文本。

## 9. 不可变约束

以下约束不能被配置关闭：

- 商品事实不得绕过商品库。
- 正式政策不得绕过正式知识库。
- 候选知识不得直接对客生效。
- AI经验池不得作为事实依据。
- 客户可见回复不得跳过最终润色。
- 发送前不得跳过目标会话复核。
