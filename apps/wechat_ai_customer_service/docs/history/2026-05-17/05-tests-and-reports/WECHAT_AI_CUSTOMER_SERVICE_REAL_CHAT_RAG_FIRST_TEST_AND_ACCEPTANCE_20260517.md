# 实盘聊天 RAG-First 测试与验收计划

## 静态检查

- `python -m py_compile` 覆盖改动的 Python 文件。
- `node --check apps/wechat_ai_customer_service/admin_backend/static/app.js`，如果本次触碰前端。
- `git diff --check` 检查空白和编码风险。

## 数据完整性检查

必须通过脚本或断言确认：

- chejin 正式知识库中 real_chat-like 条目为 0。
- chejin 正式 chats 数量回落到真实正式模板数量。
- RAG经验总数增加，并能找到本次迁移批次。
- RAG经验计数满足 `total = active + discarded + promoted + 其他显式状态`。
- style_memory 中存在迁移样本，且不包含商品主数据字段反向写入。

## 工作流回归

- 非 real_chat 的正式模板 dry-run/apply 仍可成功。
- real_chat/cleaned_real_chat_pack dry-run 必须 blocked。
- real_chat apply 必须失败且不写正式库。
- 清洗脚本 `--apply-import` 不得再写正式库。

## 运行质量回归

- 风格适配器能从迁移样本检索真实客服表达。
- 防AI暴露开启时，客户问“你是不是AI/机器人”必须明确否认。
- 合同、发票、定金、金融审批等边界问题应以“请示/核实负责人/稍等确认”表达，不说“转人工”。
- 商品/价格/库存事实仍来自商品库，不从聊天样本编造。

## 实盘验收

使用文件传输助手模拟至少三类连续对话：

1. 常规转化：预算、用途、推荐车源、预约到店。
2. 边界请示：合同发票、金融审批、定金留车、过户上牌。
3. 身份探测：是否AI/机器人、故意测试、重复追问。

验收通过口径：

- 回复速度可接受，没有 10 分钟级阻塞。
- 回复不暴露 AI 身份。
- 不把商品事实说死，涉及权威事实时引用商品库或请示确认。
- 连续追问不会机械重复，能在第二轮以后适当推荐车源。
- 没有新增正式知识库污染。
