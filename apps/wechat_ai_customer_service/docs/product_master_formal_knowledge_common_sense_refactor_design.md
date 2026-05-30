# 商品库 / 正式知识 / LLM常识层边界与代码收束方案

## 目标

本方案用于把微信智能客服的商品事实、正式知识、AI经验池和LLM常识推理重新收束到清晰层级，避免测试车型、历史话术或散落在路由代码里的临时规则干扰真实商用商品库。

核心目标：

1. 商品库优先级最高。
2. 正式知识优先级次之。
3. LLM常识层只做受约束的泛化分析，不提供商品事实。
4. AI经验池只做历史经验、问法理解和话术风格参考，不覆盖商品库和正式知识。
5. 路由代码不再保存具体车型、价格、库存等业务事实。

## 非目标

本方案不改变RPA操控微信、悬浮球、键鼠锁、微信窗口识别等执行层逻辑。

本方案不重做知识库后台UI，只定义运行时边界和后续必要校验。

本方案不要求立刻删除历史数据，但要求历史数据不能作为商品事实参与当前回复。

## 当前问题

当前系统主结构已经把商品主数据拆到了 `product_master`，但仍有几个隐患：

1. `realtime_reply_router.py` 中存在具体车型、品牌、车型组合比较话术。
2. 某些测试车型词既用于意图识别，也可能影响推荐排序和回复内容。
3. `products` 作为运行时 evidence 名称容易和普通正式知识混淆。
4. AI经验池和正式知识都可能包含历史车型/价格文本，如果缺少后置约束，LLM可能把历史内容当成当前事实。
5. LLM通用分析能力已经在实际工作中被使用，但没有单独命名为一层，导致泛化判断散落在路由、提示词和兜底话术里。

## 目标层级

### 1. 商品库层

代码入口：

- `product_master/items`
- `ProductMasterStore`
- `KnowledgeRuntime.list_items("products")`

权威范围：

- 商品名称
- 品牌/车型/别名/SKU
- 年份
- 价格
- 库存/是否可售
- 公里数
- 车况摘要
- 门店/城市/可看车状态
- 商品标签和结构化属性

规则：

- 商品事实只能来自商品库。
- 任何正式知识、AI经验池、LLM常识都不能覆盖商品库字段。
- 商品库缺失时，不能编造具体现车、价格、公里数、库存。
- 如果正式知识或RAG里出现不同价格/库存，以商品库为准。

### 2. 正式知识层

代码入口：

- `knowledge_bases/policies`
- `knowledge_bases/erp_exports`
- `product_item_knowledge/<product_id>/faq`
- `product_item_knowledge/<product_id>/rules`
- `product_item_knowledge/<product_id>/explanations`
- 云端共享公共知识缓存中已授权的正式知识

权威范围：

- 交易流程
- 金融/贷款边界
- 检测报告说明
- 售后/质保/过户/试驾规则
- 公司主体信息
- 门店服务规则
- 某个商品的专属FAQ、解释、注意事项

规则：

- 正式知识优先级低于商品库，高于AI经验池和LLM常识。
- 商品专属正式知识必须绑定 `product_id`。
- 商品专属正式知识可以解释商品库字段，但不能重写价格、库存、公里数、是否可售等商品库事实。
- 普通正式知识不应保存当前在售商品事实。

### 3. 候选知识层

代码入口：

- `review_candidates`
- 候选审核流程

权威范围：

- 待人工确认的潜在正式知识。

规则：

- 候选知识默认不参与客户可见回复的权威判断。
- 候选知识必须人工审核后才能进入正式知识。
- 候选知识不能直接写商品库；商品资料必须走商品库导入/维护入口。

### 4. AI经验池

代码入口：

- `rag_experience`
- `rag_chunks`
- `style_memory`
- 历史聊天样本

权威范围：

- 历史有效问法
- 销售沟通风格
- 客户关注点
- 常见异议处理方式
- 可复用话术结构

规则：

- AI经验池不是商品事实源。
- AI经验池不是正式业务规则源。
- RAG可以帮助系统更像真人地表达，但不能决定当前有哪些车、多少钱、是否可售。
- RAG中出现车型、价格、库存时，默认视为历史文本，只能做风格参考。

### 5. LLM常识层

新增逻辑层，建议实现为 `workflows/llm_common_sense_layer.py`。

权威范围：

- 通用行业常识
- 泛化取舍分析
- 客户问题理解
- 明确建议能力
- 表达组织能力

允许内容示例：

- “市区停车多，SUV通常比小车更有停车压力。”
- “二手车不能只看年份，还要看公里数、检测报告、保养记录。”
- “客户明确要求三选一时，应给出明确优先级，而不是模棱两可。”
- “预算有限时，优先考虑车况透明、后期维护成本和保有量。”

禁止内容示例：

- “推荐2021款凯美瑞，价格8.98万。”
- “这台车库存还在。”
- “这台车无事故。”
- “这款一定比另一款好。”
- “贷款一定能批。”

规则：

- LLM常识层不能输出商品事实。
- LLM常识层不能覆盖商品库和正式知识。
- LLM常识层可以在没有商品事实冲突时，给出泛化分析和明确建议。
- LLM常识层给出的建议必须带有边界，如“具体到某台车仍看商品库/检测报告/实车”。

## 实时回答优先级

### 商品事实类问题

优先级：

1. 商品库
2. 商品专属正式知识
3. 普通正式知识
4. AI经验池
5. LLM常识层

规则：

- 车型、价格、库存、公里数、年份、车况、门店状态只能取商品库。
- 商品库没有对应商品时，回复应转为“当前库里没匹配到这款现车，我按预算和用途帮您筛在售车”。

### 政策规则类问题

优先级：

1. 正式知识
2. 商品库中的相关结构化字段
3. AI经验池
4. LLM常识层

规则：

- 金融、合同、售后、检测、过户、到店安排等必须以正式知识为准。
- 如果正式知识缺失且问题涉及承诺边界，转人工或保守回复。

### 泛化分析类问题

优先级：

1. LLM常识层
2. AI经验池
3. 正式知识
4. 商品库候选

规则：

- 例如“轿车、SUV、MPV怎么选”“我这个预算家用怎么取舍”。
- 可以使用常识层给出明确建议。
- 一旦提到具体现车、价格、库存，必须回到商品库。

### 话术风格类问题

优先级：

1. AI经验池 / style memory
2. LLM常识层
3. 正式知识
4. 商品库

规则：

- RAG只改表达，不改事实。
- 最终回复必须经过事实守卫。

## 代码修改方案

### 第一章：新增权威层模型

新增文件：

- `apps/wechat_ai_customer_service/workflows/evidence_authority.py`

建议职责：

- 定义 evidence authority 枚举。
- 给每条 evidence 标注来源层级。
- 提供统一优先级排序。
- 提供冲突处理策略。

建议接口：

```python
class AuthorityLevel(str, Enum):
    PRODUCT_MASTER = "product_master"
    FORMAL_KNOWLEDGE = "formal_knowledge"
    PRODUCT_SCOPED_FORMAL = "product_scoped_formal"
    CANDIDATE_KNOWLEDGE = "candidate_knowledge"
    RAG_EXPERIENCE = "rag_experience"
    LLM_COMMON_SENSE = "llm_common_sense"
    STYLE_MEMORY = "style_memory"


def classify_evidence(item: dict[str, Any]) -> AuthorityLevel:
    ...


def authority_rank(level: AuthorityLevel, *, fact_type: str) -> int:
    ...


def sort_evidence_by_authority(items: list[dict[str, Any]], *, fact_type: str) -> list[dict[str, Any]]:
    ...
```

验收：

- 商品库 evidence 必须始终排在正式知识前。
- RAG和style memory不能在商品事实排序中排到商品库前面。

### 第二章：新增动态商品词汇层

新增文件：

- `apps/wechat_ai_customer_service/workflows/product_vocabulary.py`

目标：

- 从商品库实时生成品牌、车型、别名、车身类型、能源类型、价格区间等词汇。
- 替代 `realtime_reply_router.py` 中写死的具体车型/品牌词表。

建议接口：

```python
def load_product_vocabulary(*, tenant_id: str | None = None) -> dict[str, set[str]]:
    ...


def product_vocab_contains(text: str, *, vocabulary: dict[str, set[str]]) -> bool:
    ...


def product_terms_for_prompt(*, tenant_id: str | None = None, limit: int = 80) -> list[str]:
    ...
```

规则：

- 具体车型词只能从商品库字段和 aliases 派生。
- 通用车类词可以保留在平台常识层，如“轿车/SUV/MPV/新能源/油车/混动”。
- 测试车型不得作为平台通用词写死。

需要替换：

- `COMMON_VEHICLE_BRAND_OR_MODEL_TERMS`
- `CONCRETE_USED_CAR_MODEL_TERMS`
- `USED_CAR_PRODUCT_TERMS` 中的具体品牌/车型部分
- 车型组合专项判断，如“奇骏 vs H6”“高尔夫 vs 昂克赛拉”

### 第三章：新增LLM常识层

新增文件：

- `apps/wechat_ai_customer_service/workflows/llm_common_sense_layer.py`

目标：

- 把散落在路由里的泛化分析收进单独层。
- 常识层只输出“分析框架/取舍建议/表达策略”，不输出商品事实。

建议数据结构：

```python
@dataclass
class CommonSenseGuidance:
    applied: bool
    topic: str
    guidance_points: list[str]
    clear_recommendation_allowed: bool
    forbidden_fact_types: list[str]
    boundary_note: str
```

建议接口：

```python
def build_common_sense_guidance(
    *,
    customer_message: str,
    conversation_context: dict[str, Any],
    product_vocabulary: dict[str, set[str]],
) -> CommonSenseGuidance:
    ...


def common_sense_prompt_fragment(guidance: CommonSenseGuidance) -> dict[str, Any]:
    ...
```

允许迁入内容：

- 轿车/SUV/MPV取舍
- 油耗/停车/通勤/家用/接娃/老人乘坐/后备箱装载等泛化判断
- “明确三选一时给明确建议”的回答策略
- “二手车优先看车况、检测报告、公里数、保养记录”的泛化原则
- “不确定商品事实时不要编造，转回商品库或请客户补充预算/用途”的策略

不允许迁入内容：

- 具体车型组合比较模板
- 当前价格、库存、公里数
- 某台车车况承诺
- 门店状态

### 第四章：重构实时路由

修改文件：

- `apps/wechat_ai_customer_service/workflows/realtime_reply_router.py`

修改目标：

- 从“车型硬编码路由”改成“商品库动态词汇 + 通用常识主题路由”。

具体修改：

1. 删除具体车型/品牌硬编码词表。
2. 保留通用意图词，如预算、推荐、通勤、家用、油耗、车况、检测报告。
3. 引入 `product_vocabulary.py` 动态判断客户是否提到商品库内商品。
4. 引入 `llm_common_sense_layer.py` 生成泛化分析指导。
5. 本地快速回复只允许使用商品库候选生成具体推荐。
6. 如果没有商品库候选，不能输出具体车型，只能泛化分析或追问。

### 第五章：重构证据包

修改文件：

- `apps/wechat_ai_customer_service/workflows/reply_evidence_builder.py`
- `apps/wechat_ai_customer_service/adapters/knowledge_loader.py`
- `apps/wechat_ai_customer_service/workflows/evidence_resolver.py`

目标：

- evidence pack 明确分层。
- 商品库与正式知识分开传给LLM。
- RAG和常识层不得混入商品事实 evidence。

建议结构：

```json
{
  "authority_order": [
    "product_master",
    "formal_knowledge",
    "product_scoped_formal",
    "rag_experience",
    "llm_common_sense"
  ],
  "product_master": {
    "matched_products": [],
    "catalog_candidates": []
  },
  "formal_knowledge": {
    "policies": {},
    "faq": [],
    "product_scoped": []
  },
  "rag_experience": {
    "hits": [],
    "style_only": true
  },
  "llm_common_sense": {
    "guidance_points": [],
    "forbidden_fact_types": ["price", "stock", "mileage", "condition_claim"]
  }
}
```

兼容期可以保留旧字段：

- `knowledge.evidence.products`
- `knowledge.evidence.catalog_candidates`
- `knowledge.rag_evidence`

但新代码应优先读取分层字段。

### 第六章：重构LLM合成提示词

修改文件：

- `apps/wechat_ai_customer_service/workflows/llm_reply_synthesis.py`

目标：

- 在系统提示中写死权威优先级。
- LLM必须区分商品事实、正式规则、AI经验池、常识分析。

提示词要求：

1. 商品事实只来自 `product_master`。
2. 正式知识可以解释流程和政策，但不能覆盖商品事实。
3. RAG只提供风格和历史处理经验。
4. LLM常识只用于泛化分析。
5. 回复中出现具体商品名、价格、库存、公里数、车况承诺，必须有商品库 evidence。
6. 如果客户问商品库没有的车型，不要假装有现车。

### 第七章：新增客户可见回复事实守卫

修改文件：

- `apps/wechat_ai_customer_service/workflows/llm_reply_guard.py`
- `apps/wechat_ai_customer_service/workflows/final_visible_llm_polish.py`

新增能力：

- 检查回复中出现的具体商品名、价格、库存、公里数是否能在商品库 evidence 中找到。
- 检查RAG/常识层有没有带入未经商品库授权的商品事实。
- 对不合规回复执行以下动作之一：
  1. 删除未经授权的具体事实，改成泛化表达。
  2. 转人工。
  3. 要求LLM重写。

建议接口：

```python
def validate_visible_reply_authority(
    *,
    reply_text: str,
    evidence_pack: dict[str, Any],
) -> dict[str, Any]:
    ...
```

验收：

- RAG里有旧车型，商品库没有时，回复不得出现该旧车型作为当前推荐。
- 正式知识里有旧价格，商品库价格更新后，回复必须使用商品库价格。
- 常识层可以说“这类SUV停车压力更大”，但不能说“这台SUV库存还在”。

### 第八章：正式知识写入校验

修改文件：

- `apps/wechat_ai_customer_service/workflows/generate_review_candidates.py`
- 知识后台保存接口相关服务

目标：

- 防止商品事实继续进入普通正式知识。

校验规则：

- 如果候选内容包含商品名称、价格、库存、公里数、配置表，并且目标 category 是普通正式知识，则提示改入商品库或商品专属知识。
- 如果是商品专属FAQ/解释，必须绑定 `product_id`。
- 如果是政策/流程，可以进入正式知识。

### 第九章：清理历史硬编码

重点清理文件：

- `apps/wechat_ai_customer_service/workflows/realtime_reply_router.py`
- `apps/wechat_ai_customer_service/workflows/customer_intent_assist.py`
- `apps/wechat_ai_customer_service/adapters/knowledge_loader.py`
- `apps/wechat_ai_customer_service/workflows/llm_reply_synthesis.py`

清理策略：

1. 具体车型、品牌、车型组合比较，迁移到测试 fixtures 或商品库 aliases。
2. 通用判断迁入 `llm_common_sense_layer.py`。
3. 风格表达迁入 RAG/style memory，不留在路由硬编码。
4. 高风险边界继续保留在平台安全层或正式知识，不放入常识层。

静态扫描规则：

- 非测试文件中不应出现测试车型硬编码。
- 允许出现的通用词包括“轿车/SUV/MPV/新能源/油车/混动/预算/车况/检测报告”等。
- 允许商品库文件自身出现车型。

## 测试方案

### 1. 商品库优先级测试

场景：

- 商品库中某车价格为 A。
- 正式知识/RAG中历史价格为 B。

预期：

- 回复只能使用 A。
- 如果引用 B，测试失败。

### 2. 正式知识优先级测试

场景：

- 客户问贷款/过户/质保。
- 商品库只有商品字段，没有政策说明。
- 正式知识有政策。

预期：

- 回复使用正式知识。
- 不用AI经验池覆盖正式政策。

### 3. RAG旧车型污染测试

场景：

- RAG中有“凯美瑞/雅阁”等旧测试车型。
- 商品库已换成真实在售车辆，不含这些车型。

预期：

- 客服不得把旧车型作为当前现车推荐。
- 可以使用类似“先按预算和用途筛”的历史话术结构。

### 4. LLM常识层测试

场景：

- 客户问“市区通勤，轿车和SUV怎么选？”
- 商品库没有强匹配商品。

预期：

- 回复可以给出泛化建议。
- 不出现具体车名、价格、库存。

### 5. 动态商品词汇测试

场景：

- 商品库新增一个新车型 alias。
- 不修改代码。

预期：

- 路由能识别新车型。
- 推荐候选来自新商品库。

### 6. 商品事实守卫测试

场景：

- LLM mock 返回一个商品库不存在的车型和价格。

预期：

- guard 拦截或重写。
- 事件日志记录 `ungrounded_product_fact_blocked`。

### 7. 静态硬编码测试

新增测试：

- `apps/wechat_ai_customer_service/tests/run_knowledge_authority_boundary_checks.py`

检查：

- 业务运行代码中没有测试车型硬编码。
- 商品事实字段只从 `product_master` 或 evidence product candidates 读取。
- 常识层输出不包含价格、库存、公里数承诺。

## 开发顺序

### 阶段一：文档和静态审计

1. 以本文件为边界定义。
2. 扫描所有具体车型硬编码。
3. 列出保留、迁移、删除清单。

验收：

- 得到完整硬编码清单。
- 明确每个项归属：商品库、常识层、RAG风格、测试fixture。

### 阶段二：新增基础模块

1. 新增 `evidence_authority.py`。
2. 新增 `product_vocabulary.py`。
3. 新增 `llm_common_sense_layer.py`。

验收：

- 单测覆盖动态商品词汇和常识层禁区。

### 阶段三：路由收束

1. 改造 `realtime_reply_router.py`。
2. 删除车型硬编码。
3. 用商品库动态词汇和常识层替代。

验收：

- 旧测试车型不在商品库时不会被推荐。
- 商品库新增车型无需改代码即可识别。

### 阶段四：证据包和LLM合成改造

1. 分层 evidence pack。
2. 更新 LLM prompt。
3. 更新 compact/slim evidence 逻辑。

验收：

- LLM输入中能清楚看到商品库、正式知识、RAG、常识层边界。
- 商品事实只来自商品库分区。

### 阶段五：事实守卫

1. 新增客户可见回复 authority guard。
2. 拦截未授权商品事实。
3. 更新最终润色约束。

验收：

- mock LLM乱编车型/价格会被拦截。

### 阶段六：正式知识写入校验

1. 防止商品事实进入普通正式知识。
2. 商品专属知识必须绑定商品ID。
3. 候选知识进入正式知识前做分类提醒。

验收：

- 导入商品事实时进入商品库。
- 普通政策/流程仍能进入正式知识。

### 阶段七：全量测试和实盘前验证

1. 静态测试。
2. 工作流逻辑测试。
3. LLM合成测试。
4. 商品库动态更新测试。
5. 文件传输助手实盘测试。

验收：

- 商品库优先级最高。
- 正式知识优先级次之。
- RAG和LLM常识不再污染商品事实。
- 回复质量保持自然、明确、简洁。

## 最终验收标准

1. 代码中无具体测试车型硬编码参与生产路由。
2. 商品推荐只来自商品库和商品库候选。
3. 商品事实冲突时，商品库必胜。
4. 正式知识只负责政策、规则、解释和商品专属说明。
5. LLM常识层可以给明确分析，但不能提供具体商品事实。
6. AI经验池只影响话术和问法理解，不覆盖权威知识。
7. 客户可见回复经过事实守卫。
8. 商品库更新后，无需改代码即可生效。
