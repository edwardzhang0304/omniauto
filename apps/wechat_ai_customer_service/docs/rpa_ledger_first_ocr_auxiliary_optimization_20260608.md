# RPA 账本优先与 OCR 辅助优化方案（2026-06-08）

本文档是 `apps/wechat_ai_customer_service/docs/customer_visible_reply_ownership_baseline.md`
的配套实现文档。所有客户可见回复仍必须由 `customer_service_brain` 发出；
本方案只优化 RPA/OCR/调度层如何确认“该读哪条、该回谁、能不能发送”，不改变商品
事实、正式知识、Brain First、guard 与 polish 的职责边界。

## 1. 问题清单

近期实盘暴露的问题不是单个话术问题，而是会话状态链路的优先级不清：

1. 调度层已经通过未读/预览信号恢复了短消息，例如“晚上好”，但进入
   `listen_and_reply` 后又被旧的 `processed_content_keys` 去重逻辑过滤，导致
   Brain 没收到输入，表现为“已读不回”。
2. 发送前 freshness 严格 OCR 扫描可能读到未被未读红点、预览信号、capture 或账本支撑
   的单字碎片，例如“要”，并把 ready reply 标记为 stale，导致已经生成的回复被丢弃。
3. session ledger 已经存在，但定位仍偏“辅助上下文”。它应该升级为会话状态事实源：
   负责记录每个 `session_key` 的 capture、待回输入、已发送回复与上下文摘要。
4. 发送前只确认当前窗口标题仍不够。多会话并发时必须让 reply envelope、capture、
   `session_key`、消息 digest 与账本摘要形成闭环，避免 A 会话回复发给 B。
5. 短问候、短确认、短追问是高频真实客户行为，不能因为内容短或与历史内容相似就被
   默认跳过；但也不能让纯 OCR 单字误读打断发送。

## 2. 基本原则

1. **账本优先，OCR 辅助。**
   OCR/会话监控负责发现屏幕事实；一旦调度层确认成 capture，就以 capture + ledger
   作为后续规划、freshness、发送校验的第一依据。
2. **Brain 是唯一客户可见出口。**
   本方案不增加本地固定回复，不新增绕过 Brain 的兜底话术。修复对象是消息选择、
   会话归属、发送 freshness 与账本状态。
3. **账本不是业务权威。**
   Ledger 只能证明“谁在什么时候说过什么、哪条回复对应哪条输入”。商品事实仍以
   product master 为最高权威，政策流程仍以 formal knowledge 为最高权威。
4. **OCR 不能单独否决已确认状态。**
   只有 OCR 观察同时得到未读红点/会话预览/session pending/capture/ledger 的支撑时，
   才能作为“有更新消息，需要 stale 当前回复”的依据。
5. **短消息不漏，碎片不误杀。**
   调度确认过的短消息必须进入 Brain；未被调度/账本确认的 OCR 单字碎片不能直接打断
   ready reply。

## 3. 新状态契约

每个 capture、LLM task、ready reply、send 操作必须携带或继承以下字段：

- `session_key`
- `target_name`
- `conversation_type`
- `capture_id`
- `message_ids`
- `input_content_keys`
- `message_content_digest`
- `context_version`
- `last_visible_anchor`
- `reply_id`

状态链路：

1. OCR/session monitor 发现未读或预览变化。
2. 调度层建立 capture，并把 batch 写入 session ledger。
3. planner 以 scheduler capture 为权威输入，允许 ledger/context 辅助 Brain 理解上下文。
4. Brain 生成客户可见策略与文案。
5. polish 仅轻量自然化，不改变 Brain 策略。
6. ready reply 绑定 capture envelope。
7. 发送前校验当前目标、capture envelope、session ledger 状态和 freshness。
8. 发送验证成功后，才把输入标记为 processed，并写入 ledger 的 `reply_sent`。

## 4. 代码修改范围

### 4.1 CapturedMessagesConnector

`CapturedMessagesConnector.get_messages()` 需要把调度层 capture 的权威批次显式传给
workflow：

- `_scheduler_authoritative_batch`
- `_scheduler_authoritative_batch_ids`
- `_scheduler_capture_is_authoritative`

这样 planner 能区分“原始 OCR 列表”与“调度层已经确认需要回复的 batch”。

### 4.2 Workflow 批次选择

`listen_and_reply.process_target()` 在普通 `select_batch_details()` 返回空时，如果 payload
携带 scheduler authoritative batch，则使用该 batch 做一次受控 fallback：

- 只接受文本消息。
- 不接受 bot/self 已发送回复。
- 不绕过 Brain。
- 不把商品/政策事实写死进本地逻辑。
- 允许调度确认过的短消息绕过旧 content-key 去重。

同时统一短消息 repeatable 判断：调度确认的高敏短消息与 7 字以内短问候/短确认，在有
未读/调度信号支撑时可重复进入 Brain，避免“在吗/晚上好/好的/要吗”等真实短句被漏掉。

### 4.3 Freshness 校验

`ManagedListenerSchedulerBridge._freshness_check()` 继续保留 strict OCR scan 作为兜底，但
strict scan 的“新消息”必须被支撑：

- 支撑来源包括 session monitor unread、session list unread、pending capture、capture
  digest、ledger pending/recent unprocessed。
- 如果 strict scan 只看到未支撑的短碎片，例如单字“要”，不能 stale 当前 reply，只记录
  `strict_freshness_unconfirmed_ocr_observation`，让发送继续。
- 如果 strict scan 看到明确长文本或有未读/preview 支撑，则仍可 stale 并重新 capture。

### 4.4 Session Ledger 升级

更新 `customer_service_session_ledger.py`：

- 文档定位改为“会话状态事实源”，明确不作为商品/政策权威。
- capture 时记录 `target_name`、`last_capture_at`、`last_unreplied_*`。
- send 成功后记录 `last_reply_at`，并清理/覆盖待回锚点。
- 保留 `context_summary` 和 `recent_messages`，供 Brain 理解上下文，但不得授权业务事实。

## 5. 回归测试清单

离线测试必须覆盖：

1. 已存在相同 content-key 的短消息“晚上好”，若由 scheduler authoritative batch 恢复，
   planner 仍必须进入 Brain/规划流程，不得 `no eligible unprocessed text messages`。
2. 发送前 strict OCR 只读到无支撑单字“要”时，不得 stale ready reply。
3. session monitor 明确未读且内容与 capture 不一致时，仍必须 stale 并重新 capture。
4. ledger capture 不得把消息标记为 processed；只有发送成功后才标记 processed。
5. 多会话 reply envelope 的 `session_key`、`capture_id`、digest 不一致时，发送前必须阻断。
6. 客户可见回复仍必须由 Brain 输出；本次修改不得新增本地客户可见兜底。

## 6. 验收标准

- 通过 scheduler/workflow/ledger 相关静态与模拟测试。
- 可复现修复“短消息已读不回”。
- 可复现修复“无支撑 OCR 碎片导致 ready reply stale”。
- 保持 Brain First contract：没有新增非 Brain 客户可见回复出口。
- 不改变商品库/正式知识库/AI 经验池的权威边界。
