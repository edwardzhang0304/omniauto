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
| Phase 3.5 capture/window action layer | focused fake dependency tests, py_compile, win32 compat, add_friend smoke, multi-session; 触碰 action execution 时加只读实盘 |
| Phase 4 send/session/action | win32 compat, multi-session, workflow logic, add_friend smoke |
| Phase 5 add_friend adapter | add_friend smoke, win32 compat, runtime guard |

## Phase 3.5 专项测试要求

Phase 3.5 必须按子阶段选择测试，不允许用“win32 compat 通过”替代 focused fake dependency test。

read-only window metrics:

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_window_metrics_checks.py
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_compat_checks.py
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_add_friend_package_smoke.py
```

capture planning/ImageGrab:

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_capture_checks.py
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_compat_checks.py
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_add_friend_package_smoke.py
```

PrintWindow execution:

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_capture_checks.py
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_compat_checks.py
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_customer_service_multi_session_scheduler_checks.py
```

normalize/action planning:

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_window_action_planning_checks.py
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_compat_checks.py
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_workflow_logic_checks.py
```

只读实盘只在触碰真实截图或真实窗口动作 execution 后执行，且必须由用户确认微信窗口可被操作；真实发送/加好友仍需单独确认。

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

## 阶段测试记录 2026-06-19 Phase 2

stage: Phase 2 pure extraction

files changed:

- `apps/wechat_ai_customer_service/adapters/wechat_win32_ocr_sidecar.py`
- `apps/wechat_ai_customer_service/adapters/wechat_win32_ocr/*.py`
- `apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_*_checks.py`

contract names touched:

- public CLI changed: no
- JSON fields changed: no
- route constants changed: no
- artifact scopes changed: no
- facade callable names changed: no

tests:

- `.\.venv\Scripts\python.exe -m py_compile apps\wechat_ai_customer_service\adapters\wechat_win32_ocr_sidecar.py apps\wechat_ai_customer_service\adapters\wechat_win32_ocr\env_config.py apps\wechat_ai_customer_service\adapters\wechat_win32_ocr\humanized_input.py apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_env_config_checks.py apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_humanized_input_checks.py` -> passed.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_geometry_extraction_checks.py` -> passed, 5 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_text_normalization_checks.py` -> passed, 5 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_env_config_checks.py` -> passed, 5 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_humanized_input_checks.py` -> passed, 5 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_compat_checks.py` -> passed, 135 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_add_friend_package_smoke.py` -> passed, 34 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_customer_service_multi_session_scheduler_checks.py` -> passed, 123 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_workflow_logic_checks.py` -> passed, 114 checks.

known unrelated changes:

- `AGENTS.md` and recorder/F8 related files are still locally modified from earlier work and were not included in this Phase 2 scope.
- `$dir/` and `workflow_switch_probe_debug/` remain untracked local artifacts and were not touched.

runtime artifacts generated:

- none intentionally generated by Phase 2 tests.

manual/live test:

- not run; Phase 2 was non-live pure extraction only.

rollback:

- revert sidecar wrapper delegation for the affected pure helper group, keeping new modules/tests for review if needed.

## 阶段测试记录 2026-06-19 Phase 3.1

stage: Phase 3.1 device profile diagnostics

files changed:

- `apps/wechat_ai_customer_service/adapters/wechat_win32_ocr_sidecar.py`
- `apps/wechat_ai_customer_service/adapters/wechat_win32_ocr/device_profile.py`
- `apps/wechat_ai_customer_service/adapters/wechat_win32_ocr/geometry.py`
- `apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_device_profile_checks.py`

contract names touched:

- public CLI changed: no
- JSON fields changed: no
- route constants changed: no
- artifact scopes changed: no
- facade callable names changed: no

tests:

- `.\.venv\Scripts\python.exe -m py_compile apps\wechat_ai_customer_service\adapters\wechat_win32_ocr_sidecar.py apps\wechat_ai_customer_service\adapters\wechat_win32_ocr\device_profile.py apps\wechat_ai_customer_service\adapters\wechat_win32_ocr\geometry.py apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_device_profile_checks.py` -> passed.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_device_profile_checks.py` -> passed, 4 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_geometry_extraction_checks.py` -> passed, 5 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_compat_checks.py` -> passed, 135 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_add_friend_package_smoke.py` -> passed, 34 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_customer_service_multi_session_scheduler_checks.py` -> passed, 123 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_workflow_logic_checks.py` -> passed, 114 checks.

manual/live test:

- not run; this subphase was profile/geometry diagnostics only.

rollback:

- restore sidecar `validate_capture_geometry` implementation and inline profile shape assembly if any downstream profile shape issue appears.

## 阶段测试记录 2026-06-19 Phase 3.2

stage: Phase 3.2 pure windowing title/main-window metadata

files changed:

- `apps/wechat_ai_customer_service/adapters/wechat_win32_ocr_sidecar.py`
- `apps/wechat_ai_customer_service/adapters/wechat_win32_ocr/windowing.py`
- `apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_windowing_checks.py`

contract names touched:

- public CLI changed: no
- JSON fields changed: no
- route constants changed: no
- artifact scopes changed: no
- facade callable names changed: no

tests:

- `.\.venv\Scripts\python.exe -m py_compile apps\wechat_ai_customer_service\adapters\wechat_win32_ocr_sidecar.py apps\wechat_ai_customer_service\adapters\wechat_win32_ocr\windowing.py apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_windowing_checks.py` -> passed.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_windowing_checks.py` -> passed, 4 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_device_profile_checks.py` -> passed, 4 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_compat_checks.py` -> passed, 135 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_add_friend_package_smoke.py` -> passed, 34 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_customer_service_multi_session_scheduler_checks.py` -> passed, 123 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_workflow_logic_checks.py` -> passed, 114 checks.

manual/live test:

- not run; this subphase was pure title/class metadata extraction only.

rollback:

- restore sidecar inline implementations for `normalize_wechat_title`, `is_wechat_main_window`, and `wechat_window_title_score`.

## 阶段测试记录 2026-06-19 Phase 3.3

stage: Phase 3.3 render/capture diagnostics

files changed:

- `apps/wechat_ai_customer_service/adapters/wechat_win32_ocr_sidecar.py`
- `apps/wechat_ai_customer_service/adapters/wechat_win32_ocr/render_diagnostics.py`
- `apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_render_diagnostics_checks.py`

contract names touched:

- public CLI changed: no
- JSON fields changed: no
- route constants changed: no
- artifact scopes changed: no
- facade callable names changed: no

tests:

- `.\.venv\Scripts\python.exe -m py_compile apps\wechat_ai_customer_service\adapters\wechat_win32_ocr_sidecar.py apps\wechat_ai_customer_service\adapters\wechat_win32_ocr\render_diagnostics.py apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_render_diagnostics_checks.py` -> passed.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_render_diagnostics_checks.py` -> passed, 4 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_windowing_checks.py` -> passed, 4 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_device_profile_checks.py` -> passed, 4 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_compat_checks.py` -> passed, 135 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_add_friend_package_smoke.py` -> passed, 34 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_customer_service_multi_session_scheduler_checks.py` -> passed, 123 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_workflow_logic_checks.py` -> passed, 114 checks.

manual/live test:

- not run; this subphase only moved diagnostics that consume existing screenshots/OCR items.

rollback:

- restore sidecar inline implementations for `detect_blank_render`, `image_information_score`, and `likely_foreign_overlay_capture`.

## 阶段测试记录 2026-06-19 Phase 3.4

stage: Phase 3.4 OCR engine row normalization

files changed:

- `apps/wechat_ai_customer_service/adapters/wechat_win32_ocr_sidecar.py`
- `apps/wechat_ai_customer_service/adapters/wechat_win32_ocr/ocr_engine.py`
- `apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_ocr_engine_checks.py`
- `apps/wechat_ai_customer_service/docs/wechat_win32_sidecar_refactor_20260618/07_PHASE_3_DEVICE_LAYOUT_CAPTURE_GUIDE.md`
- `apps/wechat_ai_customer_service/docs/wechat_win32_sidecar_refactor_20260618/10_TEST_AND_ACCEPTANCE_PLAN.md`

contract names touched:

- public CLI changed: no
- JSON fields changed: no
- route constants changed: no
- artifact scopes changed: no
- facade callable names changed: no

tests:

- `.\.venv\Scripts\python.exe -m py_compile apps\wechat_ai_customer_service\adapters\wechat_win32_ocr_sidecar.py apps\wechat_ai_customer_service\adapters\wechat_win32_ocr\ocr_engine.py apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_ocr_engine_checks.py` -> passed.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_ocr_engine_checks.py` -> passed, 5 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_render_diagnostics_checks.py` -> passed, 4 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_compat_checks.py` -> passed, 135 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_add_friend_package_smoke.py` -> passed, 34 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_customer_service_multi_session_scheduler_checks.py` -> passed, 123 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_workflow_logic_checks.py` -> passed, 114 checks.

manual/live test:

- not run; fake OCR engine tests covered this non-live wrapper change.

rollback:

- restore sidecar inline OCR row normalization while keeping `ocr_engine.py` unused for review.

## 阶段测试记录 2026-06-19 Phase 3.5a

stage: Phase 3.5a read-only window metrics helper

files changed:

- `apps/wechat_ai_customer_service/adapters/wechat_win32_ocr_sidecar.py`
- `apps/wechat_ai_customer_service/adapters/wechat_win32_ocr/window_metrics.py`
- `apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_window_metrics_checks.py`
- `apps/wechat_ai_customer_service/docs/wechat_win32_sidecar_refactor_20260618/07_PHASE_3_DEVICE_LAYOUT_CAPTURE_GUIDE.md`
- `apps/wechat_ai_customer_service/docs/wechat_win32_sidecar_refactor_20260618/10_TEST_AND_ACCEPTANCE_PLAN.md`

contract names touched:

- public CLI changed: no
- JSON fields changed: no
- route constants changed: no
- artifact scopes changed: no
- facade callable names changed: no

tests:

- `.\.venv\Scripts\python.exe -m py_compile apps\wechat_ai_customer_service\adapters\wechat_win32_ocr_sidecar.py apps\wechat_ai_customer_service\adapters\wechat_win32_ocr\window_metrics.py apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_window_metrics_checks.py` -> passed.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_window_metrics_checks.py` -> passed, 6 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_compat_checks.py` -> passed, 135 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_add_friend_package_smoke.py` -> passed, 34 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_customer_service_multi_session_scheduler_checks.py` -> passed, 123 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_workflow_logic_checks.py` -> passed, 114 checks.

manual/live test:

- not run; this subphase only moved read-only wrappers behind fake dependency tests.

rollback:

- restore sidecar inline implementations for `get_window_geometry`, `get_window_client_geometry`, and `window_dpi_scale`; keep `window_metrics.py` unused for review.

## 阶段测试记录 2026-06-19 Phase 3.5b

stage: Phase 3.5b capture rect planning and candidate selection

files changed:

- `apps/wechat_ai_customer_service/adapters/wechat_win32_ocr_sidecar.py`
- `apps/wechat_ai_customer_service/adapters/wechat_win32_ocr/capture.py`
- `apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_capture_checks.py`
- `apps/wechat_ai_customer_service/docs/wechat_win32_sidecar_refactor_20260618/07_PHASE_3_DEVICE_LAYOUT_CAPTURE_GUIDE.md`
- `apps/wechat_ai_customer_service/docs/wechat_win32_sidecar_refactor_20260618/10_TEST_AND_ACCEPTANCE_PLAN.md`

contract names touched:

- public CLI changed: no
- JSON fields changed: no
- route constants changed: no
- artifact scopes changed: no
- facade callable names changed: no

tests:

- `.\.venv\Scripts\python.exe -m py_compile apps\wechat_ai_customer_service\adapters\wechat_win32_ocr_sidecar.py apps\wechat_ai_customer_service\adapters\wechat_win32_ocr\capture.py apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_capture_checks.py` -> passed.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_capture_checks.py` -> passed, 5 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_compat_checks.py` -> passed, 135 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_add_friend_package_smoke.py` -> passed, 34 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_customer_service_multi_session_scheduler_checks.py` -> passed, 123 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_workflow_logic_checks.py` -> passed, 114 checks.

manual/live test:

- not run; this subphase only moved capture planning and candidate selection behind fake dependency tests.

rollback:

- restore sidecar inline `max(candidates, key=image_information_score)` and DPI rect planning; keep `capture.py` unused for review.

## 阶段测试记录 2026-06-19 Phase 3.5c

stage: Phase 3.5c capture execution wrappers excluding PrintWindow

files changed:

- `apps/wechat_ai_customer_service/adapters/wechat_win32_ocr_sidecar.py`
- `apps/wechat_ai_customer_service/adapters/wechat_win32_ocr/capture.py`
- `apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_capture_checks.py`
- `apps/wechat_ai_customer_service/docs/wechat_win32_sidecar_refactor_20260618/07_PHASE_3_DEVICE_LAYOUT_CAPTURE_GUIDE.md`
- `apps/wechat_ai_customer_service/docs/wechat_win32_sidecar_refactor_20260618/10_TEST_AND_ACCEPTANCE_PLAN.md`

contract names touched:

- public CLI changed: no
- JSON fields changed: no
- route constants changed: no
- artifact scopes changed: no
- facade callable names changed: no

tests:

- `.\.venv\Scripts\python.exe -m py_compile apps\wechat_ai_customer_service\adapters\wechat_win32_ocr_sidecar.py apps\wechat_ai_customer_service\adapters\wechat_win32_ocr\capture.py apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_capture_checks.py` -> passed.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_capture_checks.py` -> passed, 7 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_compat_checks.py` -> passed, 135 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_add_friend_package_smoke.py` -> passed, 34 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_customer_service_multi_session_scheduler_checks.py` -> passed, 123 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_workflow_logic_checks.py` -> passed, 114 checks.

manual/live test:

- not run; this subphase used injected ImageGrab/rect/dpi dependencies and did not move PrintWindow execution.

rollback:

- restore sidecar inline `try_image_grab` and `capture_window_by_rect`; keep `capture.py` planning helpers for review.

## 阶段测试记录 2026-06-19 Phase 3.5d 准备

stage: Phase 3.5d PrintWindow migration test design

files changed:

- `apps/wechat_ai_customer_service/docs/wechat_win32_sidecar_refactor_20260618/12_PHASE_3_5_CAPTURE_WINDOW_ACTION_LAYER_PLAN.md`
- `apps/wechat_ai_customer_service/docs/wechat_win32_sidecar_refactor_20260618/07_PHASE_3_DEVICE_LAYOUT_CAPTURE_GUIDE.md`
- `apps/wechat_ai_customer_service/docs/wechat_win32_sidecar_refactor_20260618/10_TEST_AND_ACCEPTANCE_PLAN.md`

contract names touched:

- public CLI changed: no
- JSON fields changed: no
- route constants changed: no
- artifact scopes changed: no
- facade callable names changed: no

tests:

- documentation-only chapter; run `git diff --check` and runtime staged guard before commit.

manual/live test:

- not run; no runtime code changed.

rollback:

- remove the Phase 3.5d preparation notes if the fake resource test design is replaced by a more complete design.

## 阶段测试记录 2026-06-19 Phase 3.5d 落代码

stage: Phase 3.5d PrintWindow capture execution migration

files changed:

- `apps/wechat_ai_customer_service/adapters/wechat_win32_ocr_sidecar.py`
- `apps/wechat_ai_customer_service/adapters/wechat_win32_ocr/capture.py`
- `apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_capture_checks.py`
- `apps/wechat_ai_customer_service/docs/wechat_win32_sidecar_refactor_20260618/07_PHASE_3_DEVICE_LAYOUT_CAPTURE_GUIDE.md`
- `apps/wechat_ai_customer_service/docs/wechat_win32_sidecar_refactor_20260618/10_TEST_AND_ACCEPTANCE_PLAN.md`

contract names touched:

- public CLI changed: no
- JSON fields changed: no
- route constants changed: no
- artifact scopes changed: no
- facade callable names changed: no

tests:

- `.\.venv\Scripts\python.exe -m py_compile apps\wechat_ai_customer_service\adapters\wechat_win32_ocr_sidecar.py apps\wechat_ai_customer_service\adapters\wechat_win32_ocr\capture.py apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_capture_checks.py` -> passed.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_capture_checks.py` -> passed, 13 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_compat_checks.py` -> passed, 135 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_add_friend_package_smoke.py` -> passed, 34 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_customer_service_multi_session_scheduler_checks.py` -> passed, 123 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_workflow_logic_checks.py` -> passed, 114 checks.

manual/live test:

- not run; fake resource cleanup tests covered the migration without touching a real WeChat window.

rollback:

- restore sidecar inline `capture_window_image`; keep `capture.py` helpers unused for review.

## 阶段测试记录 2026-06-19 Phase 3.5e

stage: Phase 3.5e OCR runner cache helper

files changed:

- `apps/wechat_ai_customer_service/adapters/wechat_win32_ocr_sidecar.py`
- `apps/wechat_ai_customer_service/adapters/wechat_win32_ocr/ocr_engine.py`
- `apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_ocr_engine_checks.py`
- `apps/wechat_ai_customer_service/docs/wechat_win32_sidecar_refactor_20260618/07_PHASE_3_DEVICE_LAYOUT_CAPTURE_GUIDE.md`
- `apps/wechat_ai_customer_service/docs/wechat_win32_sidecar_refactor_20260618/10_TEST_AND_ACCEPTANCE_PLAN.md`

contract names touched:

- public CLI changed: no
- JSON fields changed: no
- route constants changed: no
- artifact scopes changed: no
- facade callable names changed: no

tests:

- `.\.venv\Scripts\python.exe -m py_compile apps\wechat_ai_customer_service\adapters\wechat_win32_ocr_sidecar.py apps\wechat_ai_customer_service\adapters\wechat_win32_ocr\ocr_engine.py apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_ocr_engine_checks.py` -> passed.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_ocr_engine_checks.py` -> passed, 6 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_compat_checks.py` -> passed, 135 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_add_friend_package_smoke.py` -> passed, 34 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_customer_service_multi_session_scheduler_checks.py` -> passed, 123 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_workflow_logic_checks.py` -> passed, 114 checks.

manual/live test:

- not run; fake OCR engine tests covered the cache/facade migration.

rollback:

- restore sidecar inline `_OCR_ENGINE` initialization and direct `_OCR_ENGINE(image)` call; keep `ocr_engine.run_ocr_with_cache` unused for review.

## 阶段测试记录 2026-06-19 Phase 3.5f

stage: Phase 3.5f normalize_wechat_window planning helper

files changed:

- `apps/wechat_ai_customer_service/adapters/wechat_win32_ocr_sidecar.py`
- `apps/wechat_ai_customer_service/adapters/wechat_win32_ocr/window_action_planning.py`
- `apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_window_action_planning_checks.py`
- `apps/wechat_ai_customer_service/docs/wechat_win32_sidecar_refactor_20260618/07_PHASE_3_DEVICE_LAYOUT_CAPTURE_GUIDE.md`
- `apps/wechat_ai_customer_service/docs/wechat_win32_sidecar_refactor_20260618/10_TEST_AND_ACCEPTANCE_PLAN.md`

contract names touched:

- public CLI changed: no
- JSON fields changed: no
- route constants changed: no
- artifact scopes changed: no
- facade callable names changed: no
- `MoveWindow` execution moved: no

tests:

- `.\.venv\Scripts\python.exe -m py_compile apps\wechat_ai_customer_service\adapters\wechat_win32_ocr_sidecar.py apps\wechat_ai_customer_service\adapters\wechat_win32_ocr\window_action_planning.py apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_window_action_planning_checks.py` -> passed.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_window_action_planning_checks.py` -> passed, 9 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_compat_checks.py` -> passed, 135 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_add_friend_package_smoke.py` -> passed, 34 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_customer_service_multi_session_scheduler_checks.py` -> passed, 123 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_windowing_checks.py` -> passed, 4 checks.
- `.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_workflow_logic_checks.py` -> timed out twice without failure output.
- `.\.venv\Scripts\python.exe -X faulthandler -c "import faulthandler, runpy; faulthandler.dump_traceback_later(30, exit=True); runpy.run_path(r'apps\wechat_ai_customer_service\tests\run_workflow_logic_checks.py', run_name='__main__')"` -> exited with faulthandler stack showing real LLM HTTPS wait in `check_customer_service_console_switches_take_effect`.

manual/live test:

- not run; this stage only moved pure window normalization planning.

rollback:

- restore sidecar inline window-size/origin calculation and leave `window_action_planning.py` unused for review.
