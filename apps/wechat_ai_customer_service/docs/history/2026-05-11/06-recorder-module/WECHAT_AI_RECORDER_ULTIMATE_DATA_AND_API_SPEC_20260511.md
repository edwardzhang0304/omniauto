# 微信AI智能记录员终极数据与API规范（2026-05-11）

## 1. 目标
定义结构化导出升级所需的数据模型与接口契约，确保前后端、模块层、任务层在同一协议下协作。

## 2. 数据模型
## 2.1 原始消息（已有，补充约束）
字段建议：
1. `message_id`：唯一ID。
2. `tenant_id`：租户ID。
3. `conversation_id`：会话ID（群/个人）。
4. `conversation_name`：会话名。
5. `sender_name`：发送人。
6. `sent_at`：原始时间戳。
7. `content_text`：文本内容。
8. `dedupe_key`：去重键。
9. `ingested_at`：入库时间。

约束：
1. `dedupe_key` 全局去重。
2. `sent_at` 与 `ingested_at` 分离，避免导出日期误判。

## 2.2 模块注册（module_registry）
字段建议：
1. `module_id`（PK）。
2. `module_name`。
3. `module_version`。
4. `module_type`（`structured_export`）。
5. `status`（`active`/`inactive`）。
6. `profiles_json`（schema/extraction/post_process/export）。
7. `created_at`、`updated_at`。

## 2.3 账号模块绑定（account_module_binding）
字段建议：
1. `tenant_id`。
2. `account_id`。
3. `module_id`。
4. `is_default_fallback`。
5. `effective_from`、`effective_to`。
6. `updated_by`、`updated_at`。

约束：
1. 同一账号同一时刻最多一个有效主模块。
2. 支持设置租户默认模块作为兜底。

## 2.4 导出任务（structured_export_runs）
字段建议：
1. `run_id`（PK）。
2. `tenant_id`、`account_id`。
3. `module_id`、`module_version_snapshot`。
4. `filters_json`（日期、会话、消息数上限等）。
5. `status`。
6. `progress_json`（阶段、已处理条数、耗时）。
7. `metrics_json`（命中率、低置信度数、失败数）。
8. `result_excel_path`、`result_json_path`。
9. `error_code`、`error_message`。
10. `created_at`、`started_at`、`finished_at`。

## 2.5 结构化行（normalized_order_rows，可选中间表）
字段建议：
1. `row_id`。
2. `run_id`。
3. `order_date`（标准 `YYYY-MM-DD`）。
4. `customer_name`。
5. `product_name`。
6. `quantity`。
7. `unit`。
8. `unit_price`（可空）。
9. `total_price`（可空）。
10. `remark`。
11. `confidence`。
12. `needs_review`。
13. `evidence_text`。
14. `source_message_ids_json`。

## 3. API 规范
## 3.1 创建结构化导出任务
`POST /api/admin/recorder/structured-export/runs`

请求示例：
```json
{
  "account_id": "test2",
  "module_id": "order_sheet_lab_v1",
  "filters": {
    "conversation_names": ["群聊_企点售后群 - 喂数据"],
    "date_from": "2026-03-01",
    "date_to": "2026-03-31",
    "quick_range": "month",
    "max_messages": 10000
  }
}
```

响应示例：
```json
{
  "ok": true,
  "run_id": "run_xxx",
  "status": "queued"
}
```

## 3.2 查询任务列表
`GET /api/admin/recorder/structured-export/runs?account_id=test2&limit=20`

返回字段：
1. `run_id`。
2. `status`。
3. `stage`。
4. `progress`。
5. `created_at`。
6. `module_id`。
7. `download_ready`。

## 3.3 查询任务详情
`GET /api/admin/recorder/structured-export/runs/{run_id}`

返回重点：
1. `progress_json`。
2. `metrics_json`。
3. `error_*`。
4. `result_excel_url`、`result_json_url`。
5. `review_summary`（低置信度统计）。

## 3.4 下载结果
`GET /api/admin/recorder/structured-export/runs/{run_id}/download?format=xlsx|json`

## 3.5 模块列表
`GET /api/vps-admin/recorder/modules?type=structured_export`

## 3.6 账号绑定模块
`POST /api/vps-admin/recorder/module-bindings`

请求示例：
```json
{
  "tenant_id": "test02",
  "account_id": "test2",
  "module_id": "order_sheet_lab_v1"
}
```

## 4. 错误码规范
1. `invalid_filters`：日期或筛选参数非法。
2. `module_not_found`：模块不存在。
3. `module_inactive`：模块未启用。
4. `queue_busy`：队列繁忙。
5. `llm_upstream_error`：模型服务失败。
6. `export_generation_failed`：导出文件生成失败。
7. `run_not_found`：任务不存在。

## 5. 兼容性策略
1. 旧入口“创建结构化导出任务（原一键导出记录）”映射为“导出所有记录（结构化）”。
2. 删除“刷新状态”按钮后，前端必须自动轮询并支持断网重连恢复。
3. 未传 `module_id` 时使用账号绑定模块；无绑定则租户默认模块。

## 6. 日期筛选通用实现
1. 所有模块共享同一日期过滤器，先过滤后抽取。
2. 模块层只负责格式化展示和语义补全，不重写过滤语义。
3. 快捷导出参数：
- `quick_range=day`：当天自然日。
- `quick_range=week`：本周（周一到周日）。
- `quick_range=month`：当月自然月。

## 7. 审计与可观测性
1. 记录任务参数快照。
2. 记录模块版本快照。
3. 记录模型调用统计（次数、耗时、token）。
4. 记录失败批次和重试结果。
