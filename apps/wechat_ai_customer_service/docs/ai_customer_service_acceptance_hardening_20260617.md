# 微信 AI 客服双会话验收加固方案

> Customer-service development baseline: [`customer_visible_reply_ownership_baseline.md`](customer_visible_reply_ownership_baseline.md).

## 背景

2026-06-17 的双会话实盘验证暴露了两个不同层面的失败容易被混在一起：

- prompt-send 阶段：测试脚本先模拟“客户”给两个会话发问题。这里失败通常是 WeChat 输入框未确认、窗口焦点漂移、OCR 不可读等 RPA 输入问题。
- reply-send 阶段：客服系统读取合成客户消息，经 Brain、调度、最终 RPA 发送客服回复。这里失败可能是 Brain 没有产出客户可见回复，也可能是发送层阻断。

这两类问题如果只落成 `reply_timeout` 或 `prompt_send_failed`，会让排障方向偏掉。验收脚本必须把“RPA 输入没准备好”和“Brain no-visible”分开记录。

## 硬边界

- 客户可见回复仍只能由 `customer_service_brain` 或 Brain repair 产出。
- 验收脚本不得为 `customer_service_brain_no_visible_reply` 生成本地兜底话术。
- RPA 发送前必须继续执行目标会话确认、输入框确认、发送后确认。
- 输入框无法确认时必须停下，不允许盲发。
- 双会话验证必须保留 session_key、目标会话、已发送目标和缺失目标证据。

## 推荐验收拆分

默认验收客服链路时使用：

```powershell
.\.venv\Scripts\python.exe runtime\two_visible_session_customer_service_live.py --skip-prompt-send --synthetic-input-only --rounds 1
```

这个模式跳过“替客户发送提示语”的 RPA 前置动作，只把合成客户消息注入调度器，然后执行 Brain 规划和真实客服回复发送。它更适合判断客服模块有没有被改坏。

单独验证 prompt-send RPA 能力时再去掉 `--skip-prompt-send`。如果失败，应归类为 `prompt_send_rpa`，不等同于客服 Brain 失败。

低风险离线/预验收可以使用：

```powershell
.\.venv\Scripts\python.exe runtime\two_visible_session_customer_service_live.py --skip-prompt-send --synthetic-input-only --dry-reply-send --rounds 1
```

## 失败分类

验收脚本输出应包含 `failure_category` 和 `failure`。

| category | 含义 | 处理方向 |
| --- | --- | --- |
| `prompt_send_rpa` | 测试脚本替客户发送提示语时输入框、焦点或确认失败 | 修 RPA 输入确认、窗口焦点、截图/OCR 诊断，不动 Brain 出话权 |
| `brain_no_visible` | 没有任何客服回复发出，且 tick 中出现 `customer_service_brain_no_visible_reply` 或空闲无可见回复 | 按 Brain no-visible 分类、证据包、repair/重试链路排查 |
| `partial_brain_no_visible` | 部分会话已成功发送，另一个会话 Brain no-visible 或最终未产出 | 优先看缺失会话的 Brain 输入、session_key、上下文污染和 no-visible 事件 |
| `reply_send_rpa` | reply 阶段出现 `send_input_not_ready`、`target_not_confirmed` 等发送层硬阻断 | 修回复发送 RPA，不让调度器误标已处理 |
| `reply_timeout` | 超时但没有更明确硬信号 | 看 tick 活跃计数、LLM 队列、Brain/调度日志 |
| `sent_target_mismatch` | 发送成功但目标覆盖不对 | 优先查多会话绑定和发送前目标确认 |

## 诊断证据

`compact_send` 应保留：

- `state` / `reason` / `error`
- `pre_send_guard` / `post_send_guard`
- `window_probe`
- `input_mode` / `confirmed_by`
- `probe_token` / `probe_tokens`
- `input_region`
- `input_visual_confirm`
- `input_clear_reason`

这些字段用于判断点击是否落进输入框、输入框是否已有草稿、OCR 是否读到本轮 token、是否因为焦点漂移被阻断。

## 开发落点

本轮代码只改验收脚本的可观测性和失败归类：

- 保持 `runtime\two_visible_session_customer_service_live.py` 的现有双会话测试流程。
- prompt-send 失败时写入 `failure_category=prompt_send_rpa`。
- reply 阶段失败时根据 tick 事件、已发送目标覆盖和缺失目标归类。
- 自检覆盖 no-visible、partial no-visible、reply-send RPA 和 prompt-send RPA 摘要。

不修改 Brain 话术生成、不新增本地模板、不改变客户可见回复所有权。

## 验收矩阵

- `py_compile` 通过。
- `--self-check` 通过。
- `run_customer_service_brain_contract_checks.py` 通过。
- `run_customer_service_multi_session_scheduler_checks.py` 通过。
- `run_brain_first_static_architecture_audit.py` 通过。

如需实盘，先跑默认客服链路验收，再单独跑 prompt-send RPA 能力测。
