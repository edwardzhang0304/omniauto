# 后台 Worker 改造计划（P1）

## 目标
利用已有 `WorkQueueService` 建立独立后台 worker 进程，彻底将非回复类工作从前台移除。

## 已有基础设施

`admin_backend/services/work_queue.py` 已提供：
- `enqueue()`：入队，支持去重（dedupe_key）、优先级、延迟执行
- `claim()`：出队，支持锁机制（lock_seconds）、重试
- `complete()` / `fail()`：完成/失败
- 双后端：文件（默认）或 Postgres

## 后台 Worker 设计

### 进程模型

新建文件：`apps/wechat_ai_customer_service/scripts/background_worker.py`

运行方式：由 managed listener 或系统服务管理，独立进程长期运行。

```python
# 伪代码
while True:
    jobs = work_queue.claim(queue="customer_service", limit=3, lock_seconds=600)
    for job in jobs:
        handler = JOB_HANDLERS.get(job["kind"])
        if handler:
            try:
                result = handler(job["payload"])
                work_queue.complete(job["job_id"], result)
            except Exception as e:
                work_queue.fail(job["job_id"], str(e), retry=True)
    time.sleep(5)
```

### 任务类型定义

| kind | 说明 | LLM 需求 | 预估耗时 |
|------|------|---------|---------|
| `experience_interpretation` | 对 raw_messages 中的新消息做业务类型解读、意图标注 | pro | 5-15s/条 |
| `rag_quality_audit` | 对新吸收的 RAG experience 做质量审核、风险检查 | pro | 3-10s/条 |
| `knowledge_compile` | 触发 `KnowledgeCompiler().compile_to_disk()` | 无 | 1-3s |
| `conversation_summary` | 对长对话做摘要、提取客户画像 | pro | 10-30s |
| `customer_data_sync` | 批量写入 Excel、同步到其他系统 | 无 | 1-5s |
| `raw_message_archive` | 原始消息归档、过期清理 | 无 | 1-2s |
| `diagnostics_deep_check` | 运行 LLM 知识审计 | pro | 30-120s |

### 前台入队点

**文件**：`apps/wechat_ai_customer_service/workflows/listen_and_reply.py`

在 `process_target()` 发送完回复后、函数返回前，将以下工作改为 enqueue：

```python
# 当前：同步执行
maybe_record_raw_messages(target, config, messages)   # → 改为 enqueue
write_customer_data(target_state, config)             # → 改为 enqueue
update_state_file(state)                              # → 保留同步（轻量），或改为延迟写入

# 新增入队
work_queue.enqueue(
    kind="experience_interpretation",
    payload={"message_ids": message_ids, "target": target.name},
    dedupe_key=f"exp_interp:{tenant_id}:{message_ids[-1]}",
)
work_queue.enqueue(
    kind="customer_data_sync",
    payload={"target": target.name, "tenant_id": tenant_id},
    dedupe_key=f"data_sync:{tenant_id}:{target.name}",
)
```

### 后台 Handler 实现

每个 handler 独立文件或集中在 `admin_backend/services/background_handlers.py`：

```python
JOB_HANDLERS = {
    "experience_interpretation": handle_experience_interpretation,
    "rag_quality_audit": handle_rag_quality_audit,
    "knowledge_compile": handle_knowledge_compile,
    "conversation_summary": handle_conversation_summary,
    "customer_data_sync": handle_customer_data_sync,
    "raw_message_archive": handle_raw_message_archive,
    "diagnostics_deep_check": handle_diagnostics_deep_check,
}
```

### Worker 生命周期管理

由 `CustomerServiceRuntime` 统一管理：
- `start()`：同时启动 listener 和 background_worker
- `stop()`：同时停止 listener 和 background_worker
- `status()`：返回 listener_pid + worker_pid + queue_summary

---

## P1 新建文件清单

| 文件 | 说明 |
|------|------|
| `scripts/background_worker.py` | 后台 worker 主进程 |
| `admin_backend/services/background_handlers.py` | 各任务类型的 handler 实现 |

## P1 修改文件清单

| 文件 | 修改说明 |
|------|---------|
| `workflows/listen_and_reply.py` | 发送回复后 enqueue 后台任务，不再同步执行重操作 |
| `admin_backend/services/customer_service_runtime.py` | 管理 worker 进程的生命周期 |
| `admin_backend/services/work_queue.py` | 如有必要，扩展队列功能（如批量 claim） |

## P1 预期效果

前台延迟进一步降低：
- 普通查询：**2.5-3.5s**（去掉了 0.5-1s 后置工作）
- 高风险查询：**4-5s**

后台任务独立运行，不再影响前台响应。
