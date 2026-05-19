# RAG 经验治理历史数据迁移手册（2026-05-19）

## 1. 目的

本手册用于修复历史 RAG经验数据中“自动吸纳”和“建议废弃”并存的问题，尤其是 chejin 账号中由清洗实盘聊天迁移产生的冲突数据。

迁移只处理治理状态和检索准入，不直接改正式知识库，不写商品库。

## 2. 迁移对象

主要对象：

```text
apps/wechat_ai_customer_service/data/tenants/chejin/rag_experience/experiences.json
```

相关对象：

```text
apps/wechat_ai_customer_service/data/tenants/chejin/rag_index/
apps/wechat_ai_customer_service/data/tenants/chejin/style_memory/
apps/wechat_ai_customer_service/data/tenants/chejin/review_candidates/
```

## 3. 迁移前检查

### 3.1 必须确认

- 当前租户是 `chejin`。
- 服务端没有正在写 RAG经验。
- 前端没有执行中的学习任务。
- 已备份当前 Git 状态或数据快照。

### 3.2 审计命令

建议提供脚本：

```powershell
python apps\wechat_ai_customer_service\scripts\audit_rag_experience_governance.py --tenant chejin --output runtime\rag_governance_audit_chejin.json
```

输出必须包含：

- 总经验数。
- 按 `status` 统计。
- 按 `experience_review.status` 统计。
- 按 `ai_interpretation.recommended_action` 统计。
- 冲突项数量。
- 冲突项 reason 分布。
- `by_governance_state` 与 `governance_accounting`。
- `governance_conflicts_after_resolution_count`。
- 是否有未知状态。

说明：历史字段里的 `legacy_auto_kept_with_ai_discard_count` 可以作为旧数据痕迹保留；验收以统一治理后的 `governance_conflicts_after_resolution_count=0` 和 `legacy_retrievable_with_ai_discard_count=0` 为准。

## 4. 备份策略

### 4.1 备份目录

```text
runtime/backups/rag_governance/<tenant_id>/<timestamp>/
```

### 4.2 必备备份文件

- `experiences.json`
- `rag_index/index.json`
- `style_memory/examples.jsonl`
- `review_candidates/pending/`
- 迁移前审计报告。

### 4.3 备份 manifest

```json
{
  "migration_id": "rag_governance_20260519_XXXXXX",
  "tenant_id": "chejin",
  "created_at": "2026-05-19T00:00:00",
  "source_files": [],
  "sha256": {},
  "audit_report": "..."
}
```

## 5. Dry-run 迁移

### 5.1 命令

```powershell
python apps\wechat_ai_customer_service\scripts\migrate_rag_experience_governance.py --tenant chejin --dry-run --report runtime\rag_governance_dry_run_chejin.json
```

### 5.2 Dry-run 必须输出

- 将被标记为 `auto_discarded` 的数量。
- 将被标记为 `style_only` 的数量。
- 将被标记为 `retrievable_experience` 的数量。
- 将被标记为 `candidate_suggested` 的数量。
- 不处理的人工已处理数量。
- 不处理的 promoted 数量。
- 每类样本前 20 条。

### 5.3 Dry-run 验收

- 总数不变。
- 没有未知状态。
- 商品主数据形态不进入 `retrievable_experience`。
- 文件传输助手和测试 marker 不进入 `retrievable_experience`。
- 动态车型推荐不进入候选。

## 6. 分类修复规则

### 6.1 商品事实类

识别条件：

- 车型、价格、库存、里程、车况、配置、现车等。

结果：

- 默认 `retrieval_allowed=false`。
- 如果含可借鉴表达且来自真实聊天：`effective_state=style_only`。
- 如果低价值或高风险承诺：`effective_state=auto_discarded`。

### 6.2 真实聊天太具体

识别条件：

- 具体客户上下文。
- 一次性问答。
- 特定称呼或场景。
- 无法泛化为稳定规则。

结果：

- `style_only` 优先。
- 不生成候选。

### 6.3 边界承诺类

识别条件：

- 最低价。
- 贷款包过。
- 合同发票。
- 留车定金。
- 事故水泡火烧承诺。

结果：

- 不检索。
- 不晋升。
- 有表达价值时 `style_only`。
- 否则 `auto_discarded`。

### 6.4 稳定流程类

识别条件：

- 置换流程。
- 到店看车流程。
- 资料准备。
- 售前沟通顺序。
- 高价值、低风险、可泛化。

结果：

- `candidate_suggested`。
- 可自动创建 pending candidate。
- 不自动入正式库。

## 7. 正式迁移

### 7.1 命令

```powershell
python apps\wechat_ai_customer_service\scripts\migrate_rag_experience_governance.py --tenant chejin --apply --backup --report runtime\rag_governance_apply_chejin.json
```

### 7.2 写入内容

每条处理过的经验写入：

- `governance`
- `governance_migration`

必要时更新：

- `experience_review.status`
- `review_state`
- `quality`

不得修改：

- 正式知识库。
- 商品主数据。
- 原始上传文件。

## 8. 索引重建

迁移后必须重建 RAG index：

```powershell
python - <<'PY'
from apps.wechat_ai_customer_service.workflows.rag_experience_store import rebuild_rag_index_safely
rebuild_rag_index_safely("chejin", trigger="rag_governance_migration", force_sync=True)
PY
```

验收：

- index 不包含 `retrieval_allowed=false` 的经验。
- index 不包含商品主数据形态经验。
- index 不包含文件传输助手或测试 marker。

## 9. 回滚

### 9.1 回滚条件

任一情况必须回滚：

- 迁移后经验总数变化异常。
- RAG index 无法重建。
- 前端加载失败。
- 正式知识库被误改。
- 商品库被误改。

### 9.2 回滚方式

从备份目录恢复：

- `experiences.json`
- `rag_index/index.json`
- `style_memory/examples.jsonl`
- `review_candidates/pending/`

恢复后重启服务并重新跑审计。

## 10. 迁移后验收

- 冲突项数量为 0。
- 统一治理后的冲突项数量为 0：`governance_conflicts_after_resolution_count=0`。
- 旧质量层不再出现“可检索 + AI建议废弃”：`legacy_retrievable_with_ai_discard_count=0`。
- `total = by_governance_state` 之和。
- `total = by_status` 之和。
- `style_only` 样本可被风格层读取。
- `auto_discarded` 不参与RAG检索。
- `candidate_suggested` 可以生成 pending candidate。
- 正式知识库不新增 real_chat 条目。
- 商品库不被修改。
