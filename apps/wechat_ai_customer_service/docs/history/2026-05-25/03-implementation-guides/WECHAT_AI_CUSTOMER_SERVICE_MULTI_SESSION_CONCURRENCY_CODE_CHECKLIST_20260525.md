# 微信自动客服多会话并发调度代码清单（2026-05-25）

## 1. 代码改造范围

| 文件或模块 | 操作 |
|---|---|
| `admin_backend/services/session_monitor.py` | 修 pending 保留、活跃截断、公平优先级 |
| `workflows/listen_and_reply.py` | 拆分 capture/build reply/send，保留旧入口 |
| `scripts/run_customer_service_listener.py` | 接入 scheduler loop、worker pool、运行状态 |
| `adapters/wechat_win32_ocr_sidecar.py` | 增强会话列表 OCR 预览、时间、未读信号 |
| `adapters/wechat_connector.py` | 保持 RPA lock；必要时暴露 capture/send 专用结果字段 |
| `admin_backend/services/customer_service_settings.py` | 增加调度器配置读写 |
| `admin_backend/api/customer_service.py` | 暴露调度状态和配置 |
| `web_frontend` 相关控制台文件 | 显示队列积压、运行状态、暂停状态 |
| `tests/` | 新增多会话调度、stale、发送队列和 RPA-only 测试 |

## 2. 新增文件建议

- `apps/wechat_ai_customer_service/admin_backend/services/customer_service_scheduler_state.py`
- `apps/wechat_ai_customer_service/admin_backend/services/customer_service_scheduler.py`
- `apps/wechat_ai_customer_service/tests/run_customer_service_multi_session_scheduler_checks.py`
- `apps/wechat_ai_customer_service/tests/run_customer_service_multi_session_live_dryrun.py`
- `runtime/rpa_customer_multi_session_live.py`

## 3. 必做实现项

### 3.1 Scheduler state

- [ ] 原子读写 JSON 状态。
- [ ] 文件锁保护并发写。
- [ ] session 状态机。
- [ ] context_version 递增。
- [ ] pending capture queue。
- [ ] LLM task queue。
- [ ] ready send queue。
- [ ] stale reply 标记。
- [ ] expired / failed 状态审计。

### 3.2 SessionMonitor 修复

- [ ] 活跃会话截断前全部记录 pending。
- [ ] 未处理 pending 不能被下一轮无变化清除。
- [ ] 预览文本为空时不误判已读。
- [ ] 新增 `pending_since`、`last_detected_at`、`last_dispatched_at`。
- [ ] 支持公平排序。
- [ ] 支持 ignored_names 和 enabled_names。

### 3.3 RPA capture-only

- [ ] 快速切换目标会话并读取消息。
- [ ] 复用 history backfill。
- [ ] 复用 select_batch_details。
- [ ] gap risk 时暂停该会话，不创建自动回复。
- [ ] 捕获成功后写 capture batch。
- [ ] 不调用 LLM。
- [ ] 不发送微信消息。

### 3.4 LLM worker pool

- [ ] 全局并发上限。
- [ ] 同一会话单 inflight。
- [ ] LLM timeout。
- [ ] 完成后校验 context_version。
- [ ] stale 不入发送队列。
- [ ] 失败可 fallback 或 handoff。
- [ ] 结果写审计。

### 3.5 Send runner

- [ ] ready reply FIFO。
- [ ] 同一会话只发送最新版本。
- [ ] 发送前调用 freshness check。
- [ ] 发现新消息则 stale + requeue。
- [ ] 成功后 mark processed。
- [ ] 失败后 send_failed，不盲目重发。
- [ ] 保持人类化 RPA 输入。

### 3.6 Pause / stop

- [ ] F8 暂停停止 capture。
- [ ] F8 暂停停止 send。
- [ ] F8 暂停不再派发新 LLM task。
- [ ] 正在运行的 LLM 可完成但不发送。
- [ ] 停止时状态写入 stopped，不留下 sending 半状态。

## 4. 代码审计红线

- [ ] 任何新线程不得直接调用 RPA send。
- [ ] 任何 stale reply 不得发送。
- [ ] 任何异常不得跳过 state 保存。
- [ ] 任何 wxauto4 fallback 不得默认启用。
- [ ] 任何批量复制粘贴不得成为常规发送路径。
- [ ] 任何会话名匹配失败不得误发到当前窗口。
- [ ] 任何 LLM 输出不得绕过身份 guard 和风险 guard。

## 5. 静态检查命令

最低检查：

~~~powershell
python -m py_compile apps/wechat_ai_customer_service/workflows/listen_and_reply.py apps/wechat_ai_customer_service/scripts/run_customer_service_listener.py apps/wechat_ai_customer_service/admin_backend/services/session_monitor.py apps/wechat_ai_customer_service/adapters/wechat_win32_ocr_sidecar.py apps/wechat_ai_customer_service/adapters/wechat_connector.py
~~~

新增模块后追加：

~~~powershell
python -m py_compile apps/wechat_ai_customer_service/admin_backend/services/customer_service_scheduler_state.py apps/wechat_ai_customer_service/admin_backend/services/customer_service_scheduler.py
~~~

## 6. 单元测试清单

- [ ] 3 会话同时 pending，全部进入 capture queue。
- [ ] 10 会话同时 pending，每轮只处理 3 个，其余保持 pending。
- [ ] 同一会话 context_version 递增后旧 LLM task stale。
- [ ] 多个 ready reply 按 ready_at FIFO。
- [ ] 同一会话多个 ready reply 只发送最新。
- [ ] freshness check 发现新消息后不发送旧回复。
- [ ] F8 pause 后 capture/send 停止。
- [ ] worker timeout 后进入 failed 或 fallback。

## 7. 集成测试清单

- [ ] 新调度器关闭时旧串行链路通过。
- [ ] 新调度器开启 no-send 模式通过。
- [ ] RPA-only status/capabilities 证明 `adapter=win32_ocr`。
- [ ] SessionMonitor 在无 preview/time 时不清 pending。
- [ ] managed listener watchdog 不误杀正常慢 RPA 发送。
- [ ] runtime status 和悬浮球状态同步。

## 8. 实盘测试清单

- [ ] 3 会话并发短测，每会话 3 条。
- [ ] 5 会话并发压力，每会话 5 条。
- [ ] 单会话 LLM 思考期间继续补充消息。
- [ ] 发送队列积压后恢复。
- [ ] F8 暂停、恢复、停止。
- [ ] 微信窗口最小化、尺寸不对、被遮挡后恢复。
- [ ] 发送前目标窗口校验。
- [ ] 白屏、掉线、登录窗口检测停机。

## 9. 回滚检查

- [ ] 配置关闭 `concurrency_scheduler.enabled` 后恢复旧行为。
- [ ] 新 state 文件损坏时能重建或隔离。
- [ ] 旧 state 去重记录不被覆盖。
- [ ] 回滚后不会重发已发送回复。
