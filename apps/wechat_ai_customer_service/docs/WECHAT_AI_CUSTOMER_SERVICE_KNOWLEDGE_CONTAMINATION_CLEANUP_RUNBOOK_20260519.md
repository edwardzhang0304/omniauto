# 知识污染清理与回滚手册 2026-05-19

## 适用场景

当发现某个账号出现旧测试问题、文件传输助手问题、AI 自回复或商品事实被错误学习后，用本手册执行排查、清理和复核。

## 清理命令

先 dry-run：

```powershell
python apps\wechat_ai_customer_service\scripts\clean_knowledge_contamination.py --tenant chejin
```

确认报告后应用：

```powershell
python apps\wechat_ai_customer_service\scripts\clean_knowledge_contamination.py --tenant chejin --apply
```

脚本会自动写报告到：

```text
runtime/apps/wechat_ai_customer_service/test_artifacts/knowledge_contamination_cleanup/<tenant>_<timestamp>/report.json
```

应用模式会自动备份被修改文件到同一目录的 `backups/` 下。

## 脚本动作

1. RAG sources/chunks：
   - `wechat_raw_message` 直接隔离。
   - `products/erp_exports` 直接隔离。
   - `raw_messages` 路径直接隔离。
   - `raw_inbox/chats` 旧直传聊天模板隔离，要求走 RAG 经验层。
   - 含测试 marker 或模型回复 marker 的 source/chunk 隔离。
2. Raw messages：
   - 文件传输助手、自回复、非文本、测试 marker、模型回复 marker 禁止学习。
   - customer-service 默认观察消息禁止学习。
   - 全部不可学习 batch 标记 skipped。
3. Customer service settings：
   - `auto_learn=false`。
   - `raw_messages.learning_enabled=false`。
   - `allow_customer_service_learning=false`。
4. Runtime state：
   - 清理旧 `sent_replies/operator_alerts/handoff_events/pending_customer_data/bootstrap_events` 中的测试/模型回复/过期上下文。
   - 保留 processed message ids，避免重启后重复回复历史消息。
5. RAG experiences：
   - 商品主数据、raw_wechat 未审核经验、测试或模型回复经验标记 discarded。
6. Formal knowledge：
   - 生产种子规则从 `test_fixture` 规范为 `manual_seed`。
   - 客户可见文案清掉“AI可以/AI只能/转人工确认”等暴露系统身份的措辞。

## chejin 本次执行结果

最终清理批次：

```text
runtime/apps/wechat_ai_customer_service/test_artifacts/knowledge_contamination_cleanup/chejin_20260519_015348/report.json
```

关键结果：

1. RAG active direct source：0。
2. RAG active direct chunk：0。
3. RAG index entry：870，全部来自 RAG experience 可检索经验。
4. raw message learnable：0。
5. runtime state 旧测试 marker：0。
6. formal seed：18 条全部规范为 `manual_seed`。

补充复核（2026-05-19 03:32）：

1. 文件传输助手历史 raw message 中曾残留旧 `秦PLUS/40公里` 自测记录，但均为 `learning_enabled=false` 且 `excluded_reason=file_transfer_test_channel`，不会进入学习或检索。
2. 为避免前端/人工复核误判，已备份并移除当前 `messages.json` 中命中的历史测试 raw message。
3. 备份文件：`runtime/apps/wechat_ai_customer_service/tenants/chejin/raw_messages/messages.before_pollution_cleanup_20260519_033224.json`。
4. 移除归档：`runtime/apps/wechat_ai_customer_service/tenants/chejin/raw_messages/messages.pollution_removed_20260519_033224.json`。
5. 复扫当前生效 raw message 与 chejin active 知识目录，旧测试标记命中数为 0。

## 模板污染复核

如果知识库/RAG 已清理但回复仍串入旧场景，应继续检查本地确定性模板：

1. 比较类模板不得因为上一轮候选车出现过，就把未被客户提问的车型强塞进回答。
2. 人物关系、性别、驾驶人身份、通勤距离、预算、城市等客户事实，必须来自当前对话或权威库，不得写死在模板中。
3. 地址/联系人、当天提车、合同发票、价格谈判等边界问题，需要保留客户具体诉求后再请示，不能统一落成“确认后回复”的空泛话术。
4. 新增模板后要补对应回归测试，避免“形式安全、内容串场”。

## 回滚方式

如需要回滚某次清理：

1. 打开该次报告目录的 `backups/`。
2. 按原相对路径复制回项目目录。
3. 执行：

```powershell
python apps\wechat_ai_customer_service\scripts\clean_knowledge_contamination.py --tenant chejin
```

如果 dry-run 再次报告污染，说明回滚恢复了旧风险；通常不建议回滚到清理前状态。
