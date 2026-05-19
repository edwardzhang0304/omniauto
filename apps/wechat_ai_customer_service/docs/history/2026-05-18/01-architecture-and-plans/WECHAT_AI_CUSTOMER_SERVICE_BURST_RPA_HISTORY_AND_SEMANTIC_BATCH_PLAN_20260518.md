# 微信自动客服连续消息与刷屏场景优化开发文档

日期：2026-05-18

## 1. 目标

本次优化解决两个实盘风险：

1. 客户连续发送多条文字时，系统不能简单逐条或固定截断处理，应判断这些消息是同一事件的补充，还是多个独立问题。
2. 客户极端刷屏导致微信页面上最早消息不可见时，系统应优先调用既有 RPA 能力补读历史，而不是直接基于最后几条断章取义回复。

## 2. 约束

1. 不新写一套坐标滚动、鼠标滚轮或图像识别技术代码。
2. 必须复用现有微信 RPA 边界：`wxauto4` sidecar。
3. 历史补读必须有限次数，避免卡住微信、拖慢回复或造成 token 失控。
4. 如果补读失败，不允许崩溃；应回退到当前可见消息的安全回复策略。
5. 多条消息语义判断默认走轻量本地规则，只有后续确有必要时再引入前台 LLM。

## 3. 当前问题

当前链路大致是：

1. `WeChatConnector.get_messages()`
2. `wxauto4_sidecar.py` 调用 `wx.ChatWith()` 和 `wx.GetAllMessage()`
3. `listen_and_reply.py` 从当前消息列表倒序选择未处理文本
4. 将选中的多条消息直接拼接为 `combined`
5. 进入意图、RAG、回复合成和发送前新消息检查

风险点：

1. `GetAllMessage()` 只能读取当前窗口已加载的 UIA 消息；微信 4.x 下不可见消息未必注册为 UI 控件。
2. 如果客户刷屏太多，旧批次可能已经不在当前可见消息中。
3. 之前已将默认批量合并从 3 提高到 8，但这仍只是数量合并，不等于语义合并。

## 4. 目标架构

新增两层，但不改变主回复链路的核心结构。

```text
微信窗口
  -> wxauto4 sidecar
  -> 受控历史补读 LoadMoreCache
  -> 去重/裁剪后的消息窗口
  -> 连续消息批次选择
  -> 批次语义规划器
  -> 现有意图/RAG/风格/风控/发送链路
```

## 5. 受控历史补读层

### 5.1 使用的底层能力

只调用 `wxauto4.WeChat.LoadMoreCache(load_times=N)`。

不新增：

1. 鼠标滚轮坐标逻辑
2. 页面截图识别
3. 自定义 UIA 遍历滚动
4. 无限上翻循环

### 5.2 触发条件

满足任一条件时触发：

1. 当前可见未处理连续消息数达到配置阈值。
2. 发送前新鲜度检查发现原批次不在当前可见消息中。
3. 当前批次已被截断，说明同波消息超过 `max_batch_messages`。

### 5.3 安全边界

1. `load_times` 默认小，建议 `2`。
2. `max_load_times` 上限建议 `5`。
3. 补读后最多保留最近 `80` 条消息进入后续逻辑。
4. 所有消息按 `id` 去重。
5. 补读失败只写入审计字段，不阻断监听。

## 6. 批次语义规划器

### 6.1 输入

当前选中的连续未处理文本消息：

```json
[
  {"id": "m1", "content": "想买个家用车"},
  {"id": "m2", "content": "十万左右"},
  {"id": "m3", "content": "省油点"},
  {"id": "m4", "content": "最好自动挡"}
]
```

### 6.2 输出

```json
{
  "kind": "single_event",
  "reply_strategy": "answer_as_one_need",
  "risk_level": "normal",
  "combined_text": "客户连续补充同一个需求：\n- 想买个家用车\n- 十万左右\n- 省油点\n- 最好自动挡"
}
```

### 6.3 分类

1. `single_event`：同一需求被拆成多句，应合并成一个完整需求。
2. `multi_question_same_scene`：同一业务场景下多个问题，应一次回复但自然分点。
3. `multi_question_mixed_risk`：普通问题混入合同、发票、最低价、AI身份、售后争议等边界，应普通部分可答，风险部分请示领导。
4. `spam_or_noise`：大量重复、无意义、测试边界或情绪刷屏，应简短稳住，不逐条接招。

## 7. 配置建议

```json
{
  "history_backfill": {
    "enabled": true,
    "load_times": 2,
    "max_load_times": 5,
    "trigger_visible_unprocessed_count": 6,
    "max_messages_after_load": 80,
    "freshness_load_times": 2
  },
  "semantic_batch_planner": {
    "enabled": true,
    "max_messages": 12,
    "spam_repeat_threshold": 0.72
  }
}
```

## 8. 分章落地计划

### Chapter 1：文档和配置

1. 增加本开发文档。
2. 在 chejin 实盘配置中增加 `history_backfill` 与 `semantic_batch_planner`。

### Chapter 2：RPA 历史补读接入

1. `wxauto4_sidecar.py` 增加 `--history-load-times`。
2. daemon 请求支持 `history_load_times`。
3. `wechat_connector.py` 暴露 `get_messages(..., history_load_times=N)`。
4. 不新增任何底层滚动实现，只调用 `LoadMoreCache`。

### Chapter 3：工作流补读编排

1. 在 `process_target` 初次读消息后判断是否需要补读。
2. 补读失败不阻断。
3. 发送前新鲜度检查发现原批次不可见时，先补读再判断是否过时。

### Chapter 4：语义批次规划器

1. 对当前连续消息做轻量语义分类。
2. 用规划后的 `combined_text` 进入原有意图和回复链路。
3. 审计事件记录 `semantic_batch_plan`。

### Chapter 5：测试

1. 静态编译。
2. 工作流逻辑测试。
3. sidecar 参数解析测试。
4. 模拟数据测试：
   - 4-5 条同一需求拆句。
   - 同一场景多个问题。
   - 普通问题混入合同/发票边界。
   - 30-50 条刷屏，触发历史补读与截断保护。

## 9. 验收标准

1. 不调用自写滚轮/坐标上翻代码。
2. `history_load_times` 只通过 sidecar 进入 `LoadMoreCache`。
3. 连续拆句需求被合并理解。
4. 多问题场景能分点处理。
5. 混合风险问题不会因普通问题存在而越权回答。
6. 原批次被刷出可见区时，不发送旧回复。
7. 相关静态测试和逻辑测试通过。
