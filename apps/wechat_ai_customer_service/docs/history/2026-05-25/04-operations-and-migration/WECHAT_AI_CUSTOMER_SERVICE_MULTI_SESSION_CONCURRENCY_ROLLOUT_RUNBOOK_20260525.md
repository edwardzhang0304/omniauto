# 微信自动客服多会话并发调度灰度与运维手册（2026-05-25）

## 1. 上线策略

多会话并发调度必须灰度上线，不允许一次性替换当前串行链路。

推荐阶段：

1. 本地单元测试。
2. 离线模拟调度测试。
3. 真实微信 no-send 捕获测试。
4. 文件传输助手或测试群 send 测试。
5. 3 会话小规模真实联系人测试。
6. 5 会话压力测试。
7. 长测。

## 2. 配置开关

默认关闭：

~~~json
{
  "concurrency_scheduler": {
    "enabled": false
  }
}
~~~

灰度开启：

~~~json
{
  "concurrency_scheduler": {
    "enabled": true,
    "capture_max_sessions_per_round": 3,
    "llm_max_concurrency": 2,
    "send_max_replies_per_round": 1,
    "same_session_single_inflight": true,
    "stale_reply_policy": "discard_and_requeue"
  }
}
~~~

压力测试时可调整：

- `llm_max_concurrency`: 2 -> 3。
- `send_max_replies_per_round`: 1 -> 2。
- `capture_max_sessions_per_round`: 3 -> 5。

不建议为了速度提高 RPA 并发，因为微信前台窗口只能安全串行操作。

## 3. 运行状态观察

总控台和日志应观察：

- pending sessions 数。
- LLM running 数。
- ready replies 数。
- oldest unreplied seconds。
- send failed 数。
- stale replies 数。
- current RPA action。
- operator guard 状态。
- transport risk 状态。

若 pending 增长但 LLM running 为 0，说明 worker 可能未派发。

若 ready replies 增长但 sent 不增长，说明 RPA 发送器或风控保护阻塞。

若 stale 激增，说明客户补充消息频率高或回复生成太慢，需要优化 LLM 超时、合并策略或发送节奏。

## 4. F8 暂停语义

F8 暂停后：

- 停止新 capture。
- 停止新 send。
- 停止派发新 LLM task。
- 正在运行的 LLM 可以自然完成，但结果只入队，不发送。
- 悬浮球保持显示暂停状态。
- 总控台与悬浮球状态必须同步。

F8 恢复后：

- 优先处理已 ready 且仍不过期的 reply。
- 发送前仍必须 freshness check。
- 过期 reply 标记 expired 或 stale，不直接发送。

F8 停止后：

- 不再消费任何队列。
- 当前 state 保留，供下一次启动恢复或人工清理。

## 5. 回滚流程

若出现漏回、串回、重复发送、微信异常或风控信号：

1. 立即 F8 停止。
2. 在配置中关闭 `concurrency_scheduler.enabled`。
3. 保存 scheduler state 和日志。
4. 重启 managed listener，回到旧串行链路。
5. 检查旧 state 的 processed ids，确认不会重发。
6. 分析 scheduler audit 后再重新灰度。

## 6. 故障处置

### 6.1 pending 堆积

可能原因：

- RPA 捕获失败。
- 微信窗口不可用。
- capture 上限过低。
- 会话列表 OCR 不稳定。

处理：

- 查看最近 `scheduler_capture_failed`。
- 执行 RPA status/capabilities no-send probe。
- 检查微信窗口大小、是否白屏、是否登录。
- 必要时降低捕获频率并恢复窗口。

### 6.2 LLM 堆积

可能原因：

- LLM API 慢或失败。
- 并发数过低。
- 单会话长期 inflight 未释放。
- timeout 没有正确回收任务。

处理：

- 查看 `scheduler_llm_task_timeout`。
- 降低 prompt 包大小。
- 降低 foreground LLM 使用比例。
- 清理 stuck task 为 failed，再重新入队。

### 6.3 ready reply 堆积

可能原因：

- RPA 发送器暂停。
- 发送前 freshness check 大量 stale。
- 风控 cooldown。
- 输入框不可用或窗口异常。

处理：

- 查看 `scheduler_send_failed` 和 transport risk。
- 验证 F8 状态是否暂停。
- 检查悬浮球和总控台状态同步。
- 必要时只恢复 no-send capture，暂停 send。

### 6.4 stale 过多

说明客户在思考期间不断补充，系统正确避免旧回复发送，但效率下降。

处理：

- 提高消息合并等待窗口，例如 1-2 秒。
- 降低前台 LLM timeout。
- 对高频碎片消息优先用短确认或请客户稍等的安全话术。
- 对同一会话限制每轮最多一个 active reply。

## 7. 数据保留

必须保留：

- scheduler state。
- managed listener log。
- audit jsonl。
- phase heartbeat。
- RPA screenshot artifact。
- transport risk guard state。

测试产物建议放入：

~~~text
runtime/apps/wechat_ai_customer_service/test_artifacts/multi_session_concurrency/
~~~

## 8. 验收后默认参数建议

初始生产默认：

- `llm_max_concurrency=2`
- `capture_max_sessions_per_round=3`
- `send_max_replies_per_round=1`
- `pending_session_ttl_seconds=1800`
- `reply_ready_ttl_seconds=300`
- `same_session_single_inflight=true`

稳定后可尝试：

- `llm_max_concurrency=3`
- `send_max_replies_per_round=2`

但 RPA 操作仍必须串行。
