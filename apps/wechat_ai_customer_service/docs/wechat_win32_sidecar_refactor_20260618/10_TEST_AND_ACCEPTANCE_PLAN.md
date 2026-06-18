# Test And Acceptance Plan

> Customer-visible reply ownership baseline: [../customer_visible_reply_ownership_baseline.md](../customer_visible_reply_ownership_baseline.md)

本文定义第五点拆分期间的测试矩阵。原则是：越靠近发送、点击、会话切换，测试越严格。

## 测试分层

### Layer 1 静态和 import

适用：

- 每次修改 Python 文件。

命令：

```powershell
.\.venv\Scripts\python.exe -m py_compile apps\wechat_ai_customer_service\adapters\wechat_win32_ocr_sidecar.py
```

如果新增包：

```powershell
.\.venv\Scripts\python.exe -m py_compile apps\wechat_ai_customer_service\adapters\wechat_win32_ocr\*.py
```

注意：PowerShell glob 对 `py_compile` 不一定按预期展开，必要时列出具体文件。

### Layer 2 sidecar 契约

适用：

- 每个阶段。

命令：

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_compat_checks.py
```

覆盖：

- sidecar 脚本 bootstrap。
- OCR/session/message 解析。
- 几何 helper。
- 发送 helper。
- add_friend helper。
- connector/RPA 兼容。

### Layer 3 add_friend 契约

适用：

- 每个阶段，尤其 Phase 5。

命令：

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_add_friend_package_smoke.py
```

必须保持：

- 34 项 smoke 全过。
- `add-friend-entry-click-plan` 仍是 official main route。
- Windows alias 不替代 canonical route。
- add_friend JSON/error/result/artifact 契约不变。

### Layer 4 客服多会话调度

适用：

- 改 session/parser/message/send/target switching。

命令：

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_customer_service_multi_session_scheduler_checks.py
```

目的：

- 防止拆 sidecar 时破坏多会话隔离、session key、ready reply FIFO、stale reply 处理。

### Layer 5 workflow logic

适用：

- 改发送、目标确认、OCR metadata、Brain First 周边。

命令：

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_workflow_logic_checks.py
```

目的：

- 防止 OCR/RPA speaker label 污染正文。
- 防止 send guard、freshness、handoff、polish gate 被破坏。

### Layer 6 cloud/startup

适用：

- 改启动、自检、operator guard、recorder/customer-service runtime stop。

命令：

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_cloud_auth_required_checks.py
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_vps_local_two_port_shared_sync_checks.py
```

### Layer 7 runtime guard

适用：

- 每次 staging 前。

命令：

```powershell
.\.venv\Scripts\python.exe workflows\verification\general\runtime_artifact_guard.py check-staged
```

目的：

- 防止测试产物、截图、日志、profile 被误提交。

## 阶段测试矩阵

| 阶段 | 必跑 |
| --- | --- |
| Phase 0 baseline | add_friend smoke, win32 compat, multi-session, workflow logic, runtime guard |
| Phase 1 guards | add_friend smoke, win32 compat, runtime guard |
| Phase 2 pure extraction | py_compile, win32 compat, add_friend smoke; 改文本/session 时加 multi-session |
| Phase 3 window/capture/OCR/profile | py_compile, win32 compat, add_friend smoke, multi-session |
| Phase 4 send/session/action | win32 compat, multi-session, workflow logic, add_friend smoke |
| Phase 5 add_friend adapter | add_friend smoke, win32 compat, runtime guard |

## 实盘验收分层

### 只读实盘

可在用户允许 Codex 操作微信窗口但不发送时做：

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\adapters\wechat_win32_ocr_sidecar.py status --artifact-dir runtime/sidecar_status_probe
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\adapters\wechat_win32_ocr_sidecar.py capabilities --artifact-dir runtime/sidecar_capabilities_probe
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\adapters\wechat_win32_ocr_sidecar.py sessions --artifact-dir runtime/sidecar_sessions_probe
```

### dry-run 双会话

低风险验证：

```powershell
.\.venv\Scripts\python.exe workflows\verification\wechat_customer_service\two_visible_session_customer_service_live.py --self-check
```

更接近实盘但不真实发送：

```powershell
.\.venv\Scripts\python.exe workflows\verification\wechat_customer_service\two_visible_session_customer_service_live.py --skip-prompt-send --synthetic-input-only --dry-reply-send --rounds 1
```

注意：该脚本会做微信窗口预检，不能当纯离线测试。

### 真实发送/加好友

必须用户明确确认。

前置：

- 微信已登录。
- 目标会话明确。
- 悬浮球键鼠守护开启。
- 先跑只读或 dry-run。
- 不在用户手动操作鼠标键盘时测试。

## 验收报告模板

每个阶段完成后写：

```text
stage:
files changed:
contract names touched:
public CLI changed: yes/no
JSON fields changed: yes/no
tests:
  - command:
    result:
known unrelated changes:
runtime artifacts generated:
runtime guard:
manual/live test:
rollback:
decision:
```

## 失败处理

### 契约测试失败

先停止，不继续拆。对照 [03_CONTRACT_FREEZE_AND_COMPATIBILITY_GUARD.md](03_CONTRACT_FREEZE_AND_COMPATIBILITY_GUARD.md)。

### 行为 smoke 失败

判断是否由本阶段移动引起。优先回退本阶段委托点，不要补新逻辑掩盖。

### 实盘失败

保存 artifact，停止重复点击。优先分析：

- active window。
- DPI/profile。
- OCR items。
- locator candidates。
- click point。
- post-click readback。

### runtime guard 失败

把稳定样例迁到 `tests/fixtures`，运行产物保持 runtime ignored，不要提交。

## 完整验收组合

第五点全部拆完后，至少跑：

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_add_friend_package_smoke.py
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_compat_checks.py
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_customer_service_multi_session_scheduler_checks.py
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_workflow_logic_checks.py
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_brain_first_static_architecture_audit.py
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_cloud_auth_required_checks.py
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_vps_local_two_port_shared_sync_checks.py
.\.venv\Scripts\python.exe workflows\verification\general\runtime_artifact_guard.py check-staged
```

然后再按用户要求决定是否做实盘。
