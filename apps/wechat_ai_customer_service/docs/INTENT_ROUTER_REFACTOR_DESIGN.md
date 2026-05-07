# 意图路由器重构设计文档

## 1. 背景与问题分析

当前决策链的问题：

```
maybe_capture_customer_data()  ← 关键词匹配（最高优先级，阻断后续所有流程）
maybe_match_product_knowledge()  ← 被阻断
maybe_analyze_intent()           ← heuristic 建议，不参与主决策
maybe_build_rag_reply()          ← 被 data_capture 阻断
maybe_apply_llm_reply()          ← 被 data_capture 阻断
maybe_synthesize_reply()         ← 被 data_capture 阻断
```

**致命缺陷**：客户数据捕获在决策链最前端，`has_customer_data_signal()` 用关键词列表判断"这是不是客户资料"。一旦命中，直接返回"缺姓名/电话"的话术，后续的商品匹配、RAG、LLM 全部走不到。价格询问"凯美瑞多少钱"因含"多少钱"被误判为客户数据收集意图。

## 2. 设计目标

1. **LLM 意图分析作为第一层路由**：所有消息先由 DeepSeek flash 模型判断意图，再按意图分流
2. **数据库匹配优先，LLM 润色**：产品咨询意图 → 匹配商品知识库 → LLM 润色生成回复
3. **RAG/规则约束，LLM 思考回答**：一般咨询意图 → RAG 经验检索 + 安全规则 → LLM 组织语言
4. **三层降级**：LLM 意图 → 显式关键词兜底 → 现有规则匹配

## 3. 架构变更

### 3.1 新决策链

```
1. build_evidence_pack()              ← 构建证据包（产品知识、FAQ、政策、RAG）
2. llm_intent_router.route_intent()   ← LLM flash 分析意图（1-2秒）
3. 按意图路由：
   ├── customer_data_provide → maybe_capture_customer_data() → 回复
   ├── product_inquiry       → maybe_match_product_knowledge() → build_evidence_pack(product_focused) → maybe_synthesize_reply()
   ├── handoff_request       → 直接转人工
   ├── greeting/small_talk   → maybe_build_rag_reply() → maybe_synthesize_reply()
   └── general_chat/unclear  → maybe_build_rag_reply() → maybe_synthesize_reply()
4. 兜底：如果 LLM 意图分析失败/超时，降级到现有关键词规则
```

### 3.2 新增文件

| 文件 | 说明 |
|------|------|
| `workflows/llm_intent_router.py` | LLM 意图分析引擎 |
| `tests/test_intent_router.py` | 意图路由器单元测试 |

### 3.3 修改文件

| 文件 | 修改内容 |
|------|----------|
| `workflows/listen_and_reply.py` | 重构 process_target 决策链；引入 intent_router；修改 decide_reply_with_data_capture 为 intent-driven |
| `workflows/customer_data_capture.py` | 移除 business_intent_keywords；maybe_capture_customer_data 接收意图标签而非主动判断 |
| `workflows/llm_reply_synthesis.py` | 移除 data_capture.is_customer_data 阻断逻辑；证据包加入 intent 信息 |
| `workflows/rag_answer_layer.py` | 移除 data_capture.is_customer_data 阻断逻辑 |
| `workflows/knowledge_loader.py` | detect_intent_tags 保留但降低权重，新增 intent_from_router 覆盖 |

## 4. 详细设计

### 4.1 新增 `llm_intent_router.py`

#### 数据模型

```python
@dataclass(frozen=True)
class IntentRouteResult:
    intent: str  # customer_data_provide | product_inquiry | general_chat | greeting | handoff_request | unclear
    confidence: float
    reasoning: str
    entities: dict[str, str]
    source: str  # "llm" | "keyword_fallback" | "cache"
```

#### 核心函数

```python
def route_intent(
    combined: str,
    config: dict[str, Any],
    evidence_pack: dict[str, Any] | None = None,
    target_state: dict[str, Any] | None = None,
) -> IntentRouteResult:
    """分析客户消息意图，返回路由结果。

    优先级：
    1. 检查 target_state 中的意图缓存（同一会话 60 秒内复用）
    2. 调用 DeepSeek flash 模型进行意图分析
    3. LLM 失败/超时时降级到关键词兜底
    """


def _call_llm_intent_analysis(
    combined: str,
    evidence_pack: dict[str, Any] | None,
    settings: dict[str, Any],
) -> dict[str, Any]:
    """调用 DeepSeek API 进行意图分析。"""


def _keyword_fallback_intent(combined: str) -> IntentRouteResult:
    """LLM 失败时的关键词兜底判断。"""
```

#### Prompt 设计

**System Prompt:**

```
你是微信AI客服的意图分析专家。请根据客户消息判断其真实意图。

分类标准：
- customer_data_provide：客户明确在提供/更新自己的姓名、电话、地址、联系方式、收货信息、个人资料。例如："我叫张三，电话13812345678"、"收货地址是xxx"。
- product_inquiry：客户询问产品/商品信息，包括价格、型号、配置、车况、库存、规格等。例如："凯美瑞多少钱"、"这车油耗怎么样"。
- handoff_request：客户明确要求转人工、找销售、找顾问。例如："找人工"、"我要真人客服"。
- greeting：客户打招呼、寒暄。例如："你好"、"在吗"。
- general_chat：其他业务咨询、闲聊、表达需求但不属于以上类别。例如："有什么推荐"、"预算10万"。
- unclear：消息过于模糊，无法判断意图。

重要规则：
1. 仅询问价格、询问车型不属于提供客户资料，必须标记为 product_inquiry。
2. 消息中同时包含产品询问和客户资料时，以客户资料为主（customer_data_provide）。
3. 不要过度推断，没有明确客户资料信号时不要标记为 customer_data_provide。

请输出严格JSON格式，不要有任何其他文字：
{
  "intent": "customer_data_provide|product_inquiry|general_chat|greeting|handoff_request|unclear",
  "confidence": 0.0-1.0,
  "reasoning": "判断原因的简短说明",
  "entities": {"提取的实体键": "实体值"}
}
```

**User Prompt:**

```json
{
  "customer_message": "{combined}",
  "evidence_summary": {
    "matched_products": [...],
    "matched_faq": [...],
    "intent_tags": [...]
  }
}
```

#### 调用参数

- model: deepseek-v4-flash
- max_tokens: 256
- temperature: 0.1
- timeout: 5 秒
- response_format: {"type": "json_object"}

### 4.2 修改 `listen_and_reply.py`

#### `process_target` 重构

当前逻辑（简化）：
```python
data_capture = maybe_capture_customer_data(...)
product_knowledge = maybe_match_product_knowledge(...)
decision = decide_reply_with_data_capture(combined, rules, config, data_capture, product_knowledge)
```

新逻辑：
```python
# 1. 构建证据包（用于意图分析和后续合成）
evidence_pack = build_evidence_pack(combined, context=conversation_context)

# 2. LLM 意图路由
intent_result = route_intent(combined, config, evidence_pack, target_state)

# 3. 按意图分支处理
if intent_result.intent == "customer_data_provide":
    data_capture = maybe_capture_customer_data(
        config=config, target_state=target_state, target=target, batch=batch,
        combined=combined, write_data=write_data,
        intent_result=intent_result,  # 新增参数
    )
    decision = decide_reply_for_customer_data(combined, config, data_capture)

elif intent_result.intent == "product_inquiry":
    product_knowledge = maybe_match_product_knowledge(config, target_state, combined, data_capture={"is_customer_data": False})
    update_conversation_context(target_state, product_knowledge)
    # 构建产品聚焦的证据包，送入 LLM 合成
    decision = decide_reply_for_product_inquiry(combined, rules, config, product_knowledge, evidence_pack)

elif intent_result.intent == "handoff_request":
    decision = ReplyDecision(
        reply_text=handoff_acknowledgement_text(config),
        rule_name="handoff_request",
        matched=True, need_handoff=True,
        reason="customer_explicit_handoff",
    )

else:  # general_chat, greeting, unclear
    product_knowledge = maybe_match_product_knowledge(config, target_state, combined, data_capture={"is_customer_data": False})
    decision = decide_reply(combined, rules)  # 现有规则匹配

# 4. 后续流程保持不变：rag_reply → llm_reply → llm_synthesis
```

#### 新增函数

```python
def decide_reply_for_customer_data(
    combined: str,
    config: dict[str, Any],
    data_capture: dict[str, Any],
) -> ReplyDecision:
    """客户数据提供意图的回复决策。"""


def decide_reply_for_product_inquiry(
    combined: str,
    rules: dict[str, Any],
    config: dict[str, Any],
    product_knowledge: dict[str, Any] | None,
    evidence_pack: dict[str, Any],
) -> ReplyDecision:
    """产品咨询意图的回复决策。先尝试规则匹配，如果规则未命中且有商品知识，则准备送入 LLM 合成。"""
```

### 4.3 修改 `customer_data_capture.py`

#### `maybe_capture_customer_data` 签名变更

```python
def maybe_capture_customer_data(
    config: dict[str, Any],
    target_state: dict[str, Any],
    target: TargetConfig,
    batch: list[dict[str, Any]],
    combined: str,
    write_data: bool,
    intent_result: IntentRouteResult | None = None,  # 新增
) -> dict[str, Any]:
```

逻辑变更：
- 如果传入 `intent_result` 且 `intent_result.intent == "customer_data_provide"`，执行字段提取
- 如果未传入 `intent_result`（旧调用），降级到显式关键词判断
- **移除 `has_customer_data_signal` 中的 `business_intent_keywords`**
- 保留 `extract_customer_data` 的字段提取能力

#### `has_customer_data_signal` 变更

```python
def has_customer_data_signal(text: str, fields: dict[str, str]) -> bool:
    """判断消息是否包含客户资料信号。

    仅用于 LLM 失败时的兜底判断。不再使用 business_intent_keywords，
    只保留显式关键词和已提取字段的判断。
    """
    if fields.get("phone") or fields.get("name") or fields.get("address"):
        return True
    explicit_keywords = [
        "客户资料", "客户信息", "收货信息", "联系方式",
        "联系人", "收件人", "收货地址", "联系电话", "手机号",
    ]
    if any(keyword in text for keyword in explicit_keywords):
        return True
    return False
```

### 4.4 修改 `llm_reply_synthesis.py`

#### `maybe_synthesize_reply` 变更

移除以下阻断逻辑：
```python
# 删除这段
if data_capture.get("is_customer_data"):
    payload["reason"] = "customer_data_decision_is_deterministic"
    return payload
```

原因：意图分析已经分流，到达 LLM 合成的消息不会再是 customer_data_provide。

#### `build_reply_evidence_pack` 增强

在证据包中加入意图信息：
```python
evidence_pack["intent_analysis"] = {
    "intent": intent_result.intent,
    "confidence": intent_result.confidence,
    "reasoning": intent_result.reasoning,
    "entities": intent_result.entities,
}
```

### 4.5 修改 `rag_answer_layer.py`

#### `maybe_build_rag_reply` 变更

移除以下阻断逻辑：
```python
# 删除这段
if data_capture.get("is_customer_data"):
    payload["reason"] = "customer_data_decision_is_deterministic"
    return payload
```

## 5. 降级策略

```
LLM 意图分析（首选，1-2秒）
    ↓ 成功
按意图路由
    ↓ 失败/超时（5秒）
显式关键词兜底（"客户资料："、"姓名："、"电话："等一眼能看出来的）
    ↓ 未命中
现有 decide_reply() 关键词规则匹配（保持向后兼容）
    ↓ 仍未命中
默认回复（fallback）
```

## 6. 性能考量

| 指标 | 当前 | 修改后 |
|------|------|--------|
| 客户数据判断 | 本地正则（0ms） | LLM flash（~1-2s） |
| 整体延迟 | 快但错 | 稍慢但准 |
| 成本 | 无 | 每次请求约 0.001-0.003 元 |

优化措施：
1. 意图结果缓存：同一会话 60 秒内复用（存储在 `target_state["cached_intent"]` 中）
2. 使用 deepseek-v4-flash（最便宜最快的模型）
3. max_tokens=256，只输出 JSON，控制 token 消耗
4. 超时 5 秒，失败立即降级

## 7. 测试计划

### 7.1 单元测试

测试 `llm_intent_router.py`：
- `_keyword_fallback_intent` 对各种消息的兜底判断
- `_parse_intent_json` 对 LLM 返回 JSON 的解析
- 缓存命中/过期逻辑

### 7.2 集成测试

运行现有测试套件：
- `run_workflow_logic_checks.py`
- `run_boundary_matrix_checks.py`
- `run_delivery_boundary_checks.py`

### 7.3 边界测试矩阵

| 场景 | 输入 | 期望意图 |
|------|------|----------|
| 纯价格询问 | "凯美瑞多少钱" | product_inquiry |
| 纯车型询问 | "有本田雅阁吗" | product_inquiry |
| 提供客户资料 | "我叫张三，电话13812345678" | customer_data_provide |
| 问候 | "你好" | greeting |
| 转人工 | "找销售" | handoff_request |
| 混合：价格+资料 | "凯美瑞多少钱，我叫张三电话13812345678" | customer_data_provide |
| 模糊 | "在吗" | greeting / unclear |
| 预算咨询 | "预算10万有什么推荐" | product_inquiry |
| 车况询问 | "这车有没有事故" | product_inquiry |
| 金融咨询 | "可以分期吗" | general_chat |

## 8. 实盘测试计划（文件传输助手）

### 8.1 测试步骤

1. 启动 listener，目标设为"文件传输助手"
2. 从手机微信向"文件传输助手"发送测试消息
3. 观察 listener 日志中的决策过程
4. 验证回复内容是否符合预期

### 8.2 测试用例

| # | 测试消息 | 期望行为 | 验证点 |
|---|----------|----------|--------|
| 1 | "你好" | 问候回复 | 不走客户数据捕获 |
| 2 | "凯美瑞，3年内的一般多少钱" | 产品咨询 → 知识库匹配 → LLM 润色 | **核心验证：不再误判为客户数据** |
| 3 | "我叫张三，电话13812345678" | 客户数据捕获 → 确认已记录 | 正确识别为客户资料提供 |
| 4 | "预算10万，有什么推荐" | 产品咨询 → 知识库匹配 | 正确识别为产品咨询 |
| 5 | "这车有事故吗" | 产品咨询 → 知识库/LLM 回答 | 正确识别为车况咨询 |
| 6 | "找人工" | 直接转人工 | 正确识别为 handoff |
| 7 | "凯美瑞多少钱，我叫张三" | 混合意图 → 优先客户数据 | 正确识别为 customer_data_provide |
| 8 | "在吗" | 问候回复 | 正确识别为 greeting |
| 9 | "可以分期付款吗" | general_chat → RAG/规则 → LLM | 正确识别为一般咨询 |
| 10 | "之前看的那个车还在吗" | 上下文相关咨询 | 正确识别为 product_inquiry |

### 8.3 通过标准

- 测试 #2（价格询问）**必须**通过：不再触发客户数据收集
- 测试 #3（资料提供）**必须**通过：正确记录客户资料
- 其余测试允许 1-2 个意图分类偏差，但回复内容必须合理
- 无崩溃、无 FileNotFoundError、无 PermissionError

## 9. 实施步骤

### Phase 1：新增 llm_intent_router.py（预计 2-3 轮编辑）
1. 新建 `llm_intent_router.py`：数据模型、Prompt 构建、LLM 调用、结果解析、缓存逻辑
2. 新建 `test_intent_router.py`：单元测试
3. 验证 `route_intent` 对测试用例的兜底判断正确

### Phase 2：重构 listen_and_reply.py（预计 2-3 轮编辑）
4. 修改 `process_target`：引入 `route_intent`，重构决策链
5. 新增 `decide_reply_for_customer_data` 和 `decide_reply_for_product_inquiry`
6. 修改 `decide_reply_with_data_capture` 为意图驱动版本

### Phase 3：修改 customer_data_capture.py（预计 1 轮编辑）
7. 移除 `business_intent_keywords`
8. 修改 `maybe_capture_customer_data` 接收 `intent_result`

### Phase 4：移除阻断逻辑（预计 1 轮编辑）
9. 修改 `llm_reply_synthesis.py`：移除 `data_capture.is_customer_data` 阻断
10. 修改 `rag_answer_layer.py`：移除 `data_capture.is_customer_data` 阻断

### Phase 5：全量测试（预计 1-2 轮）
11. 运行现有测试套件
12. 修复回归问题

### Phase 6：实盘测试（预计 2-3 轮）
13. 启动 listener（文件传输助手）
14. 执行 10 个测试用例
15. 根据结果调整 Prompt 或兜底逻辑
16. 确认通过后交付
