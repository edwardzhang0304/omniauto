# 微信AI智能记录员「可切换定制导出模块」实施包

> 更新说明（2026-05-09）：若需要查看“已实现功能 + 实操步骤 + 验收与回滚”的落地版文档，请同步阅读  
> `WECHAT_AI_RECORDER_ONE_SHOT_DELIVERY_RUNBOOK_20260509.md`。

## 1. 文档目标

本实施包用于指导 OmniAuto 在现有能力上完成两类建设：

1. 通用能力补完：把“微信AI智能记录员”从手动采集型能力补到可稳定运行的实时采集与任务化导出底座。
2. 定制能力建设：实现“规则 + LLM 混合抽取”，并输出客户指定格式 Excel（当前客户为“订货表”格式）。

本包默认目标是“先可用、再增强”：

1. V1 先完成可稳定抽取并导出，进价相关字段允许为空。
2. V2 再接产品库做进价/总进价回填。
3. V3 再做跨客户模板快速切换与运营化管理增强。

---

## 2. 当前基线能力盘点（已具备）

### 2.1 记录员与原始消息

1. 记录员 API：`/api/recorder/*` 已具备会话发现、会话选择、手动采集、设置管理。
2. 原始消息 API：`/api/raw-messages/*` 已具备会话/消息/批次管理与学习触发。
3. 原始消息存储：支持文件与 PostgreSQL 双后端、去重键、批次机制。

### 2.2 后台页面与通用导出

1. 管理后台存在“AI智能记录员”页面入口。
2. 已有“按类型导出 Excel / 按时间导出 Excel”，但目标是知识导出，不是订单模板导出。

### 2.3 租户与账号体系

1. VPS Admin 已支持 tenant、user 管理。
2. user 数据含 `tenant_ids` 与 `resource_scopes`。
3. tenant 数据含 `metadata`，可承载模块配置。

### 2.4 队列与后台任务

1. `WorkQueueService` 与后台 worker 已可用。
2. 已有任务 claim/complete/fail 机制，适合挂接抽取与导出任务。

---

## 3. 目标架构（通用底座 + 可切换模块）

### 3.1 架构原则

1. 采集、入库、权限、租户隔离为通用底座，不随客户变化。
2. 抽取逻辑、字段映射、Excel 模板是可插拔模块，按账号可切换。
3. 模块切换只影响“整理/导出链路”，不影响“监听/入库链路”。
4. 所有导出任务必须可追溯：谁导出、导出范围、使用模块、模块版本、结果文件。

### 3.2 逻辑分层

1. Layer A（基础采集层）：WeChat Connector -> RawMessageStore。
2. Layer B（筛选层）：按会话/时间/发送者/关键词筛选原始记录。
3. Layer C（抽取层）：规则引擎优先抽取，LLM 补全与纠错。
4. Layer D（结构化层）：标准中间模型（NormalizedOrderRow）。
5. Layer E（导出层）：按模块模板映射到目标 Excel。
6. Layer F（运营层）：任务管理、审计日志、下载、失败复跑。

---

## 4. 新增能力范围

### 4.1 通用补完能力（必须）

1. 记录员运行态管理：支持 start/stop/status。
2. 原始消息高级查询：支持时间区间、发送者、消息类型、关键词组合过滤。
3. 抽取导出任务化：进入 work queue，后台 worker 执行。
4. 结果资产化：导出文件、任务报告、异常行报告可下载。
5. 审计增强：记录模块与版本、触发账号、时间范围、行数统计。

### 4.2 定制能力（当前客户）

1. 新增模块 `order_sheet_lab_v1`。
2. 支持“规则 + LLM 混合抽取”。
3. 输出目标 Excel 列结构对齐“订货表”。
4. `进价（单价）` 与 `总进价` 暂留空。

### 4.3 可切换能力（跨客户）

1. 管理端支持维护模块注册表。
2. 管理端支持账号级模块绑定。
3. 绑定优先级：账号 > 租户默认 > 系统默认。
4. 支持同账号切换模块后立即应用于新导出任务。

---

## 5. 数据模型设计

### 5.1 模块注册表（module_registry）

建议保存于 VPS Admin state（后续可迁移 PostgreSQL）。

字段定义：

1. `module_key`: string，唯一，例如 `order_sheet_lab_v1`。
2. `module_name`: string，展示名。
3. `module_type`: string，固定 `chat_extract_export`。
4. `status`: string，`active|paused|deprecated`。
5. `version`: string，语义化版本，如 `1.0.0`。
6. `config`: object，模块配置。
7. `created_at`: datetime。
8. `updated_at`: datetime。

### 5.2 绑定关系（module_bindings）

字段定义：

1. `binding_id`: string。
2. `scope_type`: string，`user|tenant|global`。
3. `scope_id`: string，user_id 或 tenant_id，global 时固定 `*`。
4. `module_key`: string。
5. `enabled`: bool。
6. `priority`: int，保留字段。
7. `created_at`: datetime。
8. `updated_at`: datetime。

### 5.3 导出任务（extract_export_runs）

字段定义：

1. `run_id`: string。
2. `tenant_id`: string。
3. `requested_by_user_id`: string。
4. `module_key`: string。
5. `module_version`: string。
6. `filters`: object，时间范围/会话/关键词/发送者。
7. `status`: string，`queued|running|succeeded|failed|cancelled`。
8. `stats`: object，命中消息数、抽取行数、低置信度行数、丢弃行数。
9. `artifacts`: object，xlsx 路径、json 报告路径、error 报告路径。
10. `error`: string。
11. `created_at`: datetime。
12. `updated_at`: datetime。
13. `finished_at`: datetime。

### 5.4 标准中间行模型（NormalizedOrderRow）

字段定义：

1. `date_code`: string，如 `0303`。
2. `customer_name`: string，对应“姓名”。
3. `owner_name`: string，对应“责任人（老板）”。
4. `receiver_name`: string，对应“收货人”。
5. `campus`: string，对应“校区”。
6. `order_unit`: string，对应“订货单位”。
7. `product_name`: string，对应“货品名称”。
8. `quantity`: number|string。
9. `quantity_unit`: string。
10. `spec`: string。
11. `brand`: string。
12. `cost_price`: number|string|null，V1 可空。
13. `sale_price`: number|string|null。
14. `total_cost`: number|string|null，V1 可空。
15. `total_sale`: number|string|null。
16. `remark`: string。
17. `confidence`: number，0-1。
18. `evidence_message_ids`: string[]。
19. `needs_review`: bool。
20. `review_reason`: string。

---

## 6. API 合同设计

### 6.1 记录员运行态（通用补完）

1. `GET /api/recorder/runtime/status`
2. `POST /api/recorder/runtime/start`
3. `POST /api/recorder/runtime/stop`

响应标准字段：

1. `ok`
2. `running`
3. `pid`
4. `last_capture_at`
5. `queue_summary`
6. `message`

### 6.2 原始消息增强查询

`GET /api/raw-messages/messages`

新增 query 参数：

1. `start_time`
2. `end_time`
3. `sender`
4. `content_type`
5. `conversation_type`
6. `keywords`
7. `offset`
8. `limit`

### 6.3 模块管理 API（VPS Admin）

1. `GET /v1/admin/modules`
2. `POST /v1/admin/modules`
3. `PATCH /v1/admin/modules/{module_key}`
4. `GET /v1/admin/module-bindings`
5. `POST /v1/admin/module-bindings`
6. `PATCH /v1/admin/module-bindings/{binding_id}`
7. `DELETE /v1/admin/module-bindings/{binding_id}`

### 6.4 导出任务 API（管理后台）

1. `POST /api/recorder/exports/runs`
2. `GET /api/recorder/exports/runs`
3. `GET /api/recorder/exports/runs/{run_id}`
4. `GET /api/recorder/exports/runs/{run_id}/download`
5. `GET /api/recorder/exports/runs/{run_id}/report`

`POST /api/recorder/exports/runs` 请求体建议：

1. `module_key`: string，可选；为空时按绑定规则解析。
2. `time_range`: object，`start` 与 `end`。
3. `conversation_ids`: string[]。
4. `target_names`: string[]。
5. `sender_filter`: string[]。
6. `keyword_filter`: string[]。
7. `include_content_types`: string[]。
8. `export_format`: string，默认 `xlsx`。

---

## 7. 模块切换机制设计

### 7.1 解析顺序

1. 若请求显式传 `module_key`，先校验权限后直接使用。
2. 否则读取账号绑定 `scope_type=user`。
3. 若无账号绑定，读取租户默认 `scope_type=tenant`。
4. 若仍无，则读取 `scope_type=global` 默认模块。
5. 若均无，返回明确错误并提示 admin 配置模块。

### 7.2 生效规则

1. 模块变更只影响“新建 run”。
2. 已运行中的 run 固定使用创建时的 `module_key + module_version`。
3. 导出任务详情页显示模块版本，保证历史可追溯。

### 7.3 权限规则

1. 仅 admin 可维护模块注册表与绑定关系。
2. customer 仅可发起导出与查看本租户导出结果。
3. guest 默认只读，不允许发起导出任务。

---

## 8. 规则 + LLM 混合抽取设计（order_sheet_lab_v1）

### 8.1 处理流程

1. 数据准备：按条件查询原始消息。
2. 规则召回：筛出疑似订单消息。
3. 规则抽取：正则/模板解析字段。
4. LLM 补全：仅补齐规则未提取字段，或解决歧义。
5. 校验归一：数量、价格、总价、日期、重复单处理。
6. 生成中间行：NormalizedOrderRow。
7. 映射导出：按模板输出“订货表”。

### 8.2 规则优先策略

1. 强规则命中时，不让 LLM 覆盖已有高置信字段。
2. LLM 只能填空或给出“建议值 + 置信度”。
3. 冲突时按策略：规则 > LLM；若规则低置信则标记 `needs_review=true`。

### 8.3 订单消息候选规则建议

候选命中关键词建议：

1. `订`
2. `代付`
3. `元`
4. `老师`
5. `=` 或 `：`
6. 常见数量单位：`盒|箱|袋|瓶|套|个|包|桶|台`

### 8.4 抽取字段优先级

1. 日期：先用消息时间，再尝试正文内日期片段。
2. 姓名/责任人：优先解析 `姓名-责任人老师` 模式。
3. 货品名称：优先解析等号/冒号右侧主商品短语。
4. 数量单位：先取“数字+单位”组合。
5. 售价与总售价：优先正文显式金额，其次由数量*单价推导。
6. 备注：保留未结构化但关键片段。

### 8.5 LLM 输出协议（强约束 JSON）

1. 输出必须是 JSON，不允许自然语言段落。
2. 每条记录包含：字段值、置信度、证据原句索引。
3. 若无法确定，字段返回 `null` 并写 `reason`。
4. 输出总记录数不得超过输入候选消息可解释上限，防止幻觉扩写。

---

## 9. Excel 输出规范（订货表）

### 9.1 固定列顺序

1. 空首列
2. 日期
3. 姓名
4. 责任人（老板）
5. 收货人
6. 校区
7. 订货单位
8. 货品名称
9. 数量
10. 单位
11. 规格
12. 品牌
13. 进价（单价）
14. 售价（单价）
15. 总进价
16. 总售价
17. 备注

### 9.2 V1 字段策略

1. `进价（单价）` 留空。
2. `总进价` 留空。
3. `校区` 无法识别则留空。
4. 日期按文本写入，例如 `0303`。

### 9.3 附加质量信息

建议增加附加 sheet `抽取报告`：

1. run_id
2. 模块与版本
3. 输入消息量
4. 导出行数
5. 低置信度行数
6. 人工复核建议数
7. 失败原因统计

---

## 10. 前后端改造点清单

### 10.1 后端改造点

1. 新增记录员 runtime service 与 API。
2. 扩展 raw messages 查询参数与存储查询支持。
3. 新增模块注册/绑定 service（建议先放 vps_admin）。
4. 新增导出 run service。
5. 新增 `order_sheet_lab_v1` 抽取器与导出器。
6. 新增导出任务 worker handler。

### 10.2 前端改造点

1. AI智能记录员页面增加“一键导出记录”入口改造为任务化流程。
2. 增加模块展示区：当前生效模块、模块版本。
3. 增加导出任务列表：状态、行数、下载、错误查看。
4. 管理端增加“账号能力模块分配”页面。

### 10.3 配置改造点

1. tenant metadata 增加默认模块字段。
2. user 数据增加可选模块偏好字段，或通过 binding 独立表维护。
3. 系统级默认模块写入 global binding。

---

## 11. 任务分解与里程碑

### 11.1 M1（P0，先可用）

1. 完成 recorder runtime start/stop/status。
2. 完成 raw message 高级查询。
3. 完成 module_registry 与 module_bindings 的 API 与持久化。
4. 完成导出 run 任务化框架。
5. 完成 `order_sheet_lab_v1` 抽取 + 导出。
6. 完成前端“一键导出记录”任务化。
7. 完成核心回归测试。

### 11.2 M2（增强）

1. 商品库匹配进价与总进价。
2. 字段字典增强（品牌、校区、规格归一）。
3. 低置信度复核台。

### 11.3 M3（运营化）

1. 模块版本灰度发布。
2. 模块切换审计可视化。
3. 导出质量趋势报表。

---

## 12. 验收标准（DoD）

### 12.1 功能验收

1. 可实时持续采集指定会话消息并入库。
2. 可按时间范围一键发起导出任务并下载 Excel。
3. 导出列结构与目标订货表一致。
4. admin 可按账号切换模块，切换后新任务生效。

### 12.2 数据质量验收

1. 订单类消息召回率达到可用阈值（项目内定义）。
2. 高置信字段错误率可控。
3. 低置信记录必须可见，不允许静默丢弃。

### 12.3 稳定性验收

1. 导出任务失败可复跑。
2. worker 崩溃后可恢复。
3. 任务状态可追踪且审计完整。

---

## 13. 测试方案

### 13.1 单元测试

1. 规则抽取器：每类模板消息至少 5 个样本。
2. 字段映射器：空值、异常值、冲突值。
3. 模块解析器：账号/租户/全局优先级。

### 13.2 集成测试

1. 从 raw_messages 到导出 run 全链路。
2. 队列任务提交、执行、失败重试。
3. 模块切换后导出结果变化验证。

### 13.3 回归测试

1. 不影响原有知识导出功能。
2. 不影响客服监听与回复链路。
3. 不影响多租户权限边界。

---

## 14. 运维与上线策略

### 14.1 上线前检查

1. 模块注册表已存在默认模块。
2. 至少一个测试账号完成模块绑定验证。
3. worker 进程与日志路径可用。
4. 导出目录权限正确。

### 14.2 灰度发布

1. 先绑定 1 个内部测试账号。
2. 再绑定当前目标客户账号。
3. 稳定后逐步放开其他客户。

### 14.3 回滚策略

1. 将账号绑定切回旧模块。
2. 暂停新模块状态为 `paused`。
3. 保留历史 run 与导出文件，不做删除。

---

## 15. 风险清单与对策

1. 风险：消息格式变化导致规则失效。对策：保留 LLM 补全和低置信复核。
2. 风险：LLM 幻觉字段。对策：强 JSON 协议 + 字段校验 + 证据引用。
3. 风险：账号误绑定模块。对策：绑定审计 + 生效前确认弹窗。
4. 风险：大批量导出超时。对策：任务化异步执行 + 分页抓取。
5. 风险：跨租户数据泄漏。对策：tenant 强过滤 + 鉴权 + 审计。

---

## 16. 当前客户 V1 交付边界（明确）

1. 输出“订货表”格式主表可用。
2. 不做图片 OCR，不做语音内容抽取。
3. `进价（单价）`、`总进价` 留空。
4. `校区`、`品牌` 无法识别时留空。
5. 所有不确定行进入 `needs_review` 标记。

---

## 17. 与现有代码对接的关键文件参考

1. 记录员 API：[recorder.py](/D:/AI/omniauto/apps/wechat_ai_customer_service/admin_backend/api/recorder.py)
2. 原始消息 API：[raw_messages.py](/D:/AI/omniauto/apps/wechat_ai_customer_service/admin_backend/api/raw_messages.py)
3. 记录员服务：[recorder_service.py](/D:/AI/omniauto/apps/wechat_ai_customer_service/admin_backend/services/recorder_service.py)
4. 原始消息存储：[raw_message_store.py](/D:/AI/omniauto/apps/wechat_ai_customer_service/admin_backend/services/raw_message_store.py)
5. 导出 API：[exports.py](/D:/AI/omniauto/apps/wechat_ai_customer_service/admin_backend/api/exports.py)
6. 通用导出服务：[knowledge_export_service.py](/D:/AI/omniauto/apps/wechat_ai_customer_service/admin_backend/services/knowledge_export_service.py)
7. 队列 API：[jobs.py](/D:/AI/omniauto/apps/wechat_ai_customer_service/admin_backend/api/jobs.py)
8. 队列服务：[work_queue.py](/D:/AI/omniauto/apps/wechat_ai_customer_service/admin_backend/services/work_queue.py)
9. 后台 worker：[background_worker.py](/D:/AI/omniauto/apps/wechat_ai_customer_service/scripts/background_worker.py)
10. VPS Admin 服务：[app.py](/D:/AI/omniauto/apps/wechat_ai_customer_service/vps_admin/app.py)
11. VPS Admin 领域服务：[services.py](/D:/AI/omniauto/apps/wechat_ai_customer_service/vps_admin/services.py)

---

## 18. 立即开工建议

1. 先按本包执行 M1，交付最小可用“可切换模块 + 订货表导出 V1”。
2. M1 完成后再接进价映射，避免阻塞主链路上线。
3. 上线前用真实聊天样本做一次“导出对账复核”，再扩大账号范围。
