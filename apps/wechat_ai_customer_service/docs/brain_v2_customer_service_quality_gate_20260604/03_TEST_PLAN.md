# Brain v2 测试计划

## 客户可见回复所有权硬基线

- 所有客户可见回复必须由 `customer_service_brain` 发出：只能是首个有效 BrainPlan、Brain repair 后的 BrainPlan，或 Brain 自己生成的硬边界/拒绝/转人工类说明。
- Guard、质量门、语义审稿、RAG、实时路由、本地模板、旧合成器、最终润色和任何兜底模块都不能生成、替换、拼接客户可见回复；它们只能提供证据、风险、审稿意见、返修指令或轻量表达校验。
- Brain 不可用、超时、不可采纳或返修失败时，不允许本地 safe fallback 代替 Brain 发客户可见话术；必须阻断发送、记录审计，并触发内部人工/告警接口。
- 后续所有客服相关开发文档必须引用 [customer_visible_reply_ownership_baseline.md](../customer_visible_reply_ownership_baseline.md)。

## 静态测试

- Python 语法检查：
  - `python -m py_compile apps/wechat_ai_customer_service/workflows/customer_service_brain.py apps/wechat_ai_customer_service/workflows/customer_service_brain_contract.py`

## 聚焦离线测试

- `python apps/wechat_ai_customer_service/tests/run_customer_service_brain_contract_checks.py`

覆盖：

- 商品价格必须来自商品库。
- 正式政策必须来自正式知识。
- AI经验池不能作为事实依据。
- 问价问题不能被“我先看看”类空泛话术糊弄。
- 推荐/选择问题必须给出明确倾向。
- 纯问候不能被误判为要客户补电话或资料。
- 质量门失败时 Brain First 不采纳。
- repair prompt 保持权威边界。

## 回归测试

优先跑最近受影响链路：

- `python apps/wechat_ai_customer_service/tests/run_llm_reply_synthesis_checks.py`
- `python apps/wechat_ai_customer_service/tests/run_knowledge_authority_refactor_checks.py`
- `python apps/wechat_ai_customer_service/tests/run_ai_experience_pool_post_refactor_validation_checks.py`
- `python apps/wechat_ai_customer_service/tests/run_workflow_logic_checks.py`

## 后续实盘观察

实盘不在本轮代码提交中强制执行，除非用户要求立即启动微信。后续建议观察：

- 问候短句是否回复自然。
- 明确问价是否直接给价或说明缺证据。
- 多轮追问是否不漂移。
- 无关闲聊是否自然接住再软引导。
- 多会话回复是否不串会话。
