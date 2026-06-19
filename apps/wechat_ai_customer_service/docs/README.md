# 微信智能客服文档区

当前客服开发硬基线：[customer_visible_reply_ownership_baseline.md](customer_visible_reply_ownership_baseline.md)。后续新增客服开发文档必须引用该基线。

当前最新版说明请优先阅读应用 README：[`../README.md`](../README.md)。

当前 RPA 控制层优化说明：

- [`ai_customer_service_acceptance_hardening_20260617.md`](ai_customer_service_acceptance_hardening_20260617.md)：微信 AI 客服双会话验收加固方案，区分 prompt-send RPA 失败、reply-send RPA 失败和 Brain no-visible，保证验收报告不混淆排障方向。
- [`ai_customer_service_latency_optimization_master_plan_20260619.md`](ai_customer_service_latency_optimization_master_plan_20260619.md)：微信 AI 客服端到端速度优化总纲，按 P0-P5 排序推进耗时埋点、短句 Brain profile、RPA 发送、OCR 捕获和双会话调度优化。
- [`add_friend_rpa_adaptive_delivery_plan_20260617.md`](add_friend_rpa_adaptive_delivery_plan_20260617.md)：本轮 add_friend 自适应改造交付文档，定义布局模型、设备画像、语义定位、校准模式和验收矩阵。
- [`add_friend_cli_contract_stability_plan_20260617.md`](add_friend_cli_contract_stability_plan_20260617.md)：add_friend Worker-facing CLI 契约稳定化方案，要求 `add-friend-entry-click-plan` 对外稳定、内部 Windows/macOS/DPI/OCR 适配可独立演进。
- [`add_friend_rpa_adaptive_refactor_plan_20260617.md`](add_friend_rpa_adaptive_refactor_plan_20260617.md)：当前 add_friend RPA 自适应重构主文档，区分朋友 PR 原始路线、当前 Windows 主路线和后续重构方案。
- [`wechat_rpa_adaptive_control_design.md`](wechat_rpa_adaptive_control_design.md)：微信聊天模块既有自适应操控思路说明，作为 add_friend 后续对齐的架构参考。
- [`wechat_rpa_platform_resolution_audit_20260617.md`](wechat_rpa_platform_resolution_audit_20260617.md)：微信操控分系统与多分辨率适配审计。
- [`add_friend_rpa_pr_readiness_20260616.md`](add_friend_rpa_pr_readiness_20260616.md)：朋友 PR #17 的历史 readiness 快照，仅用于追溯原始实现和回归口径，不作为当前主路线源-of-truth。
- [`rpa_backend_state_machine_optimization.md`](rpa_backend_state_machine_optimization.md)
- [`rpa_backend_state_machine_test_plan.md`](rpa_backend_state_machine_test_plan.md)
- [`rpa_low_disturbance_listener_design.md`](rpa_low_disturbance_listener_design.md)
- [`rpa_high_concurrency_quality_preserving_architecture_20260602.md`](rpa_high_concurrency_quality_preserving_architecture_20260602.md)
- [`rpa_high_concurrency_quality_preserving_implementation_checklist_20260602.md`](rpa_high_concurrency_quality_preserving_implementation_checklist_20260602.md)
- [`rpa_high_concurrency_quality_preserving_test_plan_20260602.md`](rpa_high_concurrency_quality_preserving_test_plan_20260602.md)
- [`rpa_high_concurrency_quality_preserving_runtime_parameter_recommendation_20260602.md`](rpa_high_concurrency_quality_preserving_runtime_parameter_recommendation_20260602.md)
- [`rpa_brain_end_to_end_latency_optimization_plan_20260606.md`](rpa_brain_end_to_end_latency_optimization_plan_20260606.md)
- [`rpa_multi_session_dispatch_hardening_architecture_20260601.md`](rpa_multi_session_dispatch_hardening_architecture_20260601.md)
- [`rpa_multi_session_dispatch_hardening_implementation_checklist_20260601.md`](rpa_multi_session_dispatch_hardening_implementation_checklist_20260601.md)
- [`rpa_multi_session_dispatch_hardening_test_plan_20260601.md`](rpa_multi_session_dispatch_hardening_test_plan_20260601.md)
- [`rpa_multi_session_dispatch_hardening_validation_report_20260601.md`](rpa_multi_session_dispatch_hardening_validation_report_20260601.md)

当前知识与 RAG 架构说明：

- [`brain_code_mechanism_layer_integration_design_20260609.md`](brain_code_mechanism_layer_integration_design_20260609.md)
- [`canonical_input_identity_design_20260612.md`](canonical_input_identity_design_20260612.md)
- [`brain_code_mechanism_layer_rule_inventory_20260609.md`](brain_code_mechanism_layer_rule_inventory_20260609.md)
- [`brain_code_mechanism_layer_implementation_plan_20260609.md`](brain_code_mechanism_layer_implementation_plan_20260609.md)
- [`brain_code_mechanism_layer_test_acceptance_plan_20260609.md`](brain_code_mechanism_layer_test_acceptance_plan_20260609.md)
- [`conversation_strategy_state_design_20260609.md`](conversation_strategy_state_design_20260609.md)
- [`brain_v2_customer_service_quality_gate_20260604/00_INDEX.md`](brain_v2_customer_service_quality_gate_20260604/00_INDEX.md)
- [`brain_first_customer_service_20260603/00_INDEX.md`](brain_first_customer_service_20260603/00_INDEX.md)
- [`product_master_formal_knowledge_common_sense_refactor_design.md`](product_master_formal_knowledge_common_sense_refactor_design.md)
- [`authority_gated_rag_ai_experience_pool_design.md`](authority_gated_rag_ai_experience_pool_design.md)
- [`authority_gated_rag_implementation_plan.md`](authority_gated_rag_implementation_plan.md)
- [`authority_gated_rag_migration_and_audit.md`](authority_gated_rag_migration_and_audit.md)
- [`authority_gated_rag_acceptance_test_plan.md`](authority_gated_rag_acceptance_test_plan.md)

历史归档用于追溯开发过程，不作为当前功能和架构的最终依据。

- 历史归档索引：[`history/INDEX.md`](history/INDEX.md)
- 历史文档目录：[`history/`](history/)
