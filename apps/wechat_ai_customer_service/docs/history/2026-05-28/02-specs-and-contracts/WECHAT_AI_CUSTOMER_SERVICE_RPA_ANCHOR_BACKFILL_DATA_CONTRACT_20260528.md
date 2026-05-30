# 微信自动客服 RPA 锚点追溯数据契约（2026-05-28）

## 1. 配置契约

新增或扩展 `history_backfill`：

```json
{
  "history_backfill": {
    "enabled": true,
    "mode": "anchor_until_found",
    "fixed_load_times_deprecated": true,
    "trigger_when_anchor_missing": true,
    "trigger_visible_unprocessed_count": 6,
    "max_scroll_steps": 6,
    "max_duration_seconds": 12,
    "max_snapshots": 8,
    "max_messages_after_load": 80,
    "min_delay_ms": 180,
    "max_delay_ms": 650,
    "restore_to_latest": true,
    "block_on_anchor_not_found": true,
    "allow_manual_recovery_mode": false
  }
}
```

字段说明：

| 字段 | 含义 |
|---|---|
| `mode` | 实盘默认 `anchor_until_found`，兼容旧模式时可保留 `fixed_load_times` |
| `trigger_when_anchor_missing` | 当前可见窗口缺少锚点时才追溯 |
| `max_scroll_steps` | 单轮最多上翻步数 |
| `max_duration_seconds` | 单轮最长追溯时间 |
| `max_snapshots` | 单轮最多 OCR 快照 |
| `restore_to_latest` | 追溯后回到最新消息位置 |
| `block_on_anchor_not_found` | 找不到锚点时阻断自动回复 |
| `allow_manual_recovery_mode` | 是否允许人工授权补看历史 |

## 2. 会话状态契约

每个目标会话在 listener state 中维护：

```json
{
  "targets": {
    "许聪": {
      "processed_message_ids": [],
      "processed_content_keys": [],
      "handoff_message_ids": [],
      "sent_replies": [],
      "last_successful_reply_anchor": {
        "reply_trace_id": "reply_trace_xxx",
        "message_ids": ["m1", "m2"],
        "message_content_keys": ["customer\u001ftext\u001f..."],
        "reply_content_key": "normalized-reply-key",
        "reply_text_sample": "客户可见回复前 120 字",
        "processed_at": "2026-05-28T10:00:00",
        "send_verified": true
      },
      "bootstrap_events": [],
      "anchor_search_events": []
    }
  }
}
```

## 3. 锚点集合契约

运行时构造 `anchor_candidates`：

```json
{
  "anchor_candidates": [
    {
      "type": "processed_customer_message_id",
      "value": "m2",
      "priority": 100,
      "created_at": "2026-05-28T10:00:00"
    },
    {
      "type": "processed_customer_content_key",
      "value": "customer\u001ftext\u001f...",
      "priority": 90
    },
    {
      "type": "bot_reply_content_key",
      "value": "normalized-reply-key",
      "priority": 80
    }
  ]
}
```

锚点定位以最新位置为准，不以最高优先级覆盖最新位置。优先级只用于同位置冲突和审计解释。

## 4. sidecar 请求契约

旧接口仍可保留：

```json
{
  "command": "get_messages",
  "target": "许聪",
  "history_load_times": 0
}
```

新增锚点追溯请求：

```json
{
  "command": "get_messages",
  "target": "许聪",
  "history_mode": "anchor_until_found",
  "anchor_ids": ["m1", "m2"],
  "anchor_content_keys": ["customer\u001ftext\u001f..."],
  "reply_content_keys": ["normalized-reply-key"],
  "max_scroll_steps": 6,
  "max_duration_seconds": 12,
  "max_snapshots": 8,
  "min_delay_ms": 180,
  "max_delay_ms": 650,
  "restore_to_latest": true
}
```

## 5. sidecar 响应契约

```json
{
  "ok": true,
  "adapter": "win32_ocr",
  "state": "messages_ocr",
  "history_load": {
    "ok": true,
    "mode": "anchor_until_found",
    "mechanism": "win32_ocr.AnchorSearch+WheelUp+ScreenshotOCR",
    "anchor_found": true,
    "anchor_index": 7,
    "anchor_type": "processed_customer_content_key",
    "scroll_steps": 2,
    "snapshot_count": 3,
    "stopped_reason": "anchor_found",
    "restored_to_latest": true
  },
  "messages": []
}
```

允许的 `stopped_reason`：

- `anchor_found`
- `visible_anchor_found_no_scroll`
- `trigger_not_met`
- `max_scroll_steps_reached`
- `max_duration_reached`
- `ocr_low_confidence`
- `target_not_confirmed`
- `wechat_blocked`
- `exception`

## 6. workflow 审计契约

`process_target` 的事件中增加：

```json
{
  "history_backfill": {
    "enabled": true,
    "mode": "anchor_until_found",
    "applied": true,
    "anchor_found_initial": false,
    "anchor_found_after_history_load": true,
    "anchor_index_after_history_load": 7,
    "new_message_count_after_anchor": 3,
    "gap_risk": false,
    "sidecar_history_load": {}
  }
}
```

## 7. 阻断契约

当 `block_on_anchor_not_found=true` 且找不到锚点时：

```json
{
  "action": "blocked",
  "reason": "anchor_not_found_gap_risk",
  "handoff_recommended": true,
  "history_backfill": {
    "gap_risk": true,
    "gap_reason": "anchor_not_found_after_bounded_search"
  }
}
```

该结果应进入飞书/ServerChan/本地转人工接口，而不是继续自动回复。

## 8. 兼容要求

- 旧 `history_load_times` 只作为非实盘调试和人工恢复兼容入口。
- 实盘自动客服默认走 `anchor_until_found`。
- `processed_message_ids` 和 `processed_content_keys` 继续保留，作为锚点和去重基础。
- 旧审计字段不删除，只新增字段。
