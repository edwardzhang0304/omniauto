# Phase 2 Pure Extraction Guide

> Customer-visible reply ownership baseline: [../customer_visible_reply_ownership_baseline.md](../customer_visible_reply_ownership_baseline.md)

Phase 2 是第一轮真正落代码拆分，但只允许提取低风险纯函数和常量读取，不碰真实点击、发送、窗口激活。

## 目标

把没有副作用、无需真实微信窗口、可离线测试的函数从 `wechat_win32_ocr_sidecar.py` 拆到新包中，同时保持 sidecar facade 兼容。

建议新增包：

```text
apps/wechat_ai_customer_service/adapters/wechat_win32_ocr/
  __init__.py
  env_config.py
  text_normalization.py
  geometry.py
```

## 可提取对象

### env/config 纯读取

候选：

```text
env_int
env_float
env_flag
rpa_action_pacing_enabled
strict_send_focus_guard_enabled
focus_click_fallback_enabled
allow_unknown_foreground_guard
send_input_confirm_attempt_count
normalize_humanized_input_method
normalize_send_trigger_mode
humanized_input_settings
adapt_humanized_input_settings
humanized_sleep_ms
humanized_chunk_text
typed_text_delay_ms
maybe_humanized_typo_allowed
```

注意：

- `humanized_input_settings` 读取大量 env，提取时先保持返回结构完全一致。
- 不改默认值。

### 文本归一化

候选：

```text
normalize_ocr_text
normalize_session_name
strip_chat_unread_suffix
normalize_chat_title_for_match
canonical_session_name
is_file_transfer_session_alias
normalize_message_content
quick_login_like
session_name_matches
strip_session_time_suffix
is_session_name_candidate
is_session_time_text
is_message_noise
infer_conversation_type
```

注意：

- `session_name_matches` 影响目标确认，虽然是纯函数，但属于高影响 helper。提取后必须跑多会话调度和 win32 compat。

### 几何纯函数

候选：

```text
center_of_bounds
point_in_bounds
clamp_point_to_bounds
rect_overlaps_region
relative_rect
rect_in_input_area
rect_in_input_toolbar
session_split_x
chat_header_cutoff_y
active_chat_title_cutoff_y
active_chat_title_top_cutoff_y
active_chat_title_left_x
active_chat_title_right_x
active_chat_title_top_y
active_chat_title_bottom_y
search_box_point_for_geometry
session_click_x_for_geometry
calculate_send_points
_spread_points_in_rect
input_click_candidate_points
send_click_candidate_points
bounded_int
bounded_float
```

注意：

- 只搬函数，不调参数。
- 对 leading underscore 函数，如果被 facade 测试或本文件内部引用，先保持 wrapper。

## 不允许提取对象

Phase 2 不碰：

```text
activate_window
client_click
human_screen_click
send_payload
open_chat
ensure_target_ready_for_send
parse_sessions_from_ocr
parse_messages_from_ocr
run_ocr
capture_window_image
add_friend_entry_click_plan_payload
fill_add_friend_invite_form_and_confirm
```

这些留给后续阶段。

## 实施步骤

### Step 2.1 新增包和模块

新增：

```text
apps/wechat_ai_customer_service/adapters/wechat_win32_ocr/__init__.py
apps/wechat_ai_customer_service/adapters/wechat_win32_ocr/env_config.py
apps/wechat_ai_customer_service/adapters/wechat_win32_ocr/text_normalization.py
apps/wechat_ai_customer_service/adapters/wechat_win32_ocr/geometry.py
```

不要删除 sidecar 中原函数，第一步可以先复制并测试。

### Step 2.2 facade wrapper

把 sidecar 中对应函数改成：

```python
from apps.wechat_ai_customer_service.adapters.wechat_win32_ocr.geometry import calculate_send_points
```

或：

```python
def calculate_send_points(*args, **kwargs):
    return geometry.calculate_send_points(*args, **kwargs)
```

优先 import re-export；如果有全局变量耦合，再用 wrapper。

### Step 2.3 删除重复实现

只有在测试通过后，才删除 sidecar 内重复函数体。

删除时注意：

- 不改变函数名。
- 不改变 import 位置导致 pywin32 在纯测试环境强依赖。
- 不把 sidecar 的巨大常量块一次性搬空。

## 每小步测试

```powershell
.\.venv\Scripts\python.exe -m py_compile apps\wechat_ai_customer_service\adapters\wechat_win32_ocr_sidecar.py
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_compat_checks.py
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_add_friend_package_smoke.py
```

涉及 session name/text normalization 时加跑：

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_customer_service_multi_session_scheduler_checks.py
```

## 验收标准

- 新模块可以独立 import。
- sidecar `--help` 仍通过。
- facade import 旧函数仍通过。
- 测试通过。
- `git diff` 显示主要是移动/委托，没有算法改动。

## 回滚方式

如果 Phase 2 失败：

- 优先恢复 sidecar 原函数体。
- 保留新模块也可以，但不要让 sidecar 使用它。
- 不要继续 Phase 3。
