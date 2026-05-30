# AI经验池迁移与审计方案

## 迁移目标

将现有 AI经验池体系迁移为 AI经验池治理体系，并确保：

1. 聊天来源数据不再参与运行时内容依据。
2. 商品事实只从商品库读取。
3. 正式规则只从正式知识库读取。
4. 真实聊天数据继续保留为话术风格资产。
5. 所有旧索引、缓存、快照不绕过新规则。

## 迁移对象

### chejin 已知对象

| 对象 | 当前数量 | 迁移目标 |
| --- | --- | --- |
| `style_memory/examples.jsonl` 真实聊天样本 | 935 | 保留，事实脱敏后继续用于话术风格 |
| `rag_experience/experiences.json` realchat 相关记录 | 约 936 | 保留在 AI经验池，不作为内容依据 |
| `rag_index` 中 realchat 可检索经验 | 111 | 移除运行时检索权限 |
| `review_candidates` | 现有候选 | 保留，但默认不参与运行时 |
| `product_master` | 现有商品库 | 保留为唯一商品事实源 |
| `knowledge_bases` | 现有正式知识 | 保留为业务规则源 |

## 数据状态迁移规则

### 聊天来源经验

匹配来源：

- `cleaned_real_chat_pack`
- `real_chat_style`
- `wechat_raw_message`
- `raw_wechat_private`
- `raw_wechat_group`
- `raw_wechat_file_transfer`
- `ai_recorder_chat`

目标状态：

```json
{
  "governance": {
    "effective_state": "style_only",
    "final_action": "keep_style_only",
    "retrieval_allowed": false,
    "runtime_content_allowed": false,
    "promotion_allowed": false,
    "candidate_auto_create_allowed": true,
    "style_allowed": true
  }
}
```

说明：

- `candidate_auto_create_allowed=true` 表示可以生成候选。
- 不表示候选自动生效。
- 商品候选和正式知识候选都必须人工确认。

### 普通上传资料

目标状态：

- 先进入 AI经验池。
- LLM分发到候选层。
- 未确认前不作为内容依据。

如果上传入口本身是“正式知识导入”，仍建议先生成候选，由人工确认后入库。

### 商品库专用数据

目标状态：

- 直接进入 `product_master`。
- 不需要先进入 AI经验池。
- 需要保留导入审计。

如果商品信息来自聊天或普通资料，不能直接进入商品库，只能生成商品更新候选。

## 旧索引清理

迁移后必须重建：

- `rag_index/index.json`
- Postgres 中的 RAG index 表，如启用。
- runtime evidence snapshot。
- 客户端共享公共知识缓存。

审计标准：

1. `rag_index` 不包含聊天来源经验。
2. `rag_index` 不包含 `rag_experience` 作为运行时内容证据，除非该来源本身是正式授权知识镜像。
3. `reply_evidence_builder` 输出中无 `rag_evidence.hits` 聊天来源。
4. `llm_reply_synthesis` 的 prompt pack 中无历史聊天正文作为内容依据。

## 审计脚本建议

新增脚本：

- `apps/wechat_ai_customer_service/tests/audit_authority_gated_rag_sources.py`

检查项：

1. 统计 AI经验池按来源、治理状态、检索权限。
2. 扫描 `rag_index` 是否存在聊天来源。
3. 扫描 evidence pack 是否包含禁用来源。
4. 抽样运行风格检索，确认返回样本已事实脱敏。
5. 抽样运行商品事实问题，确认依据只来自商品库。
6. 抽样运行流程规则问题，确认依据只来自正式知识库。

输出示例：

```json
{
  "ok": true,
  "tenant_id": "chejin",
  "chat_sources_in_runtime_rag_index": 0,
  "chat_sources_in_style_memory": 935,
  "retrievable_ai_experience_pool_items": 0,
  "candidate_items_runtime_enabled": 0,
  "product_facts_non_product_master_sources": 0
}
```

## 迁移报告

每次迁移生成：

- `runtime/apps/wechat_ai_customer_service/tenants/<tenant>/migration_reports/authority_gated_rag_<timestamp>.json`

报告字段：

```json
{
  "tenant_id": "chejin",
  "started_at": "",
  "finished_at": "",
  "counts": {
    "experience_total": 0,
    "chat_experience_downgraded": 0,
    "style_memory_rebuilt": 0,
    "rag_index_entries_before": 0,
    "rag_index_entries_after": 0,
    "candidates_created": 0
  },
  "warnings": [],
  "rollback": {
    "backup_paths": [],
    "can_rollback": true
  }
}
```

## 回滚方案

迁移前备份：

- `rag_experience/experiences.json`
- `style_memory/examples.jsonl`
- `rag_index/index.json`
- `review_candidates`
- 相关 Postgres 表快照，如启用。

回滚动作：

1. 停止客服监听。
2. 恢复备份文件或表。
3. 重建索引。
4. 刷新管理端缓存。
5. 运行审计脚本确认状态。

## 风险与护栏

| 风险 | 处理 |
| --- | --- |
| 风格样本偷带价格/车型 | 写入风格层前事实脱敏 |
| 候选知识误生效 | 候选层 `runtime_enabled=false` |
| 旧索引继续命中聊天 | 迁移后重建索引并审计 |
| 当前会话事实和历史聊天混淆 | evidence item 增加 `source_scope=current_session/history` |
| LLM常识层越权 | prompt 和后置 guard 禁止新增商品事实 |
| 商品库缺数据导致回答变弱 | 回复改为追问、推荐筛选或转人工，不允许历史聊天补事实 |

## 迁移完成判定

满足以下条件才算完成：

1. 所有聊天来源 AI经验池记录 `runtime_content_allowed=false`。
2. 所有聊天来源 AI经验池记录 `retrieval_allowed=false`。
3. `rag_index` 无聊天来源。
4. `style_memory` 有脱敏后的风格样本。
5. 正式知识候选不参与运行时。
6. 商品事实回答审计中，依据来源只出现商品库。
7. 规则回答审计中，依据来源只出现正式知识库。
