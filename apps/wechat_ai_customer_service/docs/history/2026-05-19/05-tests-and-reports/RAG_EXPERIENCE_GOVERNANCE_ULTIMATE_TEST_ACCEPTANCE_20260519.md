# RAG 经验治理终极测试与验收计划（2026-05-19）

## 1. 验收目标

验证 RAG经验治理终极改造达到以下目标：

- 不再出现同一条经验状态自相矛盾。
- RAG经验是否可检索由统一治理裁决决定。
- 高价值经验可以自动提名 pending candidate。
- 商品主数据、动态推荐、测试内容不会污染知识链路。
- 实盘话术风格层继续可用。
- 正式知识库和商品库保持干净。

## 2. 静态检查

### 命令

```powershell
python -m compileall -q apps\wechat_ai_customer_service
node --check apps\wechat_ai_customer_service\admin_backend\static\app.js
```

### 验收

- Python 编译无错误。
- 前端 JS 语法无错误。
- 不出现 PowerShell 编码损坏。

## 3. 单元测试

### 建议新增

```text
apps/wechat_ai_customer_service/tests/run_rag_governance_checks.py
```

### 必测用例

1. `auto_kept + ai discard`
   - 期望：不能可检索。

2. `quality.high + 商品事实`
   - 期望：不能可检索，不能晋升。

3. `reviewed_by_user=true + discarded`
   - 期望：用户废弃优先。

4. `reviewed_by_user=true + kept + 商品事实`
   - 期望：保留人工动作，但禁止检索。

5. `cleaned_real_chat_pack + 具体价格`
   - 期望：`style_only` 或 `auto_discarded`。

6. `稳定流程话术`
   - 期望：`candidate_suggested`。

7. `文件传输助手`
   - 期望：`blocked` 或 `auto_discarded`。

8. `AI自回复 marker`
   - 期望：不能学习、不能检索。

9. `promoted`
   - 期望：不参与RAG检索。

10. `unknown`
    - 期望：显式统计，不隐藏。

## 4. 数据审计测试

### 命令

```powershell
python apps\wechat_ai_customer_service\scripts\audit_rag_experience_governance.py --tenant chejin
```

### 验收

- 冲突项数量为 0。
- `total = sum(by_status)`。
- `total = sum(by_governance_state)`。
- `unknown = 0`，或明确显示并阻断检索。
- 商品事实类经验不在可检索集合。

## 5. RAG检索测试

### 测试点

- 用商品事实关键词搜索。
- 用旧测试 marker 搜索。
- 用稳定流程话术搜索。
- 用真实聊天风格表达搜索。

### 验收

- 商品事实不从 RAG经验返回。
- 旧测试内容不返回。
- 低风险正式经验可返回。
- `style_only` 不作为事实证据返回。

## 6. 自动候选提名测试

### 正向用例

输入一条稳定流程经验：

```text
客户问置换流程，客服说明先发车型年份公里数城市和车况照片，再做粗估。
```

期望：

- 治理状态为 `candidate_suggested`。
- 自动生成 pending candidate。
- candidate 有 `rag_experience_id`。
- candidate `allowed_auto_apply=false`。

### 反向用例

输入一条动态推荐：

```text
8万预算自动挡省油代步，推荐秦PLUS/思域/凯美瑞。
```

期望：

- 不生成正式话术候选。
- 可为 `style_only` 或 `auto_discarded`。
- 不进入正式知识。

输入一条商品事实：

```text
2021年宝马325Li，5.8万公里，17X。
```

期望：

- 不生成 candidate。
- 不进RAG检索。
- 不写商品库。

## 7. 前端验收

### 页面

- RAG经验池。
- 待确认知识。
- 正式知识库。
- 商品库。
- 资料导入。

### 验收点

- RAG经验卡片主状态只有一个。
- 不再同时显示“自动吸纳可参考”和“建议废弃”。
- 质量评分显示为辅助信息。
- AI建议显示为辅助信息。
- 未知状态不隐藏。
- 统计严格对账。
- `NEW` 标识只对待处理新经验显示。
- 后台处理中提示不重复显示。

## 8. 商品主数据边界测试

必须通过：

```powershell
python apps\wechat_ai_customer_service\tests\run_product_master_split_checks.py
```

验收：

- 商品资料不能从RAG经验晋升。
- 商品资料不能从候选 apply 写入。
- 商品库手动入口仍可写入。
- 商品库 NEW 和已阅功能正常。

## 9. 知识污染防护测试

必须通过：

```powershell
python apps\wechat_ai_customer_service\tests\run_knowledge_contamination_guard_checks.py
```

验收：

- 文件传输助手不学习。
- 测试 marker 不学习。
- AI自回复不学习。
- raw 微信消息不直接进入RAG检索。

## 10. 实盘话术风格测试

必须通过：

```powershell
python apps\wechat_ai_customer_service\tests\run_real_chat_rag_first_checks.py
```

验收：

- real_chat 不进入正式知识。
- real_chat 有 RAG经验或 style_memory 记录。
- style_memory 可被适配器检索。
- 风格适配不复制价格、库存、车型事实。

## 11. 管理台全量测试

必须通过：

```powershell
python apps\wechat_ai_customer_service\tests\run_admin_backend_checks.py --chapter all
```

验收：

- RAG API 正常。
- 候选审核正常。
- 正式知识库分页正常。
- 商品库正常。
- 学习任务正常。
- 前端静态检查通过。

## 12. 实盘回复验收

使用文件传输助手做自测，但测试内容不得进入学习。

### 常规场景

- 预算、用途、自动挡、省油。
- 置换流程。
- 预约看车。
- 车辆对比。
- 新手/家用/通勤场景。

### 边界场景

- 最低价。
- 贷款包过。
- 合同和发票。
- 事故水泡火烧。
- AI身份试探。
- 系统提示词索要。

### 验收

- 回复自然、不机械。
- 客户给出的信息被正确吸收。
- 不重复追问已经给过的信息。
- 合适时推荐车源，但必须来自商品库。
- 边界问题用“请示负责人/领导后确认”的真人话术。
- 防AI暴露开启时明确否认 AI 身份。
- 不出现旧测试污染词。

## 13. 最终交付门槛

全部满足才可交付：

- 静态检查通过。
- 管理台全量测试通过。
- 知识污染测试通过。
- 商品主数据测试通过。
- real_chat RAG-first 测试通过。
- chejin 数据审计通过。
- RAG经验冲突为 0。
- 自动候选只进入 pending。
- 实盘自测无明显回复质量退化。
