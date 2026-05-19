# 微信AI智能记录员终极 LLM 抽取协议（2026-05-11）

## 1. 目标
把“规则主导抽取”升级为“LLM主导理解 + 结构化校验兜底”，提升自然语言泛化能力，并保证可解释与可审计。

## 2. 抽取总流程
1. 预处理：清理空消息、系统噪声、明显无关内容。
2. 语义分块（LLM Pass-1）：把聊天切成“订单语义单元”。
3. 结构抽取（LLM Pass-2）：每个语义单元生成标准JSON。
4. 结构校验（Rule Pass）：字段逻辑检查、噪声过滤。
5. 疑难修复（LLM Pass-3）：仅处理校验失败或低置信度行。
6. 导出映射：按模块模板生成目标表格。

## 3. 输入协议
每个抽取批次的输入结构：
```json
{
  "tenant_context": {
    "tenant_id": "test02",
    "module_id": "order_sheet_lab_v1",
    "module_version": "1.0.0"
  },
  "window_context": {
    "date_from": "2026-03-01",
    "date_to": "2026-03-31",
    "conversation_names": ["群聊_企点售后群 - 喂数据"]
  },
  "messages": [
    {
      "message_id": "m1",
      "sent_at": "2026-03-02 10:11:23",
      "sender_name": "张三",
      "text": "BL521A BCA蛋白浓度测定试剂盒 订2盒 110*2=220元"
    }
  ]
}
```

## 4. LLM Pass-1：语义分块规范
输出目标：
1. 找出与“下单/订货/采购意图”相关的消息簇。
2. 合并跨多条消息表达同一订单的信息。
3. 拆分一条消息中的多商品订单。

输出格式：
```json
{
  "order_segments": [
    {
      "segment_id": "seg_001",
      "source_message_ids": ["m1", "m2"],
      "segment_text": "..."
    }
  ]
}
```

## 5. LLM Pass-2：结构化抽取规范
输出字段：
1. `order_date`（必须标准化为 `YYYY-MM-DD`）。
2. `customer_name`。
3. `product_name`。
4. `quantity`。
5. `unit`。
6. `unit_price`（可空）。
7. `total_price`（可空）。
8. `remark`。
9. `confidence`（0~1）。
10. `evidence_text`（必须引用原文关键短句）。
11. `source_message_ids`。

输出示例：
```json
{
  "rows": [
    {
      "order_date": "2026-03-02",
      "customer_name": "张三",
      "product_name": "BL521A BCA蛋白浓度测定试剂盒",
      "quantity": 2,
      "unit": "盒",
      "unit_price": 110,
      "total_price": 220,
      "remark": "",
      "confidence": 0.94,
      "evidence_text": "订2盒 110*2=220元",
      "source_message_ids": ["m1"]
    }
  ]
}
```

## 6. LLM Pass-3：疑难修复规范
触发条件：
1. 缺失核心字段（日期/产品/数量）。
2. 金额明显冲突。
3. product_name 疑似人名或噪声词。
4. 置信度低于阈值（默认 0.72）。

修复输出新增字段：
1. `repair_action`：`fill`/`replace`/`keep_unresolved`。
2. `repair_reason`：简要说明。
3. `repaired_confidence`。

## 7. 结构化校验规则（辅助，不主导）
1. 日期校验：必须落在筛选窗口内。
2. 产品名校验：过滤明显人名/纯状态词/纯活动文案。
3. 数量校验：正数，且单位合理。
4. 金额校验：若可计算则对比容差（可配置，如 3%）。
5. 证据校验：`evidence_text` 不可为空且必须来自原文。

## 8. 提示词治理
1. System Prompt 固化在模块配置，禁止运行时拼接敏感业务规则。
2. Few-shot 样本按客户模块维护，并带版本号。
3. 每次导出记录 `prompt_version` 与 `sample_pack_version` 用于回溯。
4. 修改提示词必须附带回归测试结果。

## 9. 置信度策略
建议综合分：
`final_confidence = 0.5 * semantic_conf + 0.3 * schema_conf + 0.2 * business_conf`

阈值建议：
1. `>=0.85`：直接入表。
2. `0.72~0.85`：入表并打 `needs_review=true`。
3. `<0.72`：默认进入复核池。

## 10. 质量提升闭环
1. 人工修正后的结果回灌为“纠正样本”。
2. 导出前检索相似历史样本作为Few-shot增强。
3. 每周统计 Top 错误类型并调整模块配置。
4. 新错误先加样本，再加轻量规则，避免过拟合正则。

## 11. 实验仪器订货表V1约束
1. 进价单价、总进价若无法可靠获取保持空值。
2. 日期统一输出 `YYYY-MM-DD`。
3. 括号内容默认作为 `remark`，不覆盖 `product_name`。
4. 人名与产品冲突时优先产品实体，无法判断则标记复核。

## 12. 安全与合规
1. 不输出推测性敏感信息。
2. 不伪造无法从上下文推导出的价格字段。
3. 所有自动修复必须有证据片段可追溯。
