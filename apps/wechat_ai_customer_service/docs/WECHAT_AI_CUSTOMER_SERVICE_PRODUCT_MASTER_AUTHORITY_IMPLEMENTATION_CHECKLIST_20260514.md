# 微信自动客服 商品主数据权威化实施清单（2026-05-14）

## 1. 文档准备
- [x] 完成架构与开发指南。
- [x] 完成实施清单。
- [x] 完成操作手册。
- [x] 完成测试与验收计划。

## 2. 策略层改造
- [x] `source_authority_policy` 将 `products/erp_exports` 改为全源硬拒。
- [x] 输出统一拒绝原因与文案：商品主数据仅支持人工维护。
- [x] 策略版本升级（`source_authority_v2`）。

## 3. 晋升链路改造
- [x] `build_candidate_from_experience` 对商品主数据形态直接拒绝。
- [x] `resolve_formal_overlap` 禁止对商品主数据执行 replace/merge。
- [x] `save_formal_item` 禁止 RAG overlap 路径写入商品主数据。

## 4. 候选链路改造
- [x] `CandidateStore.apply_native_candidate` 禁止写入 `products/erp_exports`。
- [x] `CandidateStore.change_candidate_category` 禁止改写到 `products/erp_exports`。
- [x] `CandidateStore.supplement_candidate` 禁止补充商品主数据候选。

## 5. 自动分诊改造
- [x] `rag_experience_interpreter.guardrail_assessment` 对商品主数据形态强制 `discard` 自动降噪。

## 6. 回归与验收
- [x] 更新/新增回归断言（source authority 全源硬拒、候选 apply/reclassify 阻断）。
- [x] 跑静态检查。
- [x] 跑 `run_admin_backend_checks.py` 验证。
- [x] 跑 `run_smart_recorder_checks.py` 验证。
- [x] 补充 long-run 状态与测试日志。
