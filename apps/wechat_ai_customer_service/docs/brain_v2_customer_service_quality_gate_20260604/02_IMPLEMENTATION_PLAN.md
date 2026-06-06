# Brain v2 代码落地方案

## 改动范围

本轮只修改以下范围：

- `workflows/customer_service_brain_contract.py`
- `workflows/customer_service_brain.py`
- `tests/run_customer_service_brain_contract_checks.py`
- 配置示例中的 `customer_service_brain` 默认项

不修改 RPA 调度、商品库、正式知识库、AI经验池导入治理逻辑。

## 新增能力

### 1. BrainPlan 自检字段

允许 BrainPlan 带 `self_check` 审计字段，用于记录模型自我判断：

```json
{
  "self_check": {
    "current_question_answered": true,
    "authority_respected": true,
    "reply_is_specific": true,
    "needs_repair": false
  }
}
```

该字段只用于审计，不授权事实。

### 2. 质量门

新增 `verify_brain_reply_quality(...)`：

- 输入：标准化 BrainPlan、当前客户消息、evidence pack、settings。
- 输出：`ok`、`errors`、`warnings`、`repair_instruction`。
- 默认启用。

质量门只做通用问题检测，不写账号专属车型、价格或销售话术。

### 3. 修复门

新增一次性 `run_brain_repair_llm(...)`：

- 当 BrainPlan 权威校验失败、质量门失败或 authority guard 拒绝时触发。
- 修复输入必须把结构化校验/质量门/guard 的具体意见转成 Brain 返修提示，让 Brain 重新理解和重新规划。
- 若 provider 为 `manual_json` 或修复 LLM 不可用，则不修复，保留失败原因并进入 Brain 安全兜底或人工转接；Brain First 模式下不得退回旧结构化业务模板接管。
- 修复结果必须重新走 normalize、fact validation、quality verifier、authority guard。
- 修复门不得输出客户可见模板，唯一输出仍是 BrainPlan。

### 3.1 权限边界

- `customer_service_brain` 是正常客服回复的唯一决策主体。
- 结构化路由、RAG、AI经验池、质量门、guard、最终润色只提供证据、候选、边界、审稿意见、轻量表达建议。
- 发现坏回复时优先改全局 Brain 输入、证据包、返修提示、验证合同或上下文隔离，不通过新增局部关键词/车型/预算/话术分支来“补答案”。
- 最终润色只可弱改写，不得改变事实、推荐策略、风险判断和会话意图。

### 3.2 代码改动前纠偏审计

任何回复质量修复 PR 前，应在描述或测试备注中回答：

1. 这是 Brain 理解问题、证据问题、权威数据问题、guard/质量门误判、润色越权、OCR/RPA污染，还是多会话绑定问题？
2. 修复是否提升一类通用能力，而不是只覆盖某个关键词、车型、预算或测试话术？
3. 如果结构化层发现问题，是否已经转成 Brain 返修意见，而不是直接生成客户可见答案？
4. 如果需要改结构化数据/规则，是否属于商品库事实、正式知识、安全边界、捕获清洗或会话绑定这类硬问题？
5. 是否新增或更新了防止旧模板接管、润色越权、Brain 草稿污染上下文的测试？

### 4. 配置项

新增默认配置：

```json
{
  "quality_verifier_enabled": true,
  "quality_repair_enabled": true,
  "max_quality_repair_attempts": 1,
  "quality_repair_timeout_seconds": 8
}
```

## 审计字段

`customer_service_brain` 事件增加：

- `quality_verification`
- `quality_repair`
- `repaired_brain_plan`

用于定位大脑是否答偏、是否触发过修复、修复是否成功。

## 回滚方式

- 将 `customer_service_brain.quality_verifier_enabled=false` 可关闭质量门。
- 将 `customer_service_brain.quality_repair_enabled=false` 可保留拦截但不做修复。
- 将 `customer_service_brain.mode=off` 可退回原链路。
