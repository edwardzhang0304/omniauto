# 微信自动客服 RPA 稳定与风控优化文档索引（2026-05-23）

## 目标
- 在 `wxauto4` 保持技术储备禁用前提下，持续强化 `win32_ocr` 纯 RPA 链路。
- 将“防风控”收敛为可审计、可配置、可回滚的工程能力，不依赖隐蔽驱动或硬件指纹伪造。

## 文档清单
- 架构方案
  - `../01-architecture-and-plans/WECHAT_AI_CUSTOMER_SERVICE_RPA_STABILITY_ANTI_RISK_ARCHITECTURE_20260523.md`
- 参数契约
  - `../02-specs-and-contracts/WECHAT_AI_CUSTOMER_SERVICE_RPA_HUMANIZED_SEND_SPEC_20260523.md`
- 开发落地指南
  - `../03-implementation-guides/WECHAT_AI_CUSTOMER_SERVICE_RPA_HUMANIZED_SEND_DEVELOPMENT_GUIDE_20260523.md`
- 运维与故障处置
  - `../04-operations-and-migration/WECHAT_AI_CUSTOMER_SERVICE_RPA_STABILITY_OPERATION_RUNBOOK_20260523.md`
- 测试与验收计划
  - `../05-tests-and-reports/WECHAT_AI_CUSTOMER_SERVICE_RPA_STABILITY_TEST_AND_ACCEPTANCE_PLAN_20260523.md`
- 风控边界声明
  - `../99-misc/WECHAT_AI_CUSTOMER_SERVICE_RPA_DETECTION_BOUNDARY_20260523.md`

## 交付原则
- 参数默认安全保守，可在 `listener_config.json` 细调。
- 所有关键行为必须能在日志中定位：输入方式、降级路径、被动下线探针、停机原因。
- 若验证不达标，必须回到实现阶段继续迭代，不允许“带病验收”。
