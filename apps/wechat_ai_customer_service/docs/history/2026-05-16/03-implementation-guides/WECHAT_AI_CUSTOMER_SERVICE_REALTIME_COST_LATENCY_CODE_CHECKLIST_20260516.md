# 微信自动客服实时响应与 token 成本优化代码清单（2026-05-16）

## 1. 修改前检查

- 确认当前租户配置：`jiangsu_chejin_usedcar_customer_20260501`。
- 备份当前运行配置和审计日志路径。
- 确认微信、8765、8766、本地 sidecar 状态。
- 确认当前 RAG 经验池没有待误用商品主数据。
- 确认 `identity_guard_enabled` 当前策略符合客户不可识别 AI 的要求。

## 2. 代码修改范围

### 2.1 必改

| 文件 | 修改 |
|---|---|
| `scripts/run_customer_service_listener.py` | 增加整轮 watchdog timeout，超时杀子进程并恢复下一轮 |
| `workflows/listen_and_reply.py` | 接入 runtime route、token budget、后台任务投递 |
| `workflows/llm_reply_synthesis.py` | 支持非默认前台调用、实时 profile、小包预算、超时回退 |
| `workflows/reply_evidence_builder.py` | 增加 realtime profile，瘦身历史/RAG/商品/规则 |
| `configs/jiangsu_chejin_xucong_live.example.json` | 增加 `realtime_reply` 配置，调整合成默认策略 |

### 2.2 建议新增

| 文件 | 用途 |
|---|---|
| `workflows/realtime_reply_router.py` | 判断 L0/L1/L2/L3 路由 |
| `workflows/realtime_token_budget.py` | token 预算、超预算标记、自动降级状态 |
| `workflows/realtime_reply_templates.py` | 常规场景轻量模板与真实客服短句组合 |
| `tests/run_realtime_reply_router_checks.py` | 路由单元测试 |
| `tests/run_realtime_token_budget_checks.py` | token 预算和降级测试 |

## 3. P0 watchdog 实现清单

- `run_once()` 增加 `timeout_seconds` 参数。
- 使用 `subprocess.Popen` + `communicate(timeout=...)` 替代无限 `subprocess.run`。
- timeout 时终止进程树。
- 写日志：
  - `managed_listener_watchdog_timeout`
  - command
  - duration
  - timeout_seconds
- runtime status 写：
  - `state=idle` 或 `state=degraded`
  - `last_reason=watchdog_timeout`
- 不标记消息 processed，避免漏回复。
- 下一轮继续扫描并合并最新上下文。

## 4. P1 路由器实现清单

路由输入：

- `combined`
- `decision`
- `intent_assist`
- `rag_reply`
- `product_knowledge`
- `data_capture`
- `config`
- `target_state`

路由输出：

- `level`
- `reason`
- `foreground_llm_allowed`
- `max_latency_seconds`
- `max_prompt_tokens`
- `max_completion_tokens`
- `fallback_reply`
- `background_jobs`

规则：

- 问候、感谢、结束语：L0。
- 留资采集：L0。
- 高风险边界：L0 + handoff alert。
- 明确商品事实：L0。
- 常规预算推荐：L1。
- 多轮复杂指代：L2。
- 后台经验/候选知识：L3。

## 5. P2 证据包瘦身清单

`reply_evidence_builder.py`：

- 增加 `profile` 参数。
- `profile="realtime"` 时：
  - `max_history_messages <= 6`
  - `history_char_budget <= 1200`
  - `max_rag_hits <= 2`
  - `max_rag_text_chars <= 180`
  - `max_catalog_candidates <= 3`
  - `selected_items` 只保留命中项。
  - `platform_rules` 只保留命中摘要。

`llm_reply_synthesis.py`：

- 从 `runtime_route` 读取是否允许调用。
- 从 `token_budget` 读取 max tokens。
- 禁止 L2 重试。
- 超时返回 existing reply，不阻塞。

## 6. P3 商品前置清单

- 新增商品候选排序：
  - 预算匹配。
  - 用途匹配。
  - 关键词匹配。
  - 库存可用。
  - 城市/门店匹配。
- 回复只引用商品库字段。
- RAG 命中商品资料形态时不得进入经验晋升。
- 商品库字段缺失时，用“需要核实”话术。

## 7. P4 后台任务清单

实时发送后 enqueue：

- `reply_quality_review`
- `conversation_summary`
- `rag_experience_audit`
- `customer_profile_update`

要求：

- 队列去重。
- 失败可重试。
- 结果写审计或候选。
- 不直接写商品库。
- 不直接写正式知识，除非已有人工确认入口。

## 8. P5 前端/后台可观测清单

后台 API 或状态文件应能展示：

- 当前监听状态。
- 最近一次 watchdog。
- 最近 20 条消息路由等级。
- 前台 LLM 调用率。
- 平均 tokens/message。
- P95 响应耗时。
- 自动降级是否开启。
- 当前是否处于省 token 模式。

## 9. 必测命令

代码修改后至少运行：

```powershell
python -m py_compile apps/wechat_ai_customer_service/scripts/run_customer_service_listener.py
python -m py_compile apps/wechat_ai_customer_service/workflows/listen_and_reply.py
python -m py_compile apps/wechat_ai_customer_service/workflows/llm_reply_synthesis.py
python -m py_compile apps/wechat_ai_customer_service/workflows/reply_evidence_builder.py
python apps/wechat_ai_customer_service/tests/run_workflow_logic_checks.py
python apps/wechat_ai_customer_service/tests/run_jiangsu_chejin_used_car_checks.py
python apps/wechat_ai_customer_service/tests/run_jiangsu_chejin_llm_synthesis_checks.py
```

新增测试后补充：

```powershell
python apps/wechat_ai_customer_service/tests/run_realtime_reply_router_checks.py
python apps/wechat_ai_customer_service/tests/run_realtime_token_budget_checks.py
```

## 10. 不可接受回归

- 前台普通消息仍出现 10k+ prompt。
- LLM timeout 后监听器停止轮询。
- 高风险边界为了省 token 直接给承诺。
- 商品事实被 RAG 或 LLM 改写。
- 防暴露 AI 身份开启时，客户可见文本出现“AI/机器人/转人工/人工客服”。
- 后台 LLM 直接写正式知识或商品库。
