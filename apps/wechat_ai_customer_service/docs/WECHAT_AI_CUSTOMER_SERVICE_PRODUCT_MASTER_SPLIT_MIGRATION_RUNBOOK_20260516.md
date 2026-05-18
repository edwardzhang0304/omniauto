# Product Master Split Migration Runbook

Date: 2026-05-16

## Goal

Move product master data out of formal knowledge storage without losing compatibility with existing runtime, tests, or UI.

## Phase 1: Prepare

1. Create product master root helpers.
2. Add `ProductMasterStore`.
3. Add migration script.
4. Add tests before changing broad behavior.

## Phase 2: Copy Product Data

For each tenant:

1. Read legacy product items from:

```text
knowledge_bases/products/items/*.json
```

2. Copy normalized items to:

```text
product_master/items/*.json
```

3. Write product master `schema.json`, `resolver.json`, and `manifest.json`.

4. Do not delete legacy files during migration.

## Phase 3: Switch Reads

1. `KnowledgeRuntime.list_items("products")` reads product master first.
2. `KnowledgeBaseStore.list_items("products")` reads product master first.
3. Formal category iteration excludes product master.

## Phase 4: Switch Writes

1. `KnowledgeBaseStore.save_item("products")` writes product master.
2. Product console inventory updates write product master.
3. Product generator confirmations write product master.
4. Candidate apply to `products` remains blocked.

## Phase 5: UI Clarification

1. Product catalog is the main product-maintenance entry.
2. Formal knowledge editor hides product master from ordinary formal categories.
3. Product master can still be viewed through compatibility APIs.

## Rollback

Rollback does not require data deletion:

1. Disable product-master-first reads by reverting code.
2. Legacy product files remain in `knowledge_bases/products`.
3. Product master copies remain inert if old code is restored.

## Verification Checklist

- Product count before/after migration matches.
- Product console lists products.
- Product detail opens.
- Inventory update writes product master.
- Candidate apply to `products` fails.
- RAG promotion to `products` fails.
- Chejin recommendation still uses vehicle products only.
