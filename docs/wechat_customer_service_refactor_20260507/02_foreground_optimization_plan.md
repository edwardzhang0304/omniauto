# 前台优化改造计划（P0）

## 目标
在不改变整体架构的前提下，将前台单次回复延迟从 5-10s 压缩到 3-5s。

## 改造项清单

### 1. 缩短意图识别超时

**文件**：`apps/wechat_ai_customer_service/configs/jiangsu_chejin_xucong_live.example.json`

**变更**：
```json
"intent_router": {
  "llm": {
    "enabled": true,
    "timeout_seconds": 2,    // 从 5 改为 2
    "max_tokens": 256
  },
  "cache_seconds": 60
}
```

**说明**：flash 模型做 5-6 类意图分类通常 1s 内完成，2s timeout 足够覆盖 95% 情况，失败时自动降级到关键词兜底。

---

### 2. 异步化后置工作

**文件**：`apps/wechat_ai_customer_service/workflows/listen_and_reply.py`

**当前问题**：`process_target()` 末尾同步执行以下操作：
- `write_customer_data_to_excel()`（~0.3s）
- `maybe_record_raw_messages()`（~0.2s）
- state 文件写入（~0.2s）

**改造方案**：在 `process_target()` 返回前，将上述工作改为 `threading.Thread(daemon=True)` fire-and-forget。

**具体位置**：
- 在 `listen_and_reply.py` 的 `process_target()` 函数末尾（约 line 700-800 之间，需现场确认）
- 新建辅助函数 `enqueue_background_tasks()` 负责启动后台线程

**注意**：
- Excel 写入有并发风险，后台线程需要自己的文件锁或排队机制
- state 写入如果改为异步，需确保下一轮 `--once` 能读到最新状态（当前 state 是文件读写，已有锁机制）

---

### 3. 并行化非 LLM 查找

**文件**：`apps/wechat_ai_customer_service/workflows/listen_and_reply.py`

**当前流程**（串行）：
```
build_evidence_pack() → route_intent() → maybe_match_product_knowledge() → maybe_build_rag_reply()
```

**改造后**（并行）：
```
build_evidence_pack()
  │
  ├─ 并行启动 route_intent(flash)
  ├─ 并行启动 maybe_match_product_knowledge()
  ├─ 并行启动 maybe_build_rag_reply()   // 但 RAG 依赖 intent_tags，需延迟到 intent 返回后
  └─ 并行启动 extract_customer_data()
```

**实现方式**：使用 `concurrent.futures.ThreadPoolExecutor(max_workers=3)` 并行执行无依赖的查找任务。

**依赖关系**：
- `maybe_build_rag_reply()` 需要 `intent_assist` 中的 `intent_tags`，所以必须在 `route_intent()` 完成后执行
- `maybe_match_product_knowledge()` 和 `extract_customer_data()` 与意图识别无依赖，可并行

**具体位置**：`process_target()` 函数中 line 332-455 区域

---

### 4. 收紧 pro 模型升级条件

**文件**：`apps/wechat_ai_customer_service/workflows/llm_reply_synthesis.py`

**当前问题**：`select_synthesis_model_route()` 中某些升级条件过于宽松，导致普通查询也走 pro。

**需审查的条件**：
- `long_conversation_context`：当前阈值 80+ 条消息，可收紧到 120+ 条
- `long_message`：当前阈值 420+ 字符，可收紧到 600+ 字符
- `pro_when_rag_only_authority`：如果 RAG 是唯一证据且主题为权威话题，则升级 pro。可改为仅当 RAG 证据涉及价格/库存/售后等硬边界时才升级。

**配置变更**（`configs/*.json`）：
```json
"model_routing": {
  "pro_intent_tags": ["payment", "invoice", "after_sales", "handoff", "customer_data"],
  "pro_safety_reasons": ["matched_faq_requires_handoff", "invoice_amount_entity", "contract_risk", "payment_boundary", "price_approval_required"],
  "pro_when_must_handoff": true,
  "pro_when_rag_only_authority": false    // 从 true 改为 false，由 guard 层兜底
}
```

---

### 5. 拟人化规则已更新

**文件**：`apps/wechat_ai_customer_service/configs/platform_safety_rules.example.json`

**状态**：✅ 已完成

**变更**：强化 `natural_reply_style` 规则，明确要求拟人化、避免机械化。

**注意**：如果租户使用自定义的 safety rules 文件（非 example），需要手动同步该规则。

---

## P0 改造后预期延迟

| 场景 | 改造前 | 改造后 |
|------|--------|--------|
| 普通查询（flash intent + flash synthesis） | 5-8s | **3-4s** |
| 高风险查询（flash intent + pro synthesis） | 7-10s | **5-6s** |
| 意图识别超时降级 | 5-8s | **3-4s**（timeout 从 5s 降到 2s） |

---

## P0 文件修改清单

| 文件 | 修改类型 | 说明 |
|------|---------|------|
| `configs/jiangsu_chejin_xucong_live.example.json` | 配置 | 缩短 intent_router timeout |
| `workflows/listen_and_reply.py` | 代码 | 异步化后置工作 + 并行化非LLM查找 |
| `workflows/llm_reply_synthesis.py` | 代码 | 收紧 pro 升级条件 |
| `configs/platform_safety_rules.example.json` | 规则 | ✅ 已完成 |
