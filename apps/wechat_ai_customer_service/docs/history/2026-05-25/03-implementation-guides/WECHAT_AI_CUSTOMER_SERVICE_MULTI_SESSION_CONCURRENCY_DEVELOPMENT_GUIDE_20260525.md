# 微信自动客服多会话并发调度开发指南（2026-05-25）

## 1. 开发原则

- 先拆调度，再优化性能。
- 先离线模拟，再实盘发送。
- 先保证队列不会丢，再保证延迟更低。
- RPA 操作保持串行，LLM worker 可并发。
- 所有新能力必须可通过配置关闭，回到旧串行链路。

## 2. 推荐模块拆分

### 2.1 `scheduler_state.py`

职责：

- 读写多会话调度状态文件。
- 提供文件锁和原子写。
- 管理 session、capture、llm task、reply queue。
- 提供状态迁移校验。

建议位置：

~~~text
apps/wechat_ai_customer_service/admin_backend/services/customer_service_scheduler_state.py
~~~

### 2.2 `session_monitor.py` 增强

当前 `SessionMonitor` 不能在未处理活跃会话超过上限时可靠保留 pending。需要：

- 将截断前的活跃会话全部写入 pending。
- 未处理会话不因下一轮没有变化而清除 `unread_detected`。
- 引入 `pending_since`、`last_detected_at`、`last_dispatched_at`。
- 若 RPA 会话列表缺少预览和时间，不能据此判定无新消息。

### 2.3 `capture_runner.py`

职责：

- 从 pending session 中选出本轮要读取的会话。
- 调用 `WeChatConnector.get_messages()`。
- 复用 history backfill、select_batch、gap guard。
- 捕获消息后写入 capture store。
- 快速返回，不调用 LLM。

可先复用 `listen_and_reply.process_target()` 中的读取前半段，再逐步拆出纯函数。

### 2.4 `llm_task_worker.py`

职责：

- 从 `llm_task_queue` 领取任务。
- 调用现有规则、商品库、RAG、意图、LLM 合成链路。
- 不操控微信。
- 完成后校验 `context_version`。
- 生成 ready reply 或 stale/failure。

第一阶段可以在 managed listener 父进程内用 `ThreadPoolExecutor`，后续再独立进程化。

### 2.5 `send_runner.py`

职责：

- 从 `send_queue` 取 ready reply。
- 串行调用 RPA。
- 复用现有 `detect_newer_messages_before_send()`。
- 发送成功后调用现有 mark processed / sent reply 逻辑。
- 发送 stale 时触发合并重算。

## 3. 分阶段落地

### Phase 0：文档与测试基线

- 完成本文件及配套契约、测试计划、风险登记。
- 固化当前串行行为的回归测试。
- 新增多会话调度模拟测试框架。

### Phase 1：状态队列与单元测试

- 新增 scheduler state 模块。
- 实现 session pending 队列。
- 实现 context_version。
- 实现 ready reply FIFO。
- 不接入真实微信，不调用真实 LLM。

验收：

- 10 个会话同时 pending，不丢失。
- 超过每轮处理上限后，剩余会话仍保持 pending。
- 同一会话版本递增后，旧 reply 自动 stale。

### Phase 2：RPA 捕获与 LLM 解耦

- 从 `process_target()` 拆出 capture-only 路径。
- 捕获后投递 LLM task，不等待模型。
- 保留旧 `process_target()` 作为 fallback。
- LLM task 可先用同步函数在线程池中运行。

验收：

- A 会话 LLM 慢时，B/C 会话仍可被读取。
- LLM 完成后写 ready reply。
- F8 暂停后停止新捕获和新发送。

### Phase 3：串行发送队列

- 新增 send runner。
- 接入 freshness check。
- 发送成功后写原有 audit、processed、raw capture。
- stale 后重新投递最新上下文。

验收：

- 多个 reply 同时 ready 时按 ready_at 发送。
- 同一会话新消息到达后旧 reply 不发送。
- RPA 错误进入 send_failed，不重复盲发。

### Phase 4：实盘多会话灰度

- 开启 `concurrency_scheduler.enabled=true`。
- `llm_max_concurrency=2` 起步。
- `capture_max_sessions_per_round=3` 起步。
- 先 no-send，再文件传输助手/测试群，再真实联系人。

## 4. 兼容策略

### 4.1 旧链路保留

默认关闭新调度器：

~~~json
{
  "concurrency_scheduler": {
    "enabled": false
  }
}
~~~

关闭时仍走当前 `listen_and_reply.py --once` 串行流程。

### 4.2 事件兼容

现有 audit 字段不能删除。新增字段应以 `scheduler_*` 命名，并嵌入事件对象或附加日志。

### 4.3 状态兼容

旧 state 中的：

- `processed_message_ids`
- `processed_content_keys`
- `handoff_message_ids`
- `sent_replies`
- `reply_timestamps`

仍是最终去重权威。新 scheduler state 是调度状态，不替代最终处理记录。

## 5. 关键实现注意事项

### 5.1 不要让 LLM worker 操作微信

LLM worker 只能读取持久化 capture 和知识库。任何 `WeChatConnector.get_messages()` / `send_text()` 都必须留在 RPA runner。

### 5.2 不要依赖内存队列作为唯一状态

进程重启、watchdog timeout、电脑休眠后，队列必须能恢复。内存队列只能作为性能缓存。

### 5.3 不要清掉未处理 pending

会话列表没有变化，不等于消息已处理。只有以下动作可以清 pending：

- capture 成功且没有新候选消息。
- reply sent 并完成 processed mark。
- operator 明确忽略。
- TTL 到期并进入 expired/audit，而不是静默删除。

### 5.4 同一会话版本必须强校验

同一会话内客户补充消息时，旧 LLM 输出不能发送。必须使用 `context_version` 或消息 content key 集合校验。

### 5.5 发送队列要有 backpressure

若 `send_queue` 积压过多：

- 降低 capture 频率。
- 暂停新 LLM task。
- runtime status 显示积压。
- 必要时触发人工提示。

## 6. 推荐代码复用点

可复用：

- `parse_targets()`
- `maybe_enrich_messages_with_history()`
- `select_batch_details()`
- `plan_message_batch_semantics()`
- `detect_newer_messages_before_send()`
- `mark_processed()`
- `mark_coalesced_messages()`
- `WeChatConnector` RPA lock
- managed listener 风控与 F8 operator guard

需要拆分：

- `process_target()` 中读取、决策、发送耦合过深，需要拆成 capture、build reply、send 三段。

## 7. 可观测性

runtime status 应增加：

- `pending_sessions`
- `llm_running`
- `ready_replies`
- `send_queue_depth`
- `oldest_unreplied_seconds`
- `last_scheduler_event`
- `scheduler_paused_reason`

悬浮球和总控台状态：

- 蓝色：运行中，队列正常。
- 黄色：暂停或积压明显。
- 红色：风险停机或发送失败。

## 8. 完成定义

开发完成必须同时满足：

- 新调度器关闭时旧链路完全可用。
- 新调度器开启时多会话模拟测试通过。
- RPA-only 证明仍成立，不走 wxauto4。
- 多会话实盘 no-send 和 send 测试通过。
- 长测无丢消息、无重复发送、无串会话、无白屏放大问题。
