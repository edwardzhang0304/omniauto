# 微信自动客服多会话并发调度文档索引（2026-05-25）

## 目标

本轮文档定义微信自动客服在多个用户同时频繁咨询时的调度模型。核心原则是：

- 微信 RPA 操作必须串行，避免前台窗口抢占、鼠标键盘冲突和风控风险。
- LLM 思考可以并发，不能让某一个会话的模型等待阻塞全局监听。
- 每个会话的消息捕获、LLM 任务、待发送回复和发送复检必须有持久化状态。
- 同一会话只允许一个最新有效回复任务，旧上下文回复必须能被标记为 stale 并废弃或重算。
- 多会话高峰下必须可观测、可限流、可暂停、可恢复、可回滚。

## 文档清单

| 文档 | 用途 |
|---|---|
| `../01-architecture-and-plans/WECHAT_AI_CUSTOMER_SERVICE_MULTI_SESSION_CONCURRENCY_ARCHITECTURE_20260525.md` | 总体架构、现状缺口、目标链路、调度策略 |
| `../02-specs-and-contracts/WECHAT_AI_CUSTOMER_SERVICE_MULTI_SESSION_CONCURRENCY_DATA_CONTRACT_20260525.md` | 会话、消息、LLM 任务、发送队列、状态机和审计字段契约 |
| `../03-implementation-guides/WECHAT_AI_CUSTOMER_SERVICE_MULTI_SESSION_CONCURRENCY_DEVELOPMENT_GUIDE_20260525.md` | 开发落地顺序、模块拆分、兼容策略、实现注意事项 |
| `../03-implementation-guides/WECHAT_AI_CUSTOMER_SERVICE_MULTI_SESSION_CONCURRENCY_CODE_CHECKLIST_20260525.md` | 代码改造清单、文件影响面、代码审计点 |
| `../04-operations-and-migration/WECHAT_AI_CUSTOMER_SERVICE_MULTI_SESSION_CONCURRENCY_ROLLOUT_RUNBOOK_20260525.md` | 配置、灰度、运维、回滚和故障处置 |
| `../05-tests-and-reports/WECHAT_AI_CUSTOMER_SERVICE_MULTI_SESSION_CONCURRENCY_TEST_AND_ACCEPTANCE_PLAN_20260525.md` | 静态、单元、集成、模拟、实盘、长测验收计划 |
| `../05-tests-and-reports/WECHAT_AI_CUSTOMER_SERVICE_MULTI_SESSION_CONCURRENCY_IMPLEMENTATION_REPORT_20260525.md` | 本轮代码落地、关键修复、测试结果和实盘前建议 |
| `../99-misc/WECHAT_AI_CUSTOMER_SERVICE_MULTI_SESSION_CONCURRENCY_RISK_REGISTER_20260525.md` | 风险登记、失败模式、降级策略和验收红线 |

## 与既有文档的关系

- 继承 2026-05-23 RPA 稳定与风控文档：RPA-only、F8 控制、悬浮球、键鼠锁定、被动掉线探针仍是底层前提。
- 继承 2026-05-24 消息窗口恢复与 gap guard 文档：单会话刷屏不漏读、不重复仍是会话内正确性的基础。
- 扩展 2026-05-16 实时响应与 token 成本优化文档：本轮不是只降低单条回复耗时，而是把 LLM 慢任务从 RPA 主循环中解耦。
- 保留 `wxauto4` 技术储备禁用策略，本轮不引入 wxauto4 作为并发方案。

## 当前代码审计结论

当前链路已经具备多目标轮询框架，但还不能放心验收“多个用户同时频繁聊天”：

- `listen_and_reply.py --once` 会按目标列表逐个读取、思考、发送，LLM 等待会阻塞后续会话。
- `SessionMonitor` 用会话预览文本和时间变化判断活跃，但当前纯 RPA 会话列表 OCR 主要返回会话名，预览和时间不稳定。
- `max_targets_per_iteration` 截断活跃列表后，未进入本轮处理的会话存在下一轮被误判为无变化的风险。
- RPA 有全局锁，能保护窗口操作，但也意味着不能用多 RPA worker 并行切换微信。

## 交付原则

- 先让调度正确，再追求速度。
- 先做无发送模拟，再做受控实盘。
- 任何队列任务都必须可恢复，不依赖内存瞬态状态。
- 任何旧回复在发送前都必须经过当前会话复检。
- 高峰状态下宁可延迟或告警，也不能漏回、错回、串回、重复回。
