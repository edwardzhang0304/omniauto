# P10 同目标多段续发优化

日期：2026-06-21

## 目标

在不改变现有框架、变量名称、CLI 路由、JSON 输出契约、外部 API 和 Brain First 架构的前提下，优化微信 AI 客服“同一个回复被拆成多段气泡发送”时的重复 RPA 成本。

P10 只处理一个窄场景：同一目标会话、同一次回复、第二段及之后的续发。它不改变回复生成、不改变分段策略、不跳过最终发送校验，也不通过缩短超时上限来换速度。

## 当前问题

多段发送已有两项安全优化：

- 默认只在最后一段做发送回读校验。
- 第二段及以后跳过同一次回复内的发送频率保护。

但每一段实际调用 Win32/OCR send 时，仍会先进入 `ensure_target_ready_for_send`，再进入 `send_payload`。对于同一个目标会话的连续气泡，第一段已经完成打开会话、目标确认、输入区确认和发送后校验；第二段及以后继续完整跑 target_ready，会产生重复的会话打开/确认成本。

## 不可越界边界

- 不改 `add-friend-entry-click-plan` 等既有 CLI 路由名。
- 不改 worker-facing CLI 入参和 JSON 输出契约。
- 不改现有变量、常量、公开函数名、配置路径和 artifact scope。
- 不让本地模板、fallback、guard、RAG 或 realtime route 编写客户可见回复。
- 不绕过 Brain、final polish、freshness、session envelope、target/session 防串发检查。
- 不绕过发送前目标确认、输入框确认、发送后 blank-render 防护。
- 不用“降低超时上限、到点截断、不出结果也继续”的方式优化速度。

## 方案

新增一个内部“同目标续发 fast path”，只在多段回复的第二段及以后、且第一次尝试发送该段时启用。

执行方式：

1. workflow 在发送 follow-up segment 时进入内部续发上下文。
2. connector 不改 `send_text` / `send_text_and_verify` 对外参数，通过 ContextVar 给本次调用追加内部环境变量。
3. sidecar 收到 `WECHAT_WIN32_OCR_CONTINUATION_SEND_FAST_PATH=1` 后，不再重复执行 `ensure_target_ready_for_send`。
4. sidecar 直接进入 `send_payload(..., validated_guard=None)`，因此仍会运行严格的 `validate_active_send_target` pre-send OCR 校验。
5. 如果续发 fast path 因前台漂移、目标不匹配、几何异常等失败，返回原有 retryable 状态；workflow 的下一次重试不再启用 fast path，自动回到原来的完整路径。

关键点：P10 只跳过“重复打开/准备目标会话”的外层步骤，不跳过真正授权客户可见发送的 pre-send guard。

## 观测字段

只增加 additive 字段，不替换旧字段：

- workflow phase: `same_target_continuation_fast_path`
- segment result: `same_target_continuation_fast_path`
- sidecar timing: `target_ready_continuation_fast_path`、`target_ready_skipped_for_continuation`

旧字段、旧结构、旧判断逻辑继续可用。

## 测试计划

1. 静态编译 touched Python 文件。
2. workflow 逻辑测试：
   - 续发段首尝试启用 fast path。
   - 首段不启用 fast path。
   - 续发段 fast path 失败后，重试自动回到完整路径。
   - 原有分段、最后一段校验、逐段校验、input_not_ready 不重试规则保持不变。
3. Win32/OCR compat 测试，确认新增 env 开关不破坏既有 send/guard 行为。
4. RPA 动作风险测试，确认没有新增机械重复点击、键鼠并发或危险 fallback。
5. 低量实盘验证：
   - 优先用已有三会话/双会话自问自答流程。
   - 观察多段回复第二段及以后是否出现续发 timing。
   - 若出现任何 blank_render、target_not_confirmed、错发风险，停止并回滚该 slice。

## 预期收益

对单段短回复没有影响。对被拆成 2-3 段的较长回复，理论上每个续发段可少一次外层 target_ready/open_chat 成本；实际收益取决于当前窗口是否已稳定停留在同一会话。安全失败时自动回落到旧路径，优先保证可用性和不串发。
