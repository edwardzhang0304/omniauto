# Current State And Risk Audit

> Customer-visible reply ownership baseline: [../customer_visible_reply_ownership_baseline.md](../customer_visible_reply_ownership_baseline.md)

本文记录第五点拆分前的现状。后续开发不要凭印象拆文件，必须以这里的职责地图为准。

## 审计对象

主文件：

```text
apps/wechat_ai_customer_service/adapters/wechat_win32_ocr_sidecar.py
```

本轮审计结果：

```text
总行数：10797
顶层 def/class 数：307
公开 sidecar action：status / capabilities / sessions / messages / send / recover-render / ADD_FRIEND_ROUTES
```

关键入口：

- `main()`
- `run_action(args)`
- `run_sidecar_cli()`
- `run_daemon_loop()`

现有 action 分发边界：

```text
run_action
  -> ADD_FRIEND_ROUTES 先做字段契约校验
  -> pywin32 可用性检查
  -> ensure_visible_wechat_window / activate_window / normalize_wechat_window / quick_login
  -> status / capabilities / recover-render / sessions / messages / send / add_friend
```

这说明 `wechat_win32_ocr_sidecar.py` 同时承担了 CLI facade、动作路由、窗口生命周期、OCR、输入、发送、会话切换、add_friend 业务 glue。

## 当前职责地图

### 1. CLI 和 action router

大致范围：

```text
main()
run_action()
args_for_daemon_request()
run_daemon_loop()
run_sidecar_cli()
SIDECAR_BASE_ACTIONS
SIDECAR_ACTION_CHOICES
```

职责：

- 解析 CLI 参数。
- 保持 JSON stdout 输出。
- 选择对应 action。
- 把 `ADD_FRIEND_ROUTES` 接进统一 sidecar。

风险：

- 如果在拆分中改了 action 名、参数名、stdout JSON 形态，会直接破坏 Worker/脚本/connector。
- `main()` 的返回码规则也属于外部契约，不应顺手改。

### 2. 窗口发现、前台激活、DPI 和几何

大致范围：

```text
get_window_geometry()
get_window_client_geometry()
validate_capture_geometry()
validate_send_geometry()
probe_wechat_windows()
select_primary_visible_main_window()
ensure_visible_wechat_window()
restore_wechat_window()
focus_wechat_window()
activate_window()
configure_dpi_awareness()
normalize_wechat_window()
window_dpi_scale()
search_box_point_for_geometry()
session_click_x_for_geometry()
calculate_send_points()
input_click_candidate_points()
send_click_candidate_points()
```

职责：

- 找 Windows 微信主窗口。
- 判断窗口是否可见、是否托盘隐藏、是否白屏/登录/过小。
- 计算窗口坐标、客户区坐标、截图坐标、候选点击点。

风险：

- 多分辨率、多 DPI、窗口负坐标、多屏下，这一层最容易让点位漂移。
- 当前很多函数直接返回 `(x, y)` 或 list，没有统一 `confidence/evidence/fallback` 模型。

### 3. 截图和 OCR

大致范围：

```text
capture_wechat()
capture_wechat_visible_rect()
capture_visible_screen()
capture_wechat_window_visible_screen()
capture_window_image()
capture_window_by_rect()
try_image_grab()
run_ocr()
normalize_ocr_text()
image_information_score()
likely_foreign_overlay_capture()
detect_blank_render()
recover_blank_render_payload()
```

职责：

- 采集微信窗口或屏幕截图。
- 调用 OCR。
- 判断是否白屏、遮挡、外部窗口覆盖、登录或安全提示。

风险：

- 截图坐标和窗口坐标混用时，容易把窗口内点位当屏幕点位。
- OCR 是语义证据，不应单独决定高风险点击。

### 4. 会话列表、聊天内容和消息解析

大致范围：

```text
parse_sessions_from_ocr()
enrich_sessions_with_sidebar_signals()
detect_visual_session_unread_badge()
parse_messages_from_ocr()
classify_message_side()
messages_payload()
capture_message_history_snapshots()
capture_message_history_snapshots_until_anchor()
merge_message_history_snapshots()
sidecar_message_content_key()
normalize_anchor_message_content()
normalize_anchor_reply_key()
```

职责：

- 识别左侧会话列表。
- 识别聊天窗口消息。
- 维护 anchor、history、dedupe 和 session key 相关证据。

风险：

- 这层属于代码机制层，只能输出“看到的消息、谁发的、在哪个会话”，不能生成客户可见回复。
- speaker label、联系人名、群 sender 都是 metadata，不是客户消息正文。

### 5. 发送、输入和安全确认

大致范围：

```text
send_payload()
humanized_input_settings()
adapt_humanized_input_settings()
clear_existing_input_draft()
paste_text_with_confirmation()
type_text_with_sendinput_unicode()
confirm_input_token_via_clipboard()
safe_send_trigger()
send_with_guarded_clicks()
send_with_uia_controls()
validate_active_send_target()
validate_post_send_target()
reserve_send_rate()
send_rate_decision()
coordinate_rpa_action()
active_ui_action_budget_decision()
record_ui_action()
```

职责：

- 人类化输入。
- 剪贴板/SendInput/UIA/Enter/click 多种发送模式。
- 发送前后目标确认。
- 动作频率、近点重复点击和风控预算。

风险：

- 这一层高风险，不能先拆。
- 如果目标确认、发送后回读或动作风控被弱化，会导致串会话、误发、机械动作高危。

### 6. 会话切换和目标确认

大致范围：

```text
session_name_matches()
session_row_click_candidate_points()
choose_session_row_click_point()
activate_session_candidate()
find_session_candidate_by_key()
ensure_main_session_list()
target_switch_surface_state()
open_chat()
ensure_target_ready_for_send()
active_chat_matches()
```

职责：

- 从会话列表中切换目标会话。
- 匹配 display name 和 session key。
- 在发送前确认当前会话是目标。

风险：

- 相同 display name、多会话并发、列表预览变化时容易串会话。
- 这层必须继续以 session key 和 active target guard 为核心。

### 7. add_friend Windows glue

大致范围：

```text
add_friend_*
find_add_friend_*
click_add_contact_entry_from_search_result()
paste_invite_form_text()
fill_add_friend_invite_form_and_confirm()
wait_for_add_friend_dialog_window()
wait_for_add_friend_invite_form_window()
input_add_friend_query_and_search()
write_add_friend_entry_click_review()
add_friend_entry_click_plan_payload()
```

已拆出的 add_friend 模块：

```text
add_friend_actions.py
add_friend_artifacts.py
add_friend_contract.py
add_friend_diagnostics.py
add_friend_flow.py
add_friend_flow_context.py
add_friend_flow_events.py
add_friend_layout.py
add_friend_locator.py
add_friend_ocr.py
add_friend_operator_guard.py
add_friend_pacing.py
add_friend_payloads.py
add_friend_result_mapping.py
add_friend_routes.py
add_friend_screenshot.py
```

现状判断：

- add_friend 已经有一部分“业务流程”和“payload/contract/report”从 sidecar 中拆出。
- 但 Windows 具体 locator、截图、OCR、点击、等待、表单填充仍大量留在 sidecar。
- 后续应继续把 Windows 实现细节抽到 add_friend adapter 或 win32 OCR 子模块，但 `wechat_win32_ocr_sidecar.py` 仍保留兼容 wrapper。

## 当前已经做对的事情

- `add-friend-entry-click-plan` 仍是对外稳定主入口。
- `add-friend-entry-click-plan-windows` 是 Windows alias。
- `add-friend-entry-click-plan-windows-1080p-reference` 是 reference/diagnostic route。
- `run_add_friend_entry_click_plan_flow()` 已经把 add_friend 编排从 sidecar 中抽出。
- `AddFriendOpsProtocol` 已经定义了 flow 需要的 sidecar ops。
- `run_add_friend_package_smoke.py` 已覆盖 route、artifact、contract、payload、operator guard、locator、OCR、pacing 等关键契约。

## 主要风险

### 风险 1：拆分时破坏外部 CLI 契约

表现：

- action 名变了。
- flags 名变了。
- JSON 字段变了。
- `add-friend-entry-click-plan` 被替换成 alias。

应对：

- 任何拆分都必须让 `wechat_win32_ocr_sidecar.py --help` 可用。
- `run_add_friend_package_smoke.py` 必须继续通过。
- `ADD_FRIEND_MAIN_ROUTE` 不得改为 Windows alias。

### 风险 2：把行为重写伪装成结构拆分

表现：

- 提取模块时顺手改坐标算法。
- 提取发送模块时顺手改发送确认。
- 提取 OCR 时顺手调阈值。

应对：

- 前三阶段只允许等价搬迁和 wrapper 委托。
- 行为优化必须单独建文档、单独测试、单独提交。

### 风险 3：循环 import 或脚本直跑失效

表现：

- `python apps/.../wechat_win32_ocr_sidecar.py --help` 失败。
- 从临时 cwd 运行时找不到 `apps`。
- 新模块 import 反向依赖 sidecar，形成循环。

应对：

- sidecar 继续负责 `PROJECT_ROOT` bootstrap。
- 新模块不应 import `wechat_win32_ocr_sidecar.py`。
- facade 可以 import 新模块，新模块不能 import facade。

### 风险 4：测试只覆盖 add_friend，不覆盖客服发送

表现：

- add_friend smoke 过了，但客服双会话/发送路径坏了。

应对：

- 每阶段最少跑 add_friend smoke、win32 OCR compat、客服多会话调度。
- 涉及 send/session 时必须加跑 workflow logic 和必要实盘。

## 当前不建议立刻做的事

- 不建议立刻把 1.08 万行一次性拆完。
- 不建议先拆发送和会话切换。
- 不建议引入新的平台抽象覆盖所有未来 macOS 能力。
- 不建议改 `WeChatConnector` 对外行为。
- 不建议把 add_friend 的 route 和 artifact scope 再改名。

## 下一步

先按 [04_PHASE_0_BASELINE_CHECKPOINT.md](04_PHASE_0_BASELINE_CHECKPOINT.md) 建立基线，再按 [05_PHASE_1_CONTRACT_GUARDS.md](05_PHASE_1_CONTRACT_GUARDS.md) 补齐保护网，然后才开始代码提取。
