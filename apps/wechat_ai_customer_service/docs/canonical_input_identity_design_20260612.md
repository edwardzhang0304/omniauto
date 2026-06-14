# Canonical Input Identity 统一主键改造方案（2026-06-12）

## 客户可见回复所有权硬基线

本方案继承 [customer_visible_reply_ownership_baseline.md](customer_visible_reply_ownership_baseline.md)。本轮只改造代码机制层的消息身份、账本和调度主键，不改变 Brain First 架构，不让代码机制层、Guard、质量门或任何本地模板生成客户可见回复。

## 1. 背景问题

RPA/OCR 模式下，微信消息没有 wxauto4 那种稳定控件消息对象。当前 OCR 原始 `id` 主要由：

```text
target + 消息方向 + 气泡纵坐标 + 文本内容
```

计算而来。它适合识别同一个可见气泡，但不适合作为完整业务主键：

- 客户隔一段时间重复发同一句短消息，可能被旧 OCR id 或旧 content key 吞掉。
- 客户隔一段时间重复发同一句长消息，如果气泡位置相近，也存在被误判为旧消息的理论风险。
- scheduler、workflow、ledger、reply envelope 之间如果各自使用不同身份规则，会导致“读到了但不回”“只回一个会话”“发送前校验不足”等问题。

## 2. 设计目标

新增统一业务主键 `canonical_input_id`：

- 每条进入客服回复链路的客户输入，都优先使用 `canonical_input_id` 作为业务身份。
- `canonical_input_id` 从 `MessageEnvelope` 源头生成，并在 workflow、scheduler、session ledger、reply envelope 中双写双读。
- OCR 原始 `id/message_id` 保留为视觉证据和兼容字段，但不再作为唯一业务主键。
- 旧账本和旧运行状态继续兼容，避免历史记录被重新当作新消息。

## 3. 双层身份模型

### 3.1 `canonical_visual_id`

表示“屏幕上这个可见气泡”的稳定身份，用于避免同一个旧气泡被反复 OCR 重扫后重复回复。

组成原则：

- `source_adapter`
- `conversation_id / target_name / conversation_type`
- `sender / sender_role / speaker_name`
- `message_id / bubble_id`
- `content_body`
- `bubble_rect`

不得包含单纯程序读取时间 `captured_at`，否则同一旧气泡每次截图都会变成新消息。

### 3.2 `canonical_input_id`

表示“一次客户输入发生”的业务身份，是调度、账本、Brain task、ready reply 和发送核验的主键。

默认情况下：

```text
canonical_input_id = canonical_visual_id
```

当存在可信发生信号时升级为 occurrence-aware：

- `pending_signal_id`
- `pending_since`
- `last_detected_at`
- `last_message_time`
- `screen_time_text`
- 对短问候/催促/感谢/告别等可重复短句，可继续使用 `message_time/time/captured_at` 作为发生兜底。

这样可以同时满足：

- 同一个旧气泡重扫不重复回复。
- 客户重复发同一句话时，有未读/预览/屏幕时间等发生信号即可生成新业务身份。

## 4. 链路合同

```text
OCR/RPA raw message
  -> MessageEnvelope
  -> canonical_visual_id + canonical_input_id
  -> workflow batch selection
  -> scheduler capture.message_ids
  -> llm_task.input_message_ids
  -> ready_reply.input_message_ids + message_content_digest
  -> send freshness/session envelope check
  -> ledger reply anchor
```

所有链路必须优先使用 `canonical_input_id`：

- `workflow.reply_input_message_identity`
- `scheduler_state.message_identity`
- `session_ledger.sanitize_ledger_message`
- `CapturedMessagesConnector` authoritative batch id
- reply envelope `input_message_ids`
- processed/handoff/replied anchors

## 5. 兼容策略

本轮采用“双写双读”：

- 新消息写入 `canonical_input_id` 和 `canonical_visual_id`。
- 旧字段 `id/message_id/bubble_id` 不删除。
- 读取时优先使用 `canonical_input_id`。
- 若旧数据没有 canonical 字段，则按旧逻辑兜底到 `id/message_id/content_key`。

## 6. 非目标

本轮不做：

- 不修改 Brain 的回复策略。
- 不修改商品库、正式知识库、AI经验池或共享公共策略。
- 不改变 Guard/质量门/润色层权限。
- 不把具体车型、价格、业务话术写入代码。
- 不清理历史运行数据。

## 7. 测试清单

必须覆盖：

- envelope 输出 `canonical_visual_id/canonical_input_id`。
- 同一 OCR id + 同一长文本 + 不同 pending signal，应生成不同 `canonical_input_id`。
- 同一 OCR id + 同一长文本 + 无 pending signal，应保持稳定，防止旧气泡重扫重复回复。
- 短句重复提问仍能进入 Brain。
- scheduler capture、llm task、ready reply、ledger 均使用 canonical id。
- 多会话同名/不同 `session_key` 不串线。
- 旧字段无 canonical 时仍兼容。

## 8. 验收标准

- 静态语法检查通过。
- workflow logic checks 通过。
- multi-session scheduler checks 通过。
- win32 OCR compat checks 通过相关 envelope/RPA 主键用例。
- Brain First 静态架构审计通过。
- 无新增客户可见本地 fallback。
