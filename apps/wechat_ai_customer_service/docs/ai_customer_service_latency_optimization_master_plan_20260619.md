# 微信 AI 客服端到端速度优化总纲（2026-06-19）

> Customer-service development baseline: [`customer_visible_reply_ownership_baseline.md`](customer_visible_reply_ownership_baseline.md).

## 1. 背景与目标

本文件是后续“微信 AI 客服回复速度优化”任务的大纲领。它承接已有的 [`rpa_brain_end_to_end_latency_optimization_plan_20260606.md`](rpa_brain_end_to_end_latency_optimization_plan_20260606.md)，但根据 2026-06-19 的最新实盘数据重新排序优化优先级。

最新超短句双会话实测结论：

- `你好 / 在吗`、`您好 / 还在吗`、`有空吗 / 你好` 三轮均真实发送成功。
- 双会话整轮耗时约 147-161 秒。
- 首次 OCR/会话捕获约 18.6-24.5 秒。
- 单条真实 RPA 发送约 18.4-25.9 秒。
- 从 LLM 提交到最终发出，单条约 85-137 秒。
- final visible polish 约 2.7-4.7 秒，不是当前最大瓶颈。

历史 live 数据也显示：

- 真实 RPA `send_post_seconds` 中位数约 48 秒，P90 约 60 秒，最大约 75 秒。
- dry-run 发送中位数约 0.35 秒，说明真实微信 RPA 才是端到端慢的重要来源。

一句话目标：在不破坏 Brain First、客户可见回复所有权、RPA 安全、目标会话校验和微信风控安全的前提下，把短句体感回复时间从一分钟级逐步压下来。

## 2. 硬边界

所有速度优化必须遵守以下边界：

- 不通过缩短 timeout 后“超时就不出结果/截断结果”的方式优化。
- 不跳过 `customer_service_brain`，不新增本地模板直接生成客户可见回复。
- 不让 guard、semantic reviewer、quality gate、final polish 接管客户可见回复。
- 不绕过最终可见回复校验，也不降低硬安全边界。
- 不取消发送前目标会话确认、输入框确认、发送后可读确认。
- 不为了速度恢复机械、重复、同点位、高频 RPA 操作。
- 不随意改变量名、CLI 名、路径名、JSON 字段名和对外契约。

### 2.1 框架与契约稳定红线

本任务只允许做内部优化，不允许破坏现有协作边界。由于其他模块和 Worker 包正在由其他开发者并行开发，任何对外名字或接口变化都可能导致衔接失败。

禁止事项：

- 不改已有变量名、常量名、函数名、类名、CLI 命令名、CLI 参数名、route 名。
- 不改 worker-facing 契约、JSON 输入字段、JSON 输出字段、artifact scope、文件路径和目录含义。
- 不重命名现有文件，不移动现有模块边界，不改变现有 import 路径。
- 不改变现有 public/internal API 的调用签名和返回结构。
- 不把平台特定优化通过改名暴露出去，例如不得为了 Windows 优化把既有命令改成新命令名。
- 不删除旧字段、旧路径、旧开关或旧调用方式。

允许事项：

- 在不改变旧字段含义的前提下新增可选观测字段。
- 在函数内部重排执行逻辑、减少重复计算、增加缓存和细粒度 timing。
- 新增内部 helper、adapter、compat layer，但旧入口必须继续可用。
- 新增测试、文档、诊断字段和兼容性断言。
- 如果发现名字不合理，只记录迁移建议，不直接改名。

每次落代码前必须做契约自检：

- 本次修改是否改了任何既有名字或路径？
- 本次修改是否改变了任何调用签名？
- 本次修改是否改变了既有 JSON 字段的类型或语义？
- 旧脚本、旧 CLI、旧测试入口是否仍可运行？
- 新增字段是否是可选字段，旧消费者忽略后是否仍正常？

任何确需改名或迁移的事项，必须单独提方案，写清 old name、new name、兼容层、迁移顺序和测试计划，并得到明确确认后才能做。

速度优化只能做三类事情：

- 减少重复、无效、过宽的计算和 OCR/RPA 工作。
- 对不同复杂度消息选择不同运行 profile，但仍由 Brain 产出客户可见回复。
- 增强调度、缓存、复用和观测，让真实瓶颈可定位、可验证。

## 3. 优先级排序

### P0：先补细粒度耗时记录

必须先做。否则容易误修，把 RPA 慢误判成 Brain 慢，或把测试脚本 prompt-send 慢误判成商用客服慢。

要拆出的阶段：

- `session_signal_detected_at`
- `capture_started_at`
- `capture_finished_at`
- `brain_submitted_at`
- `brain_started_at`
- `brain_finished_at`
- `evidence_pack_started_at`
- `evidence_pack_finished_at`
- `semantic_review_started_at`
- `semantic_review_finished_at`
- `brain_repair_started_at`
- `brain_repair_finished_at`
- `final_polish_started_at`
- `final_polish_finished_at`
- `reply_ready_at`
- `send_queue_entered_at`
- `send_started_at`
- `open_chat_started_at`
- `open_chat_finished_at`
- `pre_send_guard_started_at`
- `pre_send_guard_finished_at`
- `input_focus_started_at`
- `input_focus_finished_at`
- `typing_started_at`
- `typing_finished_at`
- `send_trigger_started_at`
- `send_trigger_finished_at`
- `post_send_guard_started_at`
- `post_send_guard_finished_at`
- `send_finished_at`

输出位置建议：

- audit：保留每条客户消息和每条回复的端到端 timing。
- scheduler tick：继续保留 phase summary，但增加 send 子阶段摘要。
- RPA send result：保留 open chat、guard、input、typing、trigger、post guard 的耗时。
- 验收 artifact：把每轮 summary 汇总成可读字段，避免每次都人工翻大 JSON。

验收标准：

- 能明确回答一条消息慢在 Brain、evidence、polish、capture、send queue、open chat、typing、post guard 中哪一段。
- 超短句双会话测试能输出每条回复的端到端耗时拆分。
- 不新增客户可见行为变化。

### P1：短句 Brain 轻量 profile

问题：`你好/在吗/您好/有空吗` 这类消息现在仍可能走完整业务问题链路，导致短句也有一分钟级等待。

优化方向：

- 仍由 `customer_service_brain` 产出客户可见回复。
- 对超短问候、承接、感谢、告别、简单催促等消息走轻量 Brain profile。
- 轻量 profile 可以减少证据包宽度、历史上下文长度、商品候选扩展和不必要的复杂 reviewer。
- 对含业务意图的短句，例如“秦plus多少钱”“能贷款吗”，不能当作纯问候，仍要走业务证据链。
- 对“在吗/人呢/还在吗”应让 Brain 结合当前会话上下文自然承接，而不是本地模板回复。

不能做：

- 不能新增 `if 你好 -> 固定回复` 这种本地可见话术。
- 不能跳过 final visible polish。
- 不能用行业特定关键词写死 chejin 场景。

验收标准：

- 超短问候仍由 Brain author 标记产出。
- 纯问候体感明显下降。
- 业务短句不丢事实约束。
- Brain First 静态审计和 contract tests 通过。

### P2：真实 RPA 发送链路提速

问题：真实 RPA 发送单条超短回复仍约 18-26 秒，历史 live 中位数约 48 秒。

优化方向：

- 先用 P0 的细粒度耗时确认卡点。
- 复用已确认窗口和会话状态，避免同一轮内重复全量窗口探测。
- 对已由 session_key 和 active title 双重确认的会话，减少重复 OCR 全屏扫描。
- 对短回复减少不必要的分段、重复截图和重复 post guard。
- 保留人类化输入，但把“风险防护”和“无意义等待”分开，不用固定长等待伪装安全。
- 对连续发送同一目标或同一轮多目标，复用安全缓存，但缓存必须带过期时间和窗口几何校验。

不能做：

- 不能盲发。
- 不能取消目标会话复核。
- 不能用鼠标和键盘同时瞬时操作。
- 不能重复点击同一像素点。
- 不能让发送速度变成机械高频。

验收标准：

- `send_post_seconds` 显著下降。
- `send_result` 仍包含 `pre_send_guard`、`post_send_guard`、`rpa_lock`、`confirmed_target`、`session_key`。
- 微信未掉线、未触发红色感叹号或异常风控。
- 超短、普通、长回复均能发送。

### P3：OCR 捕获链路提速

问题：超短句测试中首次 capture 仍约 18-24 秒。

优化方向：

- 区分“会话列表低扰动扫描”和“进入会话读取正文”。
- 对已知 active/pending 会话使用增量捕获，不每次全量 OCR。
- session_key、ledger、最近消息 digest 联合判断是否需要重新读取。
- 对 `--synthetic-input-only` 这类验收模式，避免混入当前真实 OCR 气泡造成噪声。
- 对真实商用模式，保留必要 OCR 回读，避免漏消息和串会话。

不能做：

- 不能用旧消息或会话标题当客户正文。
- 不能因缓存导致漏读新消息。
- 不能因为短句就跳过 session 绑定。

验收标准：

- capture 阶段耗时下降。
- 多会话不串话。
- 旧截图/旧 OCR 不污染 Brain 输入。
- `新数据测试` 群聊 speaker 与私聊 `许聪` 不混淆。

### P4：双会话调度与排队优化

问题：真实发送只能串行，第二条回复天然等待第一条 RPA 完成。短句场景下这个排队尤其明显。

优化方向：

- Brain 和 polish 继续并行，物理 RPA 发送保持串行。
- 谁先 ready 谁先进发送队列，但发送前重新确认目标会话。
- 短回复可优先发送，但不能饿死长回复。
- 发送 A 会话时，不阻塞 B 会话 Brain/polish 收集。
- 调度 summary 中明确显示 `reply_ready`、`reply_sent`、`send_queue_wait_seconds`。

不能做：

- 不能并发操控微信前台。
- 不能为了抢速度跳过 `active_chat_matches` 或 session_key 复核。
- 不能让一个会话长期霸占 RPA 锁。

验收标准：

- 双会话第二条 `submit_to_sent` 明显下降。
- 多轮双会话不串发。
- ready reply 不长期堆积。

### P5：测试口径与性能基线固化

问题：prompt-send 自问自答测试会额外模拟客户输入，这部分 RPA 不代表商用客服延迟。

优化方向：

- 性能验收默认使用：

```powershell
.\.venv\Scripts\python.exe workflows\verification\wechat_customer_service\two_visible_session_customer_service_live.py --skip-prompt-send --synthetic-input-only --rounds 1
```

- prompt-send RPA 能力单独测，不混入客服回复性能结论。
- 每次速度优化至少保留三组场景：
  - 超短问候：`你好`、`在吗`、`您好`
  - 短业务句：明确车型/价格/贷款/看车
  - 长业务句：带预算、用途、偏好、约束
- 每组同时记录 dry-run 和 live，区分 Brain/调度耗时与真实 RPA 耗时。

验收标准：

- 测试报告能分别给出 Brain、capture、RPA send、端到端耗时。
- 不再把 prompt-send RPA 慢算进商用客服回复慢。
- 性能指标可跨版本对比。

## 4. 推荐推进顺序

1. P0：先补细粒度耗时记录。
2. 用 P0 新埋点复跑超短双会话、短业务句、长业务句。
3. 根据真实拆分数据决定 P1/P2/P3 的具体改动顺序。
4. 优先做 P1 短句 Brain 轻量 profile 和 P2 RPA send 子阶段优化。
5. 再做 P3 OCR 捕获增量化。
6. 最后做 P4 调度排队优化。
7. 每阶段都跑 P5 验收矩阵，确认速度提升没有破坏 Brain First、RPA 安全、多会话隔离。

每个阶段开始前，先跑一遍“契约稳定检查”；每个阶段结束后，再跑一遍“旧入口兼容验证”。速度优化通过不等于交付通过，只有性能、质量、安全、兼容性都通过，才算该阶段完成。

## 5. 需要重点保护的既有能力

- Brain First 客户可见回复所有权。
- final visible polish 的验证与轻量自然化职责。
- 商品库、正式知识库、当前会话事实的 authority hierarchy。
- session_key + ledger + active title 的多会话隔离。
- RPA operator guard、悬浮球、防人工误触。
- add_friend 相关 CLI/变量/路径契约，本任务不触碰。
- 现有云端校验和本地双端口模拟测试基线。

## 6. 完成定义

本速度优化任务完成时，应满足：

- 每条回复都有可读端到端 timing breakdown。
- 超短句 live 双会话体感显著低于当前 147-161 秒基线。
- 普通短业务句不会因轻量 profile 漏证据、漏事实或答非所问。
- 长句质量不下降。
- 多会话不串话、不串发。
- 微信不掉线、不出现高危机械操作。
- 所有新增优化均有模拟测试、dry-run 和必要 live 验收记录。
