# 微信自动客服 商品主数据权威化测试与验收计划（2026-05-14）

## 1. 验收目标
- 验证商品主数据写回链路已被彻底硬关闭。
- 验证话术/规则等非商品主数据链路不受破坏。
- 验证自动分诊会对商品主数据形态经验做自动降噪。

## 2. 核心用例矩阵
1. `source authority`：任意来源向 `products/erp_exports` 晋升必须拒绝。
2. `rag promotion`：商品形态经验不能生成商品候选。
3. `candidate apply`：候选链路不能写商品主数据。
4. `candidate reclassify`：候选不能改写分类到 `products/erp_exports`。
5. `formal overlap`：商品类相近冲突仅允许“保留正式知识并废弃经验”。

## 3. 建议执行命令
```powershell
python -m py_compile `
  apps/wechat_ai_customer_service/admin_backend/services/source_authority_policy.py `
  apps/wechat_ai_customer_service/admin_backend/services/rag_admin_service.py `
  apps/wechat_ai_customer_service/admin_backend/services/rag_experience_interpreter.py `
  apps/wechat_ai_customer_service/admin_backend/services/candidate_store.py `
  apps/wechat_ai_customer_service/tests/run_admin_backend_checks.py `
  apps/wechat_ai_customer_service/tests/run_smart_recorder_checks.py

python apps/wechat_ai_customer_service/tests/run_admin_backend_checks.py
python apps/wechat_ai_customer_service/tests/run_smart_recorder_checks.py
```

## 4. 通过标准
- 上述命令全部通过。
- 失败信息若涉及商品主数据写回，必须明确出现“权威主数据/手动维护”类提示。
- 不出现把商品主数据从经验层写回正式库的路径。

## 5. 交付物
- 代码改动（策略层、晋升层、候选层、自动分诊层）。
- 回归日志（命令、结果、关键断言）。
- long-run 状态文件与进度日志更新。
