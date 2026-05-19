# WeChat AI 客服标准工作流架构（通用版）

## 1. 文档目标

定义一套可复用的微信 AI 客服知识学习与上线工作流，使系统能够：

1. 吸收实盘聊天经验但不过拟合噪声。
2. 在安全边界内生成更像真人客服的回复。
3. 在多行业、多租户场景中可复制、可审计、可回滚。

本架构不是“二手车专用方案”，而是“行业可插拔的通用底座”。

---

## 2. 当前架构（As-Is）

当前系统已经具备以下核心能力：

1. 三层知识结构（shared/tenant/product-scoped）
2. 运行时证据检索（KnowledgeRuntime + KnowledgeIndex + EvidenceResolver）
3. RAG 检索与经验存储（RagService + RagExperienceStore）
4. 回复合成与风控（intent router + synthesis + guard + handoff）

关键模块：

- `workflows/knowledge_runtime.py`
- `workflows/knowledge_index.py`
- `workflows/evidence_resolver.py`
- `adapters/knowledge_loader.py`
- `workflows/rag_layer.py`
- `workflows/rag_experience_store.py`
- `workflows/listen_and_reply.py`
- `workflows/llm_reply_synthesis.py`
- `workflows/llm_reply_guard.py`

---

## 3. 当前不足（Gap）

针对“实盘聊天记录持续学习”目标，当前链路仍有缺口：

1. 缺少独立的数据治理层
实盘语料会包含系统提示语、广告模板、重复口号、时效信息，当前缺少标准化清洗工位。

2. 缺少模板导入流水线
`chats` 可以承载话术模板，但缺少“批量导入、差异比对、版本回滚、发布门控”的标准流程。

3. 事实与风格检索未显式分轨
事实型知识与风格型知识存在混用风险，可能导致“口吻像真人但事实不稳定”。

4. 缺少实盘回放评估闭环
当前有功能测试，但“真实感、转人工准确率、违规承诺率、客户续聊率”等业务指标未形成统一发布门槛。

---

## 4. 目标架构（To-Be）

标准工作流分为 6 层：

### L1. 数据接入层（Data Ingestion）

输入源：

- 历史聊天记录导出
- 线上运行产生的 raw message / rag experience
- 运营手工补充素材

输出：

- 原始审计归档（不可变）
- 任务批次元数据（source、tenant、时间、版本）

### L2. 数据治理层（Data Curation）

职责：

- 去噪（系统语、广告卡片、低信息短句、重复模板）
- 去标识化（手机号、真实姓名等）
- 时效解耦（库存/数量/报价占位符化）
- 结构化（customer_message / service_reply / intent_tags / tone_tags）

输出两类标准资产：

1. `Chat Template Pack`（用于风格与追问学习）
2. `RAG Reference Pack`（用于上下文参考检索）

### L3. 模板入库层（Template Import Pipeline）

职责：

- dry-run 校验（schema、冲突、重复、风险）
- 正式导入（写入 tenant `knowledge_bases/chats/items`）
- 版本管理（发布号、变更摘要、回滚点）

关键原则：

- 导入不等于立即生效。
- 需要通过发布开关进入 runtime。

### L4. 检索编排层（Retrieval Orchestration）

必须显式分轨：

1. 事实轨：`products/policies/product_scoped`
2. 风格轨：`chats`
3. 经验轨：`rag_experience`（受质量门控）

编排顺序建议：

1. 先事实，后风格。
2. 经验轨只做参考增强，不授权高风险承诺。

### L5. 回复生成与风控层（Synthesis + Guard）

职责：

- 以事实证据为硬约束。
- 以风格模板为软约束。
- 通过 guard 统一执行风险边界（价格、合同、赔偿、账期等）。
- 不满足条件即转人工。

### L6. 回放评估与发布层（Replay Eval + Release Gate）

职责：

- 固定问题集回放
- A/B 结果对比
- 关键指标门禁

建议门禁指标：

- 违规承诺率
- 转人工准确率
- 事实一致率
- 客户续聊率
- 平均回复时长

---

## 5. 通用性与行业插件位

本架构适用于所有微信 AI 客服。行业差异通过插件位注入，不改主干流程。

标准插件位：

1. 意图词典（intent lexicon）
2. 风险词与硬边界规则（risk/handoff policy）
3. 实体抽取规则（预算、型号、合同字段等）
4. 场景标签体系（如售前/售后/投诉/复购）
5. 模板质量策略（最短长度、重复阈值、禁用词）

主干保持不变：

- 数据治理 -> 模板入库 -> 分轨检索 -> 风控生成 -> 回放发布

---

## 6. 与二手车场景关系

二手车是首个落地行业，不是唯一行业。
二手车特有规则（车况、过户、金融审批）应放在行业插件层；底座流程保持通用。

---

## 7. 成功标准

当满足以下条件，可判定标准工作流落地成功：

1. 新行业接入时不需要重写主链路。
2. 新数据批次可在不改代码情况下完成治理、导入、验收、发布。
3. 任何上线版本可追溯来源、可回滚到前一版本。
4. 线上回复风格更接近真实客服，且风险边界稳定收敛。
