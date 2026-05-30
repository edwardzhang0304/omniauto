# 微信自动客服多会话并发调度实现与测试报告（2026-05-25）

## 1. 实现范围

- 新增持久化调度状态层：session pending、capture、LLM task、ready reply、context_version、stale、send FIFO。
- 增强 `SessionMonitor`：未处理会话不因预览不变而丢失，支持全部 pending 暴露，支持无预览未读信号。
- 新增 `CustomerServiceSchedulerRuntime`：RPA capture/send 串行，LLM planning 线程池并发。
- 新增 managed listener 桥接器：`concurrency_scheduler.enabled=true` 时在父监听进程内持久调度；默认关闭时仍走旧串行链路。
- 发送前仍走 freshness check；发现新消息或 gap risk 时旧回复 stale 并重新 pending。
- 发送成功后写回旧 workflow state 的 processed/message content keys，避免新旧链路去重分裂。
- 发送成功但 post-send state/audit 写入异常时，优先保持 scheduler reply 为 sent，避免重复盲发。
- 配置示例增加 `concurrency_scheduler` 默认关闭灰度开关。

## 2. 关键修复

- 修复父进程桥接器未绑定 `WECHAT_KNOWLEDGE_TENANT` 的问题，避免读取到其他租户的本地控制台目标配置。
- 修复同一 tick 内 LLM 快速完成后 callback 读取不到未保存 capture 的问题，通过向 freshness/send callback 注入 capture snapshot 解决。
- 修复无 `win32gui` 的测试解释器中窗口归一化测试失败的问题，测试内注入 fake `MoveWindow` 以继续验证核心逻辑。

## 3. 验证结果

- `run_customer_service_multi_session_scheduler_checks.py`：14/14 通过。
- `run_workflow_logic_checks.py`：通过。
- `run_burst_message_rpa_semantic_batch_checks.py`：通过。
- `run_realtime_reply_optimization_checks.py`：通过。
- `run_boundary_matrix_checks.py`：通过。
- `run_wechat_win32_ocr_compat_checks.py`：46/46 通过。
- `run_wxauto_package_manager_checks.py`：8/8 通过。
- `run_runtime_start_cloud_guard_checks.py`：3/3 通过。
- `run_vps_local_two_port_shared_sync_checks.py`：通过本地双端口云模拟。
- `run_admin_backend_checks.py`：20/20 通过。
- `run_smart_recorder_checks.py`：通过。
- 其余非真实微信 live 的 `run_*_checks.py` 共 41 个脚本均通过。

## 4. 未执行项

- 未执行 `run_customer_service_real_wechat_comprehensive_live_checks.py`。
- 未执行 `run_customer_service_real_wechat_fresh_long_flow_checks.py`。
- 原因：真实微信实盘发送按本轮约定留给用户后续执行。

## 5. 实盘前建议

- 先在 no-send 模式打开 `concurrency_scheduler.enabled=true`，观察 scheduler state、悬浮球、总控台状态同步。
- 再用文件传输助手或测试联系人做 3 会话、5 会话并发刷屏测试。
- 实盘 send 前确认 `WECHAT_ENABLE_WXAUTO4` 未显式设为 `1`，确保仍是 RPA-first 且 wxauto4 reserve 关闭。
