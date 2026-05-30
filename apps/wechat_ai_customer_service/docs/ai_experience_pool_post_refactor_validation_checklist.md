# AI经验池架构改造后补充验证清单

## 目标

本清单用于验证“AI经验池作为入口治理和分发中枢，运行时回答只以商品库、正式知识库、当前对话事实为内容依据”的架构改造没有带来负面影响。

## 验证原则

- 先离线/模拟，全部通过后再做低频实盘。
- 实盘只做 smoke，不做刷屏压力，避免不必要的微信风控。
- 商品库事实优先级最高，其次正式知识库；AI经验池、话术风格层、LLM常识层只做辅助。
- 旧技术标识可以保留，但用户可见语义必须统一为 AI经验池。

## 离线/模拟专项清单

| 编号 | 场景 | 通过标准 | 命令或覆盖 |
| --- | --- | --- | --- |
| AEP-01 | 新导入/采集材料入口 | 上传、聊天、原始消息类材料先记录为 AI经验池项，不直接进入运行时 RAG 索引 | `run_ai_experience_pool_post_refactor_validation_checks.py` |
| AEP-02 | 入口到候选链路 | AI经验池中被判定可沉淀的经验只能生成待确认候选，不能自动写入正式知识 | `run_ai_experience_pool_post_refactor_validation_checks.py`、`run_rag_candidate_nomination_checks.py` |
| AEP-03 | 人工确认升级链路 | 经人工泛化后的候选可写入正式知识库，并被运行时读取；未泛化或含具体客户/模型回复的候选被阻断 | `run_ai_experience_pool_post_refactor_validation_checks.py`、`run_knowledge_contamination_guard_checks.py` |
| AEP-04 | 商品库边界 | AI经验池和候选知识链路不能写入商品主数据；商品事实只能来自商品库 | `run_ai_experience_pool_post_refactor_validation_checks.py`、`run_product_master_split_checks.py` |
| AEP-05 | 负面泄漏 | 旧价格、库存、手机号、VIN、具体聊天承诺、AI身份/系统提示等不能作为事实回答依据 | `run_authority_gated_ai_experience_pool_checks.py`、`run_knowledge_contamination_guard_checks.py` |
| AEP-06 | 优先级冲突 | 同时命中商品库、正式知识、AI经验池时，答案事实以商品库/正式知识为准，AI经验池只影响风格 | `run_ai_experience_pool_post_refactor_validation_checks.py`、`run_knowledge_authority_refactor_checks.py` |
| AEP-07 | 旧数据兼容 | 旧经验记录、真实聊天、上传原文记录不会被运行时检索重新捞出 | `run_authority_gated_ai_experience_pool_checks.py`、`run_rag_layer_checks.py` |
| AEP-08 | 前端和云包语义 | 管理端、VPS端、知识包说明不再出现旧经验层/经验检索误导性用户文案 | `run_ai_experience_pool_post_refactor_validation_checks.py`、文案扫描 |
| AEP-09 | 多租户隔离 | chejin、test02、default 以及测试租户的 AI经验池/正式知识/商品库互不串用 | `run_ai_experience_pool_post_refactor_validation_checks.py`、`run_multi_tenant_auth_sync_checks.py` |
| AEP-10 | 运行时质量回归 | chejin 二手车常规、连续、边界、明确建议问题仍能正常回答 | `run_realtime_reply_optimization_checks.py`、`run_workflow_logic_checks.py`、实盘 smoke |

## 实盘 smoke 清单

| 编号 | 场景 | 通过标准 |
| --- | --- | --- |
| LIVE-01 | 文件传输助手常规商品推荐 | 回复基于商品库，价格和车型贴近客户需求，不引用历史聊天作为事实 |
| LIVE-02 | 文件传输助手明确建议问题 | 对“轿车/SUV/预算/油耗/车况”类问题给出明确建议，避免空泛 |
| LIVE-03 | 实盘后置探针 | 微信保持在线，无白屏、无踢出，RPA adapter 为 `win32_ocr`，wxauto4 未启用 |

## 停止条件

- 任一离线/模拟测试失败，先修复再进入实盘。
- 实盘出现白屏、掉线、登录页、安全提示，立即停止，不继续发送。
- 发现 AI经验池材料进入运行时内容依据，视为架构阻断级问题。
