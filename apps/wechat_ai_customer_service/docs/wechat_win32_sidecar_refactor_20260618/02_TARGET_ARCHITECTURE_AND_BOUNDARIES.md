# Target Architecture And Boundaries

> Customer-visible reply ownership baseline: [../customer_visible_reply_ownership_baseline.md](../customer_visible_reply_ownership_baseline.md)

本文定义第五点拆分后的目标形态。后续代码实现不必一次性达到最终形态，但每一步都要朝这个方向移动。

## 总体设计

保留现有入口文件：

```text
apps/wechat_ai_customer_service/adapters/wechat_win32_ocr_sidecar.py
```

它继续作为稳定 facade：

- 保持 CLI 可直接运行。
- 保持 `SIDECAR_ACTION_CHOICES`。
- 保持 stdout JSON。
- 保持当前可被测试直接 import 的 public 函数兼容。
- 逐步把内部实现委托给新模块。

目标内部结构建议：

```text
apps/wechat_ai_customer_service/adapters/wechat_win32_ocr/
  __init__.py
  cli.py
  contracts.py
  env_config.py
  text_normalization.py
  windowing.py
  geometry.py
  capture.py
  ocr_engine.py
  session_parser.py
  message_parser.py
  target_switching.py
  input_methods.py
  send_flow.py
  ui_action_guard.py
  render_recovery.py
  device_profile.py
  add_friend_windows.py
```

说明：

- 这是拟新增包，不是重命名 `wechat_win32_ocr_sidecar.py`。
- 新包名称可在落代码前再确认，但不要改外部 sidecar 文件路径。
- facade 可以从这些模块 import 函数并 re-export。
- 新模块不能 import facade，避免循环依赖。

## 依赖方向

允许：

```text
wechat_win32_ocr_sidecar.py
  -> wechat_win32_ocr.*
  -> add_friend_*
  -> wechat_message_envelope
```

允许：

```text
add_friend_flow.py
  -> AddFriendOpsProtocol
  -> sidecar facade passed as ops object
```

禁止：

```text
wechat_win32_ocr.*
  -> import wechat_win32_ocr_sidecar.py
```

禁止：

```text
send/session/add_friend low-level module
  -> customer_service_brain
  -> reply authoring modules
```

sidecar 属于代码机制层，只能负责：

- OCR/RPA 捕获。
- 会话定位。
- 发送目标确认。
- 输入/点击/风控。
- 诊断产物。

它不能生成、替换或拼接客户可见回复。

## 模块边界

### `cli.py`

职责：

- 构造 argparse parser。
- 把 CLI args 转成 action request。
- 调用 action router。

不负责：

- Win32 窗口操作。
- OCR。
- add_friend 业务步骤。

迁移方式：

- 先复制 parser 构建逻辑到新模块。
- `wechat_win32_ocr_sidecar.py main()` 继续存在，只调用 `cli.main()`.
- 初期可保留旧 `main()` 为 wrapper，测试通过后再瘦身。

### `env_config.py`

职责：

- `env_int`
- `env_float`
- `env_flag`
- humanized input 默认值读取。

不负责：

- 业务流程。
- 点击和 OCR。

迁移方式：

- 先提取纯读取函数。
- 保留 sidecar 同名 wrapper。

### `text_normalization.py`

职责：

- `normalize_ocr_text`
- `normalize_session_name`
- `strip_chat_unread_suffix`
- `normalize_chat_title_for_match`
- `canonical_session_name`
- `normalize_message_content`
- add_friend OCR text helpers 中已经独立的部分继续留在 `add_friend_ocr.py`。

不负责：

- OCR 调用。
- 窗口坐标。

### `windowing.py`

职责：

- Win32 imports 和 pywin32 可用性状态。
- `probe_wechat_windows`
- `select_primary_visible_main_window`
- `ensure_visible_wechat_window`
- `restore_wechat_window`
- `focus_wechat_window`
- `activate_window`
- `configure_dpi_awareness`
- `normalize_wechat_window`
- `get_window_geometry`
- `get_window_client_geometry`

不负责：

- 业务 action。
- add_friend 表单填写。
- 发送内容。

风险：

- 高耦合 pywin32/ctypes，迁移时必须保持脚本直跑可用。

### `geometry.py`

职责：

- 坐标换算。
- search box、session row、input area、send button 等 geometry 函数。
- `calculate_send_points`
- `input_click_candidate_points`
- `send_click_candidate_points`
- jitter point helpers。

不负责：

- 点击。
- OCR。

长期目标：

每个 locator 结果返回：

```json
{
  "point": [302, 70],
  "confidence": 0.86,
  "strategy": "search_box_anchor",
  "evidence": ["geometry", "ocr_readback"],
  "fallback_used": false
}
```

### `capture.py`

职责：

- ImageGrab / PrintWindow / visible rect 截图。
- 截图保存。
- image score。
- coordinate metadata。

不负责：

- OCR 文本解释。
- 点击。

### `ocr_engine.py`

职责：

- RapidOCR 初始化。
- `run_ocr`
- OCR item 标准形态。

不负责：

- 会话解析。
- 消息解析。

### `session_parser.py`

职责：

- `parse_sessions_from_ocr`
- unread badge 视觉信号。
- session key/fingerprint。
- sidebar preview/time。

不负责：

- 切换会话。
- 点击会话。

### `message_parser.py`

职责：

- `parse_messages_from_ocr`
- `classify_message_side`
- `is_message_noise`
- message envelope 输入材料。

不负责：

- 生成回复。
- 调用 Brain。

### `target_switching.py`

职责：

- `open_chat`
- `ensure_target_ready_for_send`
- active target validation。
- session row click candidates。

不负责：

- 文本输入。
- send trigger。

### `input_methods.py`

职责：

- clipboard copy/read。
- SendInput Unicode。
- UIA set value。
- paste/type/clear draft。
- humanized chunking。

不负责：

- 目标会话选择。
- send button 点击。

### `send_flow.py`

职责：

- `send_payload`
- input confirmation。
- send trigger。
- pre/post target guard。
- rate guard。

不负责：

- 生成待发送文本。

### `ui_action_guard.py`

职责：

- UI action pacing。
- near-point repeat guard。
- action budget。
- audit jsonl。

不负责：

- 业务结果判断。

### `render_recovery.py`

职责：

- blank render detection。
- render recovery reservation。
- tray redraw。
- quick login helpers。

不负责：

- 消息或 add_friend 业务。

### `device_profile.py`

职责：

- 记录 OS、窗口、DPI、显示器、截图尺寸、layout family。
- profile diff。
- profile invalidation。

初期只做文档和只读输出，不改变现有动作。

### `add_friend_windows.py`

职责：

- add_friend 的 Windows 具体定位、等待、点击、表单填写。
- `AddFriendOpsProtocol` 所需 ops 的 Windows 实现。

不负责：

- route 命名。
- JSON payload contract。
- artifact scope mapping。

这些继续留给现有 add_friend modules：

```text
add_friend_contract.py
add_friend_routes.py
add_friend_artifacts.py
add_friend_payloads.py
add_friend_result_mapping.py
add_friend_flow.py
```

## Facade 兼容策略

拆分过程中，旧测试可能继续这样 import：

```python
from apps.wechat_ai_customer_service.adapters.wechat_win32_ocr_sidecar import parse_sessions_from_ocr
```

因此每个迁移函数必须保留 facade 同名符号。

允许做法：

```python
from apps.wechat_ai_customer_service.adapters.wechat_win32_ocr.session_parser import parse_sessions_from_ocr
```

或者：

```python
def parse_sessions_from_ocr(*args, **kwargs):
    return session_parser.parse_sessions_from_ocr(*args, **kwargs)
```

不允许：

- 删除 facade 同名函数而不改测试。
- 改函数参数含义。
- 让 facade 导入新模块时触发 Win32 side effects。

## Public Contract 与 Internal Implementation 分层

Public contract：

```text
CLI action names
CLI flags
stdout JSON
result_code/error_code/current_step
artifact directory contract
WeChatConnector method behavior
tests importing sidecar symbols
```

Internal implementation：

```text
具体 locator 算法
OCR region selection
candidate sorting
helper module layout
diagnostic metadata enrichment
```

拆分只应改变 internal implementation 的组织方式，不应改变 public contract。

## 成功形态

短期成功：

- sidecar 文件明显变薄。
- 纯函数、解析函数、geometry 函数分到新模块。
- 所有现有 smoke 通过。
- facade import 兼容。

中期成功：

- send/session/add_friend 三条高风险链路都有清晰模块边界。
- 每条链路都有独立契约测试。
- 每个 live 失败包能落出 device/layout/profile 证据。

长期成功：

- 新客户机器先 profile/calibration，再执行高风险动作。
- 不同分辨率和 DPI 通过 profile/locator 适配，而不是硬补坐标。
- 未来 macOS adapter 可以实现同一上层 connector/action contract，不污染 Windows 实现。
