# 微信自动客服多会话并发调度架构方案（2026-05-25）

## 1. 背景

当前微信自动客服已经完成纯 RPA 优先、窗口恢复、历史回补、语义批处理和风控保护。但此前实盘验证主要集中在单一会话、文件传输助手模拟、单客户连续刷屏和记录员导出。

真实客服场景中更常见的压力是：多个客户同时发消息，且每个客户都可能连续补充信息。若系统仍然把“读取会话、调用 LLM、等待回复、发送微信消息”绑定在同一个串行流程中，就会出现：

- A 客户触发慢 LLM 时，B/C/D 客户的新消息长时间不被读取。
- 高峰期间 RPA 只停留在一个窗口，其他会话的可见预览可能变化后又被覆盖。
- 发送旧回复前客户又补充新消息，若没有复检会造成答非所问。
- 多个客户排队时无法区分“已捕获等待思考”和“尚未读取”。

## 2. 当前链路审计

### 2.1 当前主循环

`run_customer_service_listener.py` 以 managed loop 方式周期性调用：

~~~text
listen_and_reply.py --once --send --write-data
~~~

`listen_and_reply.py` 每轮大致执行：

~~~text
读取配置
  -> 读取会话列表
  -> build_iteration_targets()
  -> for target in dynamic_targets:
       process_target()
         -> 切到会话
         -> 读取消息
         -> 历史回补
         -> 选择消息批次
         -> LLM/规则/RAG 生成回复
         -> 发送前复检
         -> RPA 发送
  -> 保存 state
~~~

这是正确的单线程 RPA 安全模型，但不是多会话高峰下的最优调度模型。

### 2.2 现有保护能力

- 全局 RPA lock：避免多个流程同时操控微信。
- 每会话 `processed_message_ids` 和 `processed_content_keys`：避免同一会话重复回复。
- history backfill 和 gap guard：单会话消息超出当前可见页面时尝试补读，无法确认连续性则暂停。
- freshness check：发送前发现同一会话又有新消息时，跳过旧回复。
- managed watchdog：防止单轮 RPA/LLM 过慢导致监听长期卡死。

### 2.3 关键缺口

- LLM 等待仍在 `process_target()` 内同步发生，阻塞后续会话读取。
- 会话列表活跃判断依赖预览文本/时间，但纯 RPA OCR 的会话列表数据仍不够完整。
- 活跃会话超过本轮上限时，未处理会话缺少 pending 持久化队列。
- 同一会话的“新消息已捕获但 LLM 正在思考”没有独立状态机。
- 发送队列没有全局 FIFO + 同会话 stale 复检的统一抽象。

## 3. 目标架构

目标是把“微信 RPA 串行操作”和“LLM 并发思考”拆成两个节奏：

~~~text
RPA 接收器（串行、快进快出）
  -> 会话 inbox / pending message store
  -> LLM 任务池（并发、有上限）
  -> ready reply queue
  -> RPA 发送器（串行、发送前复检）
  -> sent audit / stale replan
~~~

### 3.1 RPA 接收器

职责：

- 扫描会话列表，发现可能有新消息的会话。
- 以低扰动方式逐个切换会话并读取消息。
- 把新消息快照写入持久化队列。
- 不等待 LLM 完成。
- 不发送客户可见消息。

原则：

- 每次 RPA 操作时间短，避免停在一个会话里等模型。
- 发现高峰时按公平调度读取各会话，而不是只追最新活跃会话。
- 读取失败或 gap risk 时写状态，不静默吞掉。

### 3.2 LLM 任务池

职责：

- 从 pending message store 领取可处理会话。
- 为每个会话构造最新上下文。
- 并发执行 LLM/规则/RAG 回复生成。
- 把结果写入 ready reply queue。

原则：

- 全局并发数有限制，默认建议 2-3。
- 同一会话同一时间只允许一个 active LLM task。
- 同一会话出现新消息时，旧任务不一定中断，但完成后必须校验版本，旧版本不能进入发送队列。
- LLM 任务必须有 timeout、失败重试和 fallback 状态。

### 3.3 RPA 发送器

职责：

- 从 ready reply queue 取出已完成回复。
- 严格单线程操控微信。
- 发送前重新读取目标会话，做 freshness check。
- 若发现目标会话已有新消息，则标记当前回复 stale，并触发合并重算。
- 若多个回复同时 ready，按 ready_at 先后进入发送队列。

原则：

- 跨会话按 ready_at FIFO。
- 同一会话以最新上下文优先，不允许旧回复晚到后覆盖新消息。
- 发送后必须确认目标窗口仍然正确。
- 发送失败必须可重试或进入人工告警。

## 4. 调度模型

### 4.1 三条队列

| 队列 | 作用 | 操作者 |
|---|---|---|
| `capture_queue` | 待读取或待确认的新会话 | RPA 接收器 |
| `llm_task_queue` | 已捕获消息，等待生成回复 | LLM worker pool |
| `send_queue` | 已生成回复，等待 RPA 发送 | RPA 发送器 |

### 4.2 会话状态机

~~~text
idle
  -> suspected_unread
  -> capturing
  -> captured
  -> llm_queued
  -> llm_running
  -> reply_ready
  -> send_waiting
  -> sending
  -> sent

异常分支：
  -> capture_failed
  -> gap_risk_paused
  -> llm_failed
  -> reply_stale
  -> send_failed
  -> operator_handoff
~~~

### 4.3 同一会话版本号

每个会话维护 `context_version`：

- 每捕获到一批新客户消息，版本号递增。
- LLM 任务创建时记录 `input_context_version`。
- LLM 完成时，如果当前会话版本已经大于任务版本，则任务结果标记 `stale`。
- stale 任务不能发送，只能作为审计或诊断材料保留。

### 4.4 多会话公平性

调度优先级应由以下因素组合：

- oldest_unreplied_at：最早未回复消息时间，越早越优先。
- pending_message_count：积压消息数，越多越优先，但不能长期压制其他会话。
- last_capture_at：最近读取时间，过久未读取要提升优先级。
- risk_state：gap risk、发送失败、疑似登录异常必须暂停或告警。
- rpa_cooldown：微信 RPA 低扰动窗口，防止频繁切换。

建议策略：

- 接收器每轮最多读取 N 个会话，默认 3。
- 若 pending 会话超过 N，未读取会话必须保持 pending，不得清除。
- 每个会话每轮最多发送 1 条聚合回复。
- 高峰下优先读取“最久未读”的会话，而不是永远读取最近刷新预览的会话。

## 5. 发送前复检

发送前必须执行：

~~~text
open target chat
  -> read latest visible messages
  -> optional history backfill
  -> compare reply.input_message_ids and current latest candidates
  -> if newer customer messages exist:
       mark reply stale
       enqueue merged LLM task
       do not send
     else:
       send with humanized RPA
       verify target and write sent audit
~~~

该规则比“LLM 完成先后”优先级更高。跨会话可以 FIFO，同一会话必须最新上下文优先。

## 6. 与 RPA 风控策略的关系

- 不新增并行 RPA worker。
- 不用剪贴板批量粘贴作为常规发送方式。
- 不因高峰而取消人类化打字、间歇、误字修正、发送后确认。
- 高峰状态下通过队列和并发 LLM 提高效率，而不是提高 RPA 操作频率到危险水平。
- F8 暂停/停止必须能暂停接收器、发送器和 LLM 新任务派发；已运行 LLM 可等待完成后进入暂停状态，不再发送。

## 7. 不做事项

- 不让多个线程同时操控微信窗口。
- 不使用 wxauto4 作为并发读取或并发发送方案。
- 不让 LLM 直接写微信。
- 不绕过 freshness check。
- 不以“响应快”为理由发送旧上下文回复。

## 8. 验收定义

上线前必须证明：

- 3 个会话同时连续发消息，全部被读取并回复，无漏、无重、无串。
- 5 个会话同时发消息，系统能排队处理，延迟可解释，未处理会话保持 pending。
- 某会话在 LLM 思考期间补充消息，旧回复不发送，新回复合并上下文。
- F8 暂停后不再读取/发送，恢复后队列继续。
- 微信白屏、掉线、找不到窗口时能停机或暂停，不继续盲发。
