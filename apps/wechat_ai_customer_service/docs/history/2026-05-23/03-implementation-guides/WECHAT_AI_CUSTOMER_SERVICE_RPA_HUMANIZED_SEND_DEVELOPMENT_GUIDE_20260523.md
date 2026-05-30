# 微信自动客服 RPA 人类化发送开发指南（2026-05-23）

## 代码改造点
- `adapters/wechat_win32_ocr_sidecar.py`
  - 新增人类化输入参数解析。
  - 发送前后延时控制。
  - UIA 分段输入与纠错回删。
  - 剪贴板分段输入（非整段一次粘贴）。
- `scripts/run_customer_service_listener.py`
  - 新增 `rpa_humanized_send` 归一化与环境变量映射。
  - 启动日志记录当前生效策略。
- `tests/run_wechat_win32_ocr_compat_checks.py`
  - 增加人类化参数与分段行为回归。
- `tests/run_realtime_reply_optimization_checks.py`
  - 增加监听器配置映射回归。

## 开发注意事项
- 优先保留旧链路可用性：`clipboard_once` 必须始终可用。
- 人类化逻辑不得降低守卫等级：`target_confirm`、`rate_guard`、`logout_probe` 必须保持。
- 错字模拟只能“增删同轮闭环”，最终文本必须完全一致。

## 失败回滚策略
- 仅需将 `rpa_humanized_send.enabled=false` 或 `input_method=clipboard_once`。
- 不需要回滚架构层；保持 `rpa_first` 与被动探针照常运行。

## 代码审计检查单
- 是否存在未受控循环重试导致异常高频发送。
- 是否存在发送失败后未停机继续打字的路径。
- 是否存在掉线后仍尝试发送路径。
- 是否存在将测试消息错误沉淀到正式知识库路径。
