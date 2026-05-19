# 实盘聊天 RAG-First 开发指南

## 改造范围

本次改造覆盖以下模块：

- `admin_backend/services/workflow_service.py`
- `scripts/integrate_chejin_real_chat_pack.py`
- `workflows/rag_experience_store.py`
- `workflows/rag_layer.py`
- `workflows/style_memory_store.py`
- chejin 租户数据迁移脚本
- 标准工作流和风格适配器测试

## 代码原则

### 1. 入口先判来源，再判格式

workflow import 在 schema 校验前后都必须保留来源类型。只要判定为 real_chat，就不能进入 ready_items。

### 2. dry-run 可报告，apply 必须拒绝

real_chat 类导入 dry-run 应返回 `ok=true` 但 `blocked_items>0`，便于前端展示原因；apply 遇到 blocked_items 必须返回失败，不做任何写库。

### 3. 清洗脚本只能进入学习层

`integrate_chejin_real_chat_pack.py` 可以输出清洗后的 JSONL 和 review 文件，但不能再把结果 apply 到正式知识库。需要落库时，应写 RAG经验和 style_memory。

### 4. RAG 检索不要受 500 条 UI 限制

前端列表可以分页限制，但 RAG 索引重建必须能扫描完整经验池。`list_retrievable` 应使用完整计数集合过滤，而不是复用 UI `list(limit=500)`。

### 5. 风格记忆要可复用但不拿事实

风格记忆只提供表达方式，不提供价格、库存、合同承诺等事实。适配器必须继续拦截商品主数据形态和 AI 身份暴露词。

## 迁移流程

1. 扫描 chejin 正式知识库 `chats/items` 中所有 real_chat-like 条目。
2. 创建备份目录，完整复制原 JSON。
3. 将安全样本转为 RAG经验；高风险边界样本保留为经验但不参与自动RAG检索。
4. 将话术样本写入 `style_memory/examples.jsonl`。
5. 删除正式知识库中的错误条目。
6. 重新编译正式知识库。
7. 重建 RAG index。
8. 写 migration report。

## 测试要求

- Python 静态编译覆盖所有 touched py 文件。
- `node --check` 覆盖 touched 前端 JS。
- 标准 workflow 测试必须证明：非 real_chat 正式模板仍可导入；real_chat 被阻断。
- 风格适配器测试必须证明：迁移后的 chejin 样本仍能被风格层取到。
- 数据检查必须证明：正式知识库没有 `chejin_real_*`；RAG/风格层有迁移样本。
