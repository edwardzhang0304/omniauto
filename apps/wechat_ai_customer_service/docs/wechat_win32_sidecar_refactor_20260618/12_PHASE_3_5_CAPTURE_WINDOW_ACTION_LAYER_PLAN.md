# Phase 3.5 Capture Window Action Layer Plan

> Customer-visible reply ownership baseline: [../customer_visible_reply_ownership_baseline.md](../customer_visible_reply_ownership_baseline.md)

本文是 Phase 3 继续迁移前的细化方案。它专门约束 `capture_*`、窗口枚举/聚焦/归一化、DPI、OCR 初始化这些高风险边界，避免后续开发者按粗粒度步骤直接搬真实截图和真实窗口动作。

## 当前状态

已经完成：

- `geometry.py`：坐标、窗口尺寸 guard、send/input 点位等纯函数。
- `text_normalization.py`：OCR 文本、会话名、聊天标题、消息内容归一化。
- `env_config.py`：环境变量读取和 pacing 配置。
- `humanized_input.py`：人类化输入的纯配置、分片、延迟和 typo 计算。
- `device_profile.py`：设备 profile 结构拼装和 summary/change detection。
- `windowing.py`：窗口标题、主窗口识别、标题打分等纯 metadata helper。
- `render_diagnostics.py`：blank render、image score、foreign overlay 判定。
- `ocr_engine.py`：OCR row normalization 和 fake-engine friendly runner。

仍在 `wechat_win32_ocr_sidecar.py` 中的高风险能力：

```text
get_window_geometry
get_window_client_geometry
window_dpi_scale
probe_wechat_windows
select_primary_visible_main_window
window_content_health_score
ensure_visible_wechat_window
restore_wechat_window
focus_wechat_window
activate_window
normalize_wechat_window
capture_wechat
capture_wechat_visible_rect
capture_visible_screen
capture_wechat_window_visible_screen
capture_window_image
capture_window_by_rect
try_image_grab
run_ocr RapidOCR import/cache facade
```

## 风险分层

### A. 只读窗口信息

候选函数：

```text
get_window_geometry
get_window_client_geometry
window_dpi_scale
probe_wechat_windows
select_primary_visible_main_window
window_content_health_score
```

风险：

- `probe_wechat_windows` 依赖 `ctypes.windll.user32/kernel32` 和 WeChat 进程路径。
- `select_primary_visible_main_window` 会在多窗口时调用 `capture_wechat` + `run_ocr` 做内容探针。
- 单元测试会 monkeypatch sidecar facade 上的 `capture_wechat`、`run_ocr`、`select_primary_visible_main_window`，不能让迁移后 monkeypatch 失效。

迁移原则：

- 先迁移无截图、无窗口动作的 read-only geometry/DPI helper。
- `select_primary_visible_main_window` 在迁移前必须设计 dependency injection，默认依赖 sidecar facade wrapper，而不是在新模块里直接绑定新模块函数。
- 保持 sidecar 同名函数存在，测试和外部 import 不变。

### B. 截图和 OCR 执行

候选函数：

```text
capture_wechat
capture_wechat_visible_rect
capture_visible_screen
capture_wechat_window_visible_screen
capture_window_image
capture_window_by_rect
try_image_grab
run_ocr
```

风险：

- `capture_window_image` 使用 `PrintWindow`、Win32 DC、bitmap 释放，资源清理必须原样保持。
- `capture_window_by_rect` 会按 DPI 尝试多个 bbox，fallback 顺序影响 1920x1080、1920x1200、缩放显示器下的截图命中。
- `capture_wechat` 的 fallback 错误语义必须保持：`capture_wechat_failed: no screenshot candidate is available`。
- `capture_wechat_visible_rect` 的错误语义必须保持：`capture_wechat_visible_rect_failed: no screenshot candidate is available`。
- `capture_wechat_window_visible_screen` 的错误语义必须保持：`capture_wechat_window_visible_screen_failed`。
- `run_ocr` 的 `rapidocr_onnxruntime_unavailable: ...` 错误语义必须保持。

迁移原则：

- 先把截图保存、截图候选选择、bbox 生成等可注入依赖的逻辑拆成纯/准纯函数。
- 再迁移 `try_image_grab`，用 `image_grabber` 注入测试，不在 import 时触发屏幕访问。
- 最后才迁移 `capture_window_image`，并保留 DC/bitmap finally 清理对照测试。
- RapidOCR 初始化暂缓整体迁移；当前 sidecar 保留 `_OCR_ENGINE` 缓存是为了维持 monkeypatch 兼容。

### C. 真实窗口动作

候选函数：

```text
ensure_visible_wechat_window
restore_wechat_window
focus_wechat_window
activate_window
normalize_wechat_window
```

风险：

- 会调用 `ShowWindow`、`SetForegroundWindow`、`MoveWindow` 或线程输入附着。
- 会影响用户当前窗口焦点和微信窗口大小。
- 过度重复聚焦、机械重复点击、鼠标键盘不合理节奏都属于高危 RPA 行为。

迁移原则：

- 迁移前先把动作层分成 planning 和 execution。
- planning 可以先进入新模块，例如计算 normalize 目标窗口大小和位置。
- execution 保留在 sidecar facade，直到有 focused test 和只读/手动实盘验收。
- 保持 `humanized_action_sleep`、debounce、foreground guard 语义不变。

## 推荐拆分顺序

### Phase 3.5a: window metrics read-only helper

目标：

- 新增 `window_metrics.py`。
- 迁移 `get_window_geometry`、`get_window_client_geometry`、`window_dpi_scale` 的实现。
- sidecar 保留同名 wrapper，并把当前 `win32gui` / `ctypes.windll.user32` 作为依赖传入。

测试：

- 新增 fake win32gui/user32 的 focused test。
- `run_wechat_win32_ocr_compat_checks.py` 必须继续通过。
- `run_add_friend_package_smoke.py` 必须继续通过。

停止条件：

- 新模块 import 需要真实 Windows GUI。
- `normalize_wechat_window` 相关 compat 测试失败。
- sidecar facade 同名函数消失或签名改变。

### Phase 3.5b: capture rect planning helper

目标：

- 新增 `capture.py`，先只放 bbox planning 和 candidate selection。
- 迁移 `window_dpi_scale` 的使用点时仍通过 sidecar wrapper 注入。
- 不移动 `PrintWindow` 资源管理。

测试：

- fake rect + fake image score，确认 fallback 顺序不变。
- blank/foreign overlay 相关 compat 保持通过。

停止条件：

- `capture_wechat` 错误字符串变化。
- DPI scale > 1.05 时候选 rect 数量或顺序变化但没有测试覆盖。

### Phase 3.5c: capture execution wrapper

目标：

- 迁移 `try_image_grab` 和 `capture_window_by_rect` 到 `capture.py`。
- 通过 `image_grabber`、`rect_provider`、`dpi_scale_provider` 注入 fake 依赖。
- sidecar wrapper 继续暴露旧函数名。

测试：

- fake ImageGrab 抛错返回 `None`。
- 小尺寸 rect 返回 `None`。
- DPI fallback rect 生成和候选选择保持不变。

停止条件：

- 新模块 import 时访问真实屏幕。
- 真实截图错误被吞成不同错误语义。

### Phase 3.5d: PrintWindow execution wrapper

目标：

- 迁移 `capture_window_image`。
- 保持 `GetWindowDC`、`CreateCompatibleDC`、`CreateBitmap`、`PrintWindow`、`DeleteObject`、`ReleaseDC` 的 finally 清理。

测试：

- fake win32gui/win32ui/user32 计数资源释放。
- PrintWindow full content 失败后 classic fallback 仍执行。
- 任一 DC/bitmap 异常时返回 `None` 并释放已创建资源。

停止条件：

- 无法用 fake module 覆盖资源清理路径。
- 代码为了好测而改变 fallback 顺序。

#### Phase 3.5d 落代码前测试设计

迁移 `capture_window_image` 前必须先在 `run_wechat_win32_ocr_capture_checks.py` 里补 fake resource test。最小 fake 对象：

```text
FakeWin32Gui:
  GetWindowRect
  GetWindowDC
  DeleteObject
  ReleaseDC

FakeWin32Ui:
  CreateDCFromHandle
  CreateBitmap

FakeSrcDC:
  CreateCompatibleDC
  DeleteDC

FakeMemDC:
  SelectObject
  GetSafeHdc
  DeleteDC

FakeBitmap:
  CreateCompatibleBitmap
  GetInfo
  GetBitmapBits
  GetHandle

FakeUser32:
  PrintWindow

FakeImage:
  frombuffer hook or injected image_factory
```

必须覆盖：

- `PrintWindow(hwnd, hdc, 0x2)` 成功时，不调用 classic `PrintWindow(..., 0)`。
- full content 失败但 classic 成功时，调用顺序为 `[0x2, 0]`。
- 两次 `PrintWindow` 都失败时返回 `None`，并释放 bitmap/mem_dc/src_dc/hwnd_dc。
- `CreateCompatibleBitmap` 或 `GetBitmapBits` 抛错时返回 `None`，并释放已经创建的资源。
- `GetWindowDC` 返回空值时返回 `None`，不得创建 DC/bitmap。
- 窗口宽高小于等于 2 时直接返回 `None`，不得获取 DC。

迁移时允许给 `capture.capture_window_image()` 传入这些依赖：

```python
capture_window_image(
    hwnd,
    win32gui_module=...,
    win32ui_module=...,
    user32=...,
    image_factory=...,
)
```

sidecar wrapper 仍必须保持：

```python
def capture_window_image(hwnd: int) -> Any | None:
    ...
```

不允许：

- 在 `capture.py` import 时访问真实 Win32 DC 或屏幕。
- 为了测试方便移除 finally 清理。
- 改变 `PrintWindow` fallback 顺序。
- 改变失败返回 `None` 的语义。

### Phase 3.5e: OCR runner cache migration

目标：

- 把 sidecar 的 `_OCR_ENGINE` 缓存迁入 `ocr_engine.py`。
- sidecar `run_ocr` wrapper 保持同名、同错误语义。

测试：

- fake RapidOCR 只初始化一次。
- RapidOCR import 缺失错误仍为 `rapidocr_onnxruntime_unavailable: ...`。
- row normalization 与 Phase 3.4 测试保持一致。

停止条件：

- 现有 monkeypatch `sidecar_mod._OCR_ENGINE` 或 `sidecar_mod.RapidOCR` 兼容无法保持。
- 需要修改大量测试才能通过。

### Phase 3.5f: window action planning

目标：

- 把 `normalize_wechat_window` 中目标宽高、推荐尺寸、固定 origin、屏幕 clamp 的计算提成 pure planner。
- `MoveWindow` 仍留在 sidecar 或 action executor wrapper。

测试：

- 1920x1080、1920x1200、小屏、offscreen、custom env 均有 planner 测试。
- 旧 compat 中 `test_normalize_wechat_window_clamps_offscreen_when_size_is_already_safe` 保持通过。

停止条件：

- 默认窗口尺寸策略变化。
- `WECHAT_WIN32_OCR_WINDOW_*` 环境变量语义变化。

## Monkeypatch 兼容要求

以下名字当前测试会直接 patch sidecar facade，迁移后必须继续生效：

```text
capture_wechat
capture_wechat_window_visible_screen
run_ocr
select_primary_visible_main_window
normalize_wechat_window
```

因此新模块内部不得在 import 时永久绑定这些 sidecar 函数。需要调用时使用 wrapper 传入或 dependency object，例如：

```python
select_primary_visible_main_window(
    probe,
    geometry_provider=lambda hwnd: get_window_geometry(hwnd),
    capture_provider=lambda hwnd: capture_wechat(hwnd, artifact_dir=None, label="window_select_probe"),
    ocr_provider=run_ocr,
)
```

sidecar facade 负责把当前 wrapper 传进去。这样测试 patch sidecar facade 后，调用链仍命中新 patch。

## 只读实盘验收

迁移到截图/窗口动作前，只允许做只读验收：

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\adapters\wechat_win32_ocr_sidecar.py status --artifact-dir runtime/sidecar_phase3_5_status_probe
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\adapters\wechat_win32_ocr_sidecar.py capabilities --artifact-dir runtime/sidecar_phase3_5_capabilities_probe
```

不允许：

- 真实发送。
- 真实加好友。
- 为了验证截图而重复机械点击。
- 在用户正在手动操控鼠标键盘时测试。

## 回滚策略

每个子阶段都要能单独回滚：

1. sidecar wrapper 恢复旧 inline 实现。
2. 新模块保留但不接入。
3. 新 focused test 如发现假设错误，修测试假设，不放宽公共契约。
4. 不回滚用户或其他主题的本地改动。

## 本章完成条件

- 本文档加入索引。
- Phase 3 指南明确要求迁移动作层前先读本文。
- 测试计划包含 Phase 3.5 分层测试命令。
- 后续代码章节只能从 Phase 3.5a 开始，不得直接迁移真实截图或真实窗口动作。
