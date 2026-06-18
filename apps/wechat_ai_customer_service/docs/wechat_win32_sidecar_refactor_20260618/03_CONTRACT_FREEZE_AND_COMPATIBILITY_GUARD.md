# Contract Freeze And Compatibility Guard

> Customer-visible reply ownership baseline: [../customer_visible_reply_ownership_baseline.md](../customer_visible_reply_ownership_baseline.md)

本文是第五点拆分时的硬约束。任何阶段都不能为了“整理代码”破坏这些契约。

## 不允许随便改名

以下名称属于协作契约，不是局部实现细节：

```text
add-friend-entry-click-plan
add-friend-entry-click-plan-windows
add-friend-entry-click-plan-windows-1080p-reference
ADD_FRIEND_MAIN_ROUTE
ADD_FRIEND_WINDOWS_ROUTE
ADD_FRIEND_WINDOWS_1080P_REFERENCE_ROUTE
SIDECAR_BASE_ACTIONS
SIDECAR_ACTION_CHOICES
```

禁止：

- 把 canonical route 改成 Windows alias。
- 删除 Windows alias。
- 改 artifact scope 但不加兼容映射。
- 改 JSON 字段名。
- 改 PowerShell 脚本默认入口但不更新 smoke。

如确实需要迁移名称，必须先写迁移文档并得到用户确认，确认内容包括：

```text
old name
new name
compatibility alias
downstream callers
test updates
rollback method
```

## CLI 契约

sidecar 入口：

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\adapters\wechat_win32_ocr_sidecar.py <action> [flags]
```

基础 action 必须保留：

```text
status
capabilities
sessions
messages
send
recover-render
```

add_friend action 必须保留：

```text
add-friend-entry-click-plan
add-friend-entry-click-plan-windows
add-friend-entry-click-plan-windows-1080p-reference
```

add_friend flags 必须保留：

```text
--phone
--wechat
--verify-message
--remark-name
--remark-code
--artifact-dir
--calibration-only
```

send/messages flags 必须保留：

```text
--target
--session-key
--text
--exact
--history-load-times
--history-mode
--anchor-id
--anchor-content-key
--reply-content-key
--max-scroll-steps
--max-duration-seconds
--max-snapshots
--min-delay-ms
--max-delay-ms
--restore-to-latest
--no-restore-to-latest
```

允许：

- 增加可选 flag。
- 增加诊断字段。
- 增加内部模块。

不允许：

- 删除现有 flag。
- 改 flag 语义。
- 让 Worker 使用新 flag 才能维持旧行为。

## JSON 输出契约

所有 action 输出必须仍是 stdout JSON。

通用字段尽量保留：

```text
ok
online
adapter
state
reason
error
window_probe
artifact_dir
```

add_friend 顶层字段必须保留：

```text
ok
state
task_status
result_code
error_code
current_step
reason
error
artifact_dir
plan_path
review_json_path
review_html_path
server_report_payload
events
diagnostics
```

成功 result code 必须保留：

```text
invite_sent
already_friend
```

失败 error code 必须保留：

```text
TASK_PAYLOAD_INVALID
PHONE_NOT_FOUND
ADD_CONTACT_ENTRY_NOT_FOUND
INVITE_FORM_WINDOW_NOT_FOUND
INVITE_CONFIRM_CLICK_FAILED
ACCOUNT_RESTRICTED
WECHAT_WINDOW_NOT_READY
OPERATOR_GUARD_NOT_READY
INVITE_FIELD_VERIFICATION_FAILED
```

兼容规则：

- 可以新增字段。
- 可以让 `diagnostics` 更丰富。
- 不得移除已有字段。
- 不得把 success 的 `task_status=completed` 改成其他词。
- 不得把 failure 的 `task_status=failed` 改成其他词。
- 不得让 `already_friend` 看起来像错误终态。

## Artifact 契约

当前正式 route artifact scope：

```text
runtime/add_friend_entry_click_plan_windows/
```

当前 reference scope：

```text
runtime/add_friend_entry_click_plan_windows_1080p_reference/
```

重要说明：

- 第四点已治理 runtime Git 跟踪，runtime 输出应继续留在本地且被 Git 忽略。
- 不要把新的 live artifact 加回 Git。
- 如需稳定 fixture，应迁到 `apps/wechat_ai_customer_service/tests/fixtures/`。

## Import 兼容契约

当前测试直接从 sidecar import 很多函数，例如：

```python
from apps.wechat_ai_customer_service.adapters.wechat_win32_ocr_sidecar import (
    parse_sessions_from_ocr,
    parse_messages_from_ocr,
    calculate_send_points,
    validate_active_send_target,
    add_friend_surface_readiness,
)
```

拆分后仍要兼容：

- 这些名字可以来自新模块 re-export。
- 函数签名和返回结构必须不变。
- 新模块不能要求 Windows GUI 才能 import。

## Connector 契约

`WeChatConnector` 对上层仍应保持：

- `status`
- `capabilities`
- `list_sessions`
- `messages`
- `send_text_and_verify`
- `add_friend`

其中：

- `WeChatConnector.add_friend()` 默认调用 canonical route `add-friend-entry-click-plan`。
- 不能要求上层改成 Windows alias。

## Brain First 和代码机制层契约

sidecar 不能做：

- 根据客户消息生成回复。
- 修改 Brain 已生成的客户可见回复含义。
- 在 Brain 不可用时生成本地兜底话术并发送。

sidecar 可以做：

- 确认目标会话。
- 捕获 OCR 消息。
- 校验 freshness。
- 执行发送。
- 阻断不安全发送。
- 输出内部 handoff/alert 所需诊断。

## 每次拆分前的契约检查命令

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_add_friend_package_smoke.py
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_compat_checks.py
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_customer_service_multi_session_scheduler_checks.py
```

涉及 workflow/send/session 时增加：

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_workflow_logic_checks.py
```

涉及 cloud/startup 时增加：

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_cloud_auth_required_checks.py
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_vps_local_two_port_shared_sync_checks.py
```

## 必须停止的情况

出现以下情况时，不要继续拆下一阶段：

- `add-friend-entry-click-plan` 不在 `--help` 或 action choices 中。
- `run_add_friend_package_smoke.py` 失败。
- `run_wechat_win32_ocr_compat_checks.py` 失败且不是明确无关。
- `git diff` 中出现未经确认的 route/JSON 字段重命名。
- 新模块 import 需要真实微信窗口才能成功。
- sidecar stdout 不再是纯 JSON。
