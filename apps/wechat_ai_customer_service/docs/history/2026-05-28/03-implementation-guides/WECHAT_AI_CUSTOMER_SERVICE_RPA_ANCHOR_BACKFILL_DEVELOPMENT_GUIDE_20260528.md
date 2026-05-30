# 微信自动客服 RPA 锚点追溯开发指南（2026-05-28）

## 1. 落地目标

把自动客服历史补读从固定次数上翻改为锚点驱动追溯。开发完成后，系统应满足：

- 当前屏幕能找到上一轮处理锚点时，不触发回滚。
- 当前屏幕找不到锚点且存在缺口风险时，才小步追溯。
- 找到锚点立即停止。
- 找不到锚点时暂停或转人工。
- 发送前复检也使用同一套锚点逻辑。

## 2. 影响文件

预计影响：

| 文件 | 改造点 |
|---|---|
| `workflows/listen_and_reply.py` | 构建锚点、选择锚点后消息区间、替换 `maybe_enrich_messages_with_history` 触发逻辑 |
| `adapters/wechat_connector.py` | 增加 `history_mode=anchor_until_found` 参数透传 |
| `adapters/wechat_win32_ocr_sidecar.py` | 增加锚点搜索式历史捕获 |
| `admin_backend/services/customer_service_runtime.py` | 启动自检保留 bootstrap 门禁，但不误禁必要追溯 |
| `tests/run_workflow_logic_checks.py` | 增加锚点命中、锚点缺失、阻断、发送前 stale 测试 |
| `tests/run_wechat_win32_ocr_compat_checks.py` | 增加 sidecar 锚点搜索契约测试 |
| tenant config | 将实盘 `history_backfill.mode` 切到 `anchor_until_found` |

## 3. 分阶段步骤

### Phase 1：状态锚点

1. 在 `mark_processed` 成功发送后写入 `last_successful_reply_anchor`。
2. 保存客户消息 ID、内容 key、回复文本 key、`reply_trace_id`、发送验证结果。
3. 保持原有 `processed_message_ids`、`processed_content_keys`、`sent_replies` 不变。
4. 增加单元测试，验证锚点生成和旧状态兼容。

### Phase 2：当前窗口锚点定位

1. 新增 `build_customer_service_anchor_candidates(target_state)`。
2. 新增 `find_latest_anchor_index(messages, anchor_candidates)`。
3. 在当前可见消息里先找锚点。
4. 若找到，直接选择锚点之后的新消息，不调用历史追溯。
5. 增加测试：锚点在屏内时 connector 不应收到历史加载调用。

### Phase 3：锚点追溯 workflow

1. 新增 `maybe_enrich_messages_with_anchor_history`。
2. 只有锚点缺失且存在未处理可见消息时触发。
3. 调用 connector 的 `history_mode=anchor_until_found`。
4. 追溯返回找不到锚点时，输出 `anchor_not_found_gap_risk`。
5. 保留旧 `maybe_enrich_messages_with_history` 作为兼容或内部 fallback。

### Phase 4：sidecar 增量追溯

1. `wechat_win32_ocr_sidecar.py` 支持锚点参数。
2. 第一次截图为当前可见窗口。
3. 当前窗口找到锚点时直接返回 `visible_anchor_found_no_scroll`。
4. 未找到时按 bounded loop 小步上翻、截图、OCR、合并、查找。
5. 找到锚点立即停止。
6. 若配置要求，追溯结束后回到最新位置。

### Phase 5：发送前复检

1. `detect_newer_messages_before_send` 复用锚点搜索。
2. 如果原批次不可见但锚点可通过追溯找到，则判断锚点之后是否有新客户消息。
3. 若有新消息，当前回复标记 stale，不发送。
4. 若锚点找不到，阻断发送并转人工。

### Phase 6：配置迁移

1. 默认示例配置增加 `mode=anchor_until_found`。
2. chejin 实盘配置从 `disable_history_backfill=true` 调整为允许锚点追溯，但禁止固定次数盲滚。
3. `bootstrap` 默认只做当前可见基线，不自动固定次数历史加载。
4. 人工授权历史恢复模式单独开关，不跟实盘自动客服混用。

## 4. 关键实现注意事项

1. 不要用“所有已处理 ID”作为唯一边界，应优先使用最近一次成功回复锚点。
2. 内容指纹要同时支持完整文本和长文本片段，降低 OCR 分行变化导致的锚点丢失。
3. 同屏多个锚点时选择最新位置，而不是选择最高优先级。
4. 回滚后合并消息时保持时间顺序：旧快照在前，新快照在后。
5. 每次追溯都必须写审计字段，方便复盘是否误滚、滚了几步、为何停止。
6. LLM worker 不得调用 RPA；所有窗口操作仍由 RPA runner 串行执行。
7. 不做设备伪装、硬件指纹伪装或平台安全绕过。

## 5. 代码审计清单

- [ ] 实盘路径不再使用固定 `load_times` 作为默认历史补读。
- [ ] 当前窗口锚点命中时不触发任何上翻。
- [ ] 找到锚点后不继续上翻。
- [ ] 找不到锚点时不会发送自动回复。
- [ ] 发送前复检发现 stale 时不会发送旧回复。
- [ ] bootstrap 不会无条件历史回滚。
- [ ] 审计日志包含 `anchor_found`、`scroll_steps`、`stopped_reason`。
- [ ] wxauto4 仍不作为优先路径。

## 6. 回滚方案

若新机制出现问题，可通过配置临时切回：

```json
{
  "history_backfill": {
    "enabled": false
  }
}
```

这会牺牲历史完整性，但能保证不因追溯逻辑导致误回。旧固定次数补读不建议作为实盘回滚方案，只能用于人工调试。
