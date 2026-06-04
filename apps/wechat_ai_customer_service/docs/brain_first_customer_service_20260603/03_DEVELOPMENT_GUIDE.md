# Brain First 客服大脑开发指南

## 1. 开发策略

本次开发采用“主脑上移、旧能力降级复用”的策略。

不推倒重做：

- 保留 RPA 捕获和发送。
- 保留多会话调度。
- 保留最终润色。
- 保留商品库/正式知识库/AI经验池。
- 保留 failover 和并发 LLM 池。
- 保留 guard。

重点调整：

- 把 LLM 综合回复从后置可选改为正常业务默认主路径。
- 把 RAG、本地 route、实时回复模板降级为证据、风险和兜底。
- 把最终润色保留为客户可见表达优化，而不是业务决策补丁。

## 2. 阶段一：新增 Brain Orchestrator

### 2.1 新增文件

建议新增：

```text
apps/wechat_ai_customer_service/workflows/customer_service_brain.py
apps/wechat_ai_customer_service/workflows/customer_service_brain_contract.py
```

### 2.2 职责

`customer_service_brain.py` 负责：

- 接收 BrainInput。
- 构造 Prompt。
- 调用 LLM。
- 解析 BrainPlan。
- 调用 guard。
- 返回结构化结果。

`customer_service_brain_contract.py` 负责：

- 定义 dataclass 或 TypedDict。
- 定义 answer mode。
- 定义 evidence source type。
- 定义审计字段。
- 提供轻量 schema 校验。

### 2.3 复用点

优先复用：

- `llm_reply_synthesis.py` 的 LLM 调用、模型路由、failover、profile 选择。
- `reply_evidence_builder.py` 的 evidence pack。
- `llm_reply_guard.py` 的事实与安全守卫。
- `final_visible_llm_polish.py` 的最终润色。

### 2.4 不建议做

不要把 `llm_reply_synthesis.py` 直接大改到难以回滚。更稳妥方式：

```text
customer_service_brain.py
  -> 复用 synthesis 的调用工具
  -> 独立 Brain Prompt 和 schema
  -> 独立审计结果
```

## 3. 阶段二：改造主流程

### 3.1 修改文件

```text
apps/wechat_ai_customer_service/workflows/listen_and_reply.py
```

### 3.2 旧流程保留为 fallback

保留旧链路：

```text
decide_reply
intent_assist
maybe_build_rag_reply
maybe_apply_llm_reply
decide_realtime_reply_route
maybe_build_realtime_reply
maybe_synthesize_reply
```

但在 Brain First 模式下，正常业务走：

```text
capture
clean_text
hard_precheck
build_brain_evidence_pack
run_customer_service_brain
guard
final_visible_polish
send
```

### 3.3 插入点

建议在以下信息完成后进入 Brain：

- batch 已选定。
- combined 已清洗。
- raw_capture 已写入。
- target_state 已读取。
- customer_profile 已加载。
- hard safety precheck 已完成。

Brain 应早于：

- `maybe_build_rag_reply`
- `maybe_build_realtime_reply`
- `maybe_synthesize_reply`

### 3.4 旧链路降级逻辑

Brain First 启用时：

- `maybe_build_rag_reply` 不再产出最终回复，只产出 evidence。
- `maybe_build_realtime_reply` 不再产出正常业务最终回复。
- `decide_realtime_reply_route` 只输出 route level、风险、token profile、是否需要转人工。
- 只有系统通知、硬风险、掉线、白屏、RPA异常、人工接管等场景允许本地固定回复。

## 4. 阶段三：重构 realtime route 权限

### 4.1 修改文件

```text
apps/wechat_ai_customer_service/workflows/realtime_reply_router.py
```

### 4.2 新定位

`realtime_reply_router.py` 改为：

- 风险分级。
- 速度 profile 选择。
- 是否需要 pro 模型。
- 是否需要转人工。
- 是否允许 common sense。
- 是否检测到商品事实需求。

不再负责：

- 正常业务回复正文生成。
- 推荐具体车型文本。
- 报价文本。
- 闲聊文本。

### 4.3 允许保留的本地回复

仅允许：

- 微信掉线/白屏/窗口异常通知。
- 安全护栏失败。
- 已转人工接口触发后的内部状态。
- 明确不可回复风险的极短安全话术。

这些回复仍要经过最终润色，除非是内部状态日志，不发给客户。

## 5. 阶段四：证据包升级

### 5.1 修改文件

```text
apps/wechat_ai_customer_service/workflows/reply_evidence_builder.py
apps/wechat_ai_customer_service/workflows/evidence_authority.py
```

### 5.2 新增 evidence pack v2

保留旧字段兼容，同时新增：

```text
content_basis.product_master
content_basis.formal_knowledge
content_basis.current_conversation_facts
auxiliary.common_sense_guidance
auxiliary.style_context
audit.excluded_sources
audit.authority_conflicts
```

### 5.3 AI经验池处理

AI经验池可以进入：

- `style_context`
- `ai_experience_pool_summary`
- `audit.excluded_sources`

不能进入：

- `content_basis`
- `product_master`
- `formal_knowledge`

## 6. 阶段五：Brain Prompt 与 Schema

### 6.1 Prompt 内容

Prompt 应包含：

- 角色定义。
- 权威合同。
- 当前客户消息。
- 当前会话历史摘要。
- 商品库证据。
- 正式知识证据。
- 当前会话事实。
- 常识层指导。
- 风格层指导。
- 输出 JSON schema。

### 6.2 输出结构

必须输出：

- `understanding`
- `answer_mode`
- `reply_strategy`
- `evidence_used`
- `facts_claimed`
- `reply_segments`
- `risk`
- `confidence`
- `reason`

### 6.3 JSON 解析

复用 `customer_intent_assist.parse_json_object` 或新增严格解析器。

解析失败时：

- 不直接发送 LLM 原文。
- 进入 fallback。
- 记录失败原因。
- 不盲目重试超过配置次数。

## 7. 阶段六：Guard 强化

### 7.1 修改文件

```text
apps/wechat_ai_customer_service/workflows/llm_reply_guard.py
```

### 7.2 新增校验

- `facts_claimed` 必须有权威来源。
- 回复中出现价格、公里数、年份、库存、车况时必须能回链商品库。
- 回复中出现政策承诺时必须能回链正式知识。
- `reply_segments` 不得为空。
- `reply_segments` 不得使用省略号表示截断。
- `answer_mode` 与用户问题必须相关。
- `style_context` 不得被声明为事实来源。

### 7.3 答非所问校验

新增轻量 relevance check：

```text
用户问价 -> 回复必须包含价格或解释为什么无法报价
用户要求二选一/三选一 -> 回复必须给明确优先级
用户质疑 -> 回复必须回应质疑
用户问候 -> 回复必须先回应问候
```

初期可以本地规则检测，后续可用低成本 LLM verifier。

## 8. 阶段七：最终润色调整

### 8.1 修改文件

```text
apps/wechat_ai_customer_service/workflows/final_visible_llm_polish.py
```

### 8.2 新要求

最终润色输入应包含：

- BrainPlan。
- GuardResult。
- 原始 reply_segments。
- 不可改变事实列表。
- 不可改变风险动作。

最终润色输出：

- 1-3 条客户可见短句。
- 每条完整、有独立含义。
- 不新增事实。
- 不新增承诺。
- 不改变 answer mode。

## 9. 阶段八：配置与灰度

### 9.1 新配置

```json
{
  "customer_service_brain": {
    "enabled": false,
    "mode": "off",
    "default_for_normal_business": true,
    "fallback_to_legacy_on_error": true,
    "require_final_visible_polish": true,
    "max_reply_segments": 3,
    "require_fact_claims": true,
    "legacy_local_reply_allowed_reasons": [
      "hard_safety_handoff",
      "wechat_offline",
      "white_screen",
      "rpa_focus_lost",
      "manual_handoff"
    ]
  }
}
```

### 9.2 灰度顺序

```text
shadow
hybrid_shadow
brain_first_for_file_transfer_only
brain_first_for_chejin_single_session
brain_first_for_chejin_multi_session
brain_first_default
```

## 10. 阶段九：日志和观测

每次回复记录：

- `brain.enabled`
- `brain.mode`
- `brain.answer_mode`
- `brain.evidence_used`
- `brain.facts_claimed`
- `brain.confidence`
- `guard.reason`
- `final_polish.applied`
- `latency.capture_ms`
- `latency.evidence_ms`
- `latency.brain_llm_ms`
- `latency.guard_ms`
- `latency.polish_ms`
- `latency.send_wait_ms`
- `latency.rpa_send_ms`

## 11. 完成定义

代码落地完成必须满足：

- Brain First 灰度开关可控。
- 旧链路可回滚。
- 正常业务默认进入 Brain。
- RAG 和 realtime route 不再抢答。
- 商品事实和正式政策 guard 有效。
- 所有可见回复仍最终润色。
- 多会话隔离不被破坏。
