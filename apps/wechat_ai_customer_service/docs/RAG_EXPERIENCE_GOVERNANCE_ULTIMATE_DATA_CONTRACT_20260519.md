# RAG 经验治理终极数据契约（2026-05-19）

## 1. 目标

本契约定义 RAG 经验治理层新增字段、状态枚举、兼容逻辑和数据不变量。

核心目标：

- 保留旧数据兼容。
- 不破坏已有 `status`、`experience_review`、`quality`、`ai_interpretation` 字段。
- 新增一个权威的最终裁决字段 `governance`。
- 所有检索、晋升、前端展示统一读取 `governance`。

## 2. 现有字段定位

### `status`

顶层生命周期状态。

允许值：

- `active`
- `discarded`
- `promoted`

它只说明记录是否仍在经验池中，不足以说明是否可检索、可晋升或只作风格样本。

### `experience_review`

人工或系统处理状态。

常见值：

- `pending`
- `kept`
- `auto_kept`
- `auto_triaged`

它说明“谁处理过”，但不应直接决定最终用途。

### `quality`

质量评分。

常见字段：

- `score`
- `band`
- `retrieval_allowed`
- `reasons`
- `signals`

它说明证据质量，不等于业务治理结果。

### `ai_interpretation`

AI解释和建议。

常见字段：

- `recommended_action`
- `action_label`
- `action_reason`
- `promotion_allowed`
- `auto_triage`
- `auto_keep`

它是治理输入之一，不是唯一权威。

## 3. 新增字段：`governance`

每条 RAG 经验新增：

```json
{
  "governance": {
    "schema_version": 1,
    "policy_version": "rag_experience_governance_v1",
    "evaluated_at": "2026-05-19T00:00:00",
    "effective_state": "style_only",
    "final_action": "keep_style_only",
    "display_label": "仅作话术风格参考",
    "reason": "真实聊天样本含具体车型或价格线索，不参与RAG事实检索，但可用于学习客服表达。",
    "retrieval_allowed": false,
    "promotion_allowed": false,
    "candidate_auto_create_allowed": false,
    "style_allowed": true,
    "requires_manual_review": false,
    "risk_level": "medium",
    "source_authority": {
      "allowed": false,
      "reason": "dynamic_product_recommendation_chat_stays_rag_only"
    },
    "inputs": {
      "status": "active",
      "review_status": "auto_kept",
      "quality_band": "high",
      "quality_retrieval_allowed": true,
      "ai_recommended_action": "discard",
      "formal_relation": "novel",
      "source": "real_chat_style",
      "source_type": "cleaned_real_chat_pack"
    }
  }
}
```

## 4. 枚举定义

### 4.1 `effective_state`

| 值 | 含义 | 是否进RAG检索 | 是否可生成候选 | 是否可进风格层 |
| --- | --- | --- | --- | --- |
| `pending_review` | 待处理 | 否 | 否 | 视来源 |
| `retrievable_experience` | 可作为RAG经验参考 | 是 | 可选 | 可选 |
| `style_only` | 仅作话术风格参考 | 否 | 否 | 是 |
| `candidate_suggested` | 建议生成候选 | 否或是，视风险 | 是 | 可选 |
| `candidate_created` | 已生成候选 | 否 | 否 | 可选 |
| `auto_discarded` | 系统自动废弃 | 否 | 否 | 否 |
| `user_discarded` | 用户废弃 | 否 | 否 | 否 |
| `promoted` | 已升级候选或已处理 | 否 | 否 | 否 |
| `blocked` | 硬规则阻断 | 否 | 否 | 否 |
| `unknown` | 未知状态 | 否 | 否 | 否 |

### 4.2 `final_action`

允许值：

- `wait_for_review`
- `keep_retrievable`
- `keep_style_only`
- `suggest_candidate`
- `create_candidate`
- `auto_discard`
- `respect_user_discard`
- `respect_promoted`
- `block_by_policy`
- `manual_review_required`

### 4.3 `risk_level`

允许值：

- `low`
- `medium`
- `high`
- `blocked`

## 5. 兼容规则

### 5.1 旧数据无 `governance`

读取时必须即时计算。

写入时可逐步持久化：

- 列表接口可返回虚拟 `governance`。
- 数据修复阶段再写入文件。

### 5.2 旧 `auto_kept` 与新 `discard` 冲突

如果同时满足：

```text
experience_review.status = auto_kept
ai_interpretation.recommended_action in {discard, already_covered}
reviewed_by_user = false
```

则治理层必须以当前 guardrail/AI建议为准。

可能结果：

- `auto_discarded`
- `style_only`
- `candidate_suggested`
- `blocked`

不得继续显示为 `retrievable_experience`。

### 5.3 人工处理优先

如果：

```text
reviewed_by_user = true
experience_review.status = kept
```

则保留人工动作，但仍要单独判断 `retrieval_allowed`。

例：

```text
用户人工保留，但命中商品事实硬规则
-> effective_state = blocked
-> display_label = 人工已保留，但按商品主数据规则禁止参与RAG检索
```

如果：

```text
status = discarded
reviewed_by_user = true
```

则：

```text
effective_state = user_discarded
retrieval_allowed = false
promotion_allowed = false
style_allowed = false
```

### 5.4 商品主数据

任何命中商品主数据形态的经验：

```text
车型、价格、库存、配置、具体车况、里程、车源状态
```

默认：

```text
retrieval_allowed = false
promotion_allowed = false
candidate_auto_create_allowed = false
```

如果它来自清洗实盘聊天，且回复表达有风格价值，可：

```text
style_allowed = true
effective_state = style_only
```

否则：

```text
effective_state = auto_discarded
```

### 5.5 动态推荐

命中以下形态：

```text
预算 -> 固定车型列表
当期库存推荐
最低价/到底价
贷款条件绑定推荐
```

默认不进入正式知识候选。

可选结果：

- `style_only`：只学习承接方式。
- `retrievable_experience`：仅当不含具体车型/价格/库存，且有明确场景泛化价值。
- `auto_discarded`：含强承诺或明显污染。

## 6. 候选自动提名字段

当治理裁决为 `candidate_suggested` 时，可新增：

```json
{
  "candidate_nomination": {
    "status": "suggested",
    "suggested_at": "2026-05-19T00:00:00",
    "target_category": "chats",
    "reason": "多次出现的低风险流程话术，可整理成正式候选。",
    "auto_create_allowed": true,
    "created_candidate_id": "",
    "created_at": ""
  }
}
```

创建 pending candidate 后：

```json
{
  "candidate_nomination": {
    "status": "created",
    "created_candidate_id": "candidate_xxx",
    "created_at": "2026-05-19T00:00:00"
  },
  "governance": {
    "effective_state": "candidate_created",
    "promotion_allowed": false
  }
}
```

## 7. 统计契约

RAG经验统计必须返回：

```json
{
  "total": 1245,
  "by_status": {
    "active": 1000,
    "discarded": 200,
    "promoted": 45
  },
  "by_governance_state": {
    "pending_review": 10,
    "retrievable_experience": 320,
    "style_only": 600,
    "candidate_suggested": 20,
    "candidate_created": 15,
    "auto_discarded": 220,
    "user_discarded": 50,
    "promoted": 10,
    "blocked": 0,
    "unknown": 0
  }
}
```

不变量：

```text
total = sum(by_status.values())
total = sum(by_governance_state.values())
```

如果出现未知状态，必须显示 `unknown`，不得隐藏。

## 8. RAG检索契约

RAG经验生成 chunk 时必须满足：

```text
status = active
governance.retrieval_allowed = true
governance.effective_state in {retrievable_experience, candidate_suggested}
quality.band in {high, medium}
污染防护通过
商品主数据边界通过
```

任何一个条件不满足，不能进入 RAG index。

## 9. 前端契约

每张 RAG 经验卡片主状态只显示：

```text
governance.display_label
```

辅助区域可显示：

- 质量评分。
- AI建议。
- 来源判断。
- 正式库关系。
- 操作按钮。

前端不得用 `quality.band` 或 `experience_review.status` 自行拼最终文案。

## 10. 数据修复契约

历史修复必须写入：

```json
{
  "governance_migration": {
    "migration_id": "rag_governance_20260519_xxx",
    "previous_review_status": "auto_kept",
    "previous_ai_action": "discard",
    "previous_retrieval_allowed": true,
    "new_effective_state": "style_only",
    "dry_run_report_path": "..."
  }
}
```

任何批量处理必须可追溯、可回滚。
