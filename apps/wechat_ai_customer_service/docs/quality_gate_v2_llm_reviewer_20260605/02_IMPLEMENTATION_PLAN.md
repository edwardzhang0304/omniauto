# LLM 语义质量门 V2 实施方案

## 客户可见回复所有权硬基线

- 所有客户可见回复必须由 `customer_service_brain` 发出：只能是首个有效 BrainPlan、Brain repair 后的 BrainPlan，或 Brain 自己生成的硬边界/拒绝/转人工类说明。
- Guard、质量门、语义审稿、RAG、实时路由、本地模板、旧合成器、最终润色和任何兜底模块都不能生成、替换、拼接客户可见回复；它们只能提供证据、风险、审稿意见、返修指令或轻量表达校验。
- Brain 不可用、超时、不可采纳或返修失败时，不允许本地 safe fallback 代替 Brain 发客户可见话术；必须阻断发送、记录审计，并触发内部人工/告警接口。
- 后续所有客服相关开发文档必须引用 [customer_visible_reply_ownership_baseline.md](../customer_visible_reply_ownership_baseline.md)。

## 1. 修改范围

### 1.1 主要代码区域

建议涉及以下文件：

- `apps/wechat_ai_customer_service/workflows/customer_service_brain.py`
- `apps/wechat_ai_customer_service/workflows/customer_service_brain_contract.py`
- `apps/wechat_ai_customer_service/workflows/listen_and_reply.py`
- `apps/wechat_ai_customer_service/workflows/final_visible_llm_polish.py`
- `apps/wechat_ai_customer_service/configs/default.example.json`
- `apps/wechat_ai_customer_service/configs/jiangsu_chejin_xucong_live.example.json`

建议新增：

- `apps/wechat_ai_customer_service/workflows/customer_service_quality_reviewer.py`
- `apps/wechat_ai_customer_service/tests/run_customer_service_quality_reviewer_checks.py`

### 1.2 不应修改的范围

- 不修改商品库数据结构。
- 不修改正式知识库权威层级。
- 不改 RPA 窗口切换、键鼠锁、OCR 截图策略。
- 不改 AI 记录员导出结构，除非测试发现共享 message envelope 规则被破坏。

### 1.3 纠偏后的未完成项取舍

纠偏完成后，后续工作不应再以“补一个具体话术、补一个关键词、补一个本地回复分支”为目标，而应按下面的取舍执行。

| 项目 | 结论 | 原因 | 后续动作 |
| --- | --- | --- | --- |
| 端到端分段耗时观测 | 值得做，优先级高 | 这是定位慢回复、尾延迟、LLM 超时、RPA 等待的基础能力，不改变回复决策 | 记录 capture、Brain、reviewer、repair、final visible、queue、RPA send 各阶段耗时 |
| 默认配置与开发原则一致性 | 值得做，优先级高 | 示例配置如果和“客户可见回复必须最终校验/微润色”矛盾，后续部署容易误关关键防线 | 统一 `default.example.json`、账号 live example 和文档描述 |
| legacy route / realtime 防回退审计 | 值得做，优先级高 | 旧代码可以保留做证据、风险、fallback，但不能重新接管正常回复 | 增加合同测试或静态审计，禁止新增账号专属商品、价格、固定销售回复分支 |
| 独立 `run_customer_service_quality_reviewer_checks.py` | 有价值，但不强制作为短期硬门槛 | 如果覆盖已在 Brain contract 测试中存在，重复拆文件本身不提升质量 | 当 reviewer 测试继续增长时再拆分；短期可在测试计划中标注“可合并覆盖” |
| 语义 reviewer 的 suspicious 触发词 | 保留过渡能力，但禁止继续膨胀 | 它只决定是否请 LLM 审稿，不直接生成回复；但继续加词会滑回结构化思路 | 逐步改为通用风险信号、配置化和审计数据驱动；不为单个话术补词 |
| 全量真实客户问题集回归 | 值得做，作为验收项 | 这是验证 Brain 通用思考能力和业务可用性的最好方式 | 用真实历史问法抽样、改写、覆盖多轮上下文、追问、异议和闲聊 |
| AI 记录员完整导出回归 | 条件性值得做 | 本轮客服 Brain/guard 改造理论上不应影响记录员，但共享 OCR envelope 或账号切换改动会影响 | 触及 shared envelope、账号配置、导出模板时必须跑；客服纯回复改造时可做 smoke |
| 飞书/ServerChan 转人工实盘 | 商用前值得做，不阻塞本轮客服回复质量验收 | 它验证人工链路可靠性，但不影响 Brain 主控架构是否正确 | 在转人工规则稳定后做独立实盘验收 |
| `always` 语义 reviewer 模式 | 暂不推荐默认启用 | 它会增加延迟，也可能把 reviewer 变成过重的第二审判器 | 默认保持 `suspicious_only`；`always` 只用于离线审计或低流量灰度 |
| 为短问候/问价新增本地极速模板 | 明确否决 | 会绕过 Brain 和最终校验，重新形成两套回复体系，且容易机械重复 | 短问候和简单问价仍由 Brain 决策，可优化 prompt、缓存、证据压缩和并发 |
| 用 guard / reviewer 直接拼客户可见答案 | 明确否决 | 会让 guard、reviewer 变成第二或第三套客服大脑 | 只能输出审稿意见、风险等级、返修指令；客户可见策略回到 Brain |
| 针对单个车型、价格、预算话术写路由补丁 | 明确否决 | 商品库更新后会污染业务，且覆盖不了真实长尾表达 | 商品事实进商品库，策略问题改 Brain prompt/evidence pack/repair feedback |

### 1.4 实施优先级

P0 必须保持：

- Brain 是正常客服回复主控。
- 商品库和正式知识库是事实与政策硬权威。
- guard / reviewer / final visible polish 不生成新的业务策略。
- 多会话 capture、Brain input、ready reply、send target 绑定一致。
- OCR speaker label、群成员名、聊天标题只作为 metadata。

P1 优先补齐：

- 分段耗时审计。
- legacy route 防回退审计。
- 默认配置与文档一致。
- 真实客户问题集回归。

P2 延后但保留：

- 独立 reviewer 测试文件拆分。
- 记录员完整导出回归。
- 飞书/ServerChan 人工链路实盘。

Won't do：

- 为具体失败话术堆关键词和模板。
- 为速度绕过 Brain 或最终可见校验。
- 让质量门、guard、润色层接管客户可见回复策略。

## 2. 配置设计

在 `customer_service_brain` 下新增或固化以下配置：

```json
{
  "customer_service_brain": {
    "quality_gate_v2_enabled": true,
    "semantic_reviewer_enabled": true,
    "semantic_reviewer_mode": "suspicious_only",
    "semantic_reviewer_timeout_seconds": 8,
    "semantic_reviewer_max_tokens": 350,
    "semantic_reviewer_temperature": 0.1,
    "semantic_reviewer_cache_enabled": true,
    "semantic_reviewer_repair_once": true,
    "semantic_reviewer_soft_pass_low_risk": true,
    "semantic_reviewer_shadow_audit": true
  }
}
```

在 `final_visible_llm_polish` 下固化 Brain 来源短链路配置：

```json
{
  "final_visible_llm_polish": {
    "brain_source_policy": "llm_micro_verify",
    "brain_micro_guard_fallback_to_draft": true,
    "brain_micro_timeout_seconds": 5,
    "brain_micro_max_tokens": 80,
    "brain_micro_temperature": 0.25,
    "brain_micro_min_similarity": 0.72
  }
}
```

配置说明：

- `quality_gate_v2_enabled`：总开关。
- `semantic_reviewer_enabled`：LLM 语义审稿开关。
- `semantic_reviewer_mode`：`shadow`、`suspicious_only`、`always`。
- `semantic_reviewer_timeout_seconds`：审稿单次超时，默认 8 秒。
- `semantic_reviewer_max_tokens`：限制审稿输出，默认 350。
- `semantic_reviewer_cache_enabled`：相同上下文和 draft 命中缓存。
- `semantic_reviewer_repair_once`：只允许 Brain 修复一次。
- `semantic_reviewer_soft_pass_low_risk`：审稿不可用时，硬 guard 通过的低风险回复可发送。
- `semantic_reviewer_shadow_audit`：即使不拦截，也记录审稿结果。
- `brain_source_policy`：Brain 来源最终可见层策略。默认 `llm_micro_verify`，只做校验/微润色。
- `brain_micro_guard_fallback_to_draft`：微润色候选改变语义时，采用 Brain 原草稿继续发送。
- `brain_micro_min_similarity`：微润色候选和 Brain 草稿的最低相似度。

## 3. 新模块设计

### 3.1 `customer_service_quality_reviewer.py`

职责：

- 构建审稿 prompt。
- 调用 LLM 审稿。
- 解析 JSON 结果。
- 做 timeout 和 fallback。
- 计算审稿缓存 key。
- 标准化 reviewer verdict。

该模块不负责：

- 生成客户可见回复。
- 修改 BrainPlan。
- 授权事实。
- 发送消息。

### 3.2 数据类

建议新增轻量数据结构：

```python
@dataclass
class QualityReviewRequest:
    tenant_id: str
    target_name: str
    target_id: str
    current_user_messages: list[str]
    conversation_summary: str
    current_conversation_facts: dict[str, Any]
    brain_plan_summary: dict[str, Any]
    draft_segments: list[str]
    authority_evidence_summary: dict[str, Any]
    hard_guard_summary: dict[str, Any]
    account_rules_summary: str
    risk_level: str
```

```python
@dataclass
class QualityReviewResult:
    verdict: str
    confidence: float
    semantic_errors: list[str]
    hard_boundary_concerns: list[str]
    repair_instruction: str
    customer_visible_risk: str
    reason: str
    raw_response: str
    model: str
    elapsed_ms: int
    unavailable: bool = False
```

## 4. Prompt 设计

### 4.1 System Prompt 要点

审稿模型必须被限制为“审稿人”，而不是“客服”：

```text
你是微信客服回复质量审稿人，不是客服本人。
你只判断候选回复是否适合发送。
你不能生成客户可见回复。
你不能授权商品事实、价格、库存、政策或承诺。
商品事实只能来自 product_master。
政策事实只能来自 formal_knowledge。
如果候选回复有事实越权疑虑，请在 hard_boundary_concerns 中指出。
如果只是表达、上下文、答题方向问题，请在 semantic_errors 中指出，并给出 repair_instruction。
只输出 JSON。
```

### 4.2 审稿维度

Prompt 中应明确审稿维度：

- Direct answer：是否回答当前问题。
- Context binding：是否正确使用当前会话偏好和上一轮内容。
- No drift：是否跑题或沿用错误上下文。
- No repeated ask：是否重复问已经知道的信息。
- Human tone：是否自然、有人情味、不像模板。
- Off-topic handling：无关话题是否先友好回应，再软引导。
- Evidence discipline：是否只用已授权事实。
- Segment quality：多段是否每段完整，不像机械拆句。
- Conversation action：是否合理推进，例如推荐、解释、确认、邀约、转人工。

### 4.3 输出 JSON Schema

```json
{
  "verdict": "pass|repair|block|handoff_suggest",
  "confidence": 0.0,
  "semantic_errors": [
    "does_not_answer_current_question"
  ],
  "hard_boundary_concerns": [
    "unsupported_product_price"
  ],
  "repair_instruction": "Ask Brain to answer the current price question directly using the authorized product evidence, and avoid repeating the previous budget question.",
  "customer_visible_risk": "low|medium|high",
  "reason": "Short explanation for audit."
}
```

## 5. 接入流程

### 5.1 Brain 输出后

在 `customer_service_brain.py` 中，Brain 生成 draft 后进入：

1. 原有 BrainPlan parse 和 normalize。
2. 确定性硬 guard。
3. 轻量语法 guard。
4. LLM 语义审稿。
5. 必要时 Brain 修复一次。
6. 修复后重新跑硬 guard。
7. 最终可见校验/微润色。
8. 微润色候选 guard；若候选改变 Brain 语义，则采用 Brain 原草稿并记录审计。

### 5.2 Suspicious 判断

`suspicious_only` 模式下，下列情况触发语义审稿：

- 客户本轮包含问号、价格、推荐、比较、贷款、置换、车况、保险、售后等业务 intent。
- Brain draft 中包含较多反问，但客户已经给出关键信息。
- Brain draft 与当前客户消息关键词重合度很低。
- Brain draft 没有任何已授权 evidence ref，但包含业务事实。
- 客户连续追问或表达不满。
- draft 过长、拆段异常、含省略号或明显模板句。
- 多会话上下文存在切换风险。

低风险问候、结束语也不能绕过最终可见层；Brain 来源回复走 `llm_micro_verify`，默认原样返回，只允许极小表达修整。

### 5.3 Brain 修复

如果 reviewer 返回 `repair`：

- 把 `repair_instruction` 加入 Brain repair prompt。
- 同时传入原 BrainPlan、原 draft、当前消息、证据摘要。
- 要求 Brain 只修复当前问题，不扩展新事实。
- 修复后重新跑硬 guard。
- 最多一次。

### 5.4 Handoff 建议

如果 reviewer 返回 `handoff_suggest`：

- 不能直接转人工。
- 必须交给现有 hard handoff guard 判定。
- 如果正式知识库没有要求转人工，可要求 Brain 给出更谨慎的普通回复。

## 6. 审计字段

`customer_service_brain` 事件建议增加：

```json
{
  "quality_gate_v2": {
    "enabled": true,
    "mode": "suspicious_only",
    "review_invoked": true,
    "review_verdict": "repair",
    "review_confidence": 0.86,
    "semantic_errors": ["does_not_answer_current_question"],
    "hard_boundary_concerns": [],
    "repair_applied": true,
    "repair_success": true,
    "review_elapsed_ms": 1340,
    "cache_hit": false,
    "soft_pass": false
  }
}
```

这些字段用于复盘：

- 是否 Brain 本身理解错。
- 是否质量门误杀。
- 是否 reviewer 超时。
- 是否修复后质量提升。
- 是否存在会话错位风险。

## 7. 迁移软规则

### 7.1 保留为硬规则

- unsupported product fact
- unsupported policy claim
- AI exposure
- cross-session send
- empty reply
- truncated reply
- high-risk no handoff
- final polish bypass

### 7.2 迁移为 LLM 语义审稿

- 答非所问。
- 过度模板化。
- 重复问预算或车型。
- 没有接住客户上一轮补充。
- 对明确选择题不敢给建议。
- 闲聊回应生硬。
- 多问题漏答。
- 语气不像真人客服。
- 上下文轻微漂移。
- 错别字、别名、同义意图未被理解。

### 7.3 Shadow 观测后再决定

部分规则不确定是否会误杀，先进入 shadow：

- 关键词重合度低。
- 回复过短。
- 回复过长但已拆段。
- 缺少行动推进。
- 推荐数量与客户需求不完全一致。

## 8. 性能优化

### 8.1 减少 Brain 大请求

- 限制历史上下文长度。
- 只传最相关商品和正式知识。
- 将 AI 经验池作为风格摘要，不传大量原文。
- 当前轮多条消息先合并语义摘要，再给 Brain。

### 8.2 审稿小请求

- 审稿只需要候选回复和摘要，不需要完整知识库。
- 输出只允许小 JSON。
- 失败不重试多次。
- 审稿与最终可见层不可互相重复生成长文本。

### 8.3 最终可见层短链路

- Brain 的 `reply_segments` 必须已接近最终客户可见短句，但仍需经过轻量校验/自然化，不由润色层改写策略。
- 最终可见层使用微润色 prompt，优先原样返回。
- 微润色 token 默认 80，timeout 默认 5 秒。
- 微润色候选被 guard 拒绝时，不再让润色层阻断 Brain 安全回复，而是采用 Brain 原草稿。
- 缓存 key 包含 `brain_source_policy`，避免旧改写缓存污染短链路。

### 8.4 缓存

缓存 key 建议包含：

- tenant_id
- target_id
- current_user_messages digest
- conversation_summary digest
- brain_plan_summary digest
- draft_segments digest
- authority_evidence_summary digest

缓存只用于相同输入，不能跨会话复用。

## 9. 灰度路径

阶段一：文档和配置落地。

阶段二：新增模块和离线测试，默认 shadow。

阶段三：将 reviewer 审计写入事件，但不影响发送。

阶段四：开启 suspicious_only，替换部分软规则拦截。

阶段五：低风险实盘测试。

阶段六：根据日志决定是否扩大 always 模式或保持 suspicious_only。

## 10. 回滚方案

可通过配置回滚：

```json
{
  "customer_service_brain": {
    "quality_gate_v2_enabled": false,
    "semantic_reviewer_enabled": false
  }
}
```

回滚后：

- Brain First 主链路仍存在。
- 硬 guard 仍存在。
- 最终润色仍存在。
- 只是关闭 LLM 语义审稿和软规则迁移。
