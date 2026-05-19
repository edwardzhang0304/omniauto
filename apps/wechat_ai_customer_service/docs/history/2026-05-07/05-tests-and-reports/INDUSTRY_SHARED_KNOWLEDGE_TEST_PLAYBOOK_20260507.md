# 行业共享知识库测试与实盘演练（2026-05-07）

## 1. 静态检查
前端脚本语法：
```powershell
node --check apps/wechat_ai_customer_service/admin_backend/static/app.js
node --check apps/wechat_ai_customer_service/vps_admin/static/app.js
```

Python 语法（不落盘 AST）：
```powershell
.venv\Scripts\python.exe - <<'PY'
import ast, pathlib
files = [
    "apps/wechat_ai_customer_service/cloud_gate.py",
    "apps/wechat_ai_customer_service/sync/vps_sync.py",
    "apps/wechat_ai_customer_service/industry_catalog.py",
]
for f in files:
    ast.parse(pathlib.Path(f).read_text(encoding="utf-8"), filename=f)
print("ok")
PY
```

## 2. 自动化回归命令
建议顺序：
```powershell
.venv\Scripts\python.exe apps/wechat_ai_customer_service/tests/run_cloud_gate_lock_checks.py
.venv\Scripts\python.exe apps/wechat_ai_customer_service/tests/run_runtime_start_cloud_guard_checks.py
.venv\Scripts\python.exe apps/wechat_ai_customer_service/tests/run_multi_tenant_auth_sync_checks.py
.venv\Scripts\python.exe apps/wechat_ai_customer_service/tests/run_local_auth_shared_console_checks.py
.venv\Scripts\python.exe apps/wechat_ai_customer_service/tests/run_auth_security_checks.py
.venv\Scripts\python.exe apps/wechat_ai_customer_service/tests/run_vps_local_two_port_shared_sync_checks.py
```

说明：
- 在当前 Windows 环境，部分 runtime 目录写入需要提升权限执行。
- `run_admin_backend_checks.py --chapter foundation` 在当前基线存在 1 个与本次改造无关的历史失败（RAG experience 断言），需单独治理。

## 3. 实盘演练步骤（强制在线闭环）
### 前置约定（测试环境）
- 测试环境默认允许并推荐“本地双端口模拟云端”：
  - 服务端：`vps_admin`（本地端口 A）
  - 客户端管理端：`admin_backend`（本地端口 B）
- 标准验证脚本：`apps/wechat_ai_customer_service/tests/run_vps_local_two_port_shared_sync_checks.py`
- 在 `WECHAT_CLOUD_REQUIRED=1` 下，若报 `cloud_base_url_missing`，先视为“环境未接通”，不直接判定为代码缺陷。

### 步骤 A：验证“未连云不可用”
1. 设置：
   - `WECHAT_CLOUD_REQUIRED=1`
   - `WECHAT_CLOUD_STRICT_ONLINE=1`
2. 断开 VPS 或不给有效快照。
3. 预期：
   - `GET /api/system/status` 返回 `423`
   - runtime 启动接口返回 `cloud_authoritative_access_required` 或 `cloud_snapshot_refresh_failed`

### 步骤 B：验证“连云后可用”
1. 恢复 VPS，执行共享快照拉取。
2. 预期：
   - `cloud_gate.ok=true`
   - runtime 可启动
   - 平台规则页显示 `readonly=true`（云端托管）

### 步骤 C：验证“续租失败即停服”
1. 启动 runtime 后断网。
2. 等待一个续租周期（默认 20 秒）。
3. 预期：
   - listener 日志出现 `managed_listener_cloud_refresh_failed`
   - runtime 状态变为 `stopped`

## 4. 行业匹配演练
1. 在 VPS 管理台创建 customer 账号，选择行业（菜单来自 `/v1/admin/industries`）。
2. 拉取共享快照。
3. 预期：
   - 快照仅含 `global + 已选行业` 条目
   - `tenant_industry_id` 正确
   - `policy_bundle.industry_id` 与租户行业一致
