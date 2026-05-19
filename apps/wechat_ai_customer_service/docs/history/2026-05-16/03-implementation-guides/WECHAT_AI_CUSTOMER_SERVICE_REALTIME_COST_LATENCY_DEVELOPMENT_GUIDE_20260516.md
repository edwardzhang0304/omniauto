# 微信自动客服实时响应与 token 成本优化开发文档（2026-05-16）

## 1. 开发原则

本次改造不是关闭 LLM，而是重新定义 LLM 的位置：

- 实时链路只使用必要的 LLM。
- 后台链路充分使用 LLM。
- 安全 guard 必须始终保留。
- 商品库和正式知识优先于 RAG 和模型生成。
- 任意慢任务都不能阻塞微信监听主循环。

## 2. 推荐实施阶段

### 阶段 P0：止住卡死

目标：任何单轮异常都不能让监听器长时间停住。

修改点：

- 给 `run_customer_service_listener.py` 的 `run_once()` 增加整轮 timeout。
- timeout 后终止子进程树。
- 写入 `managed_listener_watchdog_timeout` 日志。
- runtime status 显示最近一次超时。
- 下一轮继续运行。

验收：

- 模拟子进程 sleep 超过 timeout，父监听器能恢复。
- 不会重复发送已处理消息。
- 状态页能看到 timeout 原因。

### 阶段 P1：新增实时路由器

目标：先判断是否需要 LLM，再决定回复方式。

新增模块建议：

- `workflows/realtime_reply_router.py`
- `workflows/realtime_token_budget.py`
- `workflows/realtime_reply_templates.py`

核心接口：

```python
def decide_runtime_route(*, config, combined, decision, intent_assist, product_knowledge, rag_reply, data_capture) -> dict:
    return {
        "level": "L1",
        "reason": "budget_recommendation_with_structured_products",
        "foreground_llm_allowed": False,
        "max_latency_seconds": 6,
        "fallback_reply": "...",
        "background_jobs": ["reply_quality_review"],
    }
```

验收：

- 问候、留资、高风险边界走 L0。
- 常规预算推荐优先走 L1。
- 多轮复杂问题才走 L2。
- 路由结果写入审计。

### 阶段 P2：证据包实时 profile

目标：前台 LLM 即使被调用，也只能拿小包。

修改点：

- `reply_evidence_builder.py` 增加 `profile="realtime"`。
- `llm_reply_synthesis.py` 支持从 route 读取 token budget。
- `build_synthesis_prompt_pack()` 只传实时必要字段。

建议 realtime profile：

```json
{
  "max_history_messages": 6,
  "history_char_budget": 1200,
  "max_rag_hits": 2,
  "max_rag_text_chars": 180,
  "max_catalog_candidates": 3,
  "max_tokens": 500,
  "timeout_seconds": 8,
  "retry_count": 0
}
```

验收：

- prompt 估算小于 3000 tokens。
- 普通预算推荐不再出现 10k+ prompt。
- L2 超时可回退，不影响下一轮监听。

### 阶段 P3：商品事实前置筛选

目标：商品推荐由程序先筛事实，LLM 只负责表达。

修改点：

- 新增商品候选筛选函数：
  - 预算区间。
  - 用途标签。
  - 能源类型。
  - 库存状态。
  - 城市/门店。
- 回复层只拿 Top 2-3。

验收：

- “10万通勤”优先返回预算内车源。
- 回复中价格、年份、公里数与商品库一致。
- LLM 不得虚构商品事实。

### 阶段 P4：后台 LLM 任务化

目标：把慢但有价值的智能能力迁移到 worker。

后台任务类型：

- `reply_quality_review`
- `conversation_summary`
- `rag_experience_audit`
- `customer_profile_update`
- `knowledge_candidate_generation`

验收：

- 前台发送后能投递后台任务。
- 后台失败不影响客户回复。
- 后台结果只进入候选或审计。

### 阶段 P5：成本监控与自动降级

目标：系统能发现 token 异常并自动保护。

新增能力：

- 每小时统计前台 tokens。
- P95 延迟和 P95 token 监控。
- 连续超时自动关闭前台 LLM 一段时间。
- 页面显示当前路由模式和 token 成本。

验收：

- 可以看到 L0/L1/L2 占比。
- 可以看到前台 token/message。
- 触发异常后自动进入省 token 模式。

## 3. 配置设计

建议新增：

```json
{
  "realtime_reply": {
    "enabled": true,
    "watchdog_timeout_seconds": 25,
    "default_level": "L1",
    "allow_foreground_llm": true,
    "foreground_llm_timeout_seconds": 8,
    "foreground_llm_retry_count": 0,
    "max_prompt_tokens": 3000,
    "max_completion_tokens": 500,
    "auto_degrade": {
      "enabled": true,
      "timeout_window": 3,
      "cooldown_seconds": 600
    }
  }
}
```

保留但调整：

```json
{
  "llm_reply_synthesis": {
    "enabled": true,
    "mode": "guarded_auto",
    "default_foreground": false,
    "fallback_to_existing_reply": true
  }
}
```

含义：

- `enabled=true` 表示能力存在。
- `default_foreground=false` 表示不默认阻塞实时回复。
- 是否调用由 `realtime_reply` 路由器决定。

## 4. 关键数据结构

### 4.1 审计中的 route

```json
{
  "runtime_route": {
    "level": "L1",
    "reason": "budget_recommendation_local_product_candidates",
    "foreground_llm_allowed": false,
    "fallback_available": true,
    "background_jobs": ["reply_quality_review"]
  }
}
```

### 4.2 审计中的 token budget

```json
{
  "token_budget": {
    "max_prompt_tokens": 3000,
    "max_completion_tokens": 500,
    "actual_prompt_tokens": 0,
    "actual_completion_tokens": 0,
    "actual_total_tokens": 0,
    "saved_reason": "deterministic_realtime_reply"
  }
}
```

### 4.3 审计中的 latency

```json
{
  "latency": {
    "capture_seconds": 0.8,
    "reply_build_seconds": 1.4,
    "send_seconds": 0.7,
    "total_once_seconds": 3.1
  }
}
```

## 5. 回复质量保护

为了避免省 token 后回复变机械，需要保留三类质量来源：

### 5.1 真实客服短句库

从已清洗实盘经验中沉淀短句，不直接塞大段聊天记录：

- “您这个预算可以先看...”
- “这台更偏家用稳一点...”
- “您是在南京看车吗？”
- “是否考虑贷款或置换？”
- “这块我需要先核实，确认后给您准确答复。”

### 5.2 场景模板

模板不是僵硬话术，而是结构：

```text
确认需求 + 推荐 1-2 个候选 + 简短理由 + 下一步追问
```

### 5.3 后台持续优化

后台复盘客户真实反馈，把低质量模板、漏答场景和高频问法推入人工审核，不要求每条消息实时大模型重写。

## 6. 回滚策略

任何阶段都要能回滚：

- P0 watchdog 可单独保留。
- P1 路由器可通过配置关闭，恢复旧合成链路。
- P2 realtime profile 可切回旧 profile。
- P4 后台任务失败不影响前台。
- P5 自动降级可手动关闭。

推荐上线顺序：

1. 先上 watchdog。
2. 再上路由审计但 shadow，不改变发送。
3. 再让 L0/L1 生效。
4. 最后开启 L2 小包 Flash。
