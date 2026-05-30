# 权威分层 RAG 开发落地方案

## 开发策略

本次不重做知识系统，而是在现有框架上做“收口式改造”：

1. 保留 `rag_experience` 作为 AI经验池底层。
2. 保留 `style_memory`，但强化事实脱敏和只润色边界。
3. 保留 `review_candidates`，作为正式知识唯一候选入口。
4. 保留 `product_master`，作为商品事实唯一权威入口。
5. 收紧运行时 evidence pack，禁止 AI经验池直接作为内容证据。
6. 新增经验分发服务，把原始经验自动路由到风格层、候选层、商品候选、归档。

## 阶段一：定义运行时证据合同

### 目标

让运行时明确区分：

- 内容依据。
- 当前会话事实。
- 辅助分析。
- 风格润色。
- 治理候选。

### 建议改动

扩展 `workflows/evidence_authority.py`：

- 增加 `CURRENT_CONVERSATION_FACT`。
- 增加 `AI_EXPERIENCE_POOL`。
- 增加 `CONTENT_BASIS_ALLOWED_LEVELS`。
- 增加 `STYLE_ONLY_SOURCE_TYPES`。
- 增加 `CHAT_SOURCE_TYPES`。
- 增加 `can_authorize_reply_content(item)`。
- 增加 `can_authorize_product_fact(item)`。
- 增加 `can_authorize_formal_rule(item)`。
- 增加 `can_affect_style(item)`。

### 合同建议

```python
CONTENT_BASIS_ALLOWED_LEVELS = {
    "product_master",
    "product_scoped_formal",
    "formal_knowledge",
    "current_conversation_fact",
}

STYLE_ONLY_SOURCE_TYPES = {
    "cleaned_real_chat_pack",
    "real_chat_style",
    "wechat_raw_message",
    "raw_wechat_private",
    "raw_wechat_group",
    "raw_wechat_file_transfer",
    "ai_recorder_chat",
}
```

## 阶段二：收紧运行时 evidence pack

### 目标

客户回复 LLM 只能看到允许作为内容依据的数据。

### 建议改动

修改 `workflows/reply_evidence_builder.py`：

- `knowledge.product_master` 保留。
- `knowledge.formal_knowledge` 保留。
- `conversation.current_facts` 保留。
- `knowledge.rag_experience` 从内容依据中移除。
- `knowledge.rag_evidence.hits` 不再包含 AI经验池来源。
- 新增 `style_context`，只放脱敏后的风格参考摘要。
- 新增 `audit.content_basis_sources`。
- 新增 `audit.excluded_sources`。

### 目标结构

```json
{
  "knowledge": {
    "product_master": {},
    "formal_knowledge": {},
    "current_conversation_facts": {}
  },
  "auxiliary": {
    "common_sense": {},
    "style_context": {}
  },
  "audit": {
    "content_basis_sources": [],
    "excluded_sources": []
  }
}
```

## 阶段三：禁用 AI经验池运行时检索权限

### 目标

AI经验池不再通过 `rag_index` 成为客户回复内容证据。

### 建议改动

修改 `workflows/rag_layer.py`：

- `iter_experience_chunks()` 默认不再返回 AI经验池经验。
- 如需保留调试，可加参数 `include_experience_pool=False`，生产默认关闭。
- `search()` 返回结果必须通过 `can_authorize_reply_content()` 过滤。

修改 `workflows/rag_experience_store.py`：

- 所有聊天来源默认 `retrieval_allowed=False`。
- 所有 AI经验池数据默认 `runtime_content_allowed=False`。
- 保留 `style_allowed` 和 `candidate_auto_create_allowed`。

### 迁移要求

- 将现有 `retrievable_experience` 中聊天来源全部降级。
- 重建 `rag_index`。
- 审计确认 `rag_index` 中无聊天来源。

## 阶段四：强化话术风格层

### 目标

保留真实销售表达价值，但不让历史事实进入回复。

### 建议改动

修改 `workflows/style_memory_store.py`：

- 新增 `sanitize_style_example(raw)`。
- 对价格、车型、里程、年份、手机号、姓名、库存、绝对承诺做模板化。
- 增加 `fact_tokens_removed` 审计字段。
- 如果无法安全脱敏，拒绝进入风格层。

修改 `workflows/reply_style_adapter.py`：

- 风格适配只接收 `style_context`。
- 不接收完整历史客服回复作为内容依据。
- 适配后必须经过事实守卫。

### 风格样本目标格式

```json
{
  "id": "style_xxx",
  "source_id": "rag_exp_xxx",
  "customer_intent": "价格咨询",
  "style_pattern": "先认可问题，再说明需要核实，最后推进到店或留需求",
  "safe_reply_template": "这个我先帮您核实一下，确认清楚再回复您，免得给您说错。",
  "removed_fact_tokens": ["price", "product_name", "mileage"],
  "runtime_usage": {
    "can_affect_style": true,
    "can_authorize_reply_content": false
  }
}
```

## 阶段五：新增 AI经验分发服务

### 目标

所有非商品库入口数据进入 AI经验池后，由 LLM 做深度分析并自动分发。

### 新增建议文件

- `admin_backend/services/experience_distribution_service.py`
- `admin_backend/services/experience_distribution_schema.py`
- `admin_backend/services/experience_distribution_audit.py`

### 服务职责

1. 读取 AI经验池 item。
2. 调用 LLM 输出结构化分发计划。
3. 经过本地安全策略校验。
4. 执行自动分发：
   - 风格层：写入 `style_memory`。
   - 正式知识候选：写入 `review_candidates`。
   - 商品候选：写入商品候选区或 `review_candidates` 中的商品更新候选。
   - 转人工候选：写入转人工规则候选。
   - 归档/废弃：更新经验池治理状态。
5. 写入审计日志。

### 分发计划结构

```json
{
  "experience_id": "rag_exp_xxx",
  "source_type": "wechat_raw_message",
  "summary": "客户询问低首付购车，客服历史回复涉及金融方案边界。",
  "claims": [
    {
      "text": "低首付需要看征信和资方审批",
      "claim_type": "formal_rule_candidate",
      "time_sensitive": false,
      "risk_level": "medium"
    }
  ],
  "routes": [
    {
      "target_layer": "formal_candidate",
      "action": "create_candidate",
      "confidence": 0.82,
      "requires_human_review": true,
      "reason": "这是稳定金融边界，不应直接自动回复承诺。"
    },
    {
      "target_layer": "style_memory",
      "action": "upsert_sanitized_style",
      "confidence": 0.74,
      "requires_human_review": false,
      "reason": "客服表达方式可复用，但具体金融承诺已移除。"
    }
  ],
  "runtime_usage": {
    "can_authorize_reply_content": false,
    "can_affect_style": true,
    "can_create_candidate": true
  }
}
```

## 阶段六：候选层与人工否决

### 目标

自动分发后，人工仍可否决、删除、改目标层、回滚。

### 建议改动

复用 `review_candidates`，补充字段：

- `source_experience_id`
- `distribution_plan_id`
- `target_layer`
- `requires_human_review`
- `runtime_enabled=false`
- `user_override`
- `rejected_at`
- `rejected_reason`

后台 UI：

- AI经验池卡片展示推荐分发目标。
- 每个 route 显示“已自动写入风格层 / 已生成候选 / 已归档”。
- 支持“否决并删除目标产物”。
- 支持“改为只保留经验”。
- 支持“升级候选为正式知识”。

## 阶段七：LLM提示词与守卫

### 目标

生成回复时，让 LLM 明确知道哪些信息能用，哪些只能参考。

### 修改点

`workflows/llm_reply_synthesis.py`：

- system prompt 增加“内容依据白名单”。
- 禁止引用 AI经验池、历史聊天、候选知识作为事实。
- 输出中增加 `basis_sources`。
- 输出中增加 `refused_sources`。

`workflows/reply_style_adapter.py`：

- 风格适配后再次校验是否引入新事实。
- 如果引入未授权事实，回退到适配前回复。

## 阶段八：数据迁移

### chejin 当前数据处理

当前 chejin 已有：

- `935` 条 `style_memory` 真实聊天风格样本。
- 约 `936` 条 realchat 相关 AI经验池记录。
- `111` 条真实聊天样本仍在 `rag_index` 中可检索。

迁移动作：

1. 保留 `style_memory`，但批量脱敏重建。
2. 将所有聊天来源经验设为：
   - `style_allowed=true`
   - `retrieval_allowed=false`
   - `runtime_content_allowed=false`
   - `promotion_allowed=false`，除非已生成候选且人工确认。
3. 重建 `rag_index`。
4. 审计确认 `rag_index` 不含聊天来源。
5. 生成迁移报告。

## 开发顺序建议

1. 先加证据权限合同和单元测试。
2. 再收紧运行时 evidence pack。
3. 再禁用 AI经验池运行时检索。
4. 再迁移 chejin 旧数据。
5. 再强化风格层脱敏。
6. 再新增 AI经验分发服务。
7. 最后改后台 UI 和全量回归。

这样可以先堵住“历史聊天参与内容依据”的最大风险，再逐步补齐自动分发能力。
