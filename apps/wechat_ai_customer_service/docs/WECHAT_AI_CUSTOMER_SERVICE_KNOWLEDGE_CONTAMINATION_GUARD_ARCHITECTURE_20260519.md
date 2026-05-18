# 微信客服知识污染防护架构 2026-05-19

## 背景

chejin 长测中曾出现“比亚迪秦新能源、每天通勤40公里、三电”等旧测试话题在后续场景中反复浮现。排查后确认，这类问题分两种：一是观察数据、学习数据、RAG 检索数据和运行态上下文之间边界不够硬导致的知识污染；二是本地确定性话术模板写死了旧测试场景，导致即使知识库干净也会复现旧话题。

## 根因

1. 客服监听链路曾同时承担“回复上下文观察”和“自动学习”职责，`auto_learn=true` 时会把文件传输助手、自测客户问题、AI 自回复写入 raw message 学习池。
2. `RawMessageStore` 过去只看批次级开关，未严格按每条消息的 `learning_enabled` 决定是否建学习 batch。
3. `RawMessageLearningService` 过去会把 raw 微信批次直接写入 RAG chunks，再生成经验审核记录，导致“未审核消息”先于审核进入可检索层。
4. `RagService.iter_chunks()` 过去只看 chunk active 状态，未按 `source_type/category/source_path/text marker` 做检索隔离。
5. 文件传输助手长测产生的运行态 `sent_replies/operator_alerts/handoff_events` 保留了旧回复，虽然后续已加时间过滤，但数据层仍不够干净。
6. 旧版实盘话术 JSONL 曾以 `upload/chats` 直接进入 RAG chunks，绕开了 RAG 经验层和风格层审核，容易造成机械化高频话术。
7. 本地回复模板曾把“每天40公里通勤”写入新能源三电话术，属于模板污染；这类信息不能作为固定模板出现，只能在客户明确说出后按原话引用。

## 新边界

| 层 | 允许内容 | 禁止内容 | 处理方式 |
| --- | --- | --- | --- |
| 客服监听观察层 | 当前回复所需的短期上下文、审计日志 | 文件传输助手、自回复、测试 marker、默认未授权的真实客服监听消息 | 默认只记录，不学习 |
| Raw Message 学习池 | 用户明确选中的记录员群/可信数据源 | customer_service 默认观察数据、文件传输助手、self message、模型回复 | 不建 batch 或 batch 标记 skipped |
| RAG 经验层 | 清洗后的真实聊天经验、人工保留经验 | 商品主数据、测试样本、模型自回复 | 审核后才可检索 |
| RAG chunks 直检索层 | 安全政策文档、非商品且非聊天原始上传资料 | `wechat_raw_message`、`products`、`erp_exports`、`raw_inbox/chats`、`raw_messages` 路径 | 检索时过滤，清理时隔离 |
| 商品主数据 | 人工导入/维护的车型、价格、库存、配置 | RAG 晋升、聊天经验提取、知识升级写入 | 只供回复引用，不反向学习 |
| 正式知识库 | 人工确认的稳定规则、流程、边界政策 | 真实聊天流水、测试 fixture 元数据、客户自测问题 | 作为规则使用，不存测试来源 |
| 实盘话术风格层 | 清洗后的真实客服风格样本 | 商品事实、旧测试对话、AI 自回复 | 调整语气，不授权事实 |
| 本地确定性话术模板 | 通用表达、流程性提醒、无具体客户事实的安全话术 | 写死车型、客户场景、预算、里程、通勤距离等旧测试事实 | 模板只写原则，客户事实必须来自当前对话或权威库 |

## 关键实现

1. 新增 `knowledge_contamination_guard.py` 作为统一防线，集中识别文件传输助手、测试 marker、模型回复 marker、商品主数据和 raw chat 直检索风险。
2. `RawMessageStore` 按消息级 `learning_enabled` 建 batch；不可学习消息保留审计但不会进入学习任务。
3. `RawMessageLearningService` 对 raw 微信批次改为 review-only RAG experience，不再直接 `ingest_file` 到 RAG chunks。
4. `RagService` 在索引和搜索时过滤不可检索 chunk，确保老数据即使还在磁盘，也不会被召回。
5. `listen_and_reply.py` 将 customer-service live 数据默认设为 record-only，除非未来显式配置可信学习来源。
6. 清理脚本会隔离旧 RAG chunks、关闭客服自动学习、清理运行态旧上下文、规范 formal seed 元数据。
7. 本地话术模板纳入污染审查：不得硬编码某次测试的车型、预算、通勤距离、客户身份；推荐链路只可从当前客户消息、商品主数据和已审核经验中取事实。
8. 本地模板必须做上下文门控：只有客户当前明确提到“老婆/新手/某车型/某场景”时，才允许在回复中带入对应人物、车型或场景；否则只能使用泛化但有内容的表达。

## 验收口径

1. chejin 不存在 active 的 `wechat_raw_message/products/erp_exports/raw_inbox/chats` 直检索 chunk。
2. raw messages 中 `learning_enabled=true` 的文件传输助手、自回复、测试 marker、模型回复 marker 数量为 0。
3. RAG 搜索旧测试词时，结果只能来自已审核 RAG experience 或正式规则，不得来自 raw 微信消息或旧直传聊天模板。
4. 运行态 state 中不得残留 `[车金AI]`、`REALWX_`、`LIVEFLOW_`、`GENLIVE`、`LLMSYN_` 等可污染上下文。
5. 正式知识库种子规则使用 `manual_seed`，不再以 `test_fixture` 作为生产来源。
6. 用新场景长测时，不得出现未由当前客户主动提供的旧测试事实，例如“40公里通勤”“秦PLUS”等；如果出现，要同时排查 RAG 检索源、运行态上下文和本地模板三条路径。
7. 长测报告除检查旧知识污染外，还要检查模板串场，例如比较 `奇骏/哈弗H6` 时不得无依据出现 `途观L`，公司用车场景不得无依据出现 `老婆/爱人/露营` 等旧场景词。
