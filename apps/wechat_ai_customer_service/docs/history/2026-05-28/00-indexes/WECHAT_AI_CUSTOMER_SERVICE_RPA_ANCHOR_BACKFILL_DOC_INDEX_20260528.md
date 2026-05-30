# 微信自动客服 RPA 锚点追溯文档索引（2026-05-28）

## 目标

本轮文档把微信自动客服的历史回滚机制从“固定次数补读”升级为“锚点驱动的增量追溯”。

核心判断是：历史回滚不是坏动作，错误、机械、没有停止条件的回滚才是风险。新的机制应先在当前可见窗口查找上一轮处理锚点；能找到就不回滚，找不到才低扰动、小步追溯；找到锚点立即停止；找不到则暂停或转人工。

## 文档清单

| 文档 | 用途 |
|---|---|
| `../01-architecture-and-plans/WECHAT_AI_CUSTOMER_SERVICE_RPA_ANCHOR_BACKFILL_ARCHITECTURE_20260528.md` | 总体架构、现状缺口、目标流程、锚点策略和回滚停止条件 |
| `../02-specs-and-contracts/WECHAT_AI_CUSTOMER_SERVICE_RPA_ANCHOR_BACKFILL_DATA_CONTRACT_20260528.md` | 配置、状态、sidecar 请求响应、审计字段和兼容契约 |
| `../03-implementation-guides/WECHAT_AI_CUSTOMER_SERVICE_RPA_ANCHOR_BACKFILL_DEVELOPMENT_GUIDE_20260528.md` | 分阶段落地步骤、代码影响面、兼容策略和审计点 |
| `../03-implementation-guides/WECHAT_AI_CUSTOMER_SERVICE_RPA_SANDBOX_SAFETY_EXECUTION_PLAN_20260528.md` | 本轮风险收束、静态/全量/实盘测试顺序，以及沙盒双号测试门禁 |
| `../05-tests-and-reports/WECHAT_AI_CUSTOMER_SERVICE_RPA_ANCHOR_BACKFILL_TEST_AND_ACCEPTANCE_PLAN_20260528.md` | 单元、集成、模拟、实盘、长测和验收标准 |
| `../99-misc/WECHAT_AI_CUSTOMER_SERVICE_RPA_ANCHOR_BACKFILL_RISK_REGISTER_20260528.md` | 风险登记、失败模式、停机/转人工策略、后续自测清单、RPA 高风险行为和不可做事项 |

## 与既有文档的关系

- 继承 2026-05-18 连续消息与刷屏优化文档，但替换其中“固定 `load_times` 补读”的默认实盘策略。
- 继承 2026-05-23 RPA 稳定与低扰动操作原则，继续保持 RPA-only，wxauto4 仅作为技术储备。
- 继承 2026-05-24 消息窗口恢复与 gap guard 思路，但把 gap guard 的定位依据明确为“上一轮成功处理锚点”。
- 继承 2026-05-25 多会话并发调度设计：RPA 操作仍串行，LLM 可并发；会话内消息边界由本方案负责。

## 方案一句话

每个会话保存“上一轮成功回复边界”，下一轮先在当前屏幕找边界；找到则只处理边界之后的新消息，找不到才逐步上翻找边界，找到即停，找不到就暂停或转人工。

## 交付前提

- 不伪造设备、硬件、网络或微信环境。
- 不恢复 wxauto4 优先级。
- 不让 LLM 线程直接操作微信窗口。
- 不在实盘中无条件固定次数上翻。
- 不因为追求完整性而牺牲错回、串回、重复回的安全底线。
