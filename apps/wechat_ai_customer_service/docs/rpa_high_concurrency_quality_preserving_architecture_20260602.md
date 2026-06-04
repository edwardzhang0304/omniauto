# 微信自动客服高并发保质量优化方案（2026-06-02）

## 1. 目标与边界

### 1.1 本轮目标
- 在**不降低回复质量**的前提下，提高多会话同时咨询时的总体吞吐与平均等待体验。
- 将当前“后台 LLM 小并发 + 微信前台串行”的链路，升级为“后台多阶段高并发 + 微信前台严格串行”的结构。
- 明确区分：
1. 哪些阶段可以通过增加系统资源与并发度来提速。
2. 哪些阶段即使机器性能充足，也必须保持串行以避免错会话、白屏、风控和焦点错乱。

### 1.2 质量底线
本轮方案默认遵循以下质量底线，不允许为了加速而破坏：
1. 不降模型档位，不引入更差模型作为默认回复模型。
2. 不裁剪正式知识、商品库、当前对话事实的内容依据优先级。
3. 不通过粗暴缩短 prompt、关闭最终润色、缩短历史上下文等方式换速度。
4. 不取消最终润色的质量责任，只调整其调度方式与资源分配方式。

### 1.3 非目标
本轮不改：
1. 商品库 / 正式知识库 / AI经验池 / 常识层的业务层级。
2. 人工转接规则。
3. RPA 键鼠人类化动作策略。
4. 微信前台发送必须串行的安全边界。

## 2. 现状复盘

### 2.1 当前链路并非完全串行
当前链路已经具备部分并发能力：
1. `CustomerServiceSchedulerRuntime` 内部已有 LLM 线程池。
2. 主回复规划（`llm_reply_synthesis`）与最终可见润色（`final_visible_llm_polish`）都走远程 LLM。
3. 微信前台捕获与发送已经保持单通道串行。

但当前仍有三个现实问题：
1. 后台 LLM 并发度偏低，默认 `llm_max_concurrency=2`。
2. 主回复规划与最终润色仍然在同一条任务生命周期里顺序发生，导致单条链路尾部偏长。
3. 发送前台虽然正确地保持串行，但当前“ready reply 形成速度”仍然被前序规划节奏限制。

### 2.2 现有关键配置（As-Is）
- `concurrency_scheduler.llm_max_concurrency = 2`
- `concurrency_scheduler.send_max_replies_per_round = 1`
- `multi_target.max_targets_per_iteration = 1`
- `llm_reply_synthesis.timeout_seconds = 12`
- `final_visible_llm_polish.timeout_seconds = 6`

### 2.3 已知结论
结合近期实测与无发送重放，可以确认：
1. 当前上游 relay 可用，`gpt-5.4` 能稳定调用。
2. 小请求直打上游时，单次耗时并不高，说明“上游不可用”不是主因。
3. 真正的长尾来自**本地链路结构**：主回复规划重、最终润色追加一跳、前台发送必须串行。

## 3. 核心判断

### 3.1 可以并发的部分
以下阶段可以提升并发，不必牺牲质量：
1. 主回复规划（规则 + 检索 + LLM synthesis）。
2. 最终可见润色（final visible polish）。
3. 多会话之间的 LLM 思考。
4. 后台非前台型校验与排队。

### 3.2 不能并发的部分
以下阶段必须保持单通道串行：
1. 微信窗口切换。
2. RPA 打开目标会话。
3. 微信输入框打字。
4. 微信发送按钮/回车发送。
5. 发送前后的会话确认与 post-send guard。

原因不是电脑性能，而是：
1. 微信前台只有一个焦点。
2. 多个 RPA worker 同时碰前台，极易造成会话错位与风控。
3. 当前“RPA 串行 + LLM 并发”是正确边界，不能为了并发而打破。

## 4. 目标架构（To-Be）

### 4.1 设计原则
1. **后台尽量并发**：规划与润色都可以并发排队。
2. **前台绝对串行**：任何时刻只允许一个发送执行单元碰微信前台。
3. **会话隔离**：每个会话自己的 capture、planner、polish、ready-reply 必须严格绑定，不允许串单。
4. **发送前最终确认**：即使后台都完成，真正发送前仍必须再次确认当前目标会话正确。
5. **不降质量**：主回复与最终润色都保留，只优化执行拓扑，不降低推理质量。

### 4.2 目标链路

```text
被动会话监控（低扰动）
  -> 串行 RPA capture（快进快出）
  -> Planner Queue（并发）
  -> Planner Worker Pool（并发）
  -> Polish Queue（并发）
  -> Final Polish Worker Pool（并发）
  -> Ready Reply Queue（按完成先后排队）
  -> 串行 RPA freshness + send
  -> processed anchor / audit / telemetry
```

### 4.3 两级后台任务池

#### A. Planner Worker Pool
职责：
1. 读取 capture snapshot。
2. 完成规则、知识检索、主回复生成。
3. 输出“可发送草稿 + 结构化决策元数据”。

要求：
1. 不触碰微信前台。
2. 不依赖 RPA。
3. 同一会话同一时间最多一个 active planner task。

#### B. Final Polish Worker Pool
职责：
1. 读取 planner 输出草稿。
2. 调用 `final_visible_llm_polish` 做最终话术润色。
3. 输出“已润色 final reply”或“保底草稿 reply”。

要求：
1. 与 planner 池解耦，不占用 planner 并发额度。
2. 默认继续保持 quality gate，不取消 guard。
3. 若上游不可用或润色被 guard 拒绝，仍保留现有安全降级逻辑，但不视为主回复失败。

### 4.4 Ready Reply Queue
新增明确语义：
1. `planner_done_waiting_polish`
2. `ready_polished`
3. `ready_fallback_draft`
4. `sending`
5. `sent / send_failed / stale`

说明：
1. 发送队列只消费 `ready_polished` 或 `ready_fallback_draft`。
2. 不允许发送队列直接等待 planner。
3. 发送顺序保持“已完成即排队，真正发送仍先来先到”。

## 5. 状态机调整

### 5.1 会话级状态
- `capture_pending`
- `capturing`
- `captured`
- `planner_running`
- `polish_running`
- `reply_ready`
- `sending`
- `idle`

### 5.2 任务级状态

#### Planner task
- `queued`
- `running`
- `completed`
- `failed`
- `stale`

#### Polish task
- `queued`
- `running`
- `completed`
- `degraded`
- `failed`
- `stale`

### 5.3 核心约束
1. 同一会话只允许一个 capture inflight。
2. 同一会话只允许一个 planner inflight。
3. 同一会话只允许一个 polish inflight。
4. 同一会话 ready reply 只保留最新有效版本，旧版本必须可 stale。

## 6. 并发策略

### 6.1 线程池拆分
当前建议从一个 LLM 池拆成两个：
1. `planner_max_concurrency`
2. `polish_max_concurrency`

原因：
1. 防止最终润色占满 planner 池。
2. 高峰期优先保证新消息先进入规划，而不是全部堵在润色上。
3. 便于分别观测 planner 与 polish 的队列等待时间。

### 6.2 建议并发度
在“不在乎多耗系统资源”的前提下，建议分档：

#### 标准高并发
- `planner_max_concurrency = 4`
- `polish_max_concurrency = 4`

#### 激进高并发
- `planner_max_concurrency = 6`
- `polish_max_concurrency = 6`

说明：
1. 这是后台 LLM 并发，不是 RPA 并发。
2. 真正能不能长期跑满，还取决于上游 relay 的稳定性与本机网络。

### 6.3 与上游并发的关系
本方案允许更多后台任务并发访问上游，但要明确：
1. 并发访问上游主要提升**总吞吐**。
2. 不保证缩短**单条请求**耗时。
3. 因此应把它理解为“多客户同时来时更不容易排队”，而不是“单条消息秒回”。

## 7. 发送阶段保持串行的理由

### 7.1 原则不变
发送仍然必须：
1. 单线程。
2. 单窗口焦点。
3. 单目标确认。

### 7.2 发送前检查
即使后台已完成并发规划，发送前仍需：
1. freshness 判定。
2. 当前目标会话确认。
3. 输入区确认。
4. post-send confirmation。

### 7.3 不做的事
本轮明确不做：
1. 多个 RPA worker 同时切微信。
2. 多窗口并行发送。
3. 多线程同时键鼠操作。

## 8. 质量保护策略

### 8.1 不降质量的具体含义
本轮实现不得引入以下退化：
1. 缩小商品库/正式知识命中范围。
2. 默认减少对当前对话历史的理解。
3. 关闭最终润色。
4. 将高质量模型换成更弱模型。
5. 通过过度缩短 prompt 换速度。

### 8.2 允许的优化
允许做的是：
1. 分离线程池。
2. 让 planner 与 polish 并发排队。
3. 让其他会话在某会话 polish 期间继续 planner。
4. 增加队列和状态机元数据。

## 9. 可观测性要求

新增或强化以下观测指标：
1. `planner_queue_wait_seconds`
2. `planner_runtime_seconds`
3. `polish_queue_wait_seconds`
4. `polish_runtime_seconds`
5. `ready_queue_wait_seconds`
6. `send_wait_seconds`
7. `polish_degraded_rate`
8. `planner_failed_rate`
9. `wrong_target_guard_block_count`
10. `stale_before_send_count`

这些指标必须至少写入：
1. scheduler state
2. managed listener log
3. 测试产物 JSON

## 10. 回滚设计

### 10.1 快速回滚
保留以下回滚路径：
1. planner / polish 双池回退到单 LLM 池。
2. `polish_max_concurrency=1` 退回顺序润色。
3. `planner_max_concurrency=2` 退回现有保守并发。

### 10.2 不能回滚的原则
以下原则不应被回滚：
1. 前台 RPA 串行。
2. 会话发送前确认。
3. 旧 reply stale 机制。

## 11. 验收目标

### 11.1 正确性
1. 多会话并发下 0 次错发。
2. 0 次因并发引起的重复回复。
3. 0 次因并发引起的漏回。

### 11.2 质量
1. 业务正确性不低于当前版本。
2. 最终润色命中率不因并发改造而明显下降。
3. 降级仅出现在真实上游异常或 guard 拒绝场景。

### 11.3 性能
1. 多会话场景下总完成时间明显下降。
2. 单条回复的主要收益来自“排队减少”，而非牺牲内容质量。

## 12. 与现有文档的关系
本方案是对以下文档的延伸，不替代其内容：
1. [`rpa_backend_state_machine_optimization.md`](rpa_backend_state_machine_optimization.md)
2. [`rpa_multi_session_dispatch_hardening_architecture_20260601.md`](rpa_multi_session_dispatch_hardening_architecture_20260601.md)
3. [`rpa_speed_optimization_architecture_20260601.md`](rpa_speed_optimization_architecture_20260601.md)

本轮新增关注点只有一个：
**在不降低质量的前提下，把后台链路进一步并发化，但绝不把微信前台 RPA 变成并发执行。**
