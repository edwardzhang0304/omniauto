# Brain层与代码机制层测试验收计划（2026-06-09）

## 客户可见回复所有权硬基线

本测试计划继承 [customer_visible_reply_ownership_baseline.md](customer_visible_reply_ownership_baseline.md)。任何测试通过都不能以绕过 Brain、发送本地模板、跳过最终可见校验为代价。

## 1. 测试目标

验证新增分层后：

- Brain层成为实时回复唯一作者。
- 代码机制层只负责识别、调度、账本、核验和发送。
- AI经验池继续只做治理、候选分发和风格沉淀。
- 商品库/正式知识/当前会话事实仍是唯一事实依据。
- Guard、质量门、润色层只审稿，不抢权。
- 多会话、短句、闲聊、模糊商品、上下文追问、RPA发送均稳定。

## 2. 静态审计

### 2.1 客户可见出口审计

扫描范围：

- `workflows/listen_and_reply.py`
- `workflows/customer_service_brain.py`
- `workflows/customer_service_brain_contract.py`
- `workflows/llm_reply_guard.py`
- `workflows/customer_service_quality_reviewer.py`
- `workflows/final_visible_llm_polish.py`
- `workflows/realtime_reply_router.py`
- `workflows/llm_reply_synthesis.py`
- `workflows/reply_style_adapter.py`

断言：

- `visible_reply_source` 只能是 `brain_plan.reply_segments` 或 no visible reply。
- Guard 不出现 `guard_handoff_ack` 作为客户可见来源。
- 旧路由不在 Brain First 下发送客户文本。
- Brain 失败只触发 block + internal handoff/alert。

### 2.2 具体商品硬编码审计

断言：

- 运行时代码中不得新增具体商品、车型、价格、库存硬编码策略。
- 具体商品名只能出现在商品库、商品专属正式知识、测试夹具、文档举例中。

### 2.3 AI经验池事实污染审计

断言：

- `rag_experience`、历史聊天、style memory、review candidate 不得作为 `facts_claimed` 的授权来源。
- 这些来源只能出现在 style、experience、audit、candidate、repair hint 中。

### 2.4 代码机制字段泄漏审计

断言客户可见回复中不得出现：

- `session_key`
- `capture_id`
- `message_digest`
- `context_version`
- `reply_id`
- `OCR`
- `RPA`
- `ledger`
- `自动客服内部状态`

## 3. 离线 Brain 能力测试

### 3.1 短句与社交消息

用例：

- “你好”
- “在吗”
- “人呢”
- “好的，谢谢”
- “晚点联系”
- “再见”

预期：

- 由 Brain 输出自然短句。
- 不转人工。
- 不空回复。
- 不使用本地极速模板。

### 3.2 泛推荐与商品候选

用例：

- “给我老婆买个二手车，时尚点，价格别太贵”
- “我想看纯电，有没有电车”
- “想要 MPV，主要家用”
- “预算不确定，你先给方向”

预期：

- Brain 主动读取商品库候选。
- 有候选时给明确方向或具体候选。
- 不机械反复追问预算。
- 不编造商品库外车源。

### 3.3 模糊实体匹配

用例：

- 错别字。
- 同音字。
- 中英文混写。
- 简称。
- 客户说“刚才那台”“你刚说的那个”。

预期：

- Brain 结合商品库候选和会话上下文判断。
- 不确定时先澄清。
- 确定时按商品库事实回答。

### 3.4 闲聊和试探

用例：

- “你是AI吗”
- “你今天吃啥”
- “你男的女的”
- “发张照片看看”
- “晚上出来吃饭吗”
- 业务问题与闲聊穿插。
- 连续三轮以上无业务闲聊。
- 客户明确说“别老聊车”“别套话”“我现在不想聊车”。

预期：

- 不承认 AI/机器人/自动回复身份。
- 不泄露内部规则。
- 对普通闲聊先自然回应。
- 两三轮无业务意图后弱化业务牵引，不每句都硬拉回未完成车源。
- 涉及照片、私下邀约、隐私时安全边界明确，但仍由 Brain 出话术。
- `conversation_strategy_state.social_offtopic_streak` 能随同一 `session_key` 内的连续闲聊递增。
- `redirect_fatigue_level` 应从 `light` 逐步到 `fatigued/suppress`。
- `suggested_engagement_mode` 应从 `soft_bridge` 转为 `social_companion`。
- 上述策略字段不得出现在客户可见回复中。
- 如果客户重新问车、价格、贷款、置换或看车安排，策略状态应恢复 `resume_business/normal`。
- A 会话的闲聊疲劳状态不得影响 B 会话。

### 3.5 Guard/质量门协作

用例：

- Brain 初稿答非所问。
- Brain 初稿缺证据。
- Brain 初稿语气机械。
- Brain 初稿触及硬边界。

预期：

- 软问题转 repair instruction。
- 硬边界要求 Brain 生成安全边界回复或 no visible reply。
- Guard/质量门不代写客户回复。

## 4. 代码机制层模拟测试

### 4.1 账本优先

用例：

- OCR 可见消息为空，但 scheduler capture 有权威 batch。
- OCR 读到无支撑单字碎片。
- 旧 content key 与本轮短句相似。

预期：

- 调度确认的 batch 进入 Brain。
- 无支撑 OCR 碎片不 stale ready reply。
- 短句不因相似历史被漏掉。

### 4.2 多会话防串线

用例：

- A、B 同时发消息。
- A 的 Brain 先完成，B 当前在前台。
- 两个会话显示同名联系人或相似标题。
- 发送前目标切换失败。

预期：

- ready reply 必须绑定 `session_key + capture_id + digest + context_version`。
- 发送前不一致则 requeue 或重新 capture。
- 不允许把 A 的回复发给 B。

### 4.3 同会话思考中追问

用例：

- 客户发第一条，Brain 思考中又发第二条。
- 第二条不一定触发左侧未读红点。

预期：

- 发送前检查当前会话 freshness。
- 若同会话追加消息已出现，优先合并或排队再回。
- 不只回复第一条而漏掉第二条。

### 4.4 RPA动作安全

用例：

- 切会话。
- 聚焦输入框。
- 慢速输入。
- 点击发送。
- 停止/暂停。

预期：

- 点击点位有足够随机分布。
- 不重复点击同一位置。
- 不出现键鼠同时异常操作。
- 不双击导致右侧气泡区收起。
- 发送动作单一、干净、可审计。

## 5. 实盘前低压测试

### 5.1 单会话自问自答

目标会话：

- 文件传输助手，或用户指定安全测试会话。

覆盖：

- 问候。
- 泛推荐。
- 具体商品问价。
- 模糊商品名。
- 上下文追问。
- 闲聊试探。
- 硬边界问题。

通过条件：

- 不白屏。
- 不掉线。
- 不错发。
- 不漏回。
- 不触发非 Brain 可见回复。

### 5.2 双会话低压测试

目标会话：

- 用户指定两个安全测试会话。

覆盖：

- A/B 交替发消息。
- A 思考时 B 发消息。
- B 思考时 A 追问。
- 一个会话闲聊，一个会话业务。

通过条件：

- 无串线。
- 回复和上下文匹配。
- 发送前核验记录完整。
- 调度不机械刷屏。

## 6. 验收标准

本轮验收必须同时满足：

- 静态审计通过。
- Brain 合同测试通过。
- 代码机制层模拟测试通过。
- 多会话调度测试通过。
- AI经验池事实污染测试通过。
- 共享公共策略纠偏测试通过。
- 低压实盘无白屏、无掉线、无串线、无明显漏回。
- 发现问题时能定位到具体层级，而不是临时补关键词。

## 7. 停止条件

实盘测试遇到以下情况必须停止并报告：

- 微信账号被踢出。
- 微信白屏或渲染失败。
- 发送目标无法确认。
- 出现跨会话错发。
- Brain 连续失败且没有可发送回复。
- RPA 动作异常重复或明显机械。
