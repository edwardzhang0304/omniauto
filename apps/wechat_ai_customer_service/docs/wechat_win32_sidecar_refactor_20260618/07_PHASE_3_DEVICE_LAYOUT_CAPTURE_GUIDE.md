# Phase 3 Device Layout Capture Guide

> Customer-visible reply ownership baseline: [../customer_visible_reply_ownership_baseline.md](../customer_visible_reply_ownership_baseline.md)

Phase 3 处理中风险区域：窗口、DPI、截图、OCR、布局和设备 profile。目标是让“不同分辨率客户电脑如何适配”有清晰代码边界，但本阶段仍尽量不改变动作行为。

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

测试重点：

- 无真实微信时 import 不失败。
- `capture_wechat_window_visible_screen` 签名不变。

### Step 3.3 提取 OCR engine

把 RapidOCR 初始化移到 `ocr_engine.py`。

测试重点：

- OCR 不可用时错误结构不变。
- `run_ocr` 返回 item 字段不变。

### Step 3.4 提取 windowing

把 pywin32 window helpers 移到 `windowing.py`。

风险最高，需要小步：

1. 先移动 `is_wechat_main_window`、title normalization 等纯函数。
2. 再移动 `probe_wechat_windows`。
3. 最后移动 `activate_window`、`normalize_wechat_window`。

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
