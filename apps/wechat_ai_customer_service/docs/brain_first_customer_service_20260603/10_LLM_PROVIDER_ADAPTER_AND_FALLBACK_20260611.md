# LLM Provider Adapter 与 DeepSeek 备用链路开发方案

本方案受 [`customer_visible_reply_ownership_baseline.md`](../customer_visible_reply_ownership_baseline.md) 约束：所有客户可见回复仍必须由 `customer_service_brain` 发出。模型适配、备用切换、JSON 清洗、前端配置展示都属于运行机制层，不得生成、替换或改写客户可见话术。

## 目标

- 主用链路使用 Kimi 兼容 Anthropic Messages 协议，承担微信智能客服 Brain、质量审稿、最终可见润色等 LLM 调用。
- 备用链路使用 DeepSeek v4 Flash，在主用链路超时、限流、网关失败、模型不可用等可切换错误时自动接管。
- 对 Kimi 常见输出形态做专属适配：即使返回 ```json 代码块、JSON 前后带解释文本、或轻微格式包裹，也应先由适配层清洗后再进入 Brain 合同验证，避免无谓结构修复和已读不回。
- 客户端前端必须显示主用/备用链路、请求协议、模型、适配摘要，用户手动切换时不能留下旧模型残留。
- 不改变 Brain First 架构，不增加本地固定话术，不绕过最终润色。

## 非目标

- 不把 DeepSeek v4 Flash 作为主回答大脑，除非用户在前端主动切换主供应商。
- 不基于具体车型、具体问题新增结构化回复补丁。
- 不让 guard、质量门、最终润色层拥有客户可见回复所有权。
- 不在本轮做高压微信实盘发送测试，避免因模型切换验证引入额外 RPA 风控变量。

## 当前诊断

- 后端已经具备多 provider 与 failover 框架，`llm_config.py` 能区分主用与备用模型。
- 前端已经具备主备模型表单，但缺少模型族适配状态说明。
- 当前运行配置为主用 Kimi，备用仍是 Kimi；没有按目标配置 DeepSeek v4 Flash 备用。
- Kimi 在测试中表现为 Brain 链路更快、更稳，但偶尔会把 JSON 包在 Markdown 代码块中，导致原解析入口把可用响应误判为非 JSON。

## 设计原则

1. **Brain 唯一出口**：适配层只负责把 LLM 原始文本还原成可解析 JSON，不产生客户可见内容。
2. **模型适配归运行机制层**：Kimi/DeepSeek/OpenAI 等模型差异在 provider adapter 中消化，不污染业务回复策略。
3. **先清洗再修复**：对 Markdown fence、前后说明、单 JSON 对象提取，优先本地确定性清洗；清洗仍失败时才进入现有 Brain JSON structure repair。
4. **备用只处理故障**：只有 transient/model unavailable/gateway upstream 类错误触发 DeepSeek fallback，不因普通 schema/质量问题切换模型。
5. **前端与后端同源**：前端展示的模型、Base URL、request style、adapter profile 来自 `/api/system/llm-config`，保存后重新渲染，避免残留。

## 实现清单

### 1. 新增共享输出适配器

新增 `workflows/llm_output_adapter.py`：

- `strip_markdown_code_fence(text)`：去除完整 ```json / ``` 包裹。
- `extract_first_json_object_text(text)`：从说明文本中提取首个平衡 JSON 对象。
- `parse_llm_json_object(text)`：先直接解析，再清洗代码块，再提取对象。
- `llm_adapter_profile(provider, model)`：返回 `kimi_anthropic_messages`、`deepseek_openai_compatible`、`generic_json` 等 profile。

应用范围：

- `customer_service_brain.py`
- `customer_service_quality_reviewer.py`
- `final_visible_llm_polish.py`

### 2. Kimi 专属提示约束

在 Brain 主提示和修复提示中增加轻量协议约束：

- 只输出裸 JSON 对象。
- 不要 Markdown 代码块。
- `reply_segments` 为 1-3 条独立完整微信短句。

该约束只影响输出格式，不改变回复策略。

### 3. DeepSeek v4 Flash 备用配置

运行时配置：

- `LLM_PROVIDER=anthropic`
- `ANTHROPIC_FLASH_MODEL=kimi-for-coding`
- `ANTHROPIC_PRO_MODEL=kimi-for-coding`
- `LLM_FALLBACK_ENABLED=1`
- `LLM_FALLBACK_PROVIDER=deepseek`
- `LLM_FALLBACK_FLASH_MODEL=deepseek-v4-flash`
- `LLM_FALLBACK_PRO_MODEL=deepseek-v4-flash`

租户客服配置继续使用 Kimi 主链路；DeepSeek 只由全局 failover 机制接管。

### 4. 前端适配

`/api/system/llm-config` 返回：

- `adapter_profile`
- `adapter_notes`
- `fallback.adapter_profile`
- `fallback.adapter_notes`

前端显示：

- 当前主链路适配
- 备用链路适配
- Kimi 输出清洗已启用
- DeepSeek Flash 作为备用接管 transient failure

### 5. 测试清单

- `node --check admin_backend/static/app.js`
- `python -m py_compile` 覆盖新增/修改 Python 文件
- `run_llm_provider_config_checks.py`
- `run_customer_service_brain_contract_checks.py`
- `run_customer_service_multi_session_scheduler_checks.py`
- `run_workflow_logic_checks.py`
- `run_brain_first_static_architecture_audit.py`
- 小样本真实 LLM：Kimi 主链路 + DeepSeek 备用配置下的 Brain 回复审计

## 验收标准

- Kimi 返回 Markdown fenced JSON 时，不触发客户可见本地兜底，能被解析为 BrainPlan。
- DeepSeek v4 Flash fallback 配置可保存、可测试、可在 failover 中保持真实 provider/model。
- 前端展示主用 Kimi、备用 DeepSeek v4 Flash 和适配状态。
- Brain First 静态审计仍通过。
- 所有客户可见回复所有权仍归 `customer_service_brain`。
