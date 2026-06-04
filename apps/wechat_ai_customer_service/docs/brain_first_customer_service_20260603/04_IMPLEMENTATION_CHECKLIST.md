# Brain First 实施检查清单

## 1. 代码前检查

- 已确认本轮只做客服回复链路，不改 RPA 底层。
- 已确认商品库仍为商品事实最高权威。
- 已确认正式知识库仍为政策流程最高权威。
- 已确认 AI经验池不作为事实依据。
- 已确认所有客户可见回复必须经过最终润色。
- 已确认多会话发送仍保持串行和发送前目标复核。
- 已确认旧链路必须保留为可回滚 fallback。

## 2. 新增模块检查

### 2.1 `customer_service_brain_contract.py`

- 定义 BrainInput。
- 定义 EvidencePackV2。
- 定义 BrainPlan。
- 定义 GuardResult。
- 定义 answer mode。
- 定义 schema version。
- 提供基础校验函数。

### 2.2 `customer_service_brain.py`

- 接收 BrainInput。
- 构造 Brain Prompt。
- 调用 LLM failover。
- 解析 BrainPlan。
- 调用 guard。
- 输出审计结果。
- 支持 shadow mode。
- 支持 fallback。

## 3. 主流程改造检查

文件：

```text
apps/wechat_ai_customer_service/workflows/listen_and_reply.py
```

检查项：

- Brain First 插入点早于 RAG reply 和 realtime local reply。
- hard safety precheck 仍早于 Brain。
- Brain First 模式下 RAG 不可跳过 LLM。
- Brain First 模式下 realtime local reply 不可覆盖正常业务回复。
- Brain 输出失败时 fallback 明确记录原因。
- fallback 回复仍经过 guard 和 final polish。
- event 日志包含 Brain 审计字段。

## 4. RAG / AI经验池检查

文件：

```text
apps/wechat_ai_customer_service/workflows/reply_evidence_builder.py
apps/wechat_ai_customer_service/workflows/rag_layer.py
apps/wechat_ai_customer_service/workflows/rag_answer_layer.py
```

检查项：

- AI经验池不进入 `content_basis`。
- 历史聊天事实不进入商品事实依据。
- RAG 命中不再设置“跳过 Brain”。
- RAG hits 标注来源和权限。
- style context 已脱敏。
- audit 记录 excluded sources。

## 5. realtime route 检查

文件：

```text
apps/wechat_ai_customer_service/workflows/realtime_reply_router.py
```

检查项：

- 正常业务场景不再生成最终客户回复。
- 推荐、报价、闲聊、追问、质疑由 Brain 处理。
- `foreground_llm_allowed = False` 只用于硬风险或系统异常。
- 本地固定回复只保留系统/安全/人工接管类。
- 具体车型、价格、库存不能写死在 route 中。

## 6. Guard 检查

文件：

```text
apps/wechat_ai_customer_service/workflows/llm_reply_guard.py
```

检查项：

- 校验 `facts_claimed`。
- 校验价格必须来自商品库。
- 校验库存、年份、公里数、车况必须来自商品库。
- 校验政策承诺必须来自正式知识。
- 校验 style/AI经验池没有被当事实。
- 校验回答和用户问题相关。
- 校验 1-3 条短句完整性。
- 校验无省略号截断。
- 校验不暴露 AI 或内部系统。

## 7. 最终润色检查

文件：

```text
apps/wechat_ai_customer_service/workflows/final_visible_llm_polish.py
```

检查项：

- Brain First 下强制执行。
- 润色不能新增事实。
- 润色不能改变价格、库存、公里数、政策。
- 润色不能改变 answer mode。
- 润色后仍经过轻量事实复核。
- 润色失败时按现有 required 策略停止或 fallback，不发送未润色草稿。

## 8. 多会话检查

文件：

```text
apps/wechat_ai_customer_service/admin_backend/services/customer_service_scheduler.py
apps/wechat_ai_customer_service/workflows/listen_and_reply.py
```

检查项：

- BrainInput 带 `conversation_id`。
- BrainPlan 带 `source_message_ids`。
- ready reply 入队时绑定 target/session。
- 发送前二次确认 target/session。
- A 会话失败不污染 B 会话。
- 简短消息不被低信息规则跳过。
- 同一会话连续发多条时可合并或续答，不漏第二条。

## 9. 配置检查

新增配置：

- `customer_service_brain.enabled`
- `customer_service_brain.mode`
- `customer_service_brain.fallback_to_legacy_on_error`
- `customer_service_brain.require_final_visible_polish`
- `customer_service_brain.max_reply_segments`
- `customer_service_brain.require_fact_claims`

检查项：

- 示例配置默认 `off`，避免改变现网行为；需要灰度时由控制台或租户配置显式切到 `shadow`。
- 可对租户启用。
- 可对单会话实盘启用。
- 可快速回滚。
- UI 或配置导出不会误导用户。

## 10. 日志检查

每条回复日志包含：

- Brain 开关和模式。
- Brain answer mode。
- 使用商品 ID。
- 使用正式知识 ID。
- 使用当前会话事实。
- 使用 common sense topics。
- 使用 style ids。
- 排除的 AI经验池来源。
- guard 通过/拒绝原因。
- final polish 结果。
- 分项耗时。

## 11. 禁止项

以下情况视为实现失败：

- 为了提速跳过最终润色。
- 为了覆盖场景继续硬编码车型推荐模板。
- RAG 命中后直接跳过 Brain。
- AI经验池文本被用作价格或车况依据。
- 候选知识直接参与客户回复。
- 多会话错发。
- 问候语被直接忽略。
- 无关闲聊被生硬答非所问。
- LLM 输出未经过 guard 即发送。

## 12. 交付前检查

- 静态检查通过。
- 单元/模拟测试通过。
- 旧链路 fallback 测试通过。
- File Transfer 低压实盘通过。
- chejin 单会话实盘通过。
- chejin 双会话实盘通过。
- 日志能解释每条回复为什么这么回。
- 若出现白屏、掉线、错发，必须停止并回滚分析。
