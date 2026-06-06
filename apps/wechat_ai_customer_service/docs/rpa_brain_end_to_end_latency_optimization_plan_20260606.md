# RPA + Brain First 端到端速度优化开发文档（2026-06-06）

## 0. 硬约束

本方案只优化速度、调度、状态清理、并发和 RPA 执行效率，不改变微信自动客服的基本架构。

必须遵守：

- 不改变 Brain First 架构。客户可见回复的理解、策略、取舍、推荐、异议处理、闲聊边界和表达组织仍由 `customer_service_brain` 主导。
- 不降低回复质量。任何提速都不能以跳过 Brain、跳过 guard、跳过最终可见润色、减少必要证据、削弱安全边界为代价。
- 不允许让结构化模板、关键词分支、旧路由、本地话术或 final polish 接管 Brain 的最终回答。
- guard、质量门、语义审稿、最终润色只能做审核、反馈、轻量自然化和安全约束；发现问题时应把意见反馈给 Brain 返修。
- 商品库仍是商品事实最高权威，正式知识库仍是流程和政策最高权威。
- RPA 操作必须继续遵守低扰动、防机械重复、防误发、防错会话和发送前目标复核。

一句话目标：在不牺牲回答质量和架构边界的前提下，把“发现新消息到开始处理”和“客户发问到回复发出”的体感延迟压下来。

## 1. 现状诊断摘要

基于 2026-06-06 晚间手测日志与运行状态拆解：

### 1.1 未读识别链路

当前 live 配置已是 3-5 秒随机轮询：

- `apps/wechat_ai_customer_service/configs/jiangsu_chejin_xucong_live.example.json`
- `poll.interval_min_seconds = 3`
- `poll.interval_max_seconds = 5`

日志表现：

- 调度 tick 中位数约 3 秒。
- 调度 tick 平均约 5 秒。
- P90 约 9 秒。
- 最近状态里，`新数据测试` 从检测到捕获约 3 秒，`许聪` 约 6 秒。

结论：

- 未读识别慢不是单纯由旧的 15 秒或 25 秒硬等待导致。
- 主要体感慢来自忙时调度、RPA 锁、passive probe、旧状态清理和发送链路占用。

### 1.2 回复生成链路

最近任务统计：

- LLM 任务中位数约 25 秒。
- LLM 任务 P90 约 55 秒。
- polish 中位数约 5 秒。
- polish P90 约 10 秒。
- `ready -> sent` 中位数约 15 秒。
- `ready -> sent` P90 约 41 秒。

典型长尾：

- 某次 `许聪` 任务总耗时 57 秒。
- Brain 内部耗时 42.1 秒。
- 其中 `brain_llm` 约 10.8 秒。
- `semantic_reviewer` 约 16.6 秒。
- `quality_repair` 约 9.3 秒。
- `quality_repair_verification` 约 4.2 秒。
- 最后仍要 final polish 和 RPA 发送。

结论：

- 回答等待慢的主因是多阶段 LLM 串行叠加，不是单个模型调用慢。
- 其次是 ready 后 RPA 发送仍有较大等待，尤其长文本、目标复核、真人化输入和 stale 清理时更明显。

## 2. 优化目标

### 2.1 用户体感目标

正常状态下：

- 新未读消息应在 3-6 秒内进入候选处理。
- 简短/普通问题应尽量在 20-35 秒内完成回复。
- 复杂问题允许更久，但应避免无意义长尾，目标控制在 60 秒内。
- 多会话并发时，不应因为一个会话 Brain 思考中而长期不识别其他会话的新消息。

### 2.2 质量目标

速度优化后必须保持：

- Brain 仍是最终回复主导者。
- 商品事实不虚构。
- 正式政策不越权。
- 闲聊、问候、告别、无关问题仍能自然回应。
- 多会话不串话、不串发。
- 不因追求速度增加微信风控风险。

### 2.3 可观测目标

每一条回复必须能拆出以下耗时：

- `unread_detected_at`
- `capture_started_at`
- `capture_finished_at`
- `brain_started_at`
- `brain_finished_at`
- `semantic_review_started_at`
- `semantic_review_finished_at`
- `repair_started_at`
- `repair_finished_at`
- `final_polish_started_at`
- `final_polish_finished_at`
- `ready_at`
- `send_started_at`
- `send_finished_at`

没有这些字段，就无法区分“没识别”“识别了但没读”“读了但 Brain 慢”“ready 了但发送慢”。

## 3. 维度一：未读识别链路优化

### 3.1 保留低扰动扫描

保持低扰动原则：

- 空闲时不机械切换所有会话。
- 只识别会话列表中的未读标记、预览变化、时间变化和短消息信号。
- 发现未读后才切入对应会话捕获正文。
- 不为了追求秒级响应而恢复机械轮询切窗。

### 3.2 增加忙时未读旁路

问题：

当前一个会话处于 Brain / polish / send 链路时，调度 tick 仍在跑，但新消息可能因为 UI 锁、发送锁或状态清理而延后。

优化：

- 将“被动识别会话列表未读”与“RPA 切窗捕获正文”分开。
- Brain 思考期间允许继续做被动未读扫描。
- 如果发现其他会话未读，只登记为 pending，不立即抢占发送锁。
- 发送锁只保护实际微信前台操作，不保护纯状态扫描和后台 LLM 任务。

开发点：

- `apps/wechat_ai_customer_service/scripts/run_customer_service_listener.py`
- `apps/wechat_ai_customer_service/admin_backend/services/customer_service_scheduler_state.py`
- `apps/wechat_ai_customer_service/adapters/wechat_win32_ocr_sidecar.py`

验收：

- 一个会话 LLM 运行 30 秒时，另一个会话的新未读仍能在 3-6 秒内进入 pending。
- pending 会话不会被误清除。
- 不出现机械切窗。

### 3.3 对 event_count 做快速跟进

问题：

日志里 event_count 有变化时，下一轮 tick 仍可能受正常随机间隔或 passive probe 影响。

优化：

- 当某轮 tick 发现 `event_count > 0` 或未读候选时，安排一次 fast follow-up tick。
- fast follow-up 只做轻量二次确认，不做全量会话切换。
- fast follow-up 建议延迟 0.5-1.2 秒，并加小随机抖动。

验收：

- 发现未读候选后，不再等完整 3-5 秒才二次确认。
- fast follow-up 不触发重复点击、不切错会话。

### 3.4 passive probe 与调度避让

问题：

passive logout probe 单次可能耗时 3.9-4.5 秒。虽然忙时会 deferred，但空闲状态下可能拉长一次 tick。

优化：

- passive probe 保留，不降低安全性。
- 当最近 10 秒内有未读候选、pending 会话、ready reply 或 send 操作时，probe 继续后延。
- probe 不应与 fast follow-up 抢同一轮预算。

验收：

- probe 仍能发现掉线、白屏、辅助窗口异常。
- 有消息时 probe 不拖慢消息捕获。

### 3.5 stale / ready 状态清理前移

问题：

状态文件中残留 `ready_reply_ids` 和 `reply_stale`，会让调度器每轮背旧状态包袱。

优化：

- 启动监听时先做一次轻量 state cleanup。
- 每轮 tick 只清理小批量 stale，不做大扫除。
- stale reply 不进入发送队列。
- 会话显示状态与真实 pending / ready / sent 状态一致。

验收：

- 启动后状态中不应长期残留大量旧 `ready_reply_ids`。
- `reply_stale` 不应在无新消息时长期递增。

## 4. 维度二：回复生成链路系统性压缩

### 4.1 不压缩质量，只压缩重复链路

禁止：

- 不允许为了速度跳过 Brain。
- 不允许为了速度跳过最终可见润色。
- 不允许把短问候、报价、简单问题改成本地模板直接发。
- 不允许把 guard 或 quality gate 的本地回复直接发给客户。

允许：

- 合并重复审稿。
- 合并重复返修。
- 降低重复 LLM 调用次数。
- 缩短 Brain 输出合同。
- 压缩证据包噪声。
- 并发后台任务。
- 优化 RPA 发送动作。

### 4.2 Brain 输出合同瘦身

问题：

Brain 大请求输入和输出过长会直接放大延迟。

优化：

- Brain 输出保持短结构化计划 + 客户可见回复草稿。
- 内部理由、证据引用、风险解释只保留必要字段。
- 不要求 Brain 生成长篇审计文本。
- 客户可见回复默认短句，必要时拆成 2-3 条完整短句。

质量约束：

- 瘦身的是内部字段，不是思考能力。
- 商品证据、正式知识证据和上下文摘要不能被删到影响判断。

验收：

- Brain 仍能处理模糊车型、错别字、上下文追问、闲聊、异议和边界问题。
- Brain 输出 token 明显下降。
- 回复质量不下降。

### 4.3 审稿与返修合并

问题：

当前长尾常见形态：

```text
Brain -> semantic reviewer -> quality repair -> quality repair verification -> guard -> final polish
```

如果每一层都单独调用 LLM，会把一次回复变成多次串行 LLM。

优化：

- semantic reviewer、quality gate、guard 的非硬边界意见先聚合成一个 reviewer feedback。
- 只允许一次普通 Brain repair。
- repair 后再做必要的硬边界复核。
- 非硬边界问题不得直接转人工，不得用本地 handoff 模板替代 Brain。

硬边界例外：

- 微信掉线、白屏、错会话、发送焦点异常。
- 明确违法、内部提示词、密钥、绕过规则请求。
- 商品事实与商品库冲突且 Brain repair 后仍无法修正。
- 正式政策冲突且 Brain repair 后仍无法修正。

验收：

- 普通业务问题不再连续触发多次 LLM repair。
- guard 越权率下降。
- 转人工率下降。
- 长尾 P90 明显下降。

### 4.4 语义 reviewer 触发条件收敛

问题：

语义 reviewer 在某些普通业务问题上耗时 16 秒以上，且不一定产生有效增益。

优化：

- reviewer 不作为常态第二大脑。
- reviewer 只在风险、事实冲突、上下文不确定、OCR 污染、客户质疑、明显答非所问嫌疑时触发。
- reviewer 输出只作为 Brain repair feedback。

质量约束：

- 不取消 reviewer。
- 不让低置信 Brain 草稿绕过审核。
- 只减少无必要触发。

验收：

- 普通明确问题不进入长 reviewer 链。
- 高风险和模糊问题仍能被 reviewer 抓住。

### 4.5 final polish 保留但轻量化

问题：

final polish 中位数约 5 秒，P90 约 10 秒，有偶发 30 秒。

优化：

- final polish 必须保留。
- final polish 的职责限定为表达自然化、过长切分、去省略号、去机械感、检查客户可见文本完整性。
- final polish 不改事实、不改推荐对象、不改 Brain 策略。
- 对已经符合短句自然表达的回复，polish 仍执行，但 prompt 和输出合同要更短。
- final polish 超时或上游抖动时，必须有清晰 degraded 策略；是否允许发送 degraded 草稿由现有质量规则控制，不在本方案中放宽。

验收：

- 每条客户可见回复仍经过 final polish 记录。
- polish 不再常态改变 Brain 策略。
- polish 耗时 P90 降低。

### 4.6 后台并发与发送串行分离

问题：

发送必须串行，但 Brain / polish 不应该被发送串行拖住。

优化：

- 多会话 Brain 可并发。
- polish 可并发。
- 发送仍按全局队列串行。
- 发送前必须复核当前微信会话标题/目标。
- 同一会话出现新消息时，旧 reply stale，不得发送。

验收：

- A 会话发送时，B 会话 Brain 可以继续运行。
- A 会话 Brain 长尾时，B 会话可完成 polish 并进入 ready。
- 最终发送仍不串话、不错发。

## 5. 维度三：RPA 发送链路压缩

### 5.1 ready 到 sent 拆解

问题：

最近 `ready -> sent` 中位数约 15 秒，P90 约 41 秒。

必须新增发送阶段拆分：

- `send_queue_selected_at`
- `target_recheck_started_at`
- `target_recheck_finished_at`
- `focus_started_at`
- `focus_finished_at`
- `typing_started_at`
- `typing_finished_at`
- `send_click_started_at`
- `send_click_finished_at`
- `post_send_confirm_started_at`
- `post_send_confirm_finished_at`

验收：

- 能看出发送慢到底是目标复核慢、打字慢、点击慢、确认慢，还是等待队列慢。

### 5.2 减少无效前台动作

优化：

- 已在目标会话且目标复核通过时，不重复激活窗口。
- 输入框已聚焦时，不重复点击同一点。
- 鼠标点击继续加随机漂移，但漂移范围要足够覆盖按钮安全区域。
- 发送动作保持单一策略，避免 Enter + 点击双发送。
- 发送前后不做无意义上滑、拖动、全选。

质量与安全约束：

- 不为了速度取消目标复核。
- 不为了速度取消焦点确认。
- 不恢复剪贴板整段粘贴作为常规发送方式。

验收：

- `human_client_click` 同坐标重复率显著下降。
- 不出现输入到其他窗口。
- 不出现发送错会话。
- 不出现点击发送触发双动作。

### 5.3 真人化输入的速度边界

优化：

- 保持间歇打字、少量自然停顿和必要错字修正。
- 对短句减少过度停顿。
- 对长句按完整语义拆条发送，而不是一次输入超长文本。
- 拆条之间加自然短间隔。

验收：

- 不降低防风控策略。
- 不出现机械式固定延迟。
- 长回复不再以省略号或半句结尾。

## 6. 开发实施顺序

### 阶段 A：观测与状态清理

目标：

- 先把每一段延迟看清楚。
- 清理 stale 状态造成的调度噪声。

任务：

- 增加端到端 latency trace 字段。
- 启动时轻量清理旧 stale / sent / orphan ready 状态。
- 调度 tick summary 增加 `pending_age_seconds_max`、`oldest_ready_age_seconds`、`active_lock_reason`。

测试：

- 单会话模拟。
- 双会话模拟。
- stale reply 不发送。
- 启动后旧状态不污染新测试。

### 阶段 B：未读识别链路提速

目标：

- 不恢复机械轮询。
- 在低扰动前提下更快发现未读。

任务：

- 被动未读扫描与 RPA 捕获分离。
- event_count fast follow-up。
- passive probe 避让 pending / ready / send。
- busy 状态下仍能登记其他会话 pending。

测试：

- 一个会话 LLM 长跑，另一个会话发新消息。
- 三会话只有一个有未读，不能机械切换其他两个。
- passive probe 不拖慢有消息场景。

### 阶段 C：Brain 多阶段链路压缩

目标：

- 保持 Brain 主导和质量。
- 降低重复 LLM 审核/返修长尾。

任务：

- Brain 输出合同瘦身。
- reviewer feedback 聚合。
- 非硬边界问题最多一次 Brain repair。
- reviewer 触发条件收敛到必要场景。
- final polish 保留但 prompt 和输出合同轻量化。

测试：

- 问候、闲聊、告别。
- 具体商品报价。
- 模糊车型和错别字。
- 上下文追问。
- 客户质疑。
- 无关常识问题软引导。
- 商品库/正式知识冲突。
- guard 非硬边界不越权。

### 阶段 D：发送链路压缩

目标：

- 减少 ready 后等待。
- 降低 RPA 机械重复和风控风险。

任务：

- 发送阶段 latency trace。
- 减少重复窗口激活、重复点击、重复输入框聚焦。
- 目标复核通过时走最短安全路径。
- 长回复按完整语义拆条。

测试：

- 单条短回复。
- 多条拆分回复。
- 切到其他窗口后恢复发送。
- 多会话 ready 队列按目标正确发送。
- 发送前发现新消息时 stale 并重算。

## 7. 测试清单

### 7.1 离线/模拟测试

- 调度 tick 间隔统计。
- event_count fast follow-up。
- busy LLM 下 pending 登记。
- stale cleanup。
- reviewer feedback 聚合。
- Brain repair 次数上限。
- final polish 必经但不改策略。
- ready queue FIFO。
- 同会话 stale。
- 多会话 no-cross-send。
- 发送阶段 trace 字段完整。

### 7.2 微信实盘自问自答

- 文件传输助手单会话连续 10 轮。
- `许聪` / `新数据测试` 双会话交替 10 轮。
- 三会话只一个有未读，不机械切换。
- 一个会话连续刷两条，合并或 stale 重算正确。
- 一个会话 Brain 长尾，另一个会话未读仍可进入 pending。

### 7.3 质量回归测试

- 打招呼：自然短回复，不机械转业务。
- 告别：自然结束，不硬追问。
- 闲聊：可陪聊，软引导，不答非所问。
- 奥迪/错别字/别名：能基于商品库和上下文理解。
- 预算推荐：贴近预算，不乱推偏离区间商品。
- 客户质疑：正面回应，不重复套话。
- 置换/贷款/手续：按正式知识回答，缺证据则谨慎。
- 保险/事故等常识问题：Brain 给合理常识性解释，并提示以实际政策为准。

### 7.4 风控回归测试

- 点击坐标随机漂移有效。
- 不再同点高频点击。
- 不再 Enter + 点击双发送。
- 不再无意义上滑。
- 不再全选输入框或误选历史消息。
- 不再频繁机械切会话。
- 白屏/掉线检测仍有效。

## 8. 验收标准

### 8.1 性能验收

- 空闲状态未读识别 P50 <= 4 秒。
- 空闲状态未读识别 P90 <= 8 秒。
- 忙时其他会话未读进入 pending P90 <= 8 秒。
- 普通回复端到端 P50 <= 35 秒。
- 普通回复端到端 P90 <= 60 秒。
- ready -> sent P50 <= 12 秒。
- ready -> sent P90 <= 25 秒。

这些指标必须在不降低质量、不增加错发、不触发风控的前提下达成。

### 8.2 质量验收

- Brain ownership 审计通过。
- guard 不越权。
- final polish 必经。
- 普通问题不被错误转人工。
- 真实客户常见问题模拟集通过。
- 多会话不串话。
- 商品事实只来自商品库。
- 正式政策只来自正式知识库。

### 8.3 安全验收

- 不触发微信白屏。
- 不触发踢下线。
- F8 暂停/停止正常。
- 悬浮球状态同步。
- 发送前目标复核正常。
- 异常时进入转人工接口，不继续盲发。

## 9. 不做事项

本轮不做：

- 不为了速度关闭 final polish。
- 不为了速度关闭 guard。
- 不把问候、报价、简单问题改成本地模板直接回复。
- 不新增车型、价格、预算等硬编码分支。
- 不重写 Brain First 架构。
- 不引入 wxauto4 作为主路径。
- 不恢复机械切窗轮询。

## 10. 关键文件范围

预计涉及：

- `apps/wechat_ai_customer_service/scripts/run_customer_service_listener.py`
- `apps/wechat_ai_customer_service/admin_backend/services/customer_service_scheduler_state.py`
- `apps/wechat_ai_customer_service/workflows/customer_service_brain.py`
- `apps/wechat_ai_customer_service/workflows/listen_and_reply.py`
- `apps/wechat_ai_customer_service/workflows/final_visible_llm_polish.py`
- `apps/wechat_ai_customer_service/adapters/wechat_win32_ocr_sidecar.py`
- `apps/wechat_ai_customer_service/tests/run_customer_service_multi_session_scheduler_checks.py`
- `apps/wechat_ai_customer_service/tests/run_realtime_reply_optimization_checks.py`
- `apps/wechat_ai_customer_service/tests/run_workflow_logic_checks.py`

## 11. 推进原则

每次落代码必须遵守：

1. 先补观测，再改速度。
2. 先模拟测试，再微信实盘。
3. 发现回复质量下降，回滚对应速度优化。
4. 发现 guard / quality / polish 抢 Brain 主导，按纠偏文档修架构，不用本地模板补丁。
5. 发现风控风险，优先降 RPA 前台动作和机械重复，不通过降低回复质量解决。
