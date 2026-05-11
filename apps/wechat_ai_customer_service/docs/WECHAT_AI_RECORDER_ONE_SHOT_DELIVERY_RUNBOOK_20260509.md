# 微信AI智能记录员 一步到位交付Runbook（2026-05-09）

## 1. 文档目的

本Runbook用于把“微信AI智能记录员”项目从方案阶段推进到可交付阶段，覆盖：

1. 通用底座能力补完（采集、入库、任务化导出、租户隔离、运行态）。
2. 定制模块能力（`order_sheet_lab_v1`，规则+LLM混合抽取）。
3. 按账号切换模块能力（admin服务端配置，客户端按账号执行）。
4. 双功能独立开关能力（微信智能客服 vs AI智能记录员）。

---

## 2. 完成度总览（As-Built）

## 2.1 通用底座

已完成：

1. 记录员运行态 API：`/api/recorder/runtime/status|start|stop`。
2. 原始消息高级查询：`/api/raw-messages/messages` 支持 `offset/start_time/end_time/sender/content_type/conversation_type/keywords`。
3. 任务化导出框架：`/api/recorder/exports/runs*` + queue worker `recorder_exports`。
4. 模块注册与绑定（本地）：`/api/recorder/modules`、`/api/recorder/module-bindings`。
5. 模块注册与绑定（VPS admin）：`/v1/admin/recorder-modules`、`/v1/admin/recorder-module-bindings`。

## 2.2 定制模块

已完成：

1. 内置模块 `order_sheet_lab_v1`。
2. 规则优先抽取 + LLM补缺。
3. 导出“订货表”列结构（Sheet1）。
4. V1 留空字段策略：`进价（单价）`、`总进价`。

## 2.3 前端交付

已完成：

1. `admin_backend` 记录员页面新增：
 - `记录员总开关`。
 - `一键导出记录`（异步任务）。
 - 导出任务列表（状态、统计、下载Excel、下载报告）。
 - 当前导出模块信息展示。
2. `vps_admin` 账户页面新增：
 - 记录员模块列表。
 - 账号绑定（user scope）。
 - 租户默认绑定（tenant scope）。
 - 全局默认绑定（global scope）。
 - 绑定关系列表与删除。

## 2.4 独立开关

已完成：

1. 微信智能客服总开关：已存在并可用。
2. 记录员总开关：已新增并全链路生效。
3. 独立性验证：可出现 `customer_enabled=false` 且 `recorder_enabled=true`。

---

## 3. 关键页面与接口清单

## 3.1 本地管理端（admin_backend）

页面：

1. `AI智能记录员` 面板：`/`（前端单页内导航）。

接口：

1. `GET /api/recorder/summary`
2. `PUT /api/recorder/settings`
3. `POST /api/recorder/discover`
4. `POST /api/recorder/capture`
5. `GET /api/recorder/modules`
6. `POST /api/recorder/exports/runs`
7. `GET /api/recorder/exports/runs`
8. `GET /api/recorder/exports/runs/{run_id}`
9. `GET /api/recorder/exports/runs/{run_id}/download`
10. `GET /api/recorder/exports/runs/{run_id}/report`

## 3.2 服务端管理端（vps_admin）

页面：

1. `客户与权限` 面板内新增 `AI智能记录员模块分配` 区块。

接口：

1. `GET /v1/admin/recorder-modules`
2. `POST /v1/admin/recorder-modules`
3. `GET /v1/admin/recorder-module-bindings`
4. `POST /v1/admin/recorder-module-bindings`
5. `DELETE /v1/admin/recorder-module-bindings/{binding_id}`

---

## 4. 模块解析优先级（运行时）

导出任务解析顺序：

1. 请求显式 `module_key`（若提供）。
2. 用户绑定（`scope_type=user`）。
3. 租户默认（`scope_type=tenant`）。
4. 全局默认（`scope_type=global`）。
5. 兜底到本地激活模块列表首个可用模块。

说明：

1. 模块变更仅影响新建导出任务。
2. 历史任务保留创建时 `module_key + module_version`。

---

## 5. 运营操作手册（Admin）

## 5.1 给某个客户账号切换到订货表模块

1. 登录 `vps_admin`。
2. 进入 `客户与权限`。
3. 在 `AI智能记录员模块分配` 区域：
 - `目标账号` 选择客户账号。
 - `模块` 选择 `实验仪器订货表V1`（`order_sheet_lab_v1`）。
 - 点击 `保存账号绑定`。

## 5.2 配租户默认模块

1. 同区域选择租户。
2. 选择模块并 `保存租户默认`。

## 5.3 配全局默认模块

1. 同区域选择 `全局默认模块`。
2. 点击 `保存全局默认`。

## 5.4 客户端导出

1. 客户登录本地管理端进入 `AI智能记录员`。
2. 先 `识别会话` 并勾选要记录的会话。
3. 点击 `一键导出记录`。
4. 在导出任务列表中查看状态，完成后下载 Excel/报告。

---

## 6. 验收脚本（建议顺序）

1. `node --check apps/wechat_ai_customer_service/admin_backend/static/app.js`
2. `node --check apps/wechat_ai_customer_service/vps_admin/static/app.js`
3. `uv run python apps/wechat_ai_customer_service/tests/run_recorder_phase_a_checks.py`
4. `uv run python apps/wechat_ai_customer_service/tests/run_smart_recorder_checks.py`
5. `uv run python apps/wechat_ai_customer_service/tests/run_recorder_order_sheet_module_checks.py`
6. `uv run python apps/wechat_ai_customer_service/tests/run_vps_admin_control_plane_checks.py`

---

## 7. 已知边界与后续增强

当前边界：

1. V1 不回填 `进价（单价）` 与 `总进价`。
2. 成本价依赖产品库匹配逻辑，需在V2实现。

V2建议：

1. 产品库字段匹配策略：`cost_price -> purchase_price -> 进价 -> price_tiers`。
2. 命中成本价后自动计算 `总进价 = 数量 * 进价`。
3. 对未命中条目标记 `needs_review` 并在报告中分组展示。

---

## 8. 回滚策略

1. 在 `vps_admin` 删除账号绑定，恢复租户/全局默认模块。
2. 若新模块异常，将模块状态改为 `paused`，并切回 `raw_message_log_v1`。
3. 历史导出任务与报告保留，不做删除。

---

## 9. 交付结论

截至 2026-05-09，本需求已具备上线所需最小闭环：

1. 通用采集与任务化导出底座可用。
2. 订货表定制模块可用。
3. 双开关独立控制可用。
4. 服务端 admin 账号级模块分配可用。
5. 客户端一键导出任务化链路可用。

