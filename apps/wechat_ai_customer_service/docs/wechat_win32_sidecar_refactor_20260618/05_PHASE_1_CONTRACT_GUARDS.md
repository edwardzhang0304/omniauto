# Phase 1 Contract Guards

> Customer-visible reply ownership baseline: [../customer_visible_reply_ownership_baseline.md](../customer_visible_reply_ownership_baseline.md)

Phase 1 的目标是在真正拆代码前补保护网。只有保护网足够，后续拆分才不会把行为改坏而看不出来。

## 目标

确保以下行为被测试保护：

- sidecar CLI 可从任意 cwd 运行 `--help`。
- `add-friend-entry-click-plan` 是 canonical main route。
- Windows alias 不替代 canonical main route。
- stdout 仍是 JSON。
- facade 仍能 import 现有 public helpers。
- add_friend payload/result/error code 不变。
- runtime 输出不被重新纳入 Git。

## 可改文件

允许：

```text
apps/wechat_ai_customer_service/tests/run_add_friend_package_smoke.py
apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_compat_checks.py
apps/wechat_ai_customer_service/docs/wechat_win32_sidecar_refactor_20260618/*
```

谨慎允许：

```text
workflows/verification/general/runtime_artifact_guard.py
```

不建议：

```text
apps/wechat_ai_customer_service/adapters/wechat_win32_ocr_sidecar.py
```

Phase 1 原则上不拆 sidecar，只补测试和文档。

## 建议新增测试点

### 1. CLI action choices 固定

在 `run_wechat_win32_ocr_compat_checks.py` 增加或确认：

```text
--help 包含 status / capabilities / sessions / messages / send / recover-render
--help 包含 add-friend-entry-click-plan
--help 包含 add-friend-entry-click-plan-windows
--help 包含 add-friend-entry-click-plan-windows-1080p-reference
```

### 2. stdout JSON 固定

用不依赖真实微信的失败路径检查：

```text
在无 pywin32 或 mock 环境下，输出仍是 JSON
JSON 里有 ok/state/error
```

不要要求真实微信窗口。

### 3. facade import 固定

测试从 sidecar import 当前常用符号：

```text
parse_sessions_from_ocr
parse_messages_from_ocr
calculate_send_points
validate_capture_geometry
validate_send_geometry
normalize_wechat_window
add_friend_surface_readiness
add_friend_entry_click_plan_payload
```

后续拆分时，这些符号即便移动实现，也要继续从 facade 可 import。

### 4. add_friend canonical route 固定

已有 smoke 已覆盖很多内容，继续强化：

```text
ADD_FRIEND_MAIN_ROUTE == "add-friend-entry-click-plan"
is_add_friend_main_route("add-friend-entry-click-plan")
not is_add_friend_main_route("add-friend-entry-click-plan-windows")
WeChatConnector.add_friend() 使用 canonical route
```

### 5. JSON contract fixture

为以下 payload 保留最小契约断言：

```text
TASK_PAYLOAD_INVALID
WECHAT_WINDOW_NOT_READY
OPERATOR_GUARD_NOT_READY
PHONE_NOT_FOUND
ADD_CONTACT_ENTRY_NOT_FOUND
INVITE_FORM_WINDOW_NOT_FOUND
INVITE_CONFIRM_CLICK_FAILED
ACCOUNT_RESTRICTED
invite_sent
already_friend
```

不用固定完整 JSON，只固定上层依赖字段。

## 测试命令

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_add_friend_package_smoke.py
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_compat_checks.py
.\.venv\Scripts\python.exe workflows\verification\general\runtime_artifact_guard.py check-staged
```

## 审计命令

```powershell
rg -n "add-friend-entry-click-plan-windows|ADD_FRIEND_MAIN_ROUTE|SIDECAR_ACTION_CHOICES|task_status|result_code|error_code" apps\wechat_ai_customer_service
```

关注：

- 是否出现“把 main route 改成 windows alias”的迹象。
- 是否出现新 JSON 字段替代旧字段。

## 停止条件

- 新增测试本身需要真实微信窗口才能跑。
- 为了通过测试而改外部 contract。
- 测试写死太多实现细节，导致后续等价拆分无法进行。

## Phase 1 完成条件

- 测试能在无真实微信操作的情况下保护契约。
- 失败信息能指出是哪类契约被破坏。
- 后续拆分可以依赖这些测试快速回归。

## 2026-06-18 执行记录

已在 `run_wechat_win32_ocr_compat_checks.py` 增加 Phase 1 契约 guard：

- `--help` 必须继续暴露基础 sidecar actions、canonical add_friend route、Windows alias、1080p reference route 和现有 CLI flags。
- canonical `add-friend-entry-click-plan` 的入参校验失败路径必须继续输出 JSON，且在 `TASK_PAYLOAD_INVALID` 时 `wechat_ui_action_attempted=false`、`window_probe.reason=task_payload_invalid_before_window_probe`。
- `wechat_win32_ocr_sidecar.py` 作为 facade 必须继续导出当前外部依赖的 callable surface，例如 `run_sidecar_cli`、`args_for_daemon_request`、`parse_sessions_from_ocr`、`send_payload`、`add_friend_entry_click_plan_payload`。

本次只补测试与记录，不修改 sidecar 运行逻辑，不拆文件，不改变 CLI/JSON 契约。
