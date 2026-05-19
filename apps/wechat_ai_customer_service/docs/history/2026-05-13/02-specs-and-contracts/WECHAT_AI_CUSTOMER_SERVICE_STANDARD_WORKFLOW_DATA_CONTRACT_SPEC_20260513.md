# WeChat AI 客服标准工作流数据契约规格

## 1. 目的

统一改造前后的输入输出结构，避免出现：

1. 同一字段多种含义
2. 无法审计的数据漂移
3. 导入与运行时契约不一致

---

## 2. 契约对象总览

1. Learning Batch Manifest
2. Curated Template Item
3. Template Import Job
4. Release Manifest
5. Replay Eval Case
6. Replay Eval Report

---

## 3. Learning Batch Manifest

字段：

1. `batch_id` string，唯一
2. `tenant_id` string
3. `industry_id` string
4. `source_files` string[]
5. `time_range` object
6. `created_at` string(ISO8601)
7. `created_by` string

说明：

1. 一个 `batch_id` 对应一次清洗任务输入边界。

---

## 4. Curated Template Item（核心）

建议结构：

```json
{
  "schema_version": 1,
  "category_id": "chats",
  "id": "usedcar_tpl_xxx",
  "status": "active",
  "source": {
    "type": "cleaned_real_chat_pack",
    "batch_token": "BATCH_20260513_V1"
  },
  "data": {
    "customer_message": "客户问法",
    "service_reply": "客服回复模板",
    "intent_tags": ["需求探询"],
    "tone_tags": ["咨询式"],
    "linked_categories": ["products", "policies"],
    "linked_item_ids": [],
    "applicability_scope": "product_category",
    "product_category": "二手车",
    "usable_as_template": true,
    "additional_details": {
      "scenario": "需求探询",
      "hit_count": 12,
      "source_samples": []
    }
  },
  "runtime": {
    "allow_auto_reply": true,
    "requires_handoff": false,
    "risk_level": "normal"
  },
  "metadata": {
    "created_at": "2026-05-13T10:00:00",
    "updated_at": "2026-05-13T10:00:00",
    "created_by": "codex_cleaner",
    "updated_by": "codex_cleaner"
  }
}
```

硬约束：

1. `category_id` 必须为 `chats`
2. `data.service_reply` 必填
3. `id` 全局唯一
4. 禁止出现手机号与实名泄漏

---

## 5. Template Import Job

字段：

1. `job_id` string
2. `tenant_id` string
3. `input_file` string
4. `mode` enum(`dry_run`,`apply`)
5. `version` string
6. `summary` object
7. `conflicts` array
8. `created_at` string

`summary` 建议字段：

1. `total`
2. `new_items`
3. `updated_items`
4. `skipped_items`
5. `blocked_items`

---

## 6. Release Manifest

字段：

1. `release_version` string
2. `tenant_id` string
3. `industry_id` string
4. `batch_ids` string[]
5. `import_job_ids` string[]
6. `feature_flags` object
7. `metrics_gate` object
8. `rollback_to` string
9. `approved_by` string
10. `approved_at` string

---

## 7. Replay Eval Case

字段：

1. `case_id` string
2. `tenant_id` string
3. `industry_id` string
4. `input_messages` array
5. `expected_constraints` object
6. `risk_level` enum(`normal`,`warning`,`high`)
7. `tags` string[]

---

## 8. Replay Eval Report

字段：

1. `report_id` string
2. `release_version` string
3. `tenant_id` string
4. `summary` object
5. `metrics` object
6. `failed_cases` array
7. `generated_at` string

`metrics` 至少包含：

1. `factual_consistency`
2. `violation_rate`
3. `handoff_precision`
4. `continue_chat_rate`

---

## 9. 版本策略

1. 契约变更必须提升 `schema_version`。
2. 非破坏性字段新增允许向后兼容。
3. 破坏性字段变更必须提供迁移脚本与回滚说明。
