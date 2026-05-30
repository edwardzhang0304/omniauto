# 剩余边界验证清单（2026-05-30）

目标：在 AI经验池 / 商品库 / 正式知识 / 常识与风格辅助层完成重构后，再覆盖剩余高价值边界。测试顺序为“主模拟、辅实盘”，避免高频真实微信操作。

## 模拟优先项

| 编号 | 场景 | 通过标准 | 主要命令 |
| --- | --- | --- | --- |
| SIM-01 | AI经验池入口与分发 | AI经验池不作为运行时事实依据，商品库价格不可被旧经验覆盖 | `run_ai_experience_pool_post_refactor_validation_checks.py` |
| SIM-02 | 权威层级与污染防护 | 商品库 > 正式知识 > 当前对话事实；旧聊天/上传原文只作治理或风格辅助 | `run_authority_gated_ai_experience_pool_checks.py`, `run_knowledge_contamination_guard_checks.py` |
| SIM-03 | 商品库候选与预算贴合 | 明确“哪两台/推荐两台”走商品库候选；价格贴近客户预算 | `run_realtime_reply_optimization_checks.py`, `run_product_master_split_checks.py` |
| SIM-04 | 连续对话上下文 | 能继承预算、用途、车型偏好，不重复问已给信息 | `run_customer_service_diverse_long_checks.py`, `run_customer_service_real_wechat_fresh_long_flow_checks.py --dry-run` |
| SIM-05 | 当前轮抢占旧上下文 | 材料、金融、地址、到店等当前问题不被旧推荐需求劫持 | `run_workflow_logic_checks.py`, `run_boundary_matrix_checks.py` |
| SIM-06 | 多消息刷屏/历史回补 | 批量消息能合并理解；不漏读、不重复回复；回补仍走纯 RPA 兼容路径 | `run_burst_message_rpa_semantic_batch_checks.py`, `run_customer_service_multi_session_scheduler_checks.py` |
| SIM-07 | 多会话并发调度 | 多会话消息采集与 LLM 任务并发、回复串行发送保持稳定 | `run_customer_service_multi_session_scheduler_checks.py` |
| SIM-08 | 转人工与安全边界 | 价格砍价、贷款包过、合同发票、掉线/白屏等进入转人工或停机保护 | `run_delivery_boundary_checks.py`, `run_feishu_integration_checks.py`, `run_rpa_acceptance_report_checks.py` |
| SIM-09 | RPA窗口/白屏/掉线护栏 | RPA-only、wxauto4 未选用；白屏/辅助壳/掉线探针有效 | `run_wechat_win32_ocr_compat_checks.py`, `run_sandbox_wechat_safety_checks.py` |
| SIM-10 | 云端登录与共享知识 | 本地双端模拟通过；云门禁缺少真实 VPS 时按项目基线归类 | `run_vps_local_two_port_shared_sync_checks.py`, `run_cloud_gate_lock_checks.py` |

## 实盘低频项

| 编号 | 场景 | 通过标准 | 脚本 |
| --- | --- | --- | --- |
| LIVE-01 | 新手家庭代步连续对话 | 从刚加好友、推荐、比较、预约到资料记录均自然；商品事实来自商品库 | `chejin_sales_dialogue_context_live.py --flow-ids new_driver_family_visit` |
| LIVE-02 | 活动公司载物接待连续对话 | 能围绕预算、载物、接待、车况和预约推进，不泄漏无关上下文 | `chejin_sales_dialogue_context_live.py --flow-ids event_business_visit` |
| LIVE-03 | 置换高速家用连续对话 | 能处理置换、后排舒适、保值、到店和资料记录；高风险不承诺 | `chejin_sales_dialogue_context_live.py --flow-ids trade_in_highway_visit` |

## 复盘口径

- 回复质量：不暴露 AI、不过长、不省略号截断、不重复问预算、不承诺高风险事项。
- 层级正确：商品库和正式知识作为事实依据；AI经验池、真实聊天、风格样例只作辅助。
- 效率：常规候选推荐尽量走本地/轻量路径；必要 LLM 调用不阻塞多会话采集。
- RPA安全：低频、RPA-first、`win32_ocr`，不启用 `wxauto4`，实盘后微信保持在线。
