# add_friend RPA 自适应重构开发文档

更新时间：2026-06-17

本文是当前 add_friend RPA 后续开发的主说明。它用于把三类信息分清楚：

- 朋友 PR #17 原始版本做了什么。
- 2026-06-17 本机调优后当前文件结构是什么。
- 下一阶段如何按现有微信聊天模块的自适应操控思路重构 add_friend。

本文只落开发方案和结构边界，不包含本轮代码修改。

## 1. 当前结论

当前 add_friend 不能继续按“某台机器可用坐标”推进。后续实现必须对齐现有聊天模块的成熟思路：

```text
状态识别优先
目标确认优先
OCR/UIA/视觉证据优先
几何坐标只做兜底
点击后必须状态回读
确认不了就停止
```

当前调优版已经比朋友 PR 原版安全很多，但还没有完全达到聊天模块的架构成熟度。主要差距是：

- `+` 入口仍是几何点位主导，再用弹出菜单 OCR 回读验证。
- 申请表单的申请语、备注名、确定按钮仍是固定区域定位为主。
- 运行报告还缺少稳定的设备画像、DPI、客户区和 locator 候选证据。

因此下一阶段不是继续微调单点坐标，而是把 add_friend 改成可校准、可回放、可诊断的自适应流程。

## 2. 历史来源：朋友 PR #17 原始版本

PR 信息：

```text
merge commit: bc5c1b1
PR commit:    7199023
branch:       pr/17 / codex/add-friend-rpa
title:        Promote add_friend entry click RPA route
```

PR 原始能力：

- 新增 add_friend 主链路。
- 原始主 action 为 `add-friend-entry-click-plan`。
- 要求正式字段：`phone_or_wechat`、`verify_message`、`remark_name`、`remark_code`。
- 产物目录原始口径为 `runtime/add_friend_entry_click_plan/<timestamp>/` 与 `latest/`。
- 脚本原始口径为 `scripts/run_wechat_add_friend_entry_click_plan.ps1`。
- 文档记录过 Windows 实机回归：happy path `completed + invite_sent`，字段契约失败提前阻断。

PR 原始版本的重要限制：

- 文档没有记录显示分辨率、DPI、微信窗口客户区、截图尺寸、窗口是否归一化、微信版本等复现条件。
- `+` 入口点位核心是固定布局几何推算，而不是按钮识别。
- 原始加号逻辑接近：根据左侧栏分割线 `session_split_x(width)` 推算，再用 `split_x - 16` 点加号。
- 这在朋友测试环境可以成立，但换到 1920x1200 / 当前窗口布局后会偏。

注意：朋友也是 Windows 环境，不是 macOS。当前问题不是跨平台差异，而是 Windows 多分辨率、多 DPI、多窗口布局差异。

## 3. 当前路线命名与文件结构

### 3.1 Route 命名

当前必须把历史路线和正式路线分开理解：

```text
add-friend-entry-click-plan
  -> 历史 PR 原始入口
  -> 当前保留为 Windows 1920x1080 固定布局参考/旧路线
  -> 不作为当前 Windows 正式主入口

add-friend-entry-click-plan-windows
  -> 当前 Windows 正式主入口
  -> 后续自适应重构都应围绕这条路线推进
```

对应代码：

```text
add_friend_contract.py
  ADD_FRIEND_ENTRY_CLICK_ROUTE = "add-friend-entry-click-plan"
  ADD_FRIEND_ENTRY_CLICK_WINDOWS_ROUTE = "add-friend-entry-click-plan-windows"

add_friend_routes.py
  ADD_FRIEND_WINDOWS_1080P_REFERENCE_ROUTE = ADD_FRIEND_ENTRY_CLICK_ROUTE
  ADD_FRIEND_WINDOWS_ROUTE = ADD_FRIEND_ENTRY_CLICK_WINDOWS_ROUTE
  ADD_FRIEND_MAIN_ROUTE = ADD_FRIEND_WINDOWS_ROUTE
```

### 3.2 Artifact 目录

当前目标口径：

```text
runtime/add_friend_entry_click_plan_windows/
  当前 Windows 正式路线产物

runtime/add_friend_entry_click_plan_windows_1080p_reference/
  旧 PR 1920x1080 固定布局参考路线产物

runtime/add_friend_entry_click_plan/
  历史脚本/历史文档残留目录
  不应作为新开发主目录
```

当前注意点：

- `add_friend_artifacts.py` 已按 route 映射了 Windows 正式 scope 和 Windows 1080p reference scope。
- 旧脚本 `run_wechat_add_friend_entry_click_plan.ps1` 仍会写旧目录，后续应只作为 reference/历史脚本。
- 当前正式脚本是 `run_wechat_add_friend_entry_click_plan_windows.ps1`。
- `check_wechat_add_friend_entry_click_latest.ps1` 仍偏旧目录口径，后续实现阶段应改成可指定 route/scope，避免检查错 latest。

### 3.3 文件职责

当前文件结构应按以下职责理解：

```text
add_friend_contract.py
  字段契约、query 归一化、正式字段校验。

add_friend_routes.py
  route manifest，区分 Windows 正式路线与 Windows 1080p reference。

add_friend_artifacts.py
  route -> runtime artifact scope 映射。

add_friend_flow.py
  add_friend 主流程编排。
  这里不应该长期承载平台坐标细节，只应调用定位/动作能力。

add_friend_flow_context.py
  运行上下文、timing、event、报告收口。

add_friend_flow_events.py
  payload/result 到 step event 的映射。

add_friend_payloads.py
  任务结果 payload 构造。

add_friend_result_mapping.py
  result_code/error_code 与 server_report_payload 映射。

add_friend_locator.py
  locator 结果模型：OCR locator、geometry fallback locator、fixed geometry locator。

add_friend_ocr.py
  OCR 文本标准化、compact、匹配 helpers。

add_friend_actions.py
  点击/输入动作结果元数据。

add_friend_pacing.py
  add_friend 专属分级等待策略。

wechat_win32_ocr_sidecar.py
  当前仍承载大量 Windows Win32/OCR glue、截图、点击、OCR、具体 locator。
  后续要逐步把 add_friend 布局模型和定位逻辑从这里拆出去。
```

## 4. 当前调优版已经完成的对齐项

当前调优后的 add_friend 已经具备这些目标方案特征：

- payload 校验发生在微信 UI 操作前。
- 小窗口、快速登录、白屏、辅助壳、安全/登录提示会阻断。
- 点击 `+` 前做全窗口 OCR preflight。
- `+` 点击次数默认 1 次，最大 2 次。
- 点击 `+` 后必须 OCR 回读到弹出菜单。
- 点击菜单里的“添加朋友”必须 OCR 确认菜单项，不允许只点 expected geometry。
- 输入手机号后必须 OCR 验证 query 可见，不确认就停止。
- 搜索结果里的“添加到通讯录”走 OCR 目标定位。
- `already_friend` 作为业务完成终态处理。
- 弹窗 hwnd 失效时结构化记录，不再 traceback。
- 动作之间有随机 pause，避免鼠标键盘机械连发。

这些改动说明当前路线已经从“固定点位脚本”进化到“带回读验证的混合 RPA”。

## 5. 当前仍不达标的地方

### 5.1 `+` 入口仍是几何主导

当前 Windows 正式路线的 `+` 点位大致逻辑是：

```text
根据当前窗口 geometry
找到搜索框参考点
向右推算 add_friend plus point
点击后用菜单 OCR 验证
```

这比朋友原始 `split_x - 16` 安全，但仍是：

```text
几何定位 -> 点击 -> OCR 回读
```

目标方案应改成：

```text
多候选 locator -> 置信度排序 -> 低风险验证 -> 点击 -> OCR 回读
```

### 5.2 申请表单仍是固定区域主导

当前 `add_friend_invite_form_targets()` 主要按窗口比例生成：

- `invite_greeting_textarea`
- `invite_remark_input`
- `invite_confirm_button`

这部分使用 `fixed_geometry_locator`，属于固定区域兜底，不应作为长期主定位方式。

目标方案应改成：

- 先 OCR/UIA 确认当前确实是申请表单。
- 优先定位“发送添加朋友申请”“备注名”“确定”等语义/控件锚点。
- 几何区域只作为兜底。
- 填写后必须验证申请语和备注名已经写入，确认后才允许点确定。

### 5.3 报告缺少设备画像

当前报告有截图、OCR、target、timing，但还缺少稳定的设备画像：

- 屏幕分辨率。
- DPI scale。
- 显示器数量和坐标。
- 微信窗口 rect。
- 微信客户区 rect。
- 截图尺寸。
- window normalization 是否启用。
- locator candidates、confidence、fallback_reason。

没有这些信息，远程排查时仍会回到“为什么你这台能跑，我这台偏”的问题。

## 6. 目标架构

### 6.1 分层模型

后续 add_friend 应按以下层次实现：

```text
AddFriendFlow
  只表达业务步骤：
  打开添加朋友入口 -> 搜索账号 -> 点添加到通讯录 -> 填申请表单 -> 点确定

AddFriendSurfaceProbe
  负责状态识别：
  窗口是否可用、是否登录、是否白屏、是否安全提示、当前页面是什么

AddFriendLayoutModel / WechatLayoutModel
  负责定位：
  每个目标返回 candidates、confidence、evidence、fallback_reason

AddFriendActionExecutor
  负责动作：
  hover/click/type/paste/confirm，动作前后带 guard

AddFriendReporter
  负责证据：
  截图、OCR、device profile、locator candidates、最终结果
```

### 6.2 Locator 结果标准

所有定位结果都应该是结构化对象，而不是裸 `(x, y)`：

```json
{
  "name": "add_friend.plus_entry",
  "point": [302, 70],
  "bounds": [278, 50, 324, 92],
  "strategy": "search_box_visual_anchor",
  "confidence": 0.86,
  "evidence": ["search_box_anchor", "sidebar_top_toolbar", "candidate_inside_safe_region"],
  "fallback_used": false,
  "fallback_reason": "",
  "verify_after_action": "plus_menu_ocr_detected"
}
```

如果只能用几何兜底，必须明确写出：

```json
{
  "fallback_used": true,
  "fallback_reason": "ocr_or_visual_anchor_not_available",
  "confidence": 0.52
}
```

低置信 locator 不能执行高风险最终动作。

## 7. 分步骤重构方案

### Phase 0：文档和命名收口

目标：

- 明确 `add-friend-entry-click-plan` 是历史 PR / Windows 1080p reference。
- 明确 `add-friend-entry-click-plan-windows` 是当前 Windows 主路线。
- 文档索引中区分当前源-of-truth、历史 PR 文档、分辨率审计文档。
- 标记旧脚本、旧 runtime、旧 checker 的迁移状态。

本轮只做这一阶段。

### Phase 1：统一 surface probe

新增或整理统一探测输出，覆盖所有关键步骤：

- `stage`
- `geometry`
- `screen_metrics`
- `dpi_scale`
- `window_rect`
- `client_rect`
- `screenshot_size`
- `ocr_count`
- `surface_kind`
- `blocking_reason`
- `readiness.ok`

每一步动作前都必须经过 probe。probe 不通过时只写报告，不点击。

### Phase 2：重做 `+` 入口 locator

将当前 `add_friend_windows_plus_button_point_for_geometry()` 升级为 locator 体系。

候选来源：

- 搜索框 OCR/placeholder 锚点。
- 顶部工具栏视觉区域。
- 搜索框右侧按钮候选。
- 当前 Windows geometry fallback。
- 旧 1080p reference 仅作为对照候选，不参与默认点击。

执行规则：

- 优先选高置信候选。
- 候选必须落在 sidebar search/top toolbar 安全区域。
- 点击后必须看到菜单 OCR。
- 如果点击后没有菜单，不重复机械点同一点；只记录候选失败。

### Phase 3：搜索页 locator 收口

当前搜索输入框和搜索按钮已是 OCR 优先、几何兜底。后续要加强：

- 几何兜底必须标记 confidence 和 fallback_reason。
- 输入框点击后要确认焦点/内容。
- 输入 query 后 OCR 不确认则不点击搜索。
- 搜索按钮如果只能几何兜底，需要更强的输入确认作为前置条件。

### Phase 4：申请表单 OCR/UIA 优先

这是最重要的结构升级。

申请表单定位优先级：

1. UIA 控件，如果能定位输入框和确定按钮。
2. OCR 文本锚点：`发送添加朋友申请`、`备注名`、`确定`。
3. 视觉区域：表单输入框边界、绿色确定按钮。
4. 固定几何区域兜底。

填写后验证：

- 验证申请语至少部分可见，或通过控件/剪贴板读回确认。
- 验证备注名或 remark_code 可见。
- 验证失败不点确定。
- 点确定后必须 OCR 判断最终状态。

### Phase 5：设备画像和 replay fixture

每次 live run 生成：

```text
wechat_device_profile.json
add_friend_locator_candidates.json
add_friend_surface_probe.json
```

失败包可以转成离线 fixture：

```text
geometry.json
ocr_items.json
screenshot.png
expected_locator_regions.json
```

后续多分辨率适配优先通过 fixture 回归，而不是频繁实机试错。

### Phase 6：脚本和 checker 收口

需要整理：

- `run_wechat_add_friend_entry_click_plan_windows.ps1` 是正式脚本。
- `run_wechat_add_friend_entry_click_plan.ps1` 改成 reference/legacy 文案，或后续迁入 archive。
- `check_wechat_add_friend_entry_click_latest.ps1` 支持 `-Route windows|reference` 或 `-ArtifactScope`。
- README 和 PR readiness 不再同时声称旧路线是正式主路线。

## 8. 修改边界

下一阶段实现时应遵守：

- 不把客户可见业务内容写死在 RPA route 里。
- 不新增某个分辨率专用业务分支。
- 不在 flow 里直接塞更多裸坐标。
- 不让几何 fallback 在无验证情况下触发最终确认/发送。
- 不因失败而连续重复点击同一位置。

允许：

- 增加 locator 候选和 evidence。
- 增加只读 profile probe。
- 增加 report 字段。
- 增加 fixture 和离线测试。
- 在 sidecar 内短期保留兼容 wrapper，但新逻辑应往 layout/probe 模块收敛。

## 9. 验收标准

文档收口验收：

- 开发者能清楚区分历史 PR 路线、当前 Windows 主路线、未来自适应目标。
- docs 索引能指向当前主文档。
- 历史 PR readiness 不再被误读成当前实现源-of-truth。

实现阶段验收：

- `+` 入口不再只有一个几何点。
- 菜单、搜索、添加到通讯录、申请表单都有 OCR/UIA/视觉证据。
- 申请表单填写不确认则不点确定。
- 每个失败报告都能说明：当前页面状态、候选点、为何选择、为何停止。
- 1920x1080、1920x1200、DPI 缩放、不同窗口尺寸只通过 profile/locator 适配，不在业务 flow 里混写坐标。

测试阶段验收：

- `run_add_friend_package_smoke.py` 通过。
- `run_wechat_win32_ocr_compat_checks.py` 通过。
- 新增 locator/profile fixture 测试通过。
- 当前机器 live 低风险验证能做到：失败不盲点，成功可复盘。

