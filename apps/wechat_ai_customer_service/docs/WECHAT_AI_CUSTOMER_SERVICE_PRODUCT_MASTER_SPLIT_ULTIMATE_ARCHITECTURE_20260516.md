# Product Master Split Ultimate Architecture

Date: 2026-05-16

## Problem

The current system treats `products` as a category under `knowledge_bases`. This works operationally, but it blurs authority boundaries:

- Product facts look like formal knowledge.
- RAG experience comparison sees product facts as "formal knowledge".
- Candidate-review code needs repeated special-case blocks for products.
- Users can misunderstand product facts as promotable knowledge.

The final architecture must remove that ambiguity.

## Final Layers

### 1. Product Master

Authority:

- Product name.
- SKU/model.
- Category.
- Aliases.
- Specs.
- Price.
- Inventory.
- Shipping or viewing policy.
- Warranty or condition notes.
- Product-level risk rules.

Allowed write paths:

- Product catalog UI.
- Product assistant/manual product import.
- Explicit product-master migration script.
- Future ERP/API sync.

Forbidden write paths:

- RAG experience promotion.
- Candidate knowledge apply.
- Raw chat learning.
- Style adapter.
- Automatic knowledge closeout.

### 2. Formal Business Knowledge

Authority:

- Policies.
- Process rules.
- Boundary rules.
- Generic sales scripts.
- Customer-service guidelines.
- Product-scoped FAQ/rules/explanations only when bound to an existing product ID.

Allowed write paths:

- Manual formal-knowledge editor.
- Reviewed candidate apply for non-product-master categories.
- Product detail page for product-scoped knowledge.

Forbidden write paths:

- Direct product price/stock/spec facts.
- Chat-derived product master facts.

### 3. RAG Experience

Authority:

- Observed chats and uploaded materials as evidence.
- Customer phrasing.
- Scene patterns.
- Possible suggestions for human review.

Rules:

- RAG can be searched.
- RAG can suggest non-product formal candidates.
- RAG cannot authorize product master writes.
- Product-shaped RAG is automatically triaged or kept as non-authoritative evidence.

### 4. Live Style Adapter

Authority:

- Final wording.
- Naturalness.
- Anti-AI-exposure behavior.
- Handoff concealment wording.
- Repetition reduction.

Rules:

- It may borrow expression style.
- It may not create product facts.
- It may not overwrite price, inventory, availability, warranty, or commitments.

## New Physical Storage

Tenant product master:

```text
apps/wechat_ai_customer_service/data/tenants/<tenant_id>/product_master/
  schema.json
  resolver.json
  items/
    <product_id>.json
  manifest.json
```

Default tenant product master:

```text
apps/wechat_ai_customer_service/data/tenants/default/product_master/
```

Legacy compatibility source:

```text
apps/wechat_ai_customer_service/data/tenants/<tenant_id>/knowledge_bases/products/
apps/wechat_ai_customer_service/data/knowledge_bases/products/
```

Legacy paths are migration/fallback only. Runtime authority is `product_master`.

## Runtime Read Rules

1. Product queries call `KnowledgeRuntime.list_items("products")`.
2. `KnowledgeRuntime.list_items("products")` reads `product_master`.
3. If `product_master/items` is empty, it falls back to legacy `knowledge_bases/products/items` for compatibility.
4. Formal reply iteration excludes `products`.
5. Product facts enter reply generation through compiled product knowledge or product evidence builders, not through generic formal-knowledge iteration.

## Write Rules

1. `KnowledgeBaseStore.save_item("products", item)` writes to `product_master`.
2. Reviewed candidates with `target_category=products` remain blocked.
3. RAG promotion to `products` remains blocked.
4. Product-scoped knowledge remains in `product_item_knowledge/<product_id>/...` and requires the product ID to exist in product master.
5. Legacy `knowledge_bases/products` must not receive new product writes after the split.

## UI Rules

1. The formal knowledge list hides product master as a standalone formal category.
2. Product master appears in the product catalog module.
3. Generator/product assistant may still target `products`, but confirmation writes product master, not formal knowledge.
4. Product-scoped categories are edited from product detail context.

## Compatibility Rules

1. Existing data is copied, not destroyed.
2. Old product category files remain readable fallback during transition.
3. The compiled compatibility artifact `product_knowledge.example.json` continues to expose `products` for old runtime code.
4. Tests and docs must treat `knowledge_bases/products` as legacy, not source of truth.

## Acceptance Criteria

- Product master has its own physical root.
- Runtime product reads use product master.
- Product writes from product UI/generator land in product master.
- Candidate/RAG promotion to product master is impossible.
- Formal categories no longer rely on product category as a normal knowledge category.
- Chejin used-car replies still recommend real vehicles and avoid non-car products.
