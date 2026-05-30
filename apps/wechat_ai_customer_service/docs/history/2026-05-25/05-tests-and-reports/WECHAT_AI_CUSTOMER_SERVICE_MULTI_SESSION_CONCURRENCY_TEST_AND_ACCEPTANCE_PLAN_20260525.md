# 微信自动客服多会话并发调度测试与验收计划（2026-05-25）

## 1. 测试目标

验证多个用户同时频繁与 AI 客服聊天时，系统能：

- 快速捕获多个会话的新消息。
- 并发执行 LLM 思考。
- 串行且安全地发送微信回复。
- 不漏消息、不重复回复、不串会话、不发送旧上下文回复。
- 在暂停、窗口异常、掉线、白屏、风控信号下安全停机或暂停。

## 2. 测试阶段

### 2.1 静态检查

命令：

~~~powershell
python -m py_compile apps/wechat_ai_customer_service/workflows/listen_and_reply.py apps/wechat_ai_customer_service/scripts/run_customer_service_listener.py apps/wechat_ai_customer_service/admin_backend/services/session_monitor.py apps/wechat_ai_customer_service/adapters/wechat_win32_ocr_sidecar.py apps/wechat_ai_customer_service/adapters/wechat_connector.py
~~~

新增模块后追加 py_compile。

通过标准：

- 无语法错误。
- 无导入循环。
- 旧链路导入不依赖新调度器必须存在的 runtime state。

### 2.2 单元测试

必须覆盖：

- 10 个会话同时 pending，每轮处理上限为 3，剩余 7 个保持 pending。
- 会话列表下一轮无变化时，未处理 pending 不被清除。
- 同一会话 context_version 递增，旧 LLM task 完成后 stale。
- 多个会话 LLM task 同时完成，send queue 按 ready_at 排序。
- 同一会话两个 reply ready，只保留最新可发送。
- freshness check 发现新消息，旧 reply stale 并 requeue。
- F8 pause 状态下不 capture、不 send、不派发新 LLM。

### 2.3 集成模拟测试

使用 fake connector 模拟：

- 会话列表。
- 每个会话的消息窗口。
- LLM 延迟和完成顺序。
- RPA 发送成功/失败。

场景：

| 场景 | 输入 | 预期 |
|---|---|---|
| 三会话同时发消息 | A/B/C 各 1 条 | 三个 LLM 并发，发送 FIFO |
| A 慢 B 快 | A LLM 20 秒，B LLM 2 秒 | B 不被 A 阻塞 |
| A 补充消息 | A v1 LLM 运行中，A 又发 v2 | v1 stale，v2 重新生成 |
| 发送前新消息 | reply ready 后目标会话新增消息 | 不发送旧 reply |
| 发送失败 | RPA input unavailable | reply send_failed，停机或重试按配置 |
| pending 超限 | 10 会话，轮处理 3 | 不丢 7 个 pending |

### 2.4 真实微信 no-send 测试

目标：

- 验证 RPA-only 会话发现和捕获。
- 不发送任何客户可见消息。
- 检查队列状态、悬浮球和总控台。

流程：

1. 启动微信并登录。
2. 启动自动客服 no-send 调度模式。
3. 用多个测试会话发送消息。
4. 检查 capture queue 和 LLM task 创建。
5. 禁止 send runner 实际发送。

通过标准：

- 所有测试会话均进入 pending/captured。
- 未进入本轮处理的会话仍保持 pending。
- RPA adapter 报告 `win32_ocr`。
- 无 wxauto4 执行。
- 无白屏、掉线、误点击。

### 2.5 真实微信受控 send 测试

目标：

- 验证完整收发闭环。

建议会话：

- 文件传输助手。
- 至少 1 个测试私聊。
- 至少 1 个测试群。

场景：

- 3 会话，每会话 3 条连续消息。
- 5 会话，每会话 5 条连续消息。
- A 会话 LLM 思考期间继续补 2 条。
- B/C reply 同时 ready，按 ready_at 发送。
- F8 暂停后不再发送，恢复后继续。

通过标准：

- 每个会话收到的回复只针对该会话。
- 每个会话的连续消息被合并理解。
- 无重复回复。
- 无旧上下文回复。
- 发送动作保持人类化 RPA。
- 悬浮球状态正确。

### 2.6 长测

建议：

- 30-60 分钟 no-send soak。
- 20-30 分钟低频 send soak。
- 人工不干预微信窗口。
- 中途测试最小化/恢复窗口。

通过标准：

- pending 不无限增长。
- LLM task 无 stuck。
- ready reply 无长期阻塞。
- transport risk 无停机。
- 微信无白屏、掉线、输入框异常。

## 3. 验收指标

| 指标 | 标准 |
|---|---|
| 漏消息 | 0 |
| 重复回复 | 0 |
| 串会话发送 | 0 |
| stale reply 误发 | 0 |
| wxauto4 使用 | 0 |
| RPA 操作并发冲突 | 0 |
| 发送前复检覆盖率 | 100% |
| F8 暂停生效时间 | 小于 1 秒停止新 RPA 操作 |
| 3 会话并发响应 | 全部完成，延迟可解释 |
| 5 会话压力 | 可排队处理，不丢 pending |

## 4. 验收红线

出现任一情况必须打回：

- 任一回复发错会话。
- 任一旧上下文回复在客户补充消息后仍发送。
- 任一 pending 会话未处理却被清除。
- 任一队列任务因进程重启永久丢失。
- 任一 RPA 并发操控微信。
- 任一默认启用 wxauto4 fallback。
- 任一微信掉线/登录窗口状态下继续发送。

## 5. 测试报告要求

每轮测试报告至少包含：

- 配置摘要。
- 会话数、消息数、LLM 并发数。
- capture/llm/send 队列事件统计。
- 每个会话的消息和回复对应关系。
- stale、failed、retry、handoff 统计。
- RPA adapter 证明。
- 截图或 runtime artifact 路径。
- 是否通过验收。

## 6. 推荐产物路径

~~~text
runtime/apps/wechat_ai_customer_service/test_artifacts/multi_session_concurrency/{run_id}/
~~~

建议文件：

- `report.json`
- `report.md`
- `scheduler_state_before.json`
- `scheduler_state_after.json`
- `managed_listener.log`
- `audit_tail.jsonl`
- `rpa_screenshots/`
