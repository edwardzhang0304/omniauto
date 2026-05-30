# 微信自动客服多会话并发调度数据契约（2026-05-25）

## 1. 范围

本文定义多会话并发调度落地所需的持久化状态、队列字段、事件审计和配置契约。目标是让 RPA 接收、LLM 并发思考、RPA 串行发送之间有明确边界。

## 2. 配置契约

建议新增或归并到 `multi_target` / `concurrency_scheduler`：

~~~json
{
  "concurrency_scheduler": {
    "enabled": false,
    "capture_max_sessions_per_round": 3,
    "llm_max_concurrency": 3,
    "send_max_replies_per_round": 2,
    "same_session_single_inflight": true,
    "stale_reply_policy": "discard_and_requeue",
    "pending_session_ttl_seconds": 1800,
    "reply_ready_ttl_seconds": 900,
    "max_pending_sessions": 30,
    "max_pending_messages_per_session": 80,
    "fairness": {
      "oldest_unreplied_weight": 50,
      "pending_count_weight": 10,
      "last_capture_age_weight": 20,
      "same_session_cooldown_seconds": 2
    }
  }
}
~~~

默认必须保守：

- `enabled=false`，先通过显式开关灰度。
- `llm_max_concurrency=2` 或 `3`。
- `same_session_single_inflight=true`。
- `stale_reply_policy=discard_and_requeue`。

## 3. 会话运行态

建议持久化在租户 runtime 下，例如：

~~~text
runtime/apps/wechat_ai_customer_service/tenants/{tenant}/state/customer_service_scheduler_state.json
~~~

会话状态结构：

~~~json
{
  "session_id": "session_...",
  "target_name": "许聪",
  "exact": true,
  "conversation_type": "private",
  "status": "captured",
  "context_version": 12,
  "last_seen_at": "2026-05-25T10:00:00",
  "last_capture_at": "2026-05-25T10:00:05",
  "oldest_unreplied_at": "2026-05-25T09:59:55",
  "pending_message_count": 4,
  "llm_inflight_task_id": "llm_task_...",
  "ready_reply_ids": [],
  "risk_state": {
    "gap_risk": false,
    "login_risk": false,
    "send_input_not_ready": false,
    "last_error": ""
  }
}
~~~

`status` 可选值：

| 值 | 含义 |
|---|---|
| `idle` | 当前无待处理消息 |
| `suspected_unread` | 会话列表或外部信号提示可能有新消息 |
| `capture_pending` | 等待 RPA 读取 |
| `capturing` | 正在 RPA 读取 |
| `captured` | 已捕获新消息，等待生成回复 |
| `llm_queued` | 已创建 LLM 任务，等待 worker |
| `llm_running` | LLM 正在思考 |
| `reply_ready` | 有可发送回复等待发送 |
| `send_waiting` | 回复已进入发送队列 |
| `sending` | RPA 正在发送 |
| `paused` | 因 F8、gap risk、风控或配置暂停 |
| `failed` | 需要人工或重试 |

## 4. 消息批次契约

消息批次是 LLM 任务的输入基础：

~~~json
{
  "capture_id": "capture_...",
  "target_name": "许聪",
  "context_version": 12,
  "captured_at": "2026-05-25T10:00:05",
  "message_ids": ["msg_a", "msg_b"],
  "content_keys": ["..."],
  "messages": [
    {
      "id": "msg_a",
      "sender": "customer",
      "type": "text",
      "content": "我预算10万左右",
      "time": "2026-05-25T10:00:00"
    }
  ],
  "history_backfill": {
    "enabled": true,
    "applied": false,
    "gap_risk": false
  },
  "selection": {
    "eligible_count": 2,
    "overflow_count": 0,
    "max_batch_messages": 8
  }
}
~~~

要求：

- 同一会话新捕获消息必须递增 `context_version`。
- 同一消息不能重复进入 active LLM 任务。
- 超出可见页面时必须保留 `history_backfill` 元数据。
- 若 `gap_risk=true` 且配置要求阻断，不得创建自动回复任务。

## 5. LLM 任务契约

~~~json
{
  "task_id": "llm_task_...",
  "target_name": "许聪",
  "input_context_version": 12,
  "capture_ids": ["capture_..."],
  "input_message_ids": ["msg_a", "msg_b"],
  "status": "running",
  "created_at": "2026-05-25T10:00:06",
  "started_at": "2026-05-25T10:00:07",
  "finished_at": "",
  "timeout_seconds": 30,
  "attempt": 1,
  "route": {
    "foreground_level": "L2",
    "llm_required": true,
    "fallback_allowed": true
  },
  "result": null,
  "error": null
}
~~~

`status` 可选值：

- `queued`
- `running`
- `completed`
- `stale`
- `failed`
- `timeout`
- `cancelled`

完成校验：

- 若 `input_context_version < current_session.context_version`，任务必须标记 `stale`。
- `stale` 任务不得进入 `send_queue`。
- 若失败且有安全兜底，可以生成 fallback reply；否则进入人工告警。

## 6. 回复队列契约

~~~json
{
  "reply_id": "reply_...",
  "task_id": "llm_task_...",
  "target_name": "许聪",
  "input_context_version": 12,
  "input_message_ids": ["msg_a", "msg_b"],
  "reply_text": "可以的，10万左右通勤我建议优先看...",
  "status": "ready",
  "ready_at": "2026-05-25T10:00:18",
  "send_attempts": 0,
  "last_send_error": "",
  "freshness_check": null,
  "priority": {
    "ready_sequence": 1024,
    "oldest_unreplied_at": "2026-05-25T10:00:00"
  }
}
~~~

`status` 可选值：

- `ready`
- `send_waiting`
- `sending`
- `sent`
- `stale`
- `send_failed`
- `handoff`
- `expired`

排序规则：

- 跨会话默认按 `ready_at` 和 `ready_sequence` FIFO。
- 同一会话若有多个 ready reply，只允许最新 `context_version` 可发送。
- 发送前发现新消息，当前 reply 改为 `stale`，创建新捕获或 LLM 任务。

## 7. 会话列表活跃信号契约

`list_sessions()` 应尽量提供：

~~~json
{
  "name": "许聪",
  "title": "许聪",
  "content": "客户最新预览",
  "time": "10:01",
  "unread_badge": "2",
  "conversation_type": "private",
  "source_adapter": "win32_ocr",
  "ocr_confidence": 0.93,
  "row": {
    "center_y": 245.0,
    "top": 220.0,
    "bottom": 270.0
  }
}
~~~

最低要求：

- `name` 必须稳定。
- `row` 坐标用于后续点击目标会话。
- 若 `content/time/unread_badge` 无法可靠识别，不能据此清除 pending 状态。

## 8. 审计事件

新增事件建议：

- `scheduler_capture_enqueued`
- `scheduler_capture_started`
- `scheduler_capture_completed`
- `scheduler_capture_gap_risk`
- `scheduler_llm_task_enqueued`
- `scheduler_llm_task_started`
- `scheduler_llm_task_completed`
- `scheduler_llm_task_stale`
- `scheduler_reply_ready`
- `scheduler_send_started`
- `scheduler_send_freshness_stale`
- `scheduler_send_completed`
- `scheduler_send_failed`
- `scheduler_backpressure`

每个事件至少包含：

- `tenant_id`
- `target_name`
- `session_id`
- `context_version`
- `created_at`
- `event`
- `reason`
- `task_id` 或 `reply_id`

## 9. 不变量

- 一个微信客户端同一时刻只能有一个 RPA 操作。
- 一个会话同一时刻最多一个有效 LLM 任务。
- 一个 reply 只能发送一次。
- stale reply 永远不能发送。
- 发送前复检失败时不能盲发。
- F8 暂停期间不能启动新的 RPA 接收或发送。
- 掉线、白屏、登录窗口、输入框不可用时必须停止或暂停，不得继续队列消费。
