# 微信自动客服高并发保质量实施清单（2026-06-02）

## A. 数据结构与配置层

### A1. 调度配置扩展
- [ ] 文件：`apps/wechat_ai_customer_service/admin_backend/services/customer_service_scheduler_state.py`
- [ ] 在 `SchedulerConfig` 中新增：
  - `planner_max_concurrency`
  - `polish_max_concurrency`
  - `planner_queue_max_size`（可选）
  - `polish_queue_max_size`（可选）
- [ ] 保留现有 `send_max_replies_per_round=1` 语义不变。

### A2. 配置样例同步
- [ ] 文件：`apps/wechat_ai_customer_service/configs/default.example.json`
- [ ] 文件：`apps/wechat_ai_customer_service/configs/jiangsu_chejin_xucong_live.example.json`
- [ ] 新增高并发参数默认建议。
- [ ] 明确说明：并发仅作用于后台 LLM，不作用于微信前台 RPA。

## B. 调度状态机改造

### B1. State Store 字段补充
- [ ] 文件：`apps/wechat_ai_customer_service/admin_backend/services/customer_service_scheduler_state.py`
- [ ] 会话状态补充：
  - `planner_task_id`
  - `polish_task_id`
  - `planner_started_at`
  - `planner_finished_at`
  - `polish_started_at`
  - `polish_finished_at`
- [ ] `ready_replies` 补充：
  - `reply_variant`（`polished` / `fallback_draft`）
  - `planner_result_version`
  - `polish_result_version`

### B2. 任务状态补充
- [ ] `llm_tasks` 区分 planner 与 polish，或新增 `polish_tasks` 独立桶。
- [ ] 明确 `queued/running/completed/failed/stale/degraded` 的状态集合。

## C. Runtime 调度改造

### C1. 双线程池
- [ ] 文件：`apps/wechat_ai_customer_service/admin_backend/services/customer_service_scheduler.py`
- [ ] 当前单 `_executor` 拆为：
  - `planner_executor`
  - `polish_executor`
- [ ] 分别维护：
  - `planner_futures`
  - `polish_futures`

### C2. 调度顺序调整
- [ ] `_submit_llm_tasks()` 只负责 planner 任务提交。
- [ ] planner 完成后，不直接进入 ready queue，而是：
  1. 写入 planner result
  2. 生成 polish task
  3. 提交到 `polish_executor`
- [ ] polish 完成后才写入 `ready_replies`。

### C3. 失败与降级
- [ ] planner 失败：保持当前失败逻辑，不生成 ready reply。
- [ ] polish 失败但存在安全草稿：写入 `ready_replies`，标记 `fallback_draft`。
- [ ] polish guard 拒绝：同上，记为 `degraded`，但不当成主任务失败。

## D. Workflow 边界保持

### D1. 主回复规划边界不变
- [ ] 文件：`apps/wechat_ai_customer_service/workflows/listen_and_reply.py`
- [ ] 不改变知识层级、RAG 结构、规则优先级与业务决策。
- [ ] 仅补 planner / polish 结果结构，便于异步调度。

### D2. 最终润色边界不变
- [ ] 文件：`apps/wechat_ai_customer_service/workflows/final_visible_llm_polish.py`
- [ ] 不改业务 guard 原则。
- [ ] 不因并发改造而默认关闭或弱化 final polish。
- [ ] 只补 observability 字段：
  - queue wait
  - runtime
  - degraded reason

## E. 发送阶段保护

### E1. 发送队列保持单线程
- [ ] 文件：`apps/wechat_ai_customer_service/admin_backend/services/customer_service_scheduler.py`
- [ ] 继续保持 `send_max_replies_per_round=1` 为默认。
- [ ] 不引入任何并发 send worker。

### E2. 发送前确认不削弱
- [ ] 保持 freshness 检查。
- [ ] 保持目标会话确认。
- [ ] 保持 post-send guard。

## F. 观测与日志

### F1. 指标埋点
- [ ] planner queue/runtime
- [ ] polish queue/runtime
- [ ] ready queue wait
- [ ] send wait
- [ ] polish degraded rate
- [ ] planner failed rate

### F2. 产物落盘
- [ ] 文件：`runtime/.../state/customer_service_scheduler_state.json`
- [ ] 文件：`runtime/.../logs/customer_service_managed_listener.log`
- [ ] 文件：测试产物 JSON

## G. 测试与验收

### G1. 静态与单元
- [ ] `python -m py_compile` 覆盖改动文件
- [ ] `run_workflow_logic_checks.py`
- [ ] `run_customer_service_multi_session_scheduler_checks.py`
- [ ] 新增“双池并发”专用离线检查

### G2. 无发送重放
- [ ] 三会话并发重放
- [ ] 禁用 polish cache 的真实 API 并发验证
- [ ] 验证模型仅落在允许名单

### G3. 实盘
- [ ] 两会话真人节奏
- [ ] 三会话真人节奏
- [ ] 长稳挂机

## H. 回滚准备

### H1. 配置级回滚
- [ ] 保留单池模式开关
- [ ] 保留 `planner_max_concurrency=2` 回退值
- [ ] 保留 `polish_max_concurrency=1` 回退值

### H2. 代码级回滚
- [ ] 双池逻辑尽量封装，不改业务层大面积代码路径
- [ ] 若双池异常，可快速回退到当前单池实现
