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

- 当 BrainPlan 权威校验通过但质量门失败时触发。
- 若 provider 为 `manual_json` 或修复 LLM 不可用，则不修复，保留失败原因并走旧链路 fallback。
- 修复结果必须重新走 normalize、fact validation、quality verifier、authority guard。

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
