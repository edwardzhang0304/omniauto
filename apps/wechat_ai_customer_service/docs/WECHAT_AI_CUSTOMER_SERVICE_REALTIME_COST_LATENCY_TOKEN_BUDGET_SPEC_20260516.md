# 微信自动客服 token 预算与路由规范（2026-05-16）

## 1. 当前成本基线

从实盘审计看，当前普通预算推荐消息也可能进入重型合成链路：

- prompt 估算：约 13k tokens。
- 实际总用量：约 14k tokens。
- 历史场景中，intent advisory 与 reply synthesis 双调用时，单条消息可能超过 20k tokens。
- 一旦外部接口慢，客户等待时间会跟随 LLM 调用时间放大。

这不是可持续的实盘成本结构。

## 2. 优化目标

| 指标 | 当前风险 | 目标 |
|---|---|---|
| 普通消息前台 token | 10k-14k 常见 | 0-1800 |
| 复杂消息前台 token | 10k-20k+ | 1500-3000 |
| 高风险边界前台 token | 可能 Pro 10k+ | 0 |
| 后台学习 token | 混在前台 | 后台异步，限额执行 |
| 普通消息响应 | 偶发分钟级 | 2-8 秒 |
| 监听卡死 | 可能整段停住 | watchdog 后恢复 |

预计总节省：

- 保守估计：70%-80%。
- 如果常规咨询占比高：85%-95%。
- 高风险咨询越多，节省越明显，因为前台不再等 Pro。

## 3. 消息分类预算

### 3.1 L0：确定性回复

适用：

- 问候。
- 客户留电话、姓名、到店时间。
- 已知商品价格/库存/配置问答。
- 付款、合同、赔付、事故承诺等高风险边界。
- 客户问“你是不是 AI/机器人”等身份试探。

预算：

- 前台 LLM calls：0。
- 前台 tokens：0。
- 响应目标：1-4 秒。

质量来源：

- 正式知识库。
- 商品库。
- 安全规则。
- 已批准话术模板。
- 防暴露 AI 身份话术。

### 3.2 L1：轻量模板组合

适用：

- “10万以内上下班通勤有什么推荐？”
- “家用省油一点的有吗？”
- “外地能不能看车/提档？”
- “能不能置换？”

预算：

- 默认 LLM calls：0。
- 可选 Flash calls：1。
- 触发 Flash 时 tokens：600-1800。
- 响应目标：2-6 秒。

质量来源：

- 程序先筛商品。
- RAG 只提供说法，不提供事实。
- 模板短句自然化。

### 3.3 L2：前台轻量 LLM

适用：

- 多轮指代：“刚才那台呢？”
- 客户同时给预算、用途、家庭成员、旧车置换等复合需求。
- 模板回复会明显生硬。

预算：

- Flash calls：最多 1。
- retry：默认 0。
- prompt tokens：不超过 2500。
- completion tokens：不超过 500。
- 响应目标：4-8 秒。
- 硬超时：8-12 秒，超时回退 L1。

证据限制：

- 当前消息：完整保留，最长 800 字。
- 历史：最多 6 条，最多 1200 字。
- 商品：最多 3 个，每个最多 220 字。
- RAG：最多 2 条，每条最多 180 字。
- 规则：只传命中的规则摘要。

### 3.4 L3：后台深度 LLM

适用：

- RAG 经验解释。
- 候选知识生成。
- 话术质量复盘。
- 客户画像总结。
- 高风险案例复盘。

预算：

- 不进入前台预算。
- worker 级别设置每日/每小时 cap。
- 可用 Pro，但必须记录 usage。
- 失败可重试，不影响客户回复。

## 4. 前台 LLM 触发条件

只有满足以下条件之一，前台才允许调用 LLM：

- 本地路由判断为 L2。
- L1 模板候选质量分低于阈值。
- 客户消息存在多轮指代，本地无法可靠解引用。
- 商品候选超过 1 个且需要自然比较。
- 用户表达含混，但追问模板不足以覆盖。

以下场景禁止前台调用 LLM：

- 已触发高风险边界。
- 已命中明确商品事实。
- 已命中问候/结束语/留资采集。
- 当前轮已经超过时间预算。
- 同一批消息已调用过 LLM。
- watchdog 剩余时间不足。

## 5. 模型路由

| 场景 | 前台模型 | 后台模型 |
|---|---|---|
| 问候/留资/确认 | 无 | 无 |
| 明确商品事实 | 无 | 可选复盘 |
| 预算推荐 | 无或 Flash | 可选 Flash/Pro 复盘 |
| 多轮复杂推荐 | Flash | 可选 Pro 总结 |
| 高风险边界 | 无 | Pro 可选 |
| 经验解释 | 无 | Pro |
| 知识候选 | 无 | Pro |

原则：

- Pro 不应出现在实时前台默认路径。
- Flash 也不是默认必调，只是 L2 的工具。
- 后台 Pro 结果不得直接改商品库或正式知识，必须进入候选/审计。

## 6. token 审计字段

每次前台回复必须记录：

- `runtime_route.level`
- `runtime_route.reason`
- `runtime_route.foreground_llm_allowed`
- `token_budget.max_prompt_tokens`
- `token_budget.max_completion_tokens`
- `token_budget.actual_prompt_tokens`
- `token_budget.actual_completion_tokens`
- `token_budget.actual_total_tokens`
- `token_budget.saved_reason`
- `latency.reply_build_seconds`
- `latency.total_once_seconds`
- `watchdog.remaining_seconds_before_send`

每次后台 LLM 必须记录：

- `job_id`
- `job_kind`
- `model_tier`
- `usage`
- `source_event_id`
- `writes_candidate`
- `writes_formal_knowledge=false` 除非明确人工确认。

## 7. 成本红线

### 7.1 单条前台消息

- 正常前台总 tokens 不应超过 3000。
- 超过 3000 必须在审计中标记 `token_budget_exceeded=true`。
- 超过 5000 视为回归风险。

### 7.2 每小时

建议按租户统计：

- 前台 LLM 调用率。
- 平均 tokens/message。
- P95 tokens/message。
- P95 reply latency。
- L0/L1/L2/L3 占比。

### 7.3 异常策略

当连续 3 次前台 LLM 超时或 tokens 超预算：

- 自动进入省 token 模式。
- 暂停前台 LLM。
- 使用 L0/L1 回复。
- 后台继续记录待复盘任务。

## 8. 质量不降的关键

省 token 不是简单少传资料，而是更聪明地选择资料：

- 商品事实先由程序筛选，减少模型判断负担。
- RAG 只传最像客户问法的片段，不传完整导入文本。
- 历史只传最近必要轮次，长历史交给后台摘要。
- 高风险不用模型自由判断，直接用确定规则处理。
- 真实客服风格沉淀为短模板和句式库，常规问题无需每次重新生成。
