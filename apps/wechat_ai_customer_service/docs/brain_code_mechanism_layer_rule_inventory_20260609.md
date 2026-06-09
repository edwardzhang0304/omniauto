# 零散规则层级归属与收纳清单（2026-06-09）

## 客户可见回复所有权硬基线

本清单继承 [customer_visible_reply_ownership_baseline.md](customer_visible_reply_ownership_baseline.md)。所有客户可见回复必须由 `customer_service_brain` 发出；本清单只解决“规则应该归到哪一层”的问题。

## 1. 收纳目标

历史优化过程中，很多原则被写进了代码、prompt、测试和运行配置。它们并非全都错误，但需要归档：

- 该成为权威数据的，进入商品库或正式知识。
- 该成为通用策略的，进入共享公共策略层或 Brain层合同。
- 该成为操作机制的，进入代码机制层。
- 该只用于回归的，留在测试层。
- 该废弃的旧模板，隐藏、删除或降级为审计参考。

## 2. 归属矩阵

| 规则/内容 | 当前常见位置 | 目标层级 | 处理方式 |
| --- | --- | --- | --- |
| 所有客户可见回复必须由 Brain 发出 | AGENTS、docs、Brain contract、tests | Brain层硬基线 | 保留并继续作为最高开发约束 |
| Brain 不可用时不能本地兜底发客户 | Brain runner、listen_and_reply、tests | Brain层硬基线 + 代码机制层异常处理 | 保留，异常只触发内部告警/转人工接口 |
| Guard 不能代写转人工或拒绝话术 | llm_reply_guard、docs、tests | Guard审稿层 | 保留，任何失败只给 Brain repair instruction |
| 商品价格、库存、里程、配置、是否在售 | product_master、部分测试数据、旧路由提示 | 商品库层 | 运行时代码不得硬编码具体商品事实 |
| 金融、合同、发票、赔付、定金、试驾承诺 | policies、risk_control、guard代码 | 正式知识层 + Guard审稿层 | 稳定规则进入正式知识；代码只做硬边界检测和审稿 |
| 客户本轮说的预算、用途、偏好、联系方式 | raw_messages、ledger、profile、Brain prompt | 当前会话事实层 | 只在当前会话有效，不能反写商品库或正式知识 |
| 实体别名、错别字、同音、音译、简称归一 | shared_knowledge、product_vocabulary、Brain prompt | 共享公共策略层 + Brain层 | 共享层写原则；商品候选来自商品库；Brain 最终判断 |
| “短问候/感谢/再见也必须回复” | Brain prompt、contract、tests | Brain层策略 | 不做本地快速模板，仍由 Brain 输出短句 |
| “无关闲聊先接住，不要机械转业务” | Brain prompt、quality reviewer、旧路由 | 共享公共策略层 + Brain层 | 数据化为通用策略；Brain 判断牵引强度 |
| “客户连续找茬/试探AI时不要承认AI，但也别生硬拉车” | Brain prompt、final polish、style adapter | 正式边界 + 共享策略 + Brain层 | 身份/内部信息是硬边界；闲聊节奏是共享策略 |
| “两三轮无业务意图后弱化牵引” | 目前主要在讨论和测试期望里 | 共享公共策略层 + Brain层 + 代码机制层 | 按 [conversation_strategy_state_design_20260609.md](conversation_strategy_state_design_20260609.md) 落为 per-session 策略状态；代码只记录状态，Brain 决定话术 |
| `conversation_strategy_state` | 新增会话账本状态 | 代码机制层 -> Brain层输入 | 按 `session_key` 维护闲聊/试探/抗拒牵引状态，只作为非事实策略提示，不能进入客户可见文本 |
| “客户要电车/纯电时应扩大商品候选” | Brain prompt、contract、evidence builder | Brain层证据策略 + 代码机制层检索机制 | 原则进 Brain/共享策略；候选召回机制进代码机制层 |
| “预算内优先，超预算只能标成备选” | Brain prompt、contract、tests | Brain层策略，依据商品库 | 保留为通用推荐策略，不能写具体车型 |
| “别再问预算/前面说过/这两台”需沿用上下文 | Brain contract、ledger、tests | Brain层 + 代码机制层 | Brain 负责理解；ledger 提供上下文 |
| 历史聊天真实话术 | chats、rag_experience、style_memory | AI经验池 -> 话术风格层 | 只学表达，必须事实脱敏，不授权事实 |
| 失败案例、转人工案例、质量观察 | runtime audit、rag_experience、review candidates | AI经验池 | 进入经验池，生成候选或审计，不直接影响回复 |
| 未读红点、会话预览、OCR可见气泡 | sidecar、session_monitor、scheduler | 代码机制层 | 只用于发现消息和生成 capture |
| session_key、capture_id、message_digest、context_version | scheduler、session ledger、listen_and_reply | 代码机制层 | 作为发送核验和防串线第一依据 |
| 发送前窗口标题确认 | RPA bridge、listener | 代码机制层 | 必须升级为 session_key + digest + ledger 联合确认 |
| 鼠标点击随机化、键入节奏、发送动作安全 | RPA adapter、listener、guard json | 代码机制层 | 只管动作安全，不影响话术 |
| 微信白屏、掉线、风控停机 | listener、runtime guard | 代码机制层 + 告警接口 | 发现后停机并告警，不尝试继续发送 |
| 旧实时路由本地模板 | realtime_reply_router、listen_and_reply | 废弃旧逻辑或 advisory | Brain First 下不得作为可见出口 |
| 旧 LLM synthesis 模板 | llm_reply_synthesis | 废弃旧逻辑或证据/审稿辅助 | 不得绕过 Brain |
| reply_style_adapter 中的固定可见句 | reply_style_adapter | 话术风格层或废弃旧逻辑 | 不能直接替换 Brain 策略；仅可轻量自然化 |
| 测试中具体车型/预算案例 | tests | 测试层 | 可保留为回归夹具，但不得被运行时代码依赖 |
| 共享公共知识中“无依据就转人工”旧规则 | runtime shared cache、shared_knowledge | 需要纠偏的共享策略/风险规则 | 改成“软缺证据反馈 Brain，自然追问或说明需核实；硬边界才转人工” |

## 3. 需要优先清理的散落点

### 3.1 旧可见回复出口

重点排查：

- `workflows/listen_and_reply.py`
- `workflows/realtime_reply_router.py`
- `workflows/llm_reply_synthesis.py`
- `workflows/reply_style_adapter.py`
- `workflows/customer_intent_assist.py`

清理原则：

- 如果它生成客户可见文本，必须确认 Brain First 下不会被发送。
- 如果仍需保留，只能作为 evidence、risk、style、repair instruction。
- 如果是旧模板，迁入测试夹具或删除。

### 3.2 质量门和 Guard 的越权风险

重点排查：

- `workflows/llm_reply_guard.py`
- `workflows/customer_service_quality_reviewer.py`
- `workflows/final_visible_llm_polish.py`
- `workflows/customer_service_brain_contract.py`

清理原则：

- 硬边界只允许阻断或要求 Brain 生成边界回复。
- 软质量问题不得阻断最终发送，除非 Brain repair 后仍存在硬风险。
- 质量门不得把“没命中特定结构化答案”当作转人工理由。

### 3.3 具体商品名进入运行时代码

允许位置：

- 商品库数据。
- 商品专属正式知识。
- 测试夹具。
- 文档举例。

不允许位置：

- 运行时推荐策略。
- Guard 质量规则。
- Brain prompt 的具体商品偏置。
- 本地模板或硬编码回复。

### 3.4 共享公共知识旧口径

需要复核：

- `shared_knowledge/risk_control`
- `runtime/cache/shared_knowledge/snapshot.json`
- `conversation_strategy_state_design_20260609.md` 对应的共享公共策略候选

重点把以下旧口径改成新口径：

- 旧：没有足够依据回答的问题，AI客服应转人工。
- 新：没有授权事实时，Brain 应优先自然追问、说明需要核实、给安全范围内的常识性分析；只有触及正式硬边界或系统能力不可达时才进入转人工。
- 旧：客户闲聊必须每次拉回业务。
- 新：首轮可轻柔带回；连续两三轮无业务意图、客户抗拒牵引或身份套话时，应弱化甚至暂停业务牵引，由 Brain 自然接住。

## 4. 收纳后的目标结构

```text
商品事实
  -> product_master

政策流程/硬边界
  -> formal_knowledge / product_scoped_formal / shared risk_control

通用客服策略
  -> shared_knowledge/global_guidelines
  -> Brain prompt contract

表达风格
  -> AI经验池
  -> style_memory

实时回复决策
  -> customer_service_brain

审稿反馈
  -> guard / quality reviewer / final polish

运行可靠性
  -> code mechanism layer
  -> scheduler / session ledger / RPA / OCR / runtime guard

回归案例
  -> tests
```

## 5. 审计问题清单

每次开发前后都应回答：

1. 新增规则是否有明确层级归属？
2. 是否新增了非 Brain 客户可见出口？
3. 是否把商品事实写进了代码或共享策略？
4. 是否把历史聊天当作事实依据？
5. 是否让 guard/质量门压过 Brain？
6. 是否把代码机制字段泄漏到客户可见回复？
7. 是否存在旧模板在 Brain First 下仍可发送？
8. 是否新增了具体案例补丁，而不是通用策略？
9. 是否新增或修改了对应测试？
10. 是否更新了文档索引和层级归属说明？
