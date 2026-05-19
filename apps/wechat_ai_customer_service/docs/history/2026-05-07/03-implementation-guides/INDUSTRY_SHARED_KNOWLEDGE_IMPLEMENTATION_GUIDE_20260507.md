# 行业共享知识库改造实施指南（2026-05-07）

## 1. 核心改造点
### 1.1 行业目录与策略包
文件：
- `apps/wechat_ai_customer_service/industry_catalog.py`

职责：
- 定义行业目录（`used_car/home_appliance/fast_food/lab_instruments`）
- 定义租户默认行业映射
- 构建 `policy_bundle`（global + industry + merged）
- 提供共享库种子数据（全局 + 4 行业）

### 1.2 VPS 共享快照按行业裁剪
文件：
- `apps/wechat_ai_customer_service/vps_admin/services.py`

关键函数：
- `build_official_shared_knowledge_snapshot(...)`
- `ensure_tenant_industry_bindings(...)`

行为：
- 从全库筛选 `industry_id in {global, tenant_industry_id}` 的条目下发
- 快照带 `tenant_industry_id`, `industry_catalog`, `policy_bundle`

### 1.3 客户账号/租户行业绑定
文件：
- `apps/wechat_ai_customer_service/vps_admin/services.py`
- `apps/wechat_ai_customer_service/admin_backend/api/tenants.py`
- `apps/wechat_ai_customer_service/data/tenants/*/tenant.json`

行为：
- 新建/更新 tenant、user 支持 `industry_id`
- 现有租户补齐行业绑定

### 1.4 控制台“新建账号行业菜单”
文件：
- `apps/wechat_ai_customer_service/vps_admin/static/index.html`
- `apps/wechat_ai_customer_service/vps_admin/static/app.js`
- `apps/wechat_ai_customer_service/vps_admin/app.py`

行为：
- 新建 customer 账号显示行业下拉
- 后端接口 `GET /v1/admin/industries`
- 提交 `industry_id` 并落到用户/租户绑定

### 1.5 平台规则云端托管
文件：
- `apps/wechat_ai_customer_service/platform_safety_rules.py`
- `apps/wechat_ai_customer_service/platform_understanding_rules.py`
- `apps/wechat_ai_customer_service/admin_backend/api/system.py`

行为：
- 优先读取 `shared_snapshot.policy_bundle.merged`
- 云端强制模式下，平台规则页面只读，拒绝本地保存

### 1.6 强制在线门禁
文件：
- `apps/wechat_ai_customer_service/cloud_gate.py`
- `apps/wechat_ai_customer_service/admin_backend/auth_context.py`
- `apps/wechat_ai_customer_service/admin_backend/services/customer_service_runtime.py`
- `apps/wechat_ai_customer_service/scripts/run_customer_service_listener.py`
- `apps/wechat_ai_customer_service/workflows/listen_and_reply.py`
- `apps/wechat_ai_customer_service/sync/vps_sync.py`

行为：
- 门禁失败返回 `423`
- runtime 启动前强制刷新快照
- listener 周期续租，续租失败立即停服
- 严格在线模式增加云端健康探测

## 2. 配置项建议
强制生产配置（推荐）：
- `WECHAT_CLOUD_REQUIRED=1`
- `WECHAT_CLOUD_STRICT_ONLINE=1`
- `WECHAT_CLOUD_ONLINE_MAX_AGE_SECONDS=90`（可按链路调 30~180）
- `WECHAT_CLOUD_REFRESH_INTERVAL_SECONDS=20`
- `WECHAT_CLOUD_PROBE_TIMEOUT_SECONDS=1.5`
- `WECHAT_CLOUD_PROBE_CACHE_SECONDS=5`

开发/离线联调：
- `WECHAT_CLOUD_REQUIRED=0`
- `WECHAT_CLOUD_STRICT_ONLINE=0`

## 3. 行业新增规范（以后继续扩展时）
新增行业最小步骤：
1. 在 `INDUSTRY_DEFINITIONS` 新增行业。
2. 新增 `INDUSTRY_SAFETY_OVERRIDES` 与 `INDUSTRY_UNDERSTANDING_OVERRIDES`。
3. 在 `seed_shared_library_items()` 增加该行业冷启动规则。
4. 为目标租户配置 `industry_id`。
5. 通过 `/v1/admin/industries` 与账号创建流程验证可选。

## 4. 回滚策略
快速回滚（最小影响）：
1. 临时设置 `WECHAT_CLOUD_REQUIRED=0`（仅紧急兜底，需审批）。
2. 保留行业分层结构不回退，先恢复可用性再修复云端链路。
3. 完成修复后恢复 `WECHAT_CLOUD_REQUIRED=1`。

结构回滚（不推荐）：
- 回到单共享库模型会丢失行业精度，且会重新抬高租户私有库冗余成本。
