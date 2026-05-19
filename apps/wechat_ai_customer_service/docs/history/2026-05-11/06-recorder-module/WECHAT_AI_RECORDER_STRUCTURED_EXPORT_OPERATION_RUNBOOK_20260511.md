# 微信AI智能记录员结构化导出操作与验收手册（2026-05-11）

## 1. 适用对象

适用于以下角色：

1. 平台管理员（VPS Admin）：分配客户模块、执行全局配置。
2. 客户账号管理员（Local Admin）：喂数据、发起导出任务、下载结果验收。

## 2. 前置条件

1. 已开启并登录 `wechat_ai_customer_service` 服务端与客户端。
2. 账号可访问“AI智能记录员”页面。
3. 目标会话已在会话列表中设置为“记录中”。
4. 若使用定制模块，已完成模块绑定：
- `module_key=order_sheet_lab_v1`
- 绑定优先级：`user > global > 默认模块`

## 3. 模块切换（管理员）

在 VPS Admin 的“客户与权限 > AI智能记录员模块分配”：

1. 选择目标账号（推荐 user 级绑定）。
2. 选择模块：
- `实验仪器订货表V1 (order_sheet_lab_v1)`：规则+LLM结构化导出。
- `通用原始消息导出V1 (raw_message_log_v1)`：纯原始记录导出。
3. 保存后在客户端刷新“AI智能记录员”页面，确认“当前结构化导出模块”展示正确。

## 4. 数据喂入（文本）

### 4.1 Excel 数据源

推荐格式（示例：`群聊_企点售后群 - 喂数据.xlsx`）：

1. 消息ID
2. 消息时间（建议 `YYYY-MM-DD HH:mm:ss`）
3. 发送者
4. 消息类型（文本消息/引用消息）
5. 内容

### 4.2 喂入流程

1. 将 Excel 解析为原始消息结构并写入 `RawMessageStore`。
2. 目标会话名保持固定（如：`群聊_企点售后群 - 喂数据`）。
3. 确保导出时 `target_names` 与会话名一致。

## 5. 导出操作（客户端）

“AI智能记录员 > 结构化导出（模块 + LLM）”支持四种入口：

1. `导出所有记录（结构化）`
2. `按日导出`
3. `按周导出`
4. `按月导出`

高级筛选（默认折叠）：

1. 设置开始日期 + 结束日期。
2. 点击 `按日期范围导出`。

说明：

1. 默认导出上限 `10000`。
2. 实际消息不足 `10000` 时按实际数量导出。
3. 任务创建后状态自动轮询，无需手动刷新。

## 6. 验收清单

### 6.1 UI 验收

1. 结构化导出主按钮文案为“导出所有记录（结构化）”。
2. 不再依赖“刷新任务状态”按钮。
3. 高级筛选中可直接执行“按日期范围导出”。
4. 导出队列/处理中状态卡可自动更新。

### 6.2 结果验收

1. 下载 Excel（`Sheet1`）字段顺序与订货表模板一致。
2. 日期字段按配置输出（默认 `YYYY-MM-DD`）。
3. 缺失字段（进价、总进价）在未接产品库前允许为空。
4. 报告文件可用于复核低置信度记录。

### 6.3 回归验收命令（开发侧）

1. `node --check apps/wechat_ai_customer_service/admin_backend/static/app.js`
2. `python -m py_compile apps/wechat_ai_customer_service/admin_backend/services/recorder_export_run_service.py apps/wechat_ai_customer_service/admin_backend/services/recorder_module_registry.py apps/wechat_ai_customer_service/vps_admin/services.py`
3. `python apps/wechat_ai_customer_service/tests/run_recorder_order_sheet_module_checks.py`
4. `python apps/wechat_ai_customer_service/tests/run_smart_recorder_checks.py`

## 7. 常见问题排查

1. 长时间“队列中”：
- 检查导出 worker 是否在线。
- 检查该租户是否存在 `running` 旧任务，必要时触发 `ensure_run_job` 重排队。

2. 导出慢：
- 检查模块 LLM 配额（`llm_max_rows_per_run`）。
- 检查是否全量时间范围 + 高频长文本导致 LLM补全过多。

3. 日期格式异常（仅月日）：
- 检查消息时间源是否缺失年份。
- 检查模块 `date_output_mode` 配置与归一化逻辑。

4. 抽取噪音偏多：
- 检查是否命中过滤词规则（取消单、状态消息、纯价格说明）。
- 检查是否需要更新客户模块规则而非改通用底座。
