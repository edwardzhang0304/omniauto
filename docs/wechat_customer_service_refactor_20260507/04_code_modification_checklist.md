# 代码改造清单（文件级）

## 已完成项

| 文件 | 变更 | 状态 | 日期 |
|------|------|------|------|
| `configs/platform_safety_rules.example.json` | 强化 `natural_reply_style` 规则，要求拟人化、避免机械化 | ✅ 已完成 | 2026-05-07 |

---

## P0 待改造项

### 1. 配置文件：缩短意图识别超时

**文件**：`apps/wechat_ai_customer_service/configs/jiangsu_chejin_xucong_live.example.json`

```json
"intent_router": {
  "llm": {
    "timeout_seconds": 2    // 改前: 5
  }
}
```

**验证**：运行 listener，发送测试消息，检查 intent_result.source 是否为 "llm" 且耗时 < 2s。

---

### 2. 代码：异步化后置工作

**文件**：`apps/wechat_ai_customer_service/workflows/listen_and_reply.py`

**目标位置**：`process_target()` 函数末尾，发送消息之后、return 之前。

**需异步化的函数调用**：
- `write_customer_data_to_excel()`（数据写入）
- `maybe_record_raw_messages()`（原始消息记录）
- `append_jsonl()`（heavy audit logging）

**实现方式**：
```python
import threading

def _background_post_reply(...):
    try:
        write_customer_data_to_excel(...)
        maybe_record_raw_messages(...)
    except Exception:
        pass

threading.Thread(target=_background_post_reply, args=(...), daemon=True).start()
```

**风险**：Excel 文件并发写入。后台线程需要独立文件锁，或改用 `WorkQueueService` 排队写入。

---

### 3. 代码：并行化非 LLM 查找

**文件**：`apps/wechat_ai_customer_service/workflows/listen_and_reply.py`

**目标位置**：`process_target()` 函数 line ~332-400

**当前串行代码**：
```python
evidence_pack = build_evidence_pack(...)
intent_result = route_intent(...)
product_knowledge = maybe_match_product_knowledge(...)
data_capture = maybe_capture_customer_data(...)
```

**改造后**：
```python
from concurrent.futures import ThreadPoolExecutor

evidence_pack = build_evidence_pack(...)

with ThreadPoolExecutor(max_workers=3) as executor:
    future_intent = executor.submit(route_intent, ...)
    future_product = executor.submit(maybe_match_product_knowledge, ...)
    future_data = executor.submit(maybe_capture_customer_data, ...)
    
    intent_result = future_intent.result(timeout=3)
    product_knowledge = future_product.result()
    data_capture = future_data.result()
```

**注意**：`maybe_build_rag_reply()` 依赖 `intent_assist` 中的 `intent_tags`，需在 `intent_result` 返回后再执行。

---

### 4. 代码：收紧 pro 模型升级条件

**文件**：`apps/wechat_ai_customer_service/workflows/llm_reply_synthesis.py`

**目标位置**：`select_synthesis_model_route()` 函数 line ~272-320

**需修改的条件**：

```python
# 当前（宽松）
if len(history) >= 80:          # 改为 >= 120
    reasons.append("long_conversation_context")

if len(combined) >= 420:        # 改为 >= 600
    reasons.append("long_or_complex_message")

if rag_only_authority_topic:    # 增加更严格的子条件
    # 仅当 RAG 涉及 price/stock/invoice/payment/after_sales 时才升级
```

**配置同步**：更新 `configs/*.json` 中的 `model_routing` 参数。

---

## P1 待改造项

### 5. 新建：后台 Worker 主进程

**文件**：`apps/wechat_ai_customer_service/scripts/background_worker.py`（新建）

**职责**：
- 初始化 WorkQueueService
- 循环 `claim()` 任务
- 分发到对应 handler
- 异常处理与重试

**启动参数**：
```bash
python scripts/background_worker.py --tenant-id <id> --queue customer_service
```

---

### 6. 新建：后台 Handler 集合

**文件**：`apps/wechat_ai_customer_service/admin_backend/services/background_handlers.py`（新建）

**需实现**：
```python
def handle_experience_interpretation(payload: dict) -> dict: ...
def handle_rag_quality_audit(payload: dict) -> dict: ...
def handle_knowledge_compile(payload: dict) -> dict: ...
def handle_conversation_summary(payload: dict) -> dict: ...
def handle_customer_data_sync(payload: dict) -> dict: ...
def handle_raw_message_archive(payload: dict) -> dict: ...
def handle_diagnostics_deep_check(payload: dict) -> dict: ...
```

---

### 7. 代码：前台入队点改造

**文件**：`apps/wechat_ai_customer_service/workflows/listen_and_reply.py`

**目标位置**：`process_target()` 函数末尾

**改造**：在发送回复后，将后置工作改为 `WorkQueueService.enqueue()`：

```python
from apps.wechat_ai_customer_service.admin_backend.services.work_queue import WorkQueueService

queue = WorkQueueService(tenant_id=tenant_id)
queue.enqueue(kind="customer_data_sync", payload={...}, dedupe_key=...)
queue.enqueue(kind="raw_message_archive", payload={...}, dedupe_key=...)
# 如果 auto_learn 开启
queue.enqueue(kind="experience_interpretation", payload={...}, dedupe_key=...)
```

---

### 8. 代码：Runtime 管理后台 Worker 生命周期

**文件**：`apps/wechat_ai_customer_service/admin_backend/services/customer_service_runtime.py`

**改造**：
- `start()`：在启动 listener 后，同时启动 background_worker 子进程
- `stop()`：在停止 listener 后，同时停止 background_worker
- `status()`：增加 `worker_pid`、`worker_running`、`queue_pending_count` 字段

---

## P2 待改造项

### 9. HTTP 连接池优化

**文件**：`apps/wechat_ai_customer_service/llm_config.py` 或 DeepSeek 调用层

**目标**：复用 `urllib.request` 的 HTTP connection，避免每次 `--once` 重建 TCP 连接。

**实现**：使用 `http.client.HTTPSConnection` 池或 `urllib.request` 的 opener 复用。

---

### 10. Prompt Token 精简

**文件**：`apps/wechat_ai_customer_service/workflows/llm_reply_synthesis.py`

**目标**：减少 `build_reply_evidence_pack()` 输出的 token 数量，降低 API 响应时间。

**方向**：
- 截断过长的历史消息
- 压缩 evidence_pack 中的冗余字段
- 对 RAG hits 做更激进的截断
