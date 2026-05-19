# RAG 经验治理终极实施指南（2026-05-19）

## 1. 总体策略

本次改造分阶段落地，避免一次性大拆导致运行时不可控。

原则：

- 先新增治理裁决，不直接删除旧字段。
- 先让列表、统计、检索读取治理结果，再做数据迁移。
- 自动候选提名后置，确认治理层稳定后再开启。
- 所有阶段都必须可回滚。

## 2. Phase 0：基线冻结与审计

### 目标

在改代码前确认当前数据、冲突规模、索引状态和测试基线。

### 文件范围

只新增脚本或测试，不改业务逻辑。

建议文件：

- `apps/wechat_ai_customer_service/scripts/audit_rag_experience_governance.py`
- `apps/wechat_ai_customer_service/tests/run_rag_governance_checks.py`

### 工作清单

- 统计所有 RAG经验的 `status`。
- 统计所有 `experience_review.status`。
- 统计所有 `ai_interpretation.recommended_action`。
- 找出 `auto_kept + discard/already_covered` 冲突。
- 找出 `quality.retrieval_allowed=true` 但命中商品主数据/污染防护的经验。
- 找出未知状态。
- 输出 dry-run 报告。

### 验收标准

- 能输出当前 chejin 冲突数量。
- 能列出冲突来源类型和原因分布。
- 不修改任何数据。
- 报告中 `total = 各状态之和`。

## 3. Phase 1：新增最终治理裁决层

### 目标

新增统一函数，所有最终判断由它输出。

### 建议新增文件

- `admin_backend/services/rag_experience_governance.py`

### 建议核心函数

```python
def resolve_rag_experience_governance(item: dict) -> dict:
    ...
```

### 输入

- `status`
- `experience_review`
- `reviewed_by_user`
- `quality`
- `ai_interpretation`
- `formal_relation`
- `formal_match`
- `source`
- `source_type`
- `source_authority`
- 污染防护结果

### 输出

符合 `RAG_EXPERIENCE_GOVERNANCE_ULTIMATE_DATA_CONTRACT_20260519.md` 的 `governance` 字段。

### 修改点

- `rag_admin_service.py`
  - 列表接口附加 `governance`。
  - 统计接口增加 `by_governance_state`。

- `rag_experience_store.py`
  - `experience_is_retrievable()` 改为优先读取 governance。
  - `list_retrievable()` 改为治理层准入。

- `rag_layer.py`
  - `iter_experience_chunks()` 只索引治理允许的经验。

### 关键规则

- `auto_kept + ai discard` 不能继续可检索。
- `quality.high` 不能单独放行。
- 用户废弃永远不检索。
- 已 promoted 不检索。
- 商品主数据形态不检索。
- 实盘聊天可进入 `style_only`。

### 阶段验收

- 单元测试覆盖每种 `effective_state`。
- 现有 RAG检索测试通过。
- 冲突项在 API 中返回单一治理状态。
- 还不做批量写回，只虚拟计算即可。

## 4. Phase 2：前端统一展示

### 目标

前端不再拼接矛盾状态，主状态只展示治理裁决。

### 修改点

- `admin_backend/static/app.js`
- `admin_backend/static/styles.css`

### 工作清单

- RAG经验卡片主状态读取 `item.governance.display_label`。
- 质量评分改名为“证据质量”，避免用户理解成最终结论。
- AI建议放入辅助区，显示为“AI审核建议”。
- 若 AI建议与最终裁决不同，显示“最终以治理规则为准”。
- 统计卡片增加按治理状态分组。
- 未知状态必须显示，不能隐藏。

### 阶段验收

- 同一卡片不再同时出现“系统已自动吸纳可参考”和“建议废弃”。
- `NEW` 标识仍只对待处理且未读项生效。
- `总数 = 各治理状态数量之和`。
- `node --check app.js` 通过。

## 5. Phase 3：历史数据治理迁移

### 目标

把 chejin 现有冲突数据修复到正确治理状态。

### 建议新增脚本

- `scripts/migrate_rag_experience_governance.py`

### 工作清单

- 先备份 `experiences.json` 和 RAG index。
- dry-run 生成迁移报告。
- 对 `auto_kept + discard` 冲突分类：
  - 商品事实：`style_only` 或 `auto_discarded`。
  - 真实聊天太具体：`style_only`。
  - 边界承诺：`style_only` 或 `auto_discarded`。
  - 重复/低价值：`auto_discarded`。
- 写入 `governance`。
- 必要时更新 `experience_review.status`：
  - 系统旧 `auto_kept` 可改为 `auto_triaged`。
  - 用户人工处理不静默改写。
- 重建 RAG index。

### 阶段验收

- 迁移前后总数一致。
- 冲突数量降为 0。
- RAG index 中不包含 `governance.retrieval_allowed=false` 的经验。
- chejin 正式知识库不新增任何条目。
- style_memory 不被误删。

## 6. Phase 4：自动候选提名

### 目标

恢复用户最初想要的“高价值经验自动推到待确认知识”，但不自动入正式库。

### 建议新增服务

- `admin_backend/services/rag_experience_candidate_nominator.py`

### 触发条件

只有满足以下全部条件才自动生成 pending candidate：

- `governance.effective_state = candidate_suggested`
- `governance.candidate_auto_create_allowed = true`
- `governance.promotion_allowed = true`
- `source_authority.allowed = true`
- 不属于商品主数据。
- 不属于动态推荐污染。
- 不属于文件传输助手/测试/AI自回复。
- 与正式知识不高度重复。

### 候选生成规则

- 只写 pending candidate。
- candidate `review.requires_human_approval = true`。
- candidate `review.allowed_auto_apply = false`。
- candidate `review.rag_experience_id` 必须存在。
- 创建后经验状态改为 `candidate_created` 或保留 `active` 但禁止重复提名。

### 修改点

- `rag_admin_service.py`
  - 增加批量提名入口或后台任务调用。

- `learning_service.py`
  - 学习任务结束后可触发提名扫描，但默认可配置。

- `raw_message_learning_service.py`
  - 同上，但仍受污染防护限制。

### 阶段验收

- 上传一条稳定流程资料后，自动生成 pending candidate。
- 上传商品资料不会生成 candidate。
- 清洗真实聊天只会生成合格话术候选，不会把具体车型价格写入候选。
- 候选不会自动应用正式库。
- 重复扫描不会重复创建候选。

## 7. Phase 5：实盘话术风格层协同

### 目标

让 `style_only` 经验继续发挥价值，而不是简单废弃。

### 修改点

- `workflows/style_memory_store.py`
- `workflows/reply_style_adapter.py`
- `workflows/real_chat_learning.py`

### 工作清单

- `style_only` 可进入风格检索。
- 风格样本必须去除商品事实和承诺。
- 风格层不得影响事实证据包。
- 风格适配器审计记录使用了哪些样本。

### 阶段验收

- 清洗实盘聊天中含价格的样本不进RAG检索，但可抽取安全表达进入风格层。
- 回复中不复制旧价格、旧车型、旧客户场景。
- 风格适配后仍通过事实不漂移检查。

## 8. Phase 6：全量回归与实盘验证

### 目标

确认治理层、候选层、风格层、运行时回复整体稳定。

### 必跑测试

```powershell
python -m compileall -q apps\wechat_ai_customer_service
node --check apps\wechat_ai_customer_service\admin_backend\static\app.js
python apps\wechat_ai_customer_service\tests\run_admin_backend_checks.py --chapter all
python apps\wechat_ai_customer_service\tests\run_knowledge_contamination_guard_checks.py
python apps\wechat_ai_customer_service\tests\run_product_master_split_checks.py
python apps\wechat_ai_customer_service\tests\run_real_chat_rag_first_checks.py
python apps\wechat_ai_customer_service\tests\run_rag_governance_checks.py
```

### 实盘验收

- 文件传输助手自测不进入学习。
- chejin 回复不出现旧测试污染。
- 商品推荐仍从商品库动态取数。
- 高风险问题仍请示负责人，不暴露 AI 身份。
- 真实聊天风格有体现，但不复制事实。

## 9. 最终交付标准

只有同时满足以下条件，才算完成：

- RAG经验冲突状态为 0。
- 自动候选提名只生成 pending，不自动入正式库。
- 商品主数据晋升链路仍被硬拒。
- 前端统计严谨无隐藏项。
- RAG index 只包含治理允许的经验。
- 风格层可用且不污染事实。
- 全量测试和实盘测试通过。
