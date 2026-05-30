# 微信自动客服 RPA 稳定与风控优化架构（2026-05-23）

## 背景
- 当前主策略为 `rpa_first`，`wxauto4` 仅保留储备，不参与默认发送。
- 微信风险主要来自“节奏异常、连续失败重试、掉线后盲发、窗口漂移误操作”。

## 总体设计
- 发送链路拆成三层：
  - `节奏层`: 发送前后随机停顿、循环抖动、近阈值冷却。
  - `输入层`: 人类化输入（UIA 分段赋值 / 剪贴板分段输入），支持小概率纠错回删。
  - `守卫层`: 目标会话确认、几何检查、频率限制、被动下线探针、命中即停。

## 关键决策
- 不做硬件指纹伪造、不改微信客户端、不注入内核驱动。
- 将“防检测”限定为行为稳态与合规限流，优先降低异常特征而非绕过安全机制。
- 所有策略通过 `rpa_humanized_send` 配置注入侧车环境变量，便于回滚。

## 数据流
1. `run_customer_service_listener.py` 读取 `listener_config.json`。
2. 归一化 `rpa_humanized_send` 并映射到 `WECHAT_WIN32_OCR_*` 环境变量。
3. `wechat_win32_ocr_sidecar.py` 发送时按策略选择：
   - `uia_chunks` / `auto`: UIA `ValuePattern` 分段输入；
   - `clipboard_chunks`: 剪贴板分段输入；
   - `clipboard_once`: 兼容兜底。
4. 发送后继续执行会话守卫与风险计数，必要时停机并上报。

## 可观测性
- 日志包含：
  - `managed_listener_start.rpa_humanized_send`
  - `send_result.method`
  - `send_result.click/uia/humanized_input`
  - `transport_risk` 与 `passive_probe` 命中情况

## 验收门槛
- 静态检查 + 回归 + 全量测试全部通过。
- 文件传输助手实盘通过，且无持续 `send_input_not_ready`、`target_not_confirmed`、`login_window_detected`。
- `preflight` 与 `capabilities` 显示仍为 `win32_ocr` 主链路。
