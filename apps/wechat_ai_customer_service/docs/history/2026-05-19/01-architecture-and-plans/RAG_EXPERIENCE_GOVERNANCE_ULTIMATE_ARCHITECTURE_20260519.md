# RAG 经验治理终极架构（2026-05-19）

## 1. 背景

chejin 账号中出现大量卡片同时显示：

- “很可靠 / 系统已自动吸纳为经验，可作为RAG参考”
- “建议废弃 / 内容缺少业务价值，继续保留会增加审核噪音”

这说明当前系统把不同模块的判断并排展示，却没有统一的最终裁决。

当前冲突来源：

- `quality.band=high` 来自确定性质量评分，只说明文本证据质量较高。
- `experience_review.status=auto_kept` 来自旧自动吸纳状态。
- `ai_interpretation.recommended_action=discard` 来自AI解释器和本地 guardrail。
- 前端将这些字段直接组合展示，导致用户看到互相打架的结论。

## 2. 终极分层

```text
原始内容层
  -> RAG经验层
  -> RAG经验治理裁决层
  -> 可选：待确认知识候选层
  -> 人工审核
  -> 正式知识库
  -> 运行时回复

清洗实盘聊天
  -> RAG经验层
  -> 实盘话术风格层
  -> 治理裁决：可检索/仅风格/废弃/候选

商品主数据
  -> 商品库人工入口
  -> 运行时只读引用
```

## 3. 层级职责

### 3.1 原始内容层

只保存证据，不做业务授权。

允许来源：

- 资料上传。
- AI智能记录员选中的群聊或私聊。
- 人工导入的清洗聊天记录。
- 商品资料导入入口。

禁止：

- 文件传输助手测试内容进入学习。
- AI自回复进入学习。
- 带测试 marker 的内容进入学习。

### 3.2 RAG经验层

保存可复用的历史经验、资料摘要、聊天样本和运行时回复经验。

它回答的是：

```text
过去类似场景里，客服怎么处理过？
```

它不回答：

```text
这是不是商家正式承诺？
这台车现在多少钱？
这个库存现在是否有效？
```

### 3.3 RAG经验治理裁决层

新增终极中间层。它负责把多个模块的判断合并为一个最终结论。

输入：

- 经验状态 `status`。
- 人工审核状态 `experience_review`。
- 质量评分 `quality`。
- AI解释建议 `ai_interpretation`。
- 来源权威判断 `source_authority`。
- 污染防护判断。
- 正式知识重合判断。
- 商品主数据边界。

输出：

- `effective_state`：最终状态。
- `retrieval_allowed`：是否允许参与RAG检索。
- `promotion_allowed`：是否允许自动或手动生成候选。
- `style_allowed`：是否允许进入话术风格层。
- `final_action`：推荐动作。
- `display_label`：前端主展示文案。
- `reason`：普通用户能理解的原因。

### 3.4 待确认知识候选层

只接收治理裁决层认为值得提名的经验。

规则：

- 可以自动生成 pending candidate。
- 不允许自动应用到正式库。
- 人工审核、快照、审计、新加入标识仍然必需。
- 商品主数据候选仍然禁止从 RAG经验生成。

### 3.5 正式知识库

保存稳定、通用、可审计、人工确认的知识。

允许：

- 人工新增。
- 人工审核候选后应用。
- 明确声明为正式模板且通过来源检查的导入文件。

禁止：

- 未经人工改写的真实聊天样本。
- 动态车型推荐。
- 价格、库存、车源事实。
- 测试内容和文件传输助手内容。

### 3.6 商品主数据层

保存确定性事实，例如车型、价格、库存、配置、里程、车况摘要。

唯一写入来源：

- 商品库人工维护。
- 授权商品主数据导入。

禁止：

- RAG经验晋升。
- 候选知识晋升。
- 真实聊天提取。
- 话术风格层反向写入。

### 3.7 实盘话术风格层

只学习表达方式，不学习事实。

可学习：

- 称呼节奏。
- 接住情绪。
- 追问顺序。
- 边界缓冲话术。
- 非机械化表达变体。

不可学习：

- 价格。
- 库存。
- 车型事实。
- 贷款包过。
- 合同发票承诺。
- 事故水泡火烧等确定性车况承诺。

## 4. 最终裁决优先级

治理裁决必须按以下优先级执行：

```text
1. 硬规则和污染防护
2. 商品主数据边界
3. 用户人工处理结果
4. 当前AI解释和本地guardrail
5. 正式知识重合/冲突判断
6. 系统自动吸纳或自动分诊状态
7. 质量评分
```

解释：

- `quality.high` 只能说明“证据质量高”，不能单独决定可检索。
- `auto_kept` 是系统历史判断，不应永久压过新 guardrail。
- 用户人工 `discarded/promoted` 必须优先。
- 用户人工 `kept` 可以保留审计结果，但如果命中硬规则，仍应禁止检索或晋升。

## 5. 终极状态机

### 5.1 存储状态

继续保留原有顶层状态：

- `active`
- `discarded`
- `promoted`

### 5.2 治理最终状态

新增 `governance.effective_state`：

- `pending_review`：待处理。
- `retrievable_experience`：可作为RAG经验参考。
- `style_only`：只作话术风格参考，不参与RAG检索。
- `candidate_suggested`：建议生成待确认知识。
- `candidate_created`：已生成待确认知识。
- `auto_discarded`：系统自动废弃或降噪。
- `user_discarded`：用户废弃。
- `promoted`：已升级候选或已处理。
- `blocked`：被硬规则阻断。
- `unknown`：未知状态，必须显式显示并进入检测报告。

### 5.3 状态转换原则

允许系统自动转换：

```text
pending_review -> auto_discarded
pending_review -> retrievable_experience
pending_review -> style_only
pending_review -> candidate_suggested
auto_kept旧状态 -> auto_discarded
auto_kept旧状态 -> style_only
auto_kept旧状态 -> candidate_suggested
```

不允许系统静默转换：

```text
user_discarded -> retrievable_experience
promoted -> pending_review
user_kept -> user_discarded
```

特殊规则：

- 用户 `kept` 后，如果命中商品事实或污染硬规则，治理层可把 `retrieval_allowed=false`，但不能把用户动作静默改成废弃。
- 用户 `discarded` 永远不参与检索。
- `promoted` 不参与RAG检索，避免同一内容既在正式库又在经验层重复影响。

## 6. 自动候选提名规则

自动候选提名不是自动入库。

允许自动提名：

- 稳定流程类知识。
- 低风险、可泛化客服话术。
- 多次出现且与正式知识不重复的经验。
- 明确有业务价值且来源合格的政策/流程表达。

禁止自动提名：

- 商品主数据。
- 价格、库存、实时车源推荐。
- 动态预算到车型映射。
- 文件传输助手和测试内容。
- AI自回复。
- 金融、合同、发票、最低价等高风险承诺。
- 未经泛化的真实聊天流水。

## 7. 前端展示原则

前端必须以 `governance.display_label` 为主展示。

辅助展示：

- 质量评分：说明证据质量。
- AI建议：说明模型怎么看。
- 来源权威：说明为什么能或不能晋升。
- 正式知识关系：说明是否重复或冲突。

禁止：

- 同一卡片主区同时显示两个相反结论。
- 把 `high` 翻译成“可用”。
- 把 `auto_kept` 永久显示为“可作为RAG参考”而不看当前治理裁决。

## 8. 架构验收不变量

- 任意经验只能有一个 `governance.effective_state`。
- 如果 `governance.retrieval_allowed=false`，RAG索引不得包含该经验。
- 如果 `governance.promotion_allowed=false`，不得生成候选。
- 如果 `governance.style_allowed=true`，只能进入风格层，不得授权事实。
- 总经验数必须等于所有显式治理状态数量之和。
- 商品主数据不能从RAG经验、候选或风格层写入。
- 自动候选只能进入 pending，不能自动进入正式库。
