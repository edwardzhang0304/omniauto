# Brain层与代码机制层落地开发文档（2026-06-09）

## 客户可见回复所有权硬基线

本开发文档继承 [customer_visible_reply_ownership_baseline.md](customer_visible_reply_ownership_baseline.md)。任何代码落地都必须保证客户可见回复唯一来源是 `customer_service_brain`。

## 1. 开发目标

在不推翻现有商品库、正式知识库、AI经验池、Brain First、RPA账本优先机制的前提下，补齐两个显式层级：

1. `Brain层`
   - 收拢实时客服理解、策略、上下文、闲聊、泛推荐、模糊匹配、边界回复等运行时思考能力。

2. `代码机制层`
   - 收拢 OCR/RPA/调度/session/账本/发送核验/异常保护/性能预算/防机械动作等程序运行能力。

## 2. 非目标

本轮不做：

- 不重做商品库、正式知识库和 AI经验池底层存储。
- 不删除已有历史文档，只更新当前索引和新增前置文档。
- 不把具体车型、价格、商品推荐写入代码策略。
- 不新增本地客户可见 fallback。
- 不让代码机制层或 Guard 层接管回复内容。

## 3. 总体实施顺序

```text
阶段0：文档与归属基线
阶段1：层级标注与审计工具
阶段2：Brain层合同收束
阶段3：代码机制层合同收束
阶段4：旧模板和旧路由降权
阶段5：共享公共策略纠偏
阶段6：测试矩阵与实盘前验收
```

## 4. 阶段0：文档与归属基线

### 4.1 新增文档

- `brain_code_mechanism_layer_integration_design_20260609.md`
- `brain_code_mechanism_layer_rule_inventory_20260609.md`
- `brain_code_mechanism_layer_implementation_plan_20260609.md`
- `brain_code_mechanism_layer_test_acceptance_plan_20260609.md`

### 4.2 更新索引

- `docs/README.md` 增加新分层文档入口。
- `AGENTS.md` 增加 Brain层和代码机制层基本约束。

## 5. 阶段1：层级标注与审计工具

### 5.1 新增层级枚举

建议新增轻量合同模块，例如：

- `workflows/layer_contracts.py`

建议枚举：

```text
product_master
formal_knowledge
current_conversation_fact
shared_public_strategy
llm_common_sense
style_memory
ai_experience_pool
review_candidate
customer_service_brain
reviewer_guard
reviewer_quality
reviewer_polish
code_mechanism
legacy_advisory
test_fixture
```

### 5.2 给证据包增加 layer attribution

`reply_evidence_builder.py` 输出的证据应显式标注：

- `source_layer`
- `authority_level`
- `can_authorize_fact`
- `can_influence_style`
- `can_influence_strategy`
- `must_not_authorize`

### 5.3 新增静态审计

新增或扩展测试脚本：

- 非 Brain 客户可见出口扫描。
- 运行时代码具体商品词扫描。
- legacy route 是否仍能发送扫描。
- guard/quality 是否返回可见文本扫描。
- AI经验池来源是否进入事实依据扫描。
- code mechanism 字段是否进入可见文本扫描。

## 6. 阶段2：Brain层合同收束

### 6.1 收束目标

把以下内容明确归为 Brain层：

- 短问候、感谢、告别、催促必须自然回复。
- 客户泛推荐时，Brain 应在商品库候选内给方向，不应无意义绕圈。
- 客户明确偏好纯电、MPV、SUV、预算、用途时，Brain 应主动扩大相关商品候选并给结论。
- 客户连续试探 AI、闲聊、找茬时，Brain 应先接住情绪；两三轮无业务意图后弱化业务牵引。
- 客户说“刚才/前面/这两台/别再问预算”时，Brain 必须读取会话上下文。
- Brain 应能使用常识做非事实型分析，但不能编造商品/政策事实。

### 6.2 代码落点

可能涉及：

- `workflows/customer_service_brain.py`
- `workflows/customer_service_conversation_strategy.py`
- `workflows/customer_service_brain_contract.py`
- `workflows/customer_service_quality_reviewer.py`
- `workflows/final_visible_llm_polish.py`

### 6.3 关键约束

- 不能把具体车型写进 Brain prompt 作为偏置。
- 不能把测试案例变成硬规则。
- 质量门发现问题后只返修 Brain，不直接替换文本。

### 6.4 会话策略状态落地

连续闲聊、套话、身份试探和抗拒业务牵引，按 [conversation_strategy_state_design_20260609.md](conversation_strategy_state_design_20260609.md) 落地。

建议新增：

- `workflows/customer_service_conversation_strategy.py`
  - `classify_conversation_strategy_signal(...)`
  - `update_conversation_strategy_state(...)`
  - `build_conversation_strategy_brain_hint(...)`
  - `reset_strategy_state_on_business_intent(...)`

落地原则：

- 状态按 `session_key` 隔离，写入当前会话账本或 `target_state.conversation_strategy_state`。
- 状态只包含节奏、疲劳度、抗拒牵引、最近业务锚点等 metadata。
- 状态进入 Brain 输入时必须标注为 `non_authoritative_strategy_hint`。
- Brain 使用该状态决定牵引强度，但客户可见回复仍只来自 `BrainPlan.reply_segments`。
- Guard/质量门发现过度业务牵引，只能给 Brain repair instruction，不得代写回复。
- 客户重新提出业务问题时，状态应立即恢复 `normal/resume_business`，不能因为前面闲聊而拒绝服务。

## 7. 阶段3：代码机制层合同收束

### 7.1 收束目标

把以下内容明确归为代码机制层：

- `session_key`
- `capture_id`
- `message_digest`
- `context_version`
- `reply_id`
- `ledger_state_version`
- `last_visible_anchor`
- `freshness_check`
- `send_target_confirmation`
- `unread_signal`
- `preview_signal`
- `ocr_observation`
- `rpa_action_guard`
- `operator_guard`

### 7.2 代码落点

可能涉及：

- `admin_backend/services/customer_service_session_ledger.py`
- `admin_backend/services/customer_service_scheduler.py`
- `admin_backend/services/customer_service_scheduler_state.py`
- `admin_backend/services/session_monitor.py`
- `adapters/wechat_win32_ocr_sidecar.py`
- `scripts/run_customer_service_listener.py`
- `workflows/listen_and_reply.py`

### 7.3 关键约束

- 账本优先，OCR 辅助。
- OCR speaker label 永远是 metadata，不是正文。
- 发送前必须核验 active session 与 reply envelope。
- 未确认归属时不发送。
- 代码机制层不能生成客户可见回复。

## 8. 阶段4：旧模板和旧路由降权

### 8.1 目标

把旧路线统一降级：

- `realtime_reply_router.py`
- `llm_reply_synthesis.py`
- `reply_style_adapter.py`
- `customer_intent_assist.py`
- `listen_and_reply.py` 中的旧 fallback 与模板分支。

### 8.2 处理方式

- Brain First 开启时，旧模块只允许输出：
  - intent hint
  - evidence hint
  - risk hint
  - style hint
  - repair instruction
  - audit field
- 不允许输出可发送客户文本。

### 8.3 验收

- 运行事件中 `visible_reply_source` 必须是 `brain_plan.reply_segments`。
- `legacy_generators_disabled` 必须为 true。
- 如果 Brain 失败，事件应为 no visible reply，并触发内部告警。

## 9. 阶段5：共享公共策略纠偏

### 9.1 目标

清理共享公共知识和缓存中的旧式规则，尤其是：

- “没有足够依据就转人工”
- “超出知识库就转人工”
- “客户闲聊必须立即拉回业务”

### 9.2 新口径

- 软缺证据：反馈给 Brain，让 Brain 自然追问、说明需核实或给常识范围内建议。
- 硬边界：正式知识或平台安全规则要求时，Brain 生成安全边界回复或转人工说明。
- 闲聊：先自然回应，轻量牵引；连续无业务意图时弱化牵引。

### 9.3 数据落点

- `data/shared_knowledge/global_guidelines`
- `data/shared_knowledge/reply_style`
- `data/shared_knowledge/risk_control`
- VPS shared library 的对应正式共享知识。

## 10. 阶段6：测试与验收

落代码后按 [brain_code_mechanism_layer_test_acceptance_plan_20260609.md](brain_code_mechanism_layer_test_acceptance_plan_20260609.md) 执行：

1. 静态审计。
2. 离线模拟。
3. 机制模拟。
4. 多会话调度模拟。
5. 自问自答实盘低压测试。
6. 手动实盘验收。

新增必测：

- 连续三轮闲聊后不再强行拉回上一台车。
- 客户明确说“别老聊车/别套话”后，Brain 先接住情绪，不继续硬推预算或车型。
- 连续闲聊后客户重新问商品，系统立刻恢复业务回答。
- A 会话连续闲聊不影响 B 会话业务推荐。

## 11. 风险与缓解

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| 旧模板仍有可见出口 | 破坏 Brain 唯一出口 | 静态扫描 + contract tests |
| Guard 再次越权 | 误转人工、答非所问 | Guard 只输出 repair instruction |
| AI经验池被误当事实库 | 回答过期信息 | source authority gate |
| 代码机制层误把 OCR label 当正文 | 答非所问 | speaker metadata contract |
| 多会话 reply 串线 | 严重商用风险 | session_key + digest + ledger 三重核验 |
| 共享旧规则污染 Brain | 软问题被硬转人工 | shared knowledge 纠偏审计 |

## 12. 完成定义

只有同时满足以下条件，才算本轮分层落地完成：

- 新分层文档进入 docs 索引。
- AGENTS 开发约束包含 Brain层和代码机制层。
- 运行时回复出口唯一性有测试保护。
- 代码机制字段有统一 envelope。
- AI经验池不会进入事实依据。
- 旧模板不能在 Brain First 下发送。
- 共享公共策略旧口径完成纠偏。
- 多会话错发、短句漏回、闲聊误伤、商品候选漏召回均有模拟测试覆盖。
