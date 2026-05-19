# 微信AI客服实盘聊天 RAG-First 修复文档索引

生成时间：2026-05-17T02:51:20

## 本次修复目标

修复“清洗后的实盘聊天数据被直接导入正式知识库”的架构缺陷。修复后，实盘聊天、微信原始聊天、清洗后的客服对话样本只能进入 RAG 经验层和实盘话术风格层；除非人工把它改写成稳定、通用、可审计的规则，否则不能直接成为正式知识。

## 配套文档

1. `WECHAT_AI_CUSTOMER_SERVICE_REAL_CHAT_RAG_FIRST_ARCHITECTURE_20260517.md`
   - 定义商品主数据、正式知识、RAG经验、话术风格记忆的分层关系。
   - 定义 real_chat 类来源的硬边界。

2. `WECHAT_AI_CUSTOMER_SERVICE_REAL_CHAT_RAG_FIRST_DATA_CONTRACT_20260517.md`
   - 定义来源类型、允许落点、禁止落点、字段要求和迁移字段。
   - 给代码测试提供可执行判断标准。

3. `WECHAT_AI_CUSTOMER_SERVICE_REAL_CHAT_RAG_FIRST_DEVELOPMENT_GUIDE_20260517.md`
   - 定义导入入口、工作流服务、RAG经验、风格适配器的改造步骤。
   - 明确不得用正式知识库承载原始/清洗聊天样本。

4. `WECHAT_AI_CUSTOMER_SERVICE_REAL_CHAT_RAG_FIRST_MIGRATION_RUNBOOK_20260517.md`
   - 定义 chejin 已误入正式库的 935 条实盘聊天样本如何备份、迁移、删除和回滚。

5. `WECHAT_AI_CUSTOMER_SERVICE_REAL_CHAT_RAG_FIRST_TEST_AND_ACCEPTANCE_20260517.md`
   - 定义静态测试、回归测试、数据完整性测试和文件传输助手实盘验收标准。

## 关键验收口径

- 正式知识库 `chats` 不再包含 `source.type=cleaned_real_chat_pack` 或 `chejin_real_*` 这类实盘聊天样本。
- workflow template import 遇到 real_chat 类来源必须 dry-run 阻断，apply 不能写入正式库。
- chejin 清洗聊天样本必须可在 RAG 经验/风格层被检索或引用。
- 商品事实仍只来自商品库；实盘聊天不能反向写商品事实。
- 文件传输助手连续对话表现正常，身份规避、边界请示、推荐转化都符合当前策略。
