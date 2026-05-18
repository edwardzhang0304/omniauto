# Product Master Split Data Contract

Date: 2026-05-16

## Product Master Item

Each product item is a JSON object:

```json
{
  "schema_version": 1,
  "category_id": "products",
  "id": "safe_product_id",
  "status": "active",
  "source": {
    "type": "manual"
  },
  "data": {
    "name": "商品名称",
    "sku": "型号/SKU",
    "category": "商品类目",
    "aliases": ["客户叫法"],
    "specs": "规格参数",
    "price": 0,
    "unit": "台",
    "price_tiers": [],
    "inventory": 1,
    "shipping_policy": "发货、看车或交付说明",
    "warranty_policy": "售后、质保或车况说明",
    "reply_templates": {},
    "risk_rules": [],
    "additional_details": {}
  },
  "runtime": {
    "allow_auto_reply": true,
    "requires_handoff": false,
    "risk_level": "normal"
  },
  "metadata": {
    "created_at": "ISO_TIME",
    "updated_at": "ISO_TIME",
    "created_by": "admin",
    "updated_by": "admin"
  }
}
```

## Product Master Root

```text
product_master/
  schema.json
  resolver.json
  items/
  manifest.json
```

`schema.json` and `resolver.json` use the existing product schema and resolver shape so product UI fields remain stable.

## Formal Knowledge Contract

Formal knowledge categories exclude product master:

- `chats`
- `policies`
- `erp_exports`
- custom categories
- shared formal categories
- product-scoped categories by context only

`products` may still appear as a compatibility API category with:

```json
{
  "id": "products",
  "scope": "product_master",
  "authority": "manual_product_master_only",
  "participates_in_learning": false
}
```

## API Contract

Existing endpoints remain compatible:

- `GET /api/knowledge/products`
- `GET /api/knowledge/products/{product_id}`
- `GET /api/knowledge/categories/products/items`
- `GET /api/product-console/catalog`
- `POST /api/product-console/products/{product_id}/inventory`

Contract change:

- Reads now come from product master.
- Writes now land in product master.
- Product master is not treated as formal knowledge for RAG promotion.

## RAG and Candidate Contract

RAG experience and candidates must preserve these decisions:

```json
{
  "target_category": "products",
  "allowed": false,
  "reason": "product_master_manual_intake_only"
}
```

or:

```json
{
  "target_category": "products",
  "allowed": false,
  "reason": "rag_product_master_promotion_disabled"
}
```

## Postgres Contract

If PostgreSQL storage is enabled:

- Product master uses layer `product_master`.
- Product-scoped knowledge continues using layer `tenant_product`.
- Legacy product rows in layer `tenant` are fallback only.

## Compatibility Contract

Fallback is read-only:

1. If `product_master/items` has products, use it.
2. If it has no products, read legacy `knowledge_bases/products/items`.
3. New writes never target legacy products.
