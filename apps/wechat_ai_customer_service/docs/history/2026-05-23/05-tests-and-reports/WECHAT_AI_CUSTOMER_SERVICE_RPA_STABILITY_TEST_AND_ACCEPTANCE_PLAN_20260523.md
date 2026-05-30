# 微信自动客服 RPA 稳定性测试与验收计划（2026-05-23）

## 阶段顺序（强制）
1. 代码改造完成
2. 代码审计
3. 静态检查
4. 全量回归
5. 文件传输助手实盘
6. 深度验证（RPA-only、窗口尺寸与分辨率）

## 测试矩阵
- 单元/兼容
  - `run_wechat_win32_ocr_compat_checks.py`
  - `run_realtime_reply_optimization_checks.py`
  - `run_workflow_logic_checks.py`
- 静态
  - `python -m py_compile`（改动文件）
  - `python -m compileall -q apps/wechat_ai_customer_service`
- 全量
  - `run_admin_backend_checks.py --chapter all`
  - `run_vps_local_two_port_shared_sync_checks.py`
  - `run_knowledge_contamination_guard_checks.py`
  - `run_customer_service_diverse_long_checks.py`
- 实盘
  - `run_customer_service_real_wechat_fresh_long_flow_checks.py --scenario context_bridge`

## 验收标准
- 所有静态与全量测试通过。
- 实盘多轮无致命发送失败，`naturalness_gate=passed`。
- `preflight/capabilities` 确认 `adapter=win32_ocr`，`wxauto4_reserve_enabled=false`。
- 在不同窗口尺寸下可稳定发送；若不稳需给出固定窗口与参数适配方案。

## 失败处理
- 任一门禁失败即回到开发阶段修复，不允许跳过。
- 每次失败必须记录：命令、症状、根因、修复、复验结果。
