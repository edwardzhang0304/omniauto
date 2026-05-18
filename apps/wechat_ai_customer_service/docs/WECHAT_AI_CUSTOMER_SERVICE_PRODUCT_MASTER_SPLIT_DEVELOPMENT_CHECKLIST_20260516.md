# Product Master Split Development Checklist

Date: 2026-05-16

## Chapter 1: Storage Boundary

- Add `tenant_product_master_root`.
- Add `ProductMasterStore`.
- Add product schema/resolver helpers.
- Add migration script.
- Test: product master migration check.

## Chapter 2: Runtime Read Boundary

- Route `KnowledgeRuntime.list_items("products")` to product master.
- Route `KnowledgeRuntime.get_item("products")` to product master.
- Exclude product master from generic formal reply iteration.
- Test: runtime products are read from product master and not iterated as formal reply items.

## Chapter 3: Admin Store and API Boundary

- Route `KnowledgeBaseStore` product reads/writes to product master.
- Route schema manager product schema/resolver to product master.
- Add product master category record in `/api/knowledge/categories`.
- Test: product APIs remain compatible.

## Chapter 4: Candidate/RAG Boundary

- Keep `products` and `erp_exports` blocked from candidate apply.
- Keep RAG promotion to products blocked.
- Ensure formal comparison labels product master as product authority, not ordinary formal knowledge.
- Test: candidate and RAG product-master guards.

## Chapter 5: UI Boundary

- Hide product master from ordinary formal knowledge list.
- Keep product catalog as the user-facing maintenance entry.
- Update copy from "同步到正式知识" to "商品主数据".
- Test: frontend static string checks and `node --check`.

## Chapter 6: Compatibility and Full Regression

- Compile compatibility artifacts.
- Run admin/backend/knowledge/runtime/product tests.
- Run chejin used-car matrix.
- Run style/realtime/workflow checks.
- Run controlled live File Transfer Assistant flow.

## Hard Guardrails

- Do not let raw chat learning write product master.
- Do not let RAG promotion write product master.
- Do not let final style adapter add product facts.
- Do not remove legacy product files in the first migration; they are rollback evidence.
