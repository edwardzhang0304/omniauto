# 微信自动客服高并发保质量运行参数建议（2026-06-02）

## 1. 使用目的
本文件用于给后续代码落地提供默认参数建议，前提是：
1. 不降低回复质量。
2. 不把微信前台 RPA 改成并发。
3. 只提升后台 LLM 并发能力。

## 2. 建议新增参数

### 2.1 `concurrency_scheduler`
建议新增：

```json
{
  "concurrency_scheduler": {
    "enabled": true,
    "capture_max_sessions_per_round": 1,
    "planner_max_concurrency": 4,
    "polish_max_concurrency": 4,
    "send_max_replies_per_round": 1,
    "same_session_single_inflight": true
  }
}
```

说明：
1. `capture_max_sessions_per_round=1` 继续压低前台动作密度。
2. `planner_max_concurrency` 与 `polish_max_concurrency` 都是后台线程池参数。
3. `send_max_replies_per_round=1` 继续保证前台发送单线程。

### 2.2 `final_visible_llm_polish`

```json
{
  "final_visible_llm_polish": {
    "enabled": true,
    "required_for_send": true,
    "allow_send_when_unavailable": true,
    "provider": "openai",
    "model_tier": "flash",
    "timeout_seconds": 6,
    "retry_count": 0,
    "max_tokens": 120,
    "cache_enabled": true
  }
}
```

说明：
1. 本轮不建议默认再缩短 timeout。
2. 本轮也不建议为了追求极限速度而默认关闭 final polish。

## 3. 推荐档位

### 3.1 平衡档（默认建议）
- `planner_max_concurrency = 4`
- `polish_max_concurrency = 4`

适用：
1. 日常实盘。
2. 2~4 个会话同时活跃。

### 3.2 高压档
- `planner_max_concurrency = 6`
- `polish_max_concurrency = 6`

适用：
1. 机器资源充足。
2. 你明确以高峰多会话吞吐优先。

风险：
1. 对 relay、网络和本地 CPU/内存更敏感。
2. 不一定让单条更快，但能让多会话总排队更短。

### 3.3 回滚档
- `planner_max_concurrency = 2`
- `polish_max_concurrency = 1`

适用：
1. 现场出现不明并发异常。
2. 需要快速回退到保守模式验证问题是否来自新并发结构。

## 4. 不建议改的参数
以下参数本轮不建议为了速度随意调低：
1. `llm_reply_synthesis.timeout_seconds`
2. `final_visible_llm_polish.timeout_seconds`
3. `max_history_messages`
4. `history_char_budget`
5. `max_rag_hits`

原因：
1. 这些直接影响回复质量与内容完整性。
2. 本轮提速目标应主要靠调度并发，而不是牺牲推理输入质量。

## 5. 观测建议
落地后至少要持续观察：
1. `planner_queue_wait_seconds`
2. `planner_runtime_seconds`
3. `polish_queue_wait_seconds`
4. `polish_runtime_seconds`
5. `polish_degraded_rate`
6. `ready_queue_wait_seconds`
7. `send_wait_seconds`

## 6. 结论
本文件的核心立场只有一句：

**可以增加后台并发，但不要用削弱知识、裁剪上下文、关闭润色、或者并发 RPA 前台发送来换速度。**
