# Product Master Split Doc Index

Date: 2026-05-16

This document set defines the one-step cleanup that separates product master data from formal business knowledge for every WeChat AI customer-service account.

## Documents

1. `WECHAT_AI_CUSTOMER_SERVICE_PRODUCT_MASTER_SPLIT_ULTIMATE_ARCHITECTURE_20260516.md`
   - Final target architecture.
   - Layer boundaries.
   - Read/write ownership rules.

2. `WECHAT_AI_CUSTOMER_SERVICE_PRODUCT_MASTER_SPLIT_DATA_CONTRACT_20260516.md`
   - Product master filesystem contract.
   - Compatibility rules for old `knowledge_bases/products`.
   - Runtime and API contract.

3. `WECHAT_AI_CUSTOMER_SERVICE_PRODUCT_MASTER_SPLIT_MIGRATION_RUNBOOK_20260516.md`
   - Migration phases.
   - Rollback and compatibility strategy.
   - Operator acceptance checklist.

4. `WECHAT_AI_CUSTOMER_SERVICE_PRODUCT_MASTER_SPLIT_DEVELOPMENT_CHECKLIST_20260516.md`
   - Chapter-by-chapter implementation checklist.
   - Files to change.
   - Guardrails before each chapter advances.

5. `WECHAT_AI_CUSTOMER_SERVICE_PRODUCT_MASTER_SPLIT_TEST_AND_ACCEPTANCE_PLAN_20260516.md`
   - Static tests.
   - Focused regressions.
   - Full regression and live WeChat acceptance matrix.

## One-Line Target

Product master data answers "what is sold, price, stock, specs, availability"; formal business knowledge answers "how to sell, rules, boundaries, process"; RAG experience stores observed evidence; the live style adapter controls final wording.
