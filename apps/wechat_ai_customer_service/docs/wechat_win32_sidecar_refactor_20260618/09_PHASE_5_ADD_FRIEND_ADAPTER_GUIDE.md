# Phase 5 Add Friend Adapter Guide

> Customer-visible reply ownership baseline: [../customer_visible_reply_ownership_baseline.md](../customer_visible_reply_ownership_baseline.md)

Phase 5 专门收束 add_friend 与 Windows sidecar 的边界。它不再解决 route 命名问题，route 契约已经冻结。

## 目标

把 sidecar 中剩余的 add_friend Windows 实现细节，逐步迁到独立 Windows adapter：

```text
apps/wechat_ai_customer_service/adapters/wechat_win32_ocr/add_friend_windows.py
```

现有 add_friend 通用模块继续保留：

```text
add_friend_contract.py
add_friend_routes.py
add_friend_artifacts.py
add_friend_payloads.py
add_friend_result_mapping.py
add_friend_flow.py
add_friend_flow_context.py
add_friend_flow_events.py
add_friend_layout.py
add_friend_locator.py
add_friend_ocr.py
add_friend_operator_guard.py
add_friend_pacing.py
add_friend_screenshot.py
```

## 不改的契约

```text
add-friend-entry-click-plan
add-friend-entry-click-plan-windows
add-friend-entry-click-plan-windows-1080p-reference
runtime/add_friend_entry_click_plan_windows/
runtime/add_friend_entry_click_plan_windows_1080p_reference/
```

## 可迁移函数

候选：

```text
add_friend_ocr_compact
add_friend_item_text
add_friend_surface_text
add_friend_blocking_prompt_region
add_friend_login_or_security_block
add_friend_item_center
add_friend_zone_bounds
add_friend_region_for_point
add_friend_region_for_item
add_friend_windows_1080p_reference_plus_button_point_for_geometry
add_friend_windows_plus_button_point_for_geometry
add_friend_plus_button_point_for_geometry
add_friend_plus_entry_safe_bounds
find_sidebar_search_anchor_item
add_friend_plus_entry_target
normalize_point_for_add_friend_target
add_friend_entry_click_validation_failure_payload
find_add_friend_action_item
find_add_friend_search_result_item
classify_add_friend_ocr_surface
classify_add_friend_after_confirm_surface
add_friend_item_snapshot
add_friend_ocr_snapshots
draw_add_friend_screen_annotation
add_friend_popup_menu_bounds
run_ocr_on_screen_region
add_friend_menu_text_matches
find_add_friend_menu_item
add_friend_expected_menu_target
add_friend_popup_menu_item_click_bounds
add_friend_expected_menu_click_bounds
add_friend_menu_candidate_targets
plus_entry_popup_menu_detected
add_friend_target_review_text
add_friend_target_by_name
add_friend_target_screen_point
add_click_screen_origin_to_targets
add_friend_page_search_region
add_friend_search_result_region
add_friend_phone_not_found_detected
add_friend_search_result_add_contact_target
click_add_contact_entry_from_search_result
add_friend_invite_form_targets
paste_invite_form_text
fill_add_friend_invite_form_and_confirm
find_add_friend_page_search_targets
add_friend_query_visible_in_items
type_add_friend_query_like_human_for_entry
backspace_add_friend_query_chars
add_friend_dialog_surface_detected
is_add_friend_dialog_window_item
wait_for_add_friend_dialog_window
add_friend_invite_form_surface_detected
is_add_friend_invite_form_window_item
wait_for_add_friend_invite_form_window
click_add_friend_menu_entry_and_capture
input_add_friend_query_and_search
write_add_friend_entry_click_review
add_friend_entry_click_plan_payload
add_friend_focus_guard_ready
add_friend_pre_click_readiness_decision
add_friend_pre_click_main_window_readiness
persist_add_friend_operator_guard_release
add_friend_calibration_payload
add_friend_failure_payload
add_friend_surface_readiness
add_friend_main_entry_surface_evidence
add_friend_human_pause
add_friend_paced_pause
click_add_friend_ocr_item
add_friend_wait_before_ocr
clear_add_friend_sidebar_search_box
add_friend_virtual_key_for_digit
type_add_friend_phone_query_like_human
type_add_friend_search_query
add_friend_optional_field_fill_enabled
paste_add_friend_text_at_item
fill_add_friend_optional_fields
```

## 推荐拆分顺序

### Step 5.1 先迁移只读 add_friend helpers

先迁移：

```text
add_friend_ocr_compact
add_friend_item_text
add_friend_surface_text
add_friend_item_center
add_friend_zone_bounds
point/bounds helpers
classify_add_friend_ocr_surface
classify_add_friend_after_confirm_surface
add_friend_phone_not_found_detected
```

这些基本不点击，风险低。

### Step 5.2 迁移 locator/report helpers

迁移：

```text
add_friend_plus_entry_target
find_add_friend_action_item
find_add_friend_search_result_item
add_friend_menu_candidate_targets
plus_entry_popup_menu_detected
draw_add_friend_screen_annotation
write_add_friend_entry_click_review
```

注意：

- 不改 locator 算法。
- 不改 report JSON。
- 迁移后 smoke 应继续确认 sidecar 使用 payload builder 和 flow context。

### Step 5.3 迁移等待和表单 helpers

迁移：

```text
wait_for_add_friend_dialog_window
wait_for_add_friend_invite_form_window
paste_invite_form_text
fill_add_friend_invite_form_and_confirm
```

风险：

- 输入框/按钮定位与主题、DPI、微信版本相关。

要求：

- 原行为完全等价。
- 不把固定 geometry 改成新算法。

### Step 5.4 迁移 add_friend entry payload wrapper

最后迁移：

```text
add_friend_entry_click_plan_payload
```

建议保留 sidecar wrapper：

```python
def add_friend_entry_click_plan_payload(...):
    return add_friend_windows.add_friend_entry_click_plan_payload(...)
```

## 与 `AddFriendOpsProtocol` 的关系

当前 `add_friend_flow.py` 通过 `AddFriendOpsProtocol` 调用 sidecar ops。

短期：

- 可以继续把 sidecar 模块本身作为 `ops` 传入。

中期：

- 新增 `WindowsAddFriendOps` 对象，实现 protocol。
- `add_friend_entry_click_plan_payload` 中创建 ops 对象并传给 flow。

长期：

```text
add_friend_flow.py
  -> protocol only
WindowsAddFriendOps
  -> windowing/capture/ocr/input/action modules
sidecar facade
  -> route action to WindowsAddFriendOps
```

## 测试命令

每个 Step 后：

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_add_friend_package_smoke.py
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_compat_checks.py
.\.venv\Scripts\python.exe workflows\verification\general\runtime_artifact_guard.py check-staged
```

如果改到 operator guard：

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_cloud_auth_required_checks.py
```

## 实盘验收

加好友实盘只能在用户明确给手机号并确认后执行。

实盘前：

- 打开悬浮球键鼠守护。
- 确认微信窗口可见。
- 先跑 calibration-only。
- 再跑一次真实点击。

禁止：

- 对同一位置反复机械点击。
- 鼠标键盘无间隔并发操作。
- 在状态不确定时继续点击确认按钮。

## 完成条件

- add_friend Windows glue 不再大量堆在 sidecar 主文件。
- `run_add_friend_package_smoke.py` 全过。
- `add-friend-entry-click-plan` canonical contract 不变。
- 迁移后的 report 足够复盘 locator、OCR、geometry、fallback。
