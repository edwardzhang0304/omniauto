# 微信AI智能记录员终极优化开发前置文档总索引（2026-05-11）

## 1. 目标
本索引用于把“通用底座 + 可切换客户模块 + LLM主导抽取 + 结构化校验兜底”的全部开工资料一次性整理齐全。
团队按本文档顺序阅读后，可以直接进入开发、联调、验收与灰度上线。

## 2. 文档清单
1. `WECHAT_AI_RECORDER_ULTIMATE_PRD_20260511.md`
产品目标、范围边界、用户场景、验收指标。
2. `WECHAT_AI_RECORDER_ULTIMATE_ARCHITECTURE_AND_MODULE_SWITCH_SPEC_20260511.md`
系统架构、可切换模块机制、运行链路。
3. `WECHAT_AI_RECORDER_ULTIMATE_DATA_AND_API_SPEC_20260511.md`
数据模型、接口协议、兼容性策略。
4. `WECHAT_AI_RECORDER_ULTIMATE_LLM_EXTRACTION_PROTOCOL_20260511.md`
“规则+LLM混合抽取”升级为“LLM主导+结构化辅助”的协议细则。
5. `WECHAT_AI_RECORDER_ULTIMATE_MODULE_DEVELOPMENT_GUIDE_20260511.md`
新客户模块接入规范，确保“只换模块，不改底座”。
6. `WECHAT_AI_RECORDER_ULTIMATE_ENGINEERING_BACKLOG_20260511.md`
开发包拆解、任务依赖、里程碑、开工检查清单。
7. `WECHAT_AI_RECORDER_ULTIMATE_TEST_AND_ACCEPTANCE_PLAN_20260511.md`
测试设计、数据对齐、准确率评估、UAT清单。
8. `WECHAT_AI_RECORDER_ULTIMATE_RELEASE_AND_OPERATION_RUNBOOK_20260511.md`
部署、灰度、回滚、运维、客服与管理员操作SOP。

## 3. 推荐阅读顺序
1. 先读 PRD（明确做什么、不做什么）。
2. 再读架构与模块切换规范（明确怎么做、如何保持可切换）。
3. 再读数据与API（明确前后端和服务间契约）。
4. 再读LLM抽取协议（明确核心能力和质量保障机制）。
5. 最后看开发清单、测试验收、上线运维（进入执行阶段）。

## 4. 角色导读
- 产品/业务负责人：优先看 PRD + 验收计划。
- 后端开发：优先看 架构 + 数据API + LLM协议 + 开发清单。
- 前端开发：优先看 数据API + 开发清单 + 运行手册。
- 测试/验收：优先看 测试验收计划 + 运行手册。
- 运维/交付：优先看 上线运维手册 + 回滚方案。

## 5. 开发前“资料齐套”判定标准
满足以下条件视为文档准备完成：
1. 功能范围、边界、优先级已明确且可追溯到 PRD 编号。
2. 模块切换与多租户绑定规则已定义，不依赖口头约定。
3. 所有核心接口有请求/响应示例、错误码、版本兼容说明。
4. LLM抽取有固定输出协议、置信度策略、失败兜底策略。
5. 有可执行测试计划，包含准确率目标与基线数据口径。
6. 有灰度发布、监控、回滚与应急处理手册。

## 6. 与既有文档关系
- 既有文档 `WECHAT_AI_RECORDER_CUSTOM_EXPORT_IMPLEMENTATION_PACKAGE.md` 仍可作为历史参考。
- 本套“ULTIMATE”文档作为当前版本实施主文档；存在冲突时，以本套文档为准。
