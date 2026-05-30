# 微信自动客服 RPA 稳定运行手册（2026-05-23）

## 启动前检查
1. `preflight --target 文件传输助手 --json` 确认 `adapter=win32_ocr`。
2. 微信已人工登录且主窗口可见。
3. `listener_config.json` 中 `rpa_humanized_send` 参数已落地。

## 推荐参数档位
- 保守档（默认）
  - `input_method=auto`
  - `typing_chunk=2~6`
  - `typing_char_delay=50~180ms`
  - `typo_probability=0.22` `typo_max=1`
- 风险升高档（更慢更稳）
  - 提高 `send_pre_delay_max_ms`、`send_post_input_delay_max_ms`
  - 提高 `warning_cooldown_seconds`
  - 降低每小时发送上限

## 异常处理
- `wechat_logout_detected_by_passive_probe`
  - 立即停机；人工登录后重启。
- `wechat_send_input_not_ready_repeated`
  - 先检查窗口是否被遮挡/输入框失焦，再适度提高延时和冷却。
- `target_not_confirmed`
  - 检查窗口尺寸与侧栏可见性，必要时启用窗口归一化。

## 运行中观测
- 重点观察：
  - `transport_risk_guard_state.json`
  - `runtime_status.json` 中 `transport_risk.passive_probe`
  - `audit.jsonl` 的 `send_result.method` 与失败态统计

## 停机准则
- 掉线、登录页、安全阻塞命中阈值：必须停机。
- 连续输入确认失败达到阈值：必须停机，不得自动无限重试。
