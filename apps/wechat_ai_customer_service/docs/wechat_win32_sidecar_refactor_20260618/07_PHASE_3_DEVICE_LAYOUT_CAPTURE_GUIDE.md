# Phase 3 Device Layout Capture Guide

> Customer-visible reply ownership baseline: [../customer_visible_reply_ownership_baseline.md](../customer_visible_reply_ownership_baseline.md)

Phase 3 处理中风险区域：窗口、DPI、截图、OCR、布局和设备 profile。目标是让“不同分辨率客户电脑如何适配”有清晰代码边界，但本阶段仍尽量不改变动作行为。

迁移 `capture_*`、`activate_window`、`normalize_wechat_window`、`run_ocr` 执行层前，必须先阅读并按 [12_PHASE_3_5_CAPTURE_WINDOW_ACTION_LAYER_PLAN.md](12_PHASE_3_5_CAPTURE_WINDOW_ACTION_LAYER_PLAN.md) 执行。本文早期的 Step 3.2/3.3/3.4 是粗粒度方向，不应被理解为可以直接搬真实截图或真实窗口动作。

## 目标

新增或准备以下模块：

```text
apps/wechat_ai_customer_service/adapters/wechat_win32_ocr/windowing.py
apps/wechat_ai_customer_service/adapters/wechat_win32_ocr/capture.py
apps/wechat_ai_customer_service/adapters/wechat_win32_ocr/ocr_engine.py
apps/wechat_ai_customer_service/adapters/wechat_win32_ocr/device_profile.py
```

最终让 sidecar 只作为 facade 调用这些能力。

## 设备 profile 思路

每次重要 action 可输出只读 profile：

```json
{
  "platform": "windows",
  "adapter": "win32_ocr",
  "window": {"left": 0, "top": 0, "width": 981, "height": 860},
  "client": {"width": 981, "height": 860},
  "dpi": {"scale": 1.0},
  "capture": {"width": 981, "height": 860},
  "layout_family": "windows_wechat_sidebar_search_v1",
  "profile_version": "wechat_win32_ocr_profile.v1"
}
```

第一阶段只写诊断，不改变执行分支。

## 可提取对象

### windowing

候选：

```text
get_window_geometry
get_window_client_geometry
window_dpi_scale
probe_wechat_windows
select_primary_visible_main_window
window_content_health_score
ensure_visible_wechat_window
wechat_main_window_is_tray_hidden
probe_has_usable_visible_main_window
restore_wechat_window
focus_wechat_window
activate_window
configure_dpi_awareness
ensure_left_button_released
is_wechat_main_window
wechat_window_title_score
normalize_wechat_title
normalize_wechat_window
```

### capture

候选：

```text
capture_wechat
capture_wechat_visible_rect
capture_visible_screen
capture_wechat_window_visible_screen
capture_window_image
capture_window_by_rect
try_image_grab
image_information_score
likely_foreign_overlay_capture
```

### ocr_engine

候选：

```text
run_ocr
OCR_MIN_CONFIDENCE
_OCR_ENGINE
RapidOCR import wrapper
```

注意：

- 新模块 import 失败不能让整个仓库测试失败。
- RapidOCR 缺失时仍要允许纯测试 import。

### render/profile

候选：

```text
detect_blank_render
sidecar_payload_snapshot
sidecar_payload_is_blank_render
sidecar_payload_needs_render_recovery
reserve_render_recovery
trigger_wechat_tray_redraw
recover_blank_render_payload
quick_login_like
ensure_quick_login_if_available
```

## 不允许做

- 不改变 normalize window 默认策略。
- 不默认强制调整用户窗口大小。
- 不把 profile 写入 Git 跟踪路径。
- 不在失败时自动重复点击。
- 不把 DPI/profile 逻辑用于改变现有点位，除非单独立优化阶段。

## 实施步骤

### Step 3.1 先提取只读 profile builder

新增 `device_profile.py`：

```text
build_device_profile(window_geometry, client_geometry, screenshot_size, dpi_scale, probe)
profile_changed(old, new)
profile_summary(profile)
```

只在 payload diagnostics 中附加，不影响逻辑。

### Step 3.2 提取 capture

把截图函数迁到 `capture.py`，sidecar re-export。

注意：这是长期方向。真实迁移必须按 Phase 3.5 细化方案分为 bbox planning、ImageGrab wrapper、PrintWindow wrapper 三批执行，不能一次性搬完整 `capture_*` 链路。

测试重点：

- 无真实微信时 import 不失败。
- `capture_wechat_window_visible_screen` 签名不变。

### Step 3.3 提取 OCR engine

把 RapidOCR 初始化移到 `ocr_engine.py`。

注意：Phase 3.4 只迁移了 OCR row normalization；RapidOCR 初始化和 `_OCR_ENGINE` 缓存仍暂留 sidecar。整体迁移必须先确认 monkeypatch 兼容。

测试重点：

- OCR 不可用时错误结构不变。
- `run_ocr` 返回 item 字段不变。

### Step 3.4 提取 windowing

把 pywin32 window helpers 移到 `windowing.py`。

风险最高，需要小步：

1. 先移动 `is_wechat_main_window`、title normalization 等纯函数。
2. 再移动 `probe_wechat_windows`。
3. 最后移动 `activate_window`、`normalize_wechat_window`。

注意：`activate_window`、`normalize_wechat_window` 属于真实窗口动作，不与只读 window metrics 放在同一章提交。

## 测试命令

```powershell
.\.venv\Scripts\python.exe -m py_compile apps\wechat_ai_customer_service\adapters\wechat_win32_ocr_sidecar.py
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_compat_checks.py
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_add_friend_package_smoke.py
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_customer_service_multi_session_scheduler_checks.py
```

如果改到 startup/capabilities：

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_cloud_auth_required_checks.py
```

## 可选实盘验收

只读验收：

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\adapters\wechat_win32_ocr_sidecar.py status --artifact-dir runtime/sidecar_phase3_status_probe
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\adapters\wechat_win32_ocr_sidecar.py capabilities --artifact-dir runtime/sidecar_phase3_capabilities_probe
```

不发送消息，不点击 add_friend。

## 验收标准

- `status/capabilities/sessions` 行为不变。
- profile 只作为诊断出现。
- 真实截图/OCR路径如果不可用，应返回原有错误语义。
- 不引入新的 runtime tracked 文件。

## 回滚方式

- 先恢复 `windowing.py` 委托点。
- 保留纯 profile 模块也可以。
- 如果 pywin32 import 顺序出问题，恢复 sidecar 直接 imports。

## 执行记录 2026-06-19

Phase 3.1 已完成低风险只读诊断层拆分：

新增：

```text
apps/wechat_ai_customer_service/adapters/wechat_win32_ocr/device_profile.py
apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_device_profile_checks.py
```

调整：

- `validate_capture_geometry` 已迁入 `geometry.py`，sidecar 保留同名 wrapper。
- `add_friend_device_profile` 仍留在 sidecar 采集 Win32/DPI/显示器信息，但最终结构由 `device_profile.build_device_profile()` 组装。

未做：

- 未移动 `get_window_geometry`、`get_window_client_geometry`、`window_dpi_scale`。
- 未移动截图、OCR、窗口激活、窗口归一化、鼠标点击函数。
- 未改变 profile 输出字段或 add_friend 执行分支。
- 未做真实微信只读/实盘探针。

验证：

- `run_wechat_win32_ocr_device_profile_checks.py` 通过，覆盖 profile builder/summary/change detection 和 capture geometry guard 对照。
- `run_wechat_win32_ocr_compat_checks.py` 通过 135 项。
- `run_add_friend_package_smoke.py` 通过 34 项。
- `run_customer_service_multi_session_scheduler_checks.py` 通过 123 项。
- `run_workflow_logic_checks.py` 通过 114 项。

## 执行记录 2026-06-19 Phase 3.5f

已完成 `normalize_wechat_window` planning 层保守迁移：

调整：

- 新增 `window_action_planning.py`，只计算窗口归一化目标，不访问真实 Win32 GUI。
- sidecar `normalize_wechat_window(hwnd)` 保留同名 facade，并继续负责真实 `MoveWindow`、sleep、after/applied 判定。
- 新增 focused test 覆盖 1920x1200、1920x1080、小屏、非固定 origin、custom origin、缺失屏幕 metrics。

边界：

- 未移动 `win32gui.MoveWindow`。
- 未移动 `activate_window`、`focus_wechat_window` 或 `ensure_visible_wechat_window`。
- `WECHAT_WIN32_OCR_WINDOW_*` 环境变量语义保持。
- 默认安全窗口仍为 980x860；offscreen same-size 窗口仍会被移动回屏幕内。

验证：

- `run_wechat_win32_ocr_window_action_planning_checks.py` 通过 9 项。
- `run_wechat_win32_ocr_compat_checks.py` 通过 135 项。
- `run_add_friend_package_smoke.py` 通过 34 项。
- `run_customer_service_multi_session_scheduler_checks.py` 通过 123 项。
- `run_wechat_win32_ocr_windowing_checks.py` 通过 4 项。
- `run_workflow_logic_checks.py` 本轮在 `check_customer_service_console_switches_take_effect` 触发真实 LLM HTTPS 请求后超时；与本阶段窗口规划代码无直接路径关系，已用 faulthandler 定位并记录为环境性 runner 问题。

## 执行记录 2026-06-19 Phase 3.5g

已完成窗口动作状态判定小步抽取：

调整：

- 新增 `window_action_state.py`，集中 `FOREGROUND_READY_REASONS`、`foreground_guard_ready`、tray-hidden 判定。
- sidecar `focus_wechat_window`、`activate_window`、`wechat_main_window_is_tray_hidden` 改为调用纯状态 helper。
- 保留所有真实窗口动作在 sidecar 内，包括 `ShowWindow`、`SetForegroundWindow`、`AttachThreadInput`、ALT fallback、click fallback。

边界：

- 未移动真实聚焦/恢复执行层。
- 未改变 `foreground_matches_target` / `foreground_root_matches_target` ready 语义。
- 未把 `foreground_guard_unavailable` 或 `foreground_unknown_guard_degraded` 误当作已确认聚焦。

验证：

- `run_wechat_win32_ocr_window_action_state_checks.py` 通过 4 项。
- `run_wechat_win32_ocr_compat_checks.py` 通过 135 项。
- `run_add_friend_package_smoke.py` 通过 34 项。
- `run_customer_service_multi_session_scheduler_checks.py` 通过 123 项。
- `run_wechat_win32_ocr_window_action_planning_checks.py` 通过 9 项。

## 执行记录 2026-06-19 Phase 3.2

已完成 windowing 纯 metadata helper 小步拆分：

新增：

```text
apps/wechat_ai_customer_service/adapters/wechat_win32_ocr/windowing.py
apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_windowing_checks.py
```

已迁入：

- `normalize_wechat_title`
- `is_wechat_main_window`
- `wechat_window_title_score`

边界：

- 只处理窗口枚举结果中的 `title` / `class_name` 字段。
- 未移动 `probe_wechat_windows`、`select_primary_visible_main_window`、`restore_wechat_window`、`focus_wechat_window`、`activate_window`。
- 未改变窗口选择排序和真实窗口动作行为。

验证：

- `run_wechat_win32_ocr_windowing_checks.py` 通过 4 项。
- `run_wechat_win32_ocr_device_profile_checks.py` 通过 4 项。
- `run_wechat_win32_ocr_compat_checks.py` 通过 135 项。
- `run_add_friend_package_smoke.py` 通过 34 项。
- `run_customer_service_multi_session_scheduler_checks.py` 通过 123 项。
- `run_workflow_logic_checks.py` 通过 114 项。

## 执行记录 2026-06-19 Phase 3.3

已完成 render/capture diagnostics 小步拆分：

新增：

```text
apps/wechat_ai_customer_service/adapters/wechat_win32_ocr/render_diagnostics.py
apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_render_diagnostics_checks.py
```

已迁入：

- `detect_blank_render`
- `image_information_score`
- `likely_foreign_overlay_capture`

边界：

- 只处理已有截图对象和 OCR item 列表。
- 未移动 `capture_wechat`、`capture_window_image`、`capture_window_by_rect`、`try_image_grab`。
- 未移动 `run_ocr` 或 RapidOCR 初始化。
- 未改变 blank render 阻断、foreign overlay 过滤、capabilities/status 错误语义。

验证：

- `run_wechat_win32_ocr_render_diagnostics_checks.py` 通过 4 项。
- `run_wechat_win32_ocr_windowing_checks.py` 通过 4 项。
- `run_wechat_win32_ocr_device_profile_checks.py` 通过 4 项。
- `run_wechat_win32_ocr_compat_checks.py` 通过 135 项。
- `run_add_friend_package_smoke.py` 通过 34 项。
- `run_customer_service_multi_session_scheduler_checks.py` 通过 123 项。
- `run_workflow_logic_checks.py` 通过 114 项。

下一步注意：

- 继续 Phase 3 若要移动 `capture_*` 或 `run_ocr`，必须先单独形成更细方案，因为它们涉及真实截图、文件保存、OCR 引擎初始化和 pywin32/PIL 外部依赖。

## 执行记录 2026-06-19 Phase 3.4

已完成 OCR engine 小步拆分：

新增：

```text
apps/wechat_ai_customer_service/adapters/wechat_win32_ocr/ocr_engine.py
apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_ocr_engine_checks.py
```

已迁入：

- OCR row 标准化：text 清洗、confidence 过滤、bbox/center 字段生成、排序、foreign overlay 过滤。
- `OcrEngineRunner` / `create_ocr_runner`：用于后续把 RapidOCR 初始化从 sidecar 移出。

边界：

- sidecar 仍保留 `RapidOCR` import、`_OCR_ENGINE` 缓存和 `run_ocr` facade。
- 本阶段 `run_ocr` 只把 RapidOCR 原始结果委托给 `ocr_engine.normalize_ocr_rows()`。
- 未移动截图函数，不改变 `rapidocr_onnxruntime_unavailable` 错误语义。
- 未做真实 OCR 或真实微信截图实盘。

验证：

- `run_wechat_win32_ocr_ocr_engine_checks.py` 通过 5 项，覆盖 fake engine、row normalization、engine cache、unavailable error、foreign overlay 过滤。
- `run_wechat_win32_ocr_render_diagnostics_checks.py` 通过 4 项。
- `run_wechat_win32_ocr_compat_checks.py` 通过 135 项。
- `run_add_friend_package_smoke.py` 通过 34 项。
- `run_customer_service_multi_session_scheduler_checks.py` 通过 123 项。
- `run_workflow_logic_checks.py` 通过 114 项。

## 执行记录 2026-06-19 Phase 3.5 文档准备

新增：

```text
apps/wechat_ai_customer_service/docs/wechat_win32_sidecar_refactor_20260618/12_PHASE_3_5_CAPTURE_WINDOW_ACTION_LAYER_PLAN.md
```

已明确：

- `capture_*` 迁移要拆成 bbox planning、ImageGrab wrapper、PrintWindow wrapper。
- `normalize_wechat_window` 先拆 planning，再动 execution。
- `run_ocr` 的 RapidOCR cache 迁移必须保护 sidecar monkeypatch 兼容。
- 下一步代码只能从 Phase 3.5a read-only window metrics helper 开始。

边界：

- 本章只更新开发材料，不改变运行代码。
- 未移动真实截图、窗口聚焦、窗口调整或 OCR 初始化。

## 执行记录 2026-06-19 Phase 3.5a

已完成 read-only window metrics 小步拆分：

新增：

```text
apps/wechat_ai_customer_service/adapters/wechat_win32_ocr/window_metrics.py
apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_window_metrics_checks.py
```

已迁入：

- `get_window_geometry`
- `get_window_client_geometry`
- `window_dpi_scale`

边界：

- sidecar 保留同名 facade wrapper。
- 新模块只读取传入的 `win32gui` / `user32` / `windll` 依赖，不激活窗口、不移动窗口、不截图。
- 未移动 `probe_wechat_windows`、`select_primary_visible_main_window`、`capture_*`、`activate_window`、`normalize_wechat_window`。

验证：

- `run_wechat_win32_ocr_window_metrics_checks.py` 通过 6 项。
- `run_wechat_win32_ocr_compat_checks.py` 通过 135 项。
- `run_add_friend_package_smoke.py` 通过 34 项。
- `run_customer_service_multi_session_scheduler_checks.py` 通过 123 项。
- `run_workflow_logic_checks.py` 通过 114 项。

## 执行记录 2026-06-19 Phase 3.5b

已完成 capture planning 小步拆分：

新增：

```text
apps/wechat_ai_customer_service/adapters/wechat_win32_ocr/capture.py
apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_capture_checks.py
```

已迁入：

- `capture_rect_candidates`
- `collect_capture_candidates`
- `select_best_capture_candidate`

边界：

- sidecar 仍保留 `try_image_grab`、`capture_window_image`、`capture_window_by_rect`、`capture_wechat`、`capture_wechat_visible_rect`、截图保存和错误字符串。
- 本阶段只迁移 bbox 候选顺序和最高信息量候选选择。
- 未移动 `ImageGrab.grab`、`PrintWindow`、Win32 DC/bitmap 资源管理。

验证：

- `run_wechat_win32_ocr_capture_checks.py` 通过 5 项。
- `run_wechat_win32_ocr_compat_checks.py` 通过 135 项。
- `run_add_friend_package_smoke.py` 通过 34 项。
- `run_customer_service_multi_session_scheduler_checks.py` 通过 123 项。
- `run_workflow_logic_checks.py` 通过 114 项。

## 执行记录 2026-06-19 Phase 3.5c

已完成 capture execution wrapper 小步拆分：

调整：

- `capture.py` 增加 `try_image_grab` wrapper，支持注入 `image_grabber`。
- `capture.py` 增加 `capture_window_by_rect` wrapper，支持注入 rect/dpi/grabber 依赖。
- sidecar 保留同名 `try_image_grab` 和 `capture_window_by_rect` facade。

边界：

- 未移动 `capture_window_image`。
- 未移动 `PrintWindow`、Win32 DC、bitmap 创建/释放逻辑。
- 未改变 `capture_wechat_failed`、`capture_wechat_visible_rect_failed`、`capture_wechat_window_visible_screen_failed` 错误字符串。
- 未做真实截图或真实微信只读实盘。

验证：

- `run_wechat_win32_ocr_capture_checks.py` 通过 7 项。
- `run_wechat_win32_ocr_compat_checks.py` 通过 135 项。
- `run_add_friend_package_smoke.py` 通过 34 项。
- `run_customer_service_multi_session_scheduler_checks.py` 通过 123 项。
- `run_workflow_logic_checks.py` 通过 114 项。

## 执行记录 2026-06-19 Phase 3.5d 准备

已补 `capture_window_image` / `PrintWindow` 迁移前测试设计：

- 明确 fake `win32gui`、`win32ui`、`user32`、DC、bitmap 和 image factory 依赖。
- 明确 `PrintWindow` full-content -> classic fallback 顺序必须测试。
- 明确所有异常路径必须验证 bitmap/mem_dc/src_dc/hwnd_dc 已释放。
- 明确 `capture_window_image` sidecar facade 签名不变。

边界：

- 本阶段只更新文档，不迁移 `capture_window_image`。
- 未移动真实 Win32 DC、bitmap、`PrintWindow` 或 `Image.frombuffer` 执行代码。

## 执行记录 2026-06-19 Phase 3.5d 落代码

已完成 `capture_window_image` 迁移：

调整：

- `capture.py` 增加 `capture_window_image`，通过注入 `win32gui_module`、`win32ui_module`、`user32`、`image_factory` 执行。
- sidecar 保留同名 `capture_window_image(hwnd)` facade。
- `run_wechat_win32_ocr_capture_checks.py` 覆盖 `PrintWindow` full-content 成功、classic fallback、两次失败、bitmap异常、bits异常、无 DC、小窗口直接返回和资源释放。

边界：

- `PrintWindow` fallback 顺序保持 `0x2 -> 0`。
- 失败返回 `None` 语义不变。
- 未移动 `capture_wechat` 错误字符串和截图保存。
- 未做真实截图或真实微信只读实盘。

验证：

- `run_wechat_win32_ocr_capture_checks.py` 通过 13 项。
- `run_wechat_win32_ocr_compat_checks.py` 通过 135 项。
- `run_add_friend_package_smoke.py` 通过 34 项。
- `run_customer_service_multi_session_scheduler_checks.py` 通过 123 项。
- `run_workflow_logic_checks.py` 通过 114 项。

## 执行记录 2026-06-19 Phase 3.5e

已完成 OCR runner cache 保守迁移：

调整：

- `ocr_engine.py` 增加 `run_ocr_with_cache`。
- sidecar `run_ocr` 保留同名 facade，并继续持有 `RapidOCR` 与 `_OCR_ENGINE` 兼容点。
- 新测试确认 sidecar monkeypatch `RapidOCR` / `_OCR_ENGINE` 仍然生效。

边界：

- 未删除 sidecar 的 `RapidOCR` 变量。
- 未删除 sidecar 的 `_OCR_ENGINE` cache。
- `rapidocr_onnxruntime_unavailable: ...` 错误语义保持。
- OCR row normalization 仍由 `ocr_engine.normalize_ocr_rows` 负责。

验证：

- `run_wechat_win32_ocr_ocr_engine_checks.py` 通过 6 项。
- `run_wechat_win32_ocr_compat_checks.py` 通过 135 项。
- `run_add_friend_package_smoke.py` 通过 34 项。
- `run_customer_service_multi_session_scheduler_checks.py` 通过 123 项。
- `run_workflow_logic_checks.py` 通过 114 项。
