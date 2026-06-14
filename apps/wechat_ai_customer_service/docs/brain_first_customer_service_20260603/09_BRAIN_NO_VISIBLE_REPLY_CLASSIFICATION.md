# Brain No Visible Reply 分类审计与吞消息防护

## 关联硬基线

本方案继承并引用 [`../customer_visible_reply_ownership_baseline.md`](../customer_visible_reply_ownership_baseline.md)：

- 所有客户可见回复必须由 `customer_service_brain` 发出。
- Guard、质量门、语义审稿、RAG、实时路由、本地模板、旧合成器、最终润色和兜底模块只能提供证据、审稿意见、风险信号或轻量校验，不能替 Brain 写客户可见话术。
- Brain 不可用、超时、不可采纳、返修失败、JSON 结构失败或 guard/质量门无法放行时，必须阻断发送并保留未回复状态，不能发送本地 safe fallback。

## 目标

把“Brain 没有产出客户可见回复”从一个模糊失败，拆成可审计、可重试、可告警的状态机。

目标行为：

- 正常低风险消息，尤其是短问候、催促、感谢、告别、普通闲聊，Brain 必须尽量产出自然短回复。
- Brain 首次失败时，优先对同一个 capture 做后台重试，不重新 RPA 操作微信。
- JSON 解析失败时，先做一次结构修复重试，再判定失败。
- Guard 或质量门失败时，优先把问题反馈给 Brain repair，而不是直接阻断。
- 多次失败后，保留未回复状态并触发内部告警/转人工接口。
- 永远不允许“读了消息后清空 pending / 标记 processed，导致已读不回”。

## No Visible Reply 分类

统一在 Brain payload 中写入：

```json
{
  "no_visible_reply": {
    "class": "schema_parse_failed",
    "stage": "brain_llm",
    "retryable": true,
    "same_capture_retry": true,
    "customer_visible_reply_blocked": true
  }
}
```

分类表：

| class | stage | 说明 | 默认动作 |
| --- | --- | --- | --- |
| `llm_timeout` | `brain_llm` / `repair_llm` | 上游超时、连接中断或 transient 失败 | 同 capture 重试或 failover |
| `llm_unavailable` | `brain_llm` / `repair_llm` | API key、模型、路由不可用 | 同 capture 重试；多次失败告警 |
| `schema_parse_failed` | `brain_llm` / `repair_llm` | LLM 返回不是合法 JSON 对象 | 结构修复一次；失败后同 capture 重试 |
| `schema_invalid` | `plan_validation` | BrainPlan 字段缺失、action/mode 非法 | Brain repair |
| `empty_reply_segments` | `plan_validation` / `quality` | send_reply 却没有可见句子 | Brain repair；短社交消息必须修复 |
| `social_reply_missing` | `plan_validation` | 问候、催促、感谢、告别没有回复 | Brain repair，同 capture 重试 |
| `guard_repair_failed` | `guard` | Guard 发现问题，Brain repair 后仍无法通过 | 同 capture 重试；多次失败告警 |
| `quality_repair_failed` | `quality` / `semantic_review` | 质量门/语义审稿要求返修但修复失败 | 同 capture 重试；多次失败告警 |
| `context_insufficient` | `context` | 上下文不足但仍可由 Brain 作安全回应 | Brain repair；不得直接清空 pending |
| `duplicate_or_stale` | `scheduler` | 已有新上下文覆盖旧任务 | 不发送旧回复，不标记新消息已处理 |
| `ocr_metadata_only` | `capture` | OCR 只剩用户名/群成员名/标题等元数据 | 保留待重新捕获，不作为已处理正文 |
| `final_polish_failed` | `final_polish` | 最终润色失败但原 Brain reply 存在 | 同 capture 或同 reply 重试，不能本地改写 |

## 短消息必答合同

短问候、催促、感谢、告别、普通短闲聊属于低风险正常消息。它们不授权任何商品事实或政策承诺，但必须得到 Brain 的自然短回复。

实现要求：

- 在 `brain_input.runtime.reply_obligation` 中声明 `must_reply=true` 和消息类别。
- Prompt 明确要求 Brain 对这类消息输出 1 条自然短句，不得空回复、不得仅因此转人工。
- `validate_social_visible_reply_contract` 继续作为非话术型合同，只检查 Brain 是否产出可见回复，不写替代话术。

## JSON 结构修复

Brain 主调用或 repair 调用返回非 JSON 对象时：

1. 先用本地 JSON 提取器尝试解析完整对象。
2. 仍失败时，调用同一 LLM 路由做一次结构修复，要求只把原始输出改成 BrainPlan JSON，不新增事实、不回答客户。
3. 结构修复成功后继续进入 normalize/validate/guard。
4. 结构修复失败才进入 no-visible 分类 `schema_parse_failed`。

结构修复只修格式，不改变 Brain 决策权，也不能产生本地可见话术。

## Guard / 质量门协作

Guard、确定性质量门、语义 reviewer 都是审稿层。

- 软问题必须转成 Brain repair feedback。
- 硬边界也应尽量让 Brain 自己生成边界说明或转人工类 BrainPlan。
- reviewer 不能直接给客户可见兜底句。
- repair 失败时输出 no-visible 分类，不输出本地 fallback。

## Scheduler 防吞消息

Scheduler 对 no-visible 失败必须执行：

- 已捕获的真实 OCR 消息：同 capture 重新排队给 Brain，不重新切微信窗口。
- monitor-only 短预览：允许低扰动重新捕获一次。
- 重试期间保留 `pending_message_count`、`oldest_unreplied_at`、`llm_inflight_task_id` 或 queued task。
- 多次失败后保留未回复状态，并记录 operator alert / handoff case。
- 只有成功发送后，才能写入 `processed_message_ids` / `processed_content_keys`。

## OCR 正文清洗

OCR/RPA 识别到的会话名、群成员名、发送者名只作为元数据，不进入 Brain 正文。

实现要求：

- `current_message.clean_text` 使用正文语义文本。
- `current_message.raw_text` 可保留原始内容用于审计，但 prompt 必须标注 speaker/title 是 metadata。
- 若清洗后正文为空，分类为 `ocr_metadata_only`，不得当作客户消息已处理。

## 测试清单

静态测试：

- Brain no-visible payload 必须包含分类字段。
- 客户可见回复所有权仍只允许 Brain。
- Guard / quality / reviewer 不得新增客户可见固定话术。

合同测试：

- 短问候、催促、感谢、告别空回复必须触发 Brain repair 或 no-visible 分类。
- JSON 解析失败必须执行一次结构修复。
- 结构修复成功后可继续进入正常 BrainPlan 链路。
- 结构修复失败时不能使用 legacy fallback。

Scheduler 测试：

- `schema_parse_failed`、`llm_timeout`、`brain_quality_verification_failed`、`brain_guard_rejected` 都能进入同 capture 重试。
- 同 capture 重试不触发 RPA recapture。
- 重试耗尽后保留未回复状态并记录告警，不写 processed。

OCR 测试：

- `许聪：在吗` 在群聊中应拆成 speaker metadata + 正文 `在吗`。
- 只有 `许聪：` 或会话标题时应判定 metadata-only，不进入 Brain 可见回复流程。

## 验收标准

- 所有相关单元/模拟测试通过。
- no-visible 失败均有明确分类和阶段。
- 低风险短消息不再静默空回复。
- 失败重试使用同 capture，不产生额外 RPA 切会话。
- 成功发送前不标记 processed，不清空未回复状态。
