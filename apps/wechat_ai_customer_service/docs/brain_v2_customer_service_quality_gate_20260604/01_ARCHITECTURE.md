# Brain v2 通用自检与修复架构

## 目标

把客服回复质量问题从“局部硬规则修补”升级为“LLM 大脑输出前的通用质量合同”。

目标链路：

```text
RPA/OCR 捕获
  -> 消息归一化与会话隔离
  -> Evidence Pack 构建
  -> Brain Planner / Draft
  -> Brain Quality Verifier
  -> Brain Repair（必要时一次）
  -> Authority Guard
  -> Final Visible Polish
  -> RPA 发送前目标复核
```

## 各层职责

### Evidence Pack

负责把可用材料分层交给大脑：

- `content_basis.product_master`：商品事实最高权威。
- `content_basis.formal_knowledge`：政策、流程、边界最高权威。
- `content_basis.evidence`：已筛出的商品、FAQ、政策、商品专属知识等可验证证据。
- `auxiliary.ai_experience_pool`：经验治理、风格参考、候选分发背景。
- `auxiliary.style_context`：真实客服表达风格参考。
- `auxiliary.common_sense`：通用常识分析参考。

### LLM 客服大脑

负责理解客户问题、识别口语/错别字/别名/上下文指代、选择回复策略，并声明所用证据。

它不是模板填空器。它应该能处理：

- 问候、闲聊、告别。
- 明确商品问价、配置、推荐、比较。
- 预算、车型、用途、油耗、车况等开放需求。
- 质疑、反问、换车、追问、上下文省略。
- 无关话题的自然陪聊与软引导。

### Brain Quality Verifier

负责审查 BrainPlan 是否解决当前问题，重点不是业务知识本身，而是回复质量合同：

- 当前问题是否被正面回应。
- 明确问价时，若商品库有证据，是否给出价格或说明无法确认。
- 让推荐/选择时，是否给出明确倾向，而不是空泛绕圈。
- 客户只是问候时，是否被误导向留电话、预算或无依据资料收集。
- 回复是否机械套话、答非所问、省略号截断、过长或暴露 AI。
- 辅助层是否被当成事实依据。

### Brain Repair

当质量门失败且 LLM 可用时，只允许进行一次修复。修复输入包含：

- 原 BrainPlan。
- 失败检查项。
- 当前 evidence pack。
- 权威边界。

修复输出仍是 BrainPlan，仍必须经过 normalize、fact validation、quality verifier、authority guard 和 final polish。

### Authority Guard

继续负责事实来源、边界、风险、身份暴露等安全校验。质量门不能替代 guard。

## AI经验池兼容性

AI经验池仍是所有非商品库入口材料的治理中枢，可以沉淀风格、候选知识、候选政策、复盘经验，但运行时不能授权客户可见事实。

Brain v2 对 AI经验池的使用方式：

- 允许：理解客户常见表达、参考真人客服话术节奏、生成候选分发建议。
- 禁止：直接引用旧聊天中的价格、库存、车况、承诺、手机号、合同、售后政策。
- 禁止：把 AI经验池命中作为 `facts_claimed.source_level`。

## 非目标

- 不重写商品库、正式知识库、AI经验池的数据结构。
- 不改变 RPA 操控微信的策略。
- 不取消最终润色。
- 不通过本地硬编码业务答案修复具体车型或行业问题。
