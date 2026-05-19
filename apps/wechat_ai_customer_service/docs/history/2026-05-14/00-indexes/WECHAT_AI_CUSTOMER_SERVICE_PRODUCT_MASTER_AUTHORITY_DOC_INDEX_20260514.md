# 微信自动客服 商品主数据权威化文档索引（2026-05-14）

## 1. 背景
- 目标：将“商品资料（products/erp_exports）”定义为绝对权威主数据，彻底从 `RAG经验 -> 候选知识 -> 正式知识` 晋升链路中隔离。
- 原则：商品主数据只允许手动导入/人工维护；AI 与 RAG 只允许“读引用”，不允许“反向写入”。

## 2. 文档清单
1. `WECHAT_AI_CUSTOMER_SERVICE_PRODUCT_MASTER_AUTHORITY_ARCHITECTURE_AND_DEVELOPMENT_GUIDE_20260514.md`
2. `WECHAT_AI_CUSTOMER_SERVICE_PRODUCT_MASTER_AUTHORITY_IMPLEMENTATION_CHECKLIST_20260514.md`
3. `WECHAT_AI_CUSTOMER_SERVICE_PRODUCT_MASTER_AUTHORITY_OPERATION_RUNBOOK_20260514.md`
4. `WECHAT_AI_CUSTOMER_SERVICE_PRODUCT_MASTER_AUTHORITY_TEST_AND_ACCEPTANCE_PLAN_20260514.md`

## 3. 使用顺序
1. 先看架构与开发指南，理解边界与改造范围。
2. 按实施清单逐项核对是否完成。
3. 按操作手册做日常使用与排障。
4. 按测试与验收计划执行回归并出验收结论。
