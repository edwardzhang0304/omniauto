# WeChat AI 客服标准工作流接口规格（预实现）

## 1. 目的

在编码前先冻结接口边界，避免并行开发时出现协议漂移。

本文件描述建议接口，不代表当前全部已实现。

---

## 2. 接口分组

1. 数据治理接口
2. 模板导入接口
3. 版本发布接口
4. 回放评估接口
5. 回滚接口

---

## 3. 数据治理接口

## 3.1 创建清洗任务

`POST /api/workflow/curation/jobs`

请求：

```json
{
  "tenant_id": "default",
  "industry_id": "used_car",
  "batch_id": "batch_20260513_01",
  "source_files": [
    "D:/AI/实盘数据/二手车/rag_chunks.jsonl"
  ],
  "strict_mode": true
}
```

响应：

```json
{
  "ok": true,
  "job_id": "curate_job_xxx",
  "status": "queued"
}
```

## 3.2 查询清洗任务

`GET /api/workflow/curation/jobs/{job_id}`

返回：

1. 状态
2. 产物文件路径
3. 清洗报告摘要

---

## 4. 模板导入接口

## 4.1 Dry-run 导入

`POST /api/workflow/template-import/dry-run`

请求：

```json
{
  "tenant_id": "default",
  "industry_id": "used_car",
  "input_file": "D:/.../wechat_usedcar_knowledge_chats_items_strict.jsonl"
}
```

响应：

1. 冲突数
2. 重复数
3. 可导入数
4. 阻断原因列表

## 4.2 应用导入

`POST /api/workflow/template-import/apply`

请求：

```json
{
  "tenant_id": "default",
  "industry_id": "used_car",
  "dry_run_job_id": "import_dry_xxx",
  "release_version": "wf_20260513_v1"
}
```

响应：

1. 导入作业号
2. 版本号
3. 变更摘要

---

## 5. 版本发布接口

## 5.1 创建发布候选

`POST /api/workflow/releases`

请求：

1. `tenant_id`
2. `release_version`
3. `import_job_ids`
4. `feature_flags`

响应：

1. `release_id`
2. `status=created`

## 5.2 审批发布

`POST /api/workflow/releases/{release_id}/approve`

请求：

1. `approved_by`
2. `approval_note`

响应：

1. `status=approved`

---

## 6. 回放评估接口

## 6.1 触发评估

`POST /api/workflow/replay-eval/run`

请求：

```json
{
  "tenant_id": "default",
  "release_version": "wf_20260513_v1",
  "suite_id": "default_usedcar_suite"
}
```

响应：

1. `eval_job_id`
2. `status=running`

## 6.2 获取评估报告

`GET /api/workflow/replay-eval/jobs/{eval_job_id}`

返回：

1. 指标摘要
2. 失败 case 列表
3. 是否通过门禁

---

## 7. 回滚接口

## 7.1 执行回滚

`POST /api/workflow/releases/{release_id}/rollback`

请求：

```json
{
  "rollback_to_version": "wf_20260501_v3",
  "reason": "violation_rate_increase"
}
```

响应：

1. `ok`
2. `rolled_back_to`
3. `changed_targets`

---

## 8. CLI 对应建议

1. `python workflows/workflow_ops.py curation --batch ...`
2. `python workflows/workflow_ops.py import --dry-run ...`
3. `python workflows/workflow_ops.py import --apply ...`
4. `python workflows/workflow_ops.py eval --release ...`
5. `python workflows/workflow_ops.py release --approve ...`
6. `python workflows/workflow_ops.py release --rollback ...`

---

## 9. 鉴权与审计要求

1. 所有 `apply/approve/rollback` 操作必须要求管理员权限。
2. 所有接口记录 `tenant_id`、操作者、时间、版本、diff 摘要。
3. 评估结果与发布行为必须可追溯到同一 `release_version`。
