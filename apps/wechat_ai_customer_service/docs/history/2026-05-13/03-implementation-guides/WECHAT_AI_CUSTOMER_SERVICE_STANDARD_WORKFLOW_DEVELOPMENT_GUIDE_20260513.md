# WeChat AI 客服标准工作流开发指南

## 1. 适用范围

本指南用于规划并实施“实盘聊天记录 -> 可用知识资产 -> 安全上线”的标准研发流程。
默认面向多租户、多行业微信 AI 客服系统。

---

## 2. 研发阶段总览

## Phase 0：基线冻结与范围确认

目标：

1. 冻结当前线上行为基线。
2. 明确本次只改流程与数据，不改业务边界策略。

产出：

1. 基线回放样本集
2. 基线指标快照（违规承诺率、转人工率、续聊率）

## Phase 1：数据治理层建设

目标：

1. 建立统一清洗规范。
2. 将实盘语料转为可学习模板资产。

输入：

- `cleaned_dialogues.jsonl` / `rag_chunks.jsonl` / raw message 导出

输出：

1. `wechat_usedcar_knowledge_chats_items_strict.jsonl` 这类结构化模板包
2. 清洗报告（reject 原因分布、样本保留率）
3. 验收报告（schema 通过率、泄漏检查结果）

实施要点：

1. 过滤低价值样本（短句、纯表情、系统验证语）。
2. 去标识化（手机号、真实姓名）。
3. 时效字段占位符化（库存数、联系电话）。
4. 保留 `scenario / hit_count / source_samples` 便于溯源。

## Phase 2：模板导入流水线

目标：

1. 让模板包可标准化入库，不靠手工逐条维护。
2. 建立版本化、可回滚发布机制。

建议能力：

1. `dry-run import`：仅校验不写入
2. `apply import`：落库并生成版本号
3. `diff`：与当前线上版本比对
4. `rollback`：按版本回退

数据契约建议：

1. 必填：`id/category_id/data.service_reply/source/metadata`
2. 强校验：`service_reply` 非空、ID 唯一、risk 字段可解释
3. 审计：导入人、导入批次、源文件摘要

## Phase 3：检索编排增强（事实轨/风格轨/经验轨）

目标：

1. 事实知识优先。
2. 风格模板仅改变表达，不改变事实。
3. 经验轨只参考，不授权高风险承诺。

建议实现点（模块映射）：

1. `knowledge_loader.build_evidence_pack`：输出分轨证据结构
2. `evidence_resolver`：显式标注每条命中的轨道和优先级
3. `rag_answer_layer`：限制经验轨在 authority intent 上直接落答

## Phase 4：回复合成策略标准化

目标：

1. 将“事实硬约束 + 风格软约束 + 安全兜底”固化为统一流程。

建议流程：

1. structured evidence 生成事实骨架
2. chat template 生成表达骨架
3. LLM synthesis 填充自然语言
4. guard 最终裁决（send/handoff/fallback）

验收重点：

1. 不出现事实与模板冲突
2. 不出现越权承诺
3. 发生不确定性时必须保守转人工

## Phase 5：回放评估与发布门禁

目标：

1. 建立“可重复、可量化”的发布门禁。

固定评估集应覆盖：

1. 明确报价咨询
2. 模糊需求探询
3. 风险边界场景（合同/赔偿/金融）
4. 追问/唤醒场景
5. 跨轮上下文连续性场景

发布门禁建议：

1. 违规承诺率不高于基线
2. 转人工准确率不低于基线
3. 事实一致率高于基线
4. 续聊率提升或不下降

## Phase 6：多行业扩展

目标：

1. 验证该工作流不仅适用于二手车。

方法：

1. 不改主链路，仅替换行业插件：
   - intent/risk 词典
   - 场景标签体系
   - 事实知识类别
2. 在新行业复跑 Phase 1-5，比较迁移成本。

---

## 3. 推荐目录规范

建议新增目录：

1. `data/tenants/<tenant_id>/learning_packs/`
2. `runtime/apps/wechat_ai_customer_service/tenants/<tenant_id>/replay_eval/`
3. `runtime/apps/wechat_ai_customer_service/tenants/<tenant_id>/release_versions/`

建议文件：

1. `templates_<version>.jsonl`
2. `import_report_<version>.json`
3. `eval_report_<version>.json`
4. `release_manifest_<version>.json`

---

## 4. 关键设计约束

1. 数据治理层必须可重复执行且幂等。
2. 风险边界规则优先级高于任何模板命中。
3. 经验知识不能绕过结构化知识约束。
4. 发布必须带版本号与回滚点。
5. 任何自动学习动作都必须有审计记录。

---

## 5. 迁移策略建议

1. 先旁路上线：只做 shadow/replay，不直接影响线上回复。
2. 小流量灰度：选定低风险租户或时段。
3. 指标达标后全量切换。
4. 保留一键回滚到“上一稳定版本”的机制。

---

## 6. 结论

该开发方式是平台级工作流，不是单行业脚本。
行业差异通过配置与知识层表达，主流程保持一致，可在所有微信 AI 客服场景复用。
