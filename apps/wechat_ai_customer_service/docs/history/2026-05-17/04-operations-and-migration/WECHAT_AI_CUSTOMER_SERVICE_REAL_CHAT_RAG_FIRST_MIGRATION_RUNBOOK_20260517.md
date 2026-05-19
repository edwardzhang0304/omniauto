# chejin 实盘聊天误入正式库迁移 Runbook

## 迁移对象

租户：`jiangsu_chejin_usedcar_customer_20260501`

错误数据位置：

`apps/wechat_ai_customer_service/data/tenants/jiangsu_chejin_usedcar_customer_20260501/knowledge_bases/chats/items/chejin_real_*.json`

补充判定：即使文件名不是 `chejin_real_*`，只要 `source.type=cleaned_real_chat_pack` 或 batch token 指向 realchat，也属于迁移对象。

## 迁移前检查

- 统计正式 chats 总数。
- 统计 real_chat-like 条数。
- 统计 RAG 经验总数和状态分布。
- 统计 style_memory 是否已存在。

## 备份策略

迁移脚本必须创建：

`data/tenants/<tenant>/migration_backups/real_chat_formal_to_rag/<timestamp>/`

备份内容：

- `items/`：原始正式知识 JSON。
- `manifest.json`：迁移前计数、源文件列表、脚本版本。

## 写入策略

### RAG经验

- 安全自动回复样本：`status=active`，`experience_review.status=auto_kept`，允许参与经验检索。
- 需要请示/边界样本：`status=active`，`experience_review.status=auto_kept`，但 `safety.must_handoff=true`，质量层不允许自动检索。
- 迁移样本 `review_state.is_new=false`，避免在前端变成几百条新经验。

### 话术风格

所有样本写入 `style_memory/examples.jsonl`，用于模拟真实客服表达。

## 删除策略

只有当 RAG经验写入成功、style_memory 写入成功、备份 manifest 写入成功后，才删除正式库中的错误条目。

## 回滚策略

如需回滚：

1. 从备份 `items/` 复制 JSON 回 `knowledge_bases/chats/items`。
2. 从 `rag_experience/experiences.json` 删除 `migration.source_migration_id` 对应记录。
3. 从 `style_memory/examples.jsonl` 删除同批次记录。
4. 重新编译正式知识库。
5. 重建 RAG index。

## 验收标准

- 正式 chats 只保留人工/测试夹具/正式模板，不包含 real_chat-like 批量样本。
- 迁移 report 中 `removed_from_formal == migrated_to_rag == style_examples_written`，允许去重时单独记录。
- 风格适配器可从 `style_memory` 中检索到 chejin 实盘样本。
- RAG index 重建成功。
