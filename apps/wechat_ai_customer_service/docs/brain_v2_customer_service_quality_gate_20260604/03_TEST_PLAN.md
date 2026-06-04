# Brain v2 测试计划

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
