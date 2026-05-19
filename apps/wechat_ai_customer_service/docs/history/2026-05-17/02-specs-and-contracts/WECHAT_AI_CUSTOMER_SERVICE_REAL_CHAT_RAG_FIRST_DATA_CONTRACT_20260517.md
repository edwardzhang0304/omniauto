# 实盘聊天 RAG-First 数据契约

## 来源类型矩阵

| 来源类型 | 说明 | 允许落点 | 禁止落点 |
| --- | --- | --- | --- |
| `cleaned_real_chat_pack` | 清洗后的实盘客服聊天样本 | RAG经验、话术风格记忆、人工候选 | 正式知识库直接写入、商品主数据 |
| `real_chat` | 通用真实聊天样本 | RAG经验、话术风格记忆、人工候选 | 正式知识库直接写入、商品主数据 |
| `wechat_raw_message` | 微信原始聊天记录 | RAG经验、人工候选 | 正式知识库直接写入、商品主数据 |
| `raw_wechat_*` | 原始微信私聊/群聊/文件助手 | RAG经验、人工候选 | 正式知识库直接写入、商品主数据 |
| `manual_canonical_template` | 人工整理的正式模板 | 正式知识库、候选知识 | 商品主数据，除非类别为商品导入 |
| `workflow_import` | 标准工作流模板导入 | 正式知识库，前提是不属于 real_chat | 商品主数据、real_chat直写 |
| `product_master_import` | 商品主数据导入 | 商品主数据 | RAG晋升、正式知识库商品事实 |

## Formal Item 中的 real_chat 判定

正式知识导入前必须检查以下字段：

- `source.type`
- `source.batch_token`
- `source.original_type`
- `id`
- `metadata.created_by`
- `data.additional_details.source_hint_id`

命中以下规则时，应阻断正式库写入：

- `source.type in {cleaned_real_chat_pack, real_chat, wechat_raw_message, raw_wechat_private, raw_wechat_group, raw_wechat_file_transfer}`。
- `id` 以 `chejin_real_` 开头。
- `source.batch_token` 包含 `realchat` 或 `real_chat`。
- `data.additional_details.cleaning_kind` 存在且来源为实盘清洗。

阻断原因统一使用：`real_chat_requires_rag_first`。

## 迁移后 RAG Experience 字段

从误入正式库的聊天样本迁移到 RAG 时，使用如下结构：

- `experience_id`: `rag_exp_realchat_<hash>`。
- `source`: `real_chat_style`。
- `source_type`: `cleaned_real_chat_pack`。
- `category`: `chats`。
- `formal_knowledge_policy`: `experience_only_not_formal_knowledge`。
- `promotion_policy`: `manual_candidate_review_only`。
- `question`: 原客户问法。
- `reply_text`: 原客服回复。
- `rag_hit.text`: 可追溯的客户/客服样本摘要。
- `experience_review.status`: 安全自动保留用 `auto_kept`；高风险请示/留车/金融边界样本不参与自动RAG检索，但可进入风格层。
- `review_state.is_new`: `false`，迁移样本不应刷屏为新经验。

## 话术风格记忆字段

迁移时同步写入 `style_memory/examples.jsonl`：

- `id`: 与原正式条目或迁移经验关联。
- `customer_message`: 客户问法。
- `service_reply`: 客服回复，必须去除“转人工/机器人/AI”等暴露词。
- `source_type`: `cleaned_real_chat_pack`。
- `scenario`: 清洗时识别出的场景。
- `tone_tags`: 原样保留。
- `intent_tags`: 原样保留。
- `quality_score`: 0 到 1。
- `status`: `active` 或 `disabled`。

## 不变量

1. real_chat 类来源不得直接调用 `KnowledgeBaseStore.save_item("chats", item)`。
2. 商品事实不得由 RAG经验、候选知识或话术风格层反向写入。
3. 迁移必须先备份再删除正式库中的错误条目。
4. 正式知识库总数应只统计正式知识，不得混入话术样本数量。
5. RAG经验总数必须等于各状态数量之和，不能隐藏未知状态。
