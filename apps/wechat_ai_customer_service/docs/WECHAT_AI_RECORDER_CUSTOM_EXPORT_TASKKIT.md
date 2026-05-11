# 微信AI智能记录员定制导出任务包（可执行版）

> 更新说明（2026-05-09）：本任务包是阶段计划文档；当前可执行的落地流程、页面操作和验收命令见  
> `WECHAT_AI_RECORDER_ONE_SHOT_DELIVERY_RUNBOOK_20260509.md`。

## 1. 使用方式

本任务包用于直接分发给研发、测试、运维角色执行。  
执行顺序必须按阶段推进，不建议跳步并行跨阶段改核心契约。

---

## 2. 阶段任务清单

## 2.1 Phase A：通用底座补完

### A-1 记录员运行态管理

任务目标：

1. 实现 `/api/recorder/runtime/status`。
2. 实现 `/api/recorder/runtime/start`。
3. 实现 `/api/recorder/runtime/stop`。

交付物：

1. Runtime service 代码。
2. PID 文件、状态文件、日志落盘机制。
3. API 文档与回归测试。

验收标准：

1. 启动后 `running=true`。
2. 停止后 `running=false`。
3. 异常退出可被状态检测到。

### A-2 原始消息查询增强

任务目标：

1. 扩展 `/api/raw-messages/messages` 过滤参数。
2. 支持 `start_time/end_time/sender/content_type/conversation_type/keywords`。
3. 支持分页 `offset/limit`。

交付物：

1. API 参数处理。
2. 存储层查询适配（file + PostgreSQL）。
3. 查询性能基线测试。

验收标准：

1. 同时使用 3 个以上过滤条件仍返回正确结果。
2. 分页结果稳定，重复请求一致。

### A-3 导出任务化框架

任务目标：

1. 新增导出 run 持久化。
2. 新增 run 创建/查询/下载 API。
3. 接入 work queue + background worker。

交付物：

1. run 数据结构。
2. worker handler。
3. 前端任务列表基础视图。

验收标准：

1. 前端发起导出后立即返回 run_id。
2. 后台异步完成并可下载。
3. 失败任务可见错误信息。

---

## 2.2 Phase B：模块化能力

### B-1 模块注册表

任务目标：

1. 新增模块注册 API。
2. 支持模块状态 `active|paused|deprecated`。
3. 支持模块版本管理字段。

交付物：

1. `module_registry` 持久化结构。
2. API 与基本管理页。

验收标准：

1. 可创建模块。
2. 可停用模块。
3. 模块可按 key 查询。

### B-2 账号/租户绑定

任务目标：

1. 新增绑定 API。
2. 支持 `scope_type=user|tenant|global`。
3. 实现优先级解析链路。

交付物：

1. `module_bindings` 持久化结构。
2. 解析器 `resolve_module_for_user(tenant_id, user_id)`。

验收标准：

1. 账号绑定覆盖租户默认。
2. 租户默认覆盖全局默认。
3. 无可用模块时返回可理解错误。

---

## 2.3 Phase C：定制模块 `order_sheet_lab_v1`

### C-1 抽取引擎

任务目标：

1. 实现规则召回与规则抽取。
2. 实现 LLM 补全与冲突处理。
3. 输出标准中间模型 `NormalizedOrderRow`。

交付物：

1. 模块类：`OrderSheetLabV1Extractor`。
2. 规则配置与关键样本测试。
3. LLM Prompt 与 JSON 输出校验器。

验收标准：

1. 样本数据可稳定产出记录行。
2. 冲突字段按“规则优先”。
3. 低置信记录带 `needs_review=true`。

### C-2 模板导出器

任务目标：

1. 将中间模型映射到订货表列。
2. 生成 xlsx 文件。
3. 生成抽取报告 sheet。

交付物：

1. 导出器：`OrderSheetLabV1Exporter`。
2. Excel 样式与列顺序固化。
3. 报告字段统计。

验收标准：

1. 列顺序与目标表一致。
2. `进价（单价）` 与 `总进价` 可留空。
3. 同输入重复导出结果稳定。

---

## 2.4 Phase D：管理页面与验收闭环

### D-1 AI记录员页改造

任务目标：

1. “一键导出记录”改为任务化提交流程。
2. 展示当前生效模块与版本。
3. 展示导出任务列表与下载入口。

验收标准：

1. 用户可看到任务状态变化。
2. 可下载导出文件与报告。

### D-2 Admin模块配置页

任务目标：

1. 新增模块管理区。
2. 新增账号绑定区。
3. 新增租户默认模块配置。

验收标准：

1. admin 可完成模块分配并生效。
2. 审计日志可记录配置变更。

---

## 3. 接口模板（建议稿）

## 3.1 新建导出任务

```http
POST /api/recorder/exports/runs
Content-Type: application/json
```

```json
{
  "module_key": "",
  "time_range": {
    "start": "2025-03-01T00:00:00",
    "end": "2025-03-31T23:59:59"
  },
  "conversation_ids": [],
  "target_names": ["企点售后群"],
  "sender_filter": [],
  "keyword_filter": [],
  "include_content_types": ["text"],
  "export_format": "xlsx"
}
```

```json
{
  "ok": true,
  "item": {
    "run_id": "run_xxx",
    "status": "queued"
  }
}
```

## 3.2 查询导出任务

```http
GET /api/recorder/exports/runs?status=all&limit=50
```

## 3.3 下载导出文件

```http
GET /api/recorder/exports/runs/{run_id}/download
```

---

## 4. 模块配置模板（建议稿）

```json
{
  "module_key": "order_sheet_lab_v1",
  "module_name": "实验仪器订货表V1",
  "module_type": "chat_extract_export",
  "status": "active",
  "version": "1.0.0",
  "config": {
    "target_excel_template": "order_sheet_like",
    "date_output_mode": "MMDD_text",
    "allow_empty_cost_fields": true,
    "rule_first": true,
    "llm_enabled": true,
    "llm_fill_only_missing_fields": true,
    "max_rows_per_run": 5000,
    "supported_content_types": ["text", "quote"]
  }
}
```

---

## 5. 规则模板（建议稿）

## 5.1 候选召回规则

```json
{
  "must_any_keywords": ["订", "代付", "元", "老师"],
  "exclude_any_keywords": ["撤回了一条消息"],
  "allowed_senders": [],
  "allowed_content_types": ["text", "quote"]
}
```

## 5.2 字段抽取正则示例

```text
姓名责任人模式：(?P<customer>[\u4e00-\u9fa5A-Za-z0-9]+)[-—](?P<owner>[\u4e00-\u9fa5A-Za-z0-9]+)老师
数量单位模式：(?P<qty>\d+(\.\d+)?)\s*(?P<unit>盒|箱|袋|瓶|套|个|包|桶|台)
金额模式：(?P<price>\d+(\.\d+)?)\s*元
```

---

## 6. LLM 协议模板（建议稿）

## 6.1 输入契约

1. 仅输入候选消息片段。
2. 每条消息带唯一 `raw_message_id`。
3. 提供规则已抽取字段，要求 LLM 只补缺。

## 6.2 输出契约

```json
{
  "rows": [
    {
      "date_code": "0303",
      "customer_name": "张三",
      "owner_name": "李四",
      "receiver_name": null,
      "campus": null,
      "order_unit": "盒",
      "product_name": "XX试剂",
      "quantity": 2,
      "quantity_unit": "盒",
      "spec": null,
      "brand": null,
      "cost_price": null,
      "sale_price": 98,
      "total_cost": null,
      "total_sale": 196,
      "remark": "",
      "confidence": 0.82,
      "evidence_message_ids": ["raw_msg_xxx"],
      "needs_review": false,
      "review_reason": ""
    }
  ]
}
```

---

## 7. 测试数据准备清单

1. 正常订单文本样本不少于 100 条。
2. 非订单聊天噪声样本不少于 100 条。
3. 同一消息多商品场景样本不少于 20 条。
4. 歧义与缺失字段样本不少于 30 条。
5. 边界样本：撤回、表情、引用、空文本。

---

## 8. 测试用例矩阵（最小集）

1. `TC-A01`：记录员 runtime 启停状态。
2. `TC-A02`：原始消息多条件筛选。
3. `TC-A03`：导出任务提交与状态流转。
4. `TC-B01`：账号模块绑定覆盖租户默认。
5. `TC-B02`：租户默认覆盖全局默认。
6. `TC-C01`：规则抽取基础字段正确性。
7. `TC-C02`：LLM 仅补缺不覆盖规则字段。
8. `TC-C03`：低置信度记录正确标记。
9. `TC-C04`：Excel 列顺序与字段映射正确。
10. `TC-D01`：跨租户访问拦截。

---

## 9. 发布检查单

1. 模块 `order_sheet_lab_v1` 状态为 `active`。
2. 至少 1 个测试账号已绑定并验收通过。
3. worker 运行正常，队列无堆积。
4. 导出目录可写，下载可用。
5. 审计日志可记录模块变更与导出任务。

---

## 10. 回滚检查单

1. 将目标账号绑定切回上一稳定模块。
2. 新模块改为 `paused`。
3. 保留所有历史 run 与报告，禁止清理。
4. 验证基础采集链路不受影响。

---

## 11. 建议提交拆分（便于代码评审）

1. PR-1：recorde runtime + raw query 增强。
2. PR-2：module registry + module bindings + 权限。
3. PR-3：export runs + worker handler。
4. PR-4：order_sheet_lab_v1 抽取与导出实现。
5. PR-5：前端页面与 admin 分配页面。
6. PR-6：测试与文档补齐。
