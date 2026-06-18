# Phase 4 Send Session Action Guide

> Customer-visible reply ownership baseline: [../customer_visible_reply_ownership_baseline.md](../customer_visible_reply_ownership_baseline.md)

Phase 4 是高风险阶段：发送、会话切换、人类化输入和动作风控。只有 Phase 1-3 稳定后才能进入。

## 目标

把发送和会话切换相关代码从 sidecar 中拆成清晰模块，但不改变发送安全策略。

建议模块：

```text
apps/wechat_ai_customer_service/adapters/wechat_win32_ocr/session_parser.py
apps/wechat_ai_customer_service/adapters/wechat_win32_ocr/message_parser.py
apps/wechat_ai_customer_service/adapters/wechat_win32_ocr/target_switching.py
apps/wechat_ai_customer_service/adapters/wechat_win32_ocr/input_methods.py
apps/wechat_ai_customer_service/adapters/wechat_win32_ocr/send_flow.py
apps/wechat_ai_customer_service/adapters/wechat_win32_ocr/ui_action_guard.py
```

## 硬规则

- 发送前仍必须确认 active target。
- 发送后仍必须做 post-send target guard。
- 不得弱化 session key 绑定。
- 不得让相同 display name 会话混用。
- 不得移除 near-point repeat guard。
- 不得移除随机 pause/humanized pacing。
- 不得让 Brain 不可用时由 sidecar 生成兜底话术。

## 推荐顺序

### Step 4.1 提取 parser

先提取：

```text
parse_sessions_from_ocr
parse_messages_from_ocr
classify_message_side
detect_visual_session_unread_badge
enrich_sessions_with_sidebar_signals
message_history_dedupe_key
sidecar_message_content_key
```

原因：

- 大多可离线测试。
- 风险比真实发送低。

测试：

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_compat_checks.py
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_customer_service_multi_session_scheduler_checks.py
```

### Step 4.2 提取 UI action guard

提取：

```text
reserve_send_rate
send_rate_decision
read_send_guard_state
write_send_guard_state
ui_action_kind
ui_action_point
ui_action_min_gap_ms
count_recent_near_point_actions
coordinate_rpa_action
active_ui_action_budget_decision
record_ui_action
require_active_ui_action_budget
```

注意：

- runtime guard state 文件路径不要改，除非有兼容迁移。
- 写入仍在 runtime 下，不进 Git。

### Step 4.3 提取 input methods

提取：

```text
clipboard_copy
clipboard_read
clear_existing_input_draft
paste_text_once
sendinput_safe_text
sendinput_utf16_units
sendinput_unicode_unit
type_text_with_sendinput_unicode
paste_text_in_chunks_with_humanized_pacing
paste_text_with_confirmation
confirm_input_token_via_clipboard
safe_send_trigger
send_with_guarded_clicks
send_with_uia_controls
set_uia_control_value_humanized
set_uia_control_value
invoke_uia_button
```

注意：

- 不改默认 input method。
- 不改 clipboard fallback。
- 不改 SendInput timing。

### Step 4.4 提取 target switching

提取：

```text
session_row_click_candidate_points
choose_session_row_click_point
activate_session_candidate
find_session_candidate_by_key
visible_session_name_is_unambiguous
ensure_main_session_list
target_switch_surface_state
open_chat
ensure_target_ready_for_send
validate_active_send_target
validate_post_send_target
```

注意：

- 这是串会话风险核心层，每次改完必须跑多会话调度。

### Step 4.5 提取 send flow

最后提取：

```text
send_payload
```

保留 sidecar wrapper：

```python
def send_payload(...):
    return send_flow.send_payload(...)
```

## 测试命令

每个小步：

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_compat_checks.py
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_customer_service_multi_session_scheduler_checks.py
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_workflow_logic_checks.py
```

涉及 send 真实链路后，建议加：

```powershell
.\.venv\Scripts\python.exe workflows\verification\wechat_customer_service\two_visible_session_customer_service_live.py --self-check
```

实盘发送验收必须由用户确认后再做。

## 实盘验收建议

低风险优先：

```powershell
.\.venv\Scripts\python.exe workflows\verification\wechat_customer_service\two_visible_session_customer_service_live.py --skip-prompt-send --synthetic-input-only --dry-reply-send --rounds 1
```

真实发送只在以下条件满足后做：

- 测试全过。
- 微信界面准备好。
- 悬浮球守护开启。
- 用户确认允许实盘。

## 失败分类

### import 失败

通常是循环依赖，回退本次模块提取。

### 多会话调度失败

优先查 session parser/target switching，不要调 Brain。

### send target guard 失败

不要放宽 guard。先看 active target evidence 是否被提取时丢失。

### 动作频率失败

不要删风控。检查 runtime state path 和 env 默认值是否变了。

## Phase 4 完成条件

- send/session/parser/action guard 模块边界清晰。
- sidecar facade 兼容。
- 多会话调度和 workflow logic 通过。
- 必要实盘通过或明确未执行原因。
