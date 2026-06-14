# Brain First 客服大脑重构文档索引

## 客户可见回复所有权硬基线

- 所有客户可见回复必须由 `customer_service_brain` 发出：只能是首个有效 BrainPlan、Brain repair 后的 BrainPlan，或 Brain 自己生成的硬边界/拒绝/转人工类说明。
- Guard、质量门、语义审稿、RAG、实时路由、本地模板、旧合成器、最终润色和任何兜底模块都不能生成、替换、拼接客户可见回复；它们只能提供证据、风险、审稿意见、返修指令或轻量表达校验。
- Brain 不可用、超时、不可采纳或返修失败时，不允许本地 safe fallback 代替 Brain 发客户可见话术；必须阻断发送、记录审计，并触发内部人工/告警接口。
- 后续所有客服相关开发文档必须引用 [customer_visible_reply_ownership_baseline.md](../customer_visible_reply_ownership_baseline.md)。

## 背景

本组文档用于把微信智能客服从“规则 / RAG / 实时路由优先，LLM 后置润色”调整为“LLM 客服大脑优先，商品库与正式知识库作为权威证据，guard 负责事实和边界校验”的架构。

本轮只定义需求、架构、数据合同、开发方式和验收标准，不修改业务代码。

## 核心结论

当前系统已经具备实现 Brain First 的基础能力：

- `reply_evidence_builder.py` 已能构建商品库、正式知识、当前会话、AI经验池、常识层等证据。
- `llm_reply_synthesis.py` 已有受控 LLM 综合回复能力。
- `llm_reply_guard.py` 已有事实来源、风险边界、AI身份、内部信息、商品事实等守卫能力。
- `final_visible_llm_polish.py` 已有最终可见回复润色能力。
- 多会话调度、RPA发送前目标复核、最终润色池、LLM failover 等能力已经存在。

但当前主流程仍存在根本性缺陷：

- `rag_response.skip_llm_after_apply` 会让 RAG 命中后跳过 LLM。
- `realtime_reply_router.py` 会在 LLM 综合前生成本地回复。
- 多个 route 使用 `foreground_llm_allowed = False`，导致 LLM 被降级为后置补丁。
- 最终润色只能修饰已定稿内容，不能纠正错误策略。

因此，本次重构的本质不是“再加更多规则”，而是把正常客服回复的决策权上移到 LLM 客服大脑。

## 文档列表

1. [`01_REQUIREMENTS_AND_ARCHITECTURE.md`](01_REQUIREMENTS_AND_ARCHITECTURE.md)
   - 产品需求、非目标、现状诊断、目标架构、核心原则。

2. [`02_DATA_AND_PROMPT_CONTRACT.md`](02_DATA_AND_PROMPT_CONTRACT.md)
   - Brain 输入输出、证据包、Prompt 合同、guard 合同、审计字段。

3. [`03_DEVELOPMENT_GUIDE.md`](03_DEVELOPMENT_GUIDE.md)
   - 逐章开发方案、复用模块、需要降级的旧逻辑、配置迁移。

4. [`04_IMPLEMENTATION_CHECKLIST.md`](04_IMPLEMENTATION_CHECKLIST.md)
   - 代码落地前后的具体检查项，避免漏改和误伤。

5. [`05_TEST_AND_ACCEPTANCE_PLAN.md`](05_TEST_AND_ACCEPTANCE_PLAN.md)
   - 静态测试、离线模拟、实盘测试、质量回归、多会话回归、验收标准。

6. [`06_RISKS_ROLLOUT_AND_OPEN_DECISIONS.md`](06_RISKS_ROLLOUT_AND_OPEN_DECISIONS.md)
   - 风险清单、灰度开关、回滚方案、需要保留的人工判断点。

7. [`07_BRAIN_AUTHORITY_CORRECTION_AUDIT.md`](07_BRAIN_AUTHORITY_CORRECTION_AUDIT.md)
   - Brain 主控原则的纠偏审计，列出不应继续采用的结构化补丁方向、当前残留风险和修复前检查清单。

8. [`08_GUARD_AUTHORITY_CORRECTION_V2.md`](08_GUARD_AUTHORITY_CORRECTION_V2.md)
   - Guard/质量门越权的 V2 架构纠偏合同，规定客户可见回复所有权、Guard 分级 verdict、硬边界白名单和验收审计要求。

9. [`09_BRAIN_NO_VISIBLE_REPLY_CLASSIFICATION.md`](09_BRAIN_NO_VISIBLE_REPLY_CLASSIFICATION.md)
   - Brain 空回复 / 无客户可见回复的分类审计、结构修复、同 capture 重试和防吞消息合同。

10. [`10_LLM_PROVIDER_ADAPTER_AND_FALLBACK_20260611.md`](10_LLM_PROVIDER_ADAPTER_AND_FALLBACK_20260611.md)
   - Kimi 主链路输出适配、DeepSeek v4 Flash 备用链路、前端主备配置展示与测试验收方案。

11. [`../canonical_input_identity_design_20260612.md`](../canonical_input_identity_design_20260612.md)
   - OCR/RPA 客户输入业务主键 `canonical_input_id`、可见气泡主键 `canonical_visual_id`、session 账本与 reply envelope 绑定规则。

## 和现有文档的关系

本组文档继承以下已确认原则：

- 商品库是商品事实最高权威。
- 正式知识库是政策、流程、边界的权威。
- AI经验池只做经验治理、候选分发和话术风格参考，不作为客户回复事实依据。
- LLM常识层只做通用分析和表达组织，不生成商品事实或业务承诺。
- 所有客户可见回复必须由 `customer_service_brain` 发出；最终润色只做校验和轻量自然化，不能成为回复 owner。
- 所有客户可见回复必须经过最终润色。
- RPA 发送仍保持串行，并在发送前严格复核目标会话。

相关上游文档：

- [`../authority_gated_rag_ai_experience_pool_design.md`](../authority_gated_rag_ai_experience_pool_design.md)
- [`../authority_gated_rag_implementation_plan.md`](../authority_gated_rag_implementation_plan.md)
- [`../product_master_formal_knowledge_common_sense_refactor_design.md`](../product_master_formal_knowledge_common_sense_refactor_design.md)
- [`../rpa_quality_first_context_latency_plan_20260603.md`](../rpa_quality_first_context_latency_plan_20260603.md)

## 下一步建议

确认本组文档后，下一轮可进入代码落地：

```text
阶段一：新增 customer_service_brain 模块与数据合同
阶段二：改造 listen_and_reply 主流程，Brain First 灰度启用
阶段三：降级 realtime_reply_router 的本地回复生成权
阶段四：强化 evidence pack 与 guard
阶段五：全量模拟测试 + 低压实盘测试 + 多会话手动实盘
```
