# P4 Open Chat OCR/Confirmation Latency Plan

## 背景

P3 已确认没有通过截断超时、跳过 Brain、跳过 final polish 或跳过最终发送前目标校验来换速度。最新实盘里，短问候双会话发送通过，`target_ready` 约 4.91s / 4.52s，剩余主要耗时集中在 `open_chat`：

- `open_chat_main_list`: 约 0.9s - 1.24s，主要是主会话列表截图和 OCR。
- `open_chat_activation_*`: 约 2.27s - 2.75s，里面包含点击候选会话后的确认等待和目标 OCR 确认。
- `send_payload` 前的强目标校验仍然保留，不能作为优化对象直接砍掉。

## 不可越界约束

- 不改框架，不改变量名，不改 CLI 命令、路径、JSON 字段、公共函数名、外部 API 参数名。
- 不把 `add-friend-entry-click-plan` 等协作契约改名。
- 不新增账号、商品、行业、关键词专项硬编码。
- 不绕过 Brain First：客户可见回复仍由 `customer_service_brain` 生成。
- 不用缩短上限超时然后超时放弃结果的方式制造速度提升。
- 不跳过最终发送前 `send_payload` 强目标/会话校验。
- 不增加机械重复点击、固定像素连点、鼠标键盘同时触发等高风险动作。

## P4 目标

在保留现有安全闭环的前提下，减少 `open_chat` 阶段重复截图/OCR和确认成本。P4 只处理内部实现和观测字段，外部调用者看到的函数返回、CLI 入参和 JSON 既有字段必须兼容。

## 阶段设计

### P4.0 复盘确认

目的：确认 P3 没有破坏当前能力，再进入 P4。

验收：

- 静态编译通过。
- Win32/OCR、动作风险、人性化输入、workflow、Brain contract、scheduler、安全默认回归通过。
- 最近 P3 实盘证据仍可解释：微信在线、目标匹配、双会话发送 verified、短召唤不复活 self 历史。

### P4.1 先补细粒度观测

目的：不要凭感觉改等待和 OCR。先把 `validate_active_send_target` 的内部耗时拆出来，至少区分：

- capture/screenshot。
- OCR。
- title ROI / active title 匹配。
- sidebar/session key 辅助匹配。
- blank render / geometry guard 判断。

实现原则：

- 只新增内部 timing 字段。
- 不改变 `validate_active_send_target` 的返回语义。
- 不改变失败变成功、成功变失败的判断逻辑。
- 不删除任何等待、点击、确认动作。

### P4.2 评估一次性 OCR 复用

候选思路：`ensure_target_ready_for_send` 在切换目标前通常会先做一次当前 active target validation，随后 `open_chat` 又立刻做主列表截图/OCR。若两次之间没有窗口动作，可以考虑用短 TTL 的内部缓存复用刚刚捕获的 OCR/surface 信息，作为 `open_chat` 的首次主列表扫描输入。

安全条件：

- 同一 hwnd。
- 同一窗口 geometry。
- TTL 极短。
- 缓存来源必须是强校验路径里的真实截图/OCR。
- 缓存只能替代首次扫描，不能替代点击后的 active target 确认。
- 缓存不满足条件时必须无感回退到旧路径。

验收重点：

- 目标名不同、geometry 不同、缓存过期、blank render、OCR 不可用时全部回退旧路径。
- 最终 `send_payload` 前强校验仍然运行。
- 实盘只做低量双会话短问候验证，观察是否稳定减少 `open_chat_main_list`。

### P4.3 谨慎评估确认等待

只有在 P4.1 的真实 timing 证明点击后确认等待明显冗余，且 P4.2 稳定后，才允许评估 activation confirm wait 的参数微调。

原则：

- 保持随机化和人类节奏。
- 不改成固定短 sleep。
- 不取消点击后目标确认。
- 不允许因为一两次实盘快就全局放宽。

## 推荐推进顺序

1. 完成 P4.0 复盘并记录结果。
2. 落 P4.1 观测字段，跑全套静态和模拟回归。
3. 用低量实盘采样确认真实耗时分布。
4. 若证据支持，再做 P4.2 内部 OCR 复用。
5. P4.3 只作为后续候选，不在证据不足时提前动。

## 交付标准

- 所有改动都是内部 additive 或参数级优化。
- 外部接口、变量名、文件路径、CLI、JSON 既有字段不变。
- 测试日志能回答“到底省在哪个子阶段”，而不是只看总耗时。
- 若任何实盘出现白屏、掉线、红感叹号、目标不确认、重复机械点击迹象，立即停止并回滚本阶段行为改动。
