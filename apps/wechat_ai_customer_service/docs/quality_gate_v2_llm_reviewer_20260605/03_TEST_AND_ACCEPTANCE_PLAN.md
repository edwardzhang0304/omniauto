# LLM 语义质量门 V2 测试与验收计划

## 1. 测试目标

验证质量门升级后：

- Brain 仍是正常客服回复主控。
- 硬边界 guard 不被 LLM 审稿绕过。
- LLM 审稿能减少静态软规则误杀。
- 回复更能回答当前客户问题，而不是机械套公式。
- 问候、闲聊、无关话题、追问、质疑、明确选择题都能自然应对。
- 多会话隔离不受影响。
- 回复速度没有因审稿明显恶化。
- 最终可见层仍然强制执行，但 Brain 来源回复默认只做校验/微润色。

### 1.1 纠偏后的验收重点

纠偏后，测试不再以“某条固定话术能不能过”为唯一目标，而要验证系统是否具备通用能力：

- Brain 能基于当前消息、上下文、商品库、正式知识和辅助材料自行判断怎么回复。
- reviewer、guard、final polish 发现问题时，默认把意见返还给 Brain，而不是直接替 Brain 写答案。
- 结构化逻辑只负责证据、硬边界、风险、捕获清洗和会话绑定，不负责普通客服最终话术。
- 新增测试必须覆盖一类风险，例如上下文漂移、多问题漏答、事实越权、会话错位、润色越权，而不是只覆盖某个车型或某一句话。

### 1.2 测试优先级

P0 必跑：

- Brain contract。
- semantic reviewer 与 Brain repair 的合同测试。
- final visible micro verify 测试。
- multi-session no-cross-send 测试。
- OCR/RPA metadata 不进入正文测试。
- authority boundary 测试：商品库事实、正式知识、AI经验池、历史聊天和常识层不越权。

P1 应跑：

- 分段耗时审计报告。
- 真实客户问题集 dry-run。
- 双会话交替 dry-run 或低风险实盘。
- legacy route 防回退审计。

P2 条件性跑：

- AI 记录员完整导出回归：仅在 shared message envelope、账号切换、导出模板、记录员 OCR 清洗被触及时必须跑。
- 飞书/ServerChan 实盘：在转人工链路改动或商用前验收时跑。
- 三会话或更多会话压力实盘：只在双会话稳定且微信状态健康时跑。

不再作为验收目标：

- 为了单个失败话术新增一个本地模板后验证该话术通过。
- 为了速度跳过 Brain 或最终可见校验后验证“更快”。
- 为了覆盖文档项而机械拆分重复测试文件。

## 2. 静态检查

必须通过：

```powershell
python -B -m py_compile `
  apps\wechat_ai_customer_service\workflows\customer_service_brain.py `
  apps\wechat_ai_customer_service\workflows\customer_service_brain_contract.py `
  apps\wechat_ai_customer_service\workflows\customer_service_quality_reviewer.py `
  apps\wechat_ai_customer_service\workflows\final_visible_llm_polish.py `
  apps\wechat_ai_customer_service\workflows\listen_and_reply.py
```

如果修改前端或 TypeScript，需要按项目要求追加 `node --check`、lint 或对应测试命令。

## 3. 合同测试

建议新增并运行：

```powershell
python -B apps\wechat_ai_customer_service\tests\run_customer_service_quality_reviewer_checks.py
python -B apps\wechat_ai_customer_service\tests\run_customer_service_brain_contract_checks.py
```

如果 reviewer 覆盖已经合并在 `run_customer_service_brain_contract_checks.py` 中，可以暂时不强制拆出独立文件；但测试名称和断言必须能清楚映射到 reviewer 的职责边界。后续 reviewer 测试继续增长时，再拆出独立测试文件。

必须覆盖：

- 审稿 `pass` 不会修改客户可见回复。
- 审稿 `repair` 只返回修复指令，不输出客户可见回复。
- 审稿 `block` 不会绕过硬 guard。
- 审稿 `handoff_suggest` 不能直接转人工，必须进入转人工 guard。
- 审稿超时时，低风险 hard pass 可 soft pass，高风险不能发送。
- 审稿 cache 不跨会话复用。
- Brain 来源最终可见层使用 `brain_micro` 预算。
- Brain 来源微润色候选如果改变语义，必须回退到 Brain 原稿并通过最终校验。
- reviewer suspicious 触发逻辑只作为“是否审稿”的调度信号，不能演变为客户可见回复规则。
- guard/reviewer/final polish 的失败意见必须能回到 Brain repair，除非触碰硬边界。

## 4. 语义质量用例

### 4.1 短问候

客户：

```text
你好
在吗
```

期望：

- 不漏回。
- 不答非所问。
- 不机械地立刻推业务。
- 语气简短自然。
- 仍经过最终可见润色。

### 4.2 明确商品问题

客户：

```text
秦PLUS多少钱？
奥迪A4L还有吗？
这台车公里数多少？
```

期望：

- 如果商品库有对应商品，直接基于商品库回答。
- 别名、错别字、同音字能由 Brain 做合理联想。
- 不能编造商品库没有的价格、库存、里程。
- 不能在客户问价格时反复问预算。

### 4.3 上下文跟随

客户：

```text
我想看 MPV，主要商务接待。
预算 20 万以内。
那你推荐哪台？
```

期望：

- Brain 记住 MPV 和商务接待。
- 不能又问“想看轿车还是 SUV”。
- 推荐要贴合预算和用途。
- 如果库里不满足，要说明原因并给替代方向。

### 4.4 客户质疑

客户：

```text
你怎么一直问预算？我刚才不是说了吗？
```

期望：

- 先承认并接住客户情绪。
- 不继续机械追问。
- 根据已有信息往下一步推进。

### 4.5 明确选择题

客户：

```text
我更在意省油和车况透明，你建议轿车还是 SUV？
```

期望：

- 不模棱两可。
- 可以基于常识给明确建议。
- 涉及具体商品事实时必须回到商品库。

### 4.6 无关闲聊

客户：

```text
今天好热啊。
你吃饭了吗？
我车自己撞墙了，保险赔吗？
```

期望：

- 无伤大雅的闲聊可自然陪聊。
- 可软引导回业务，但不能生硬。
- 常识性问题可基于 LLM 常识给谨慎建议。
- 涉及具体保险理赔承诺时，不能替保险公司下结论。
- 带边界的常识回复不应被语义审稿误杀为必须正式知识授权。

### 4.7 多问题合并

客户：

```text
这车能贷款吗？我还有旧车置换，周末能看吗？
```

期望：

- 三个问题都要回应。
- 政策和流程必须来自正式知识库。
- 不漏答。

### 4.8 多段回复

客户提出复杂需求时，期望：

- 可拆为 2 到 3 条短回复。
- 每一条都有完整意思。
- 不出现“接上条”“书接上文”之类机械拆分。
- 不以省略号截断。

## 5. 权威边界用例

### 5.1 商品库和 AI 经验池冲突

如果 AI 经验池或历史聊天提到旧价格，商品库有新价格：

- 必须以商品库为准。
- 语义审稿不能放行旧价格。

### 5.2 正式知识和常识冲突

如果 LLM 常识认为某流程可行，但正式知识库要求转人工：

- 必须以正式知识库为准。
- 语义审稿只能提示“可能需要转人工”，不能覆盖规则。

### 5.3 商品库无对应事实

客户问具体车况细节，商品库没有：

- 可以说“这项我需要帮您核实”。
- 不能编造检测结果。
- 可触发转人工或后续跟进。

## 6. 多会话隔离测试

继续运行：

```powershell
python -B apps\wechat_ai_customer_service\tests\run_customer_service_multi_session_scheduler_checks.py
```

新增质量门相关断言：

- 会话 A 的审稿缓存不能被会话 B 命中。
- 会话 A 的 repair instruction 不能写入会话 B。
- 会话 A 的 ready reply 发送前必须确认 active target。
- OCR speaker label 只作为 metadata，不进入客户正文。

## 7. 模拟长流程测试

继续运行现有真实客户风格 dry-run：

```powershell
python -B apps\wechat_ai_customer_service\tests\run_customer_service_real_wechat_fresh_long_flow_checks.py --dry-run --scenario photo_studio --max-turns 8 --delay-seconds 0.1
python -B apps\wechat_ai_customer_service\tests\run_customer_service_real_wechat_fresh_long_flow_checks.py --dry-run --scenario event_planner --max-turns 8 --delay-seconds 0.1
python -B apps\wechat_ai_customer_service\tests\run_customer_service_real_wechat_fresh_long_flow_checks.py --dry-run --scenario site_manager --max-turns 8 --delay-seconds 0.1
```

同时补充二手车真实客户问题集合：

- 预算不明确。
- 预算明确。
- 明确车型。
- 车型错别字。
- 置换。
- 贷款。
- 保险。
- 到店时间。
- 车况质疑。
- 价格异议。
- 竞品比较。
- 不相关闲聊。
- 结束语。

## 8. 实盘测试计划

实盘前置条件：

- 离线测试全通过。
- LLM 主通道和 fallback 通道可用。
- 微信窗口状态正常。
- 未读识别和多会话隔离测试通过。
- 无白屏、掉线、会话错位风险。

实盘顺序：

1. 单会话文件传输助手低风险测试。
2. 单会话真实客户问题集合抽样测试。
3. 双会话交替测试，确认不串话。
4. 三会话只在低扰动稳定后测试。
5. 记录审稿耗时、Brain 耗时、最终润色耗时、RPA 发送耗时。

实盘复盘必须区分：

- Brain 理解错误。
- evidence pack 召回不足。
- 商品库或正式知识缺失。
- reviewer/guard 误判。
- final polish 越权或删改语义。
- OCR/RPA metadata 污染正文。
- 多会话绑定或发送目标错误。
- 上游 LLM 慢或超时。
- 本地调度/RPA 操作慢。

只有证据、权威数据、硬边界、捕获清洗、会话绑定这几类问题，才优先改确定性逻辑。普通回复质量问题应先改 Brain 输入、Brain prompt、repair feedback 或 reviewer 审稿意见。

停止条件：

- 微信白屏。
- 微信被踢下线。
- 会话错发。
- 硬事实错误被发送。
- 明显暴露 AI 或自动化。
- 连续两次审稿超时导致不可接受延迟。

## 9. 性能验收

建议指标：

- 短问候和普通短问题：保持自然润色前提下，尽量 30 秒左右。
- 普通业务问答：尽量 30 到 45 秒。
- 多条件复杂推荐：尽量 60 秒内。
- 语义审稿单次 p95 不超过 8 秒。
- Brain repair 只在必要时触发，不能成为常态。
- 审稿 cache 命中时额外耗时接近 0。

如果上游 LLM 波动导致长尾，应在审计里区分：

- local_capture_ms
- brain_llm_ms
- semantic_review_ms
- final_polish_ms
- rpa_send_ms

只把本地程序可优化部分纳入本轮修复。

## 10. 质量验收

通过标准：

- 不再靠新增账号专属硬编码修复普通回复质量问题。
- Brain 大脑对正常业务问题拥有主控权。
- LLM 审稿能识别答非所问、上下文漂移、机械追问。
- 硬 guard 仍能拦住事实越权和政策越权。
- 最终可见层没有被跳过；Brain 来源回复不再被最终润色大幅改写。
- 问候、闲聊、复杂业务问题都更像真人客服。
- 多会话下无串话、无错发。
- AI 经验池和历史聊天只影响风格，不授权事实。

## 11. 人工复盘清单

每轮实盘后人工检查：

- 客户这一轮到底问了什么。
- Brain 是否理解正确。
- reviewer 是否判定正确。
- final polish 是否保持事实和意图。
- 最终发出的内容是否自然。
- 是否有不必要转人工。
- 是否有机械重复。
- 是否出现明显结构化痕迹。
- 是否存在可沉淀到 AI 经验池的表达经验。
