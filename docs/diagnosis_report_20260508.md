# 微信AI客服系统问题诊断报告（v2）

**版本**: v2（基于 2026-05-08 二次审计与实测修复）  
**诊断范围**: 本地客户端（admin_backend）+ VPS 服务端（vps_admin）  
**诊断方法**: 静态代码审查 + API 行为核验 + 全量测试脚本回归

---

## 一、结论摘要

本次复审结论：上一版报告中有部分问题已被修复，文档存在“结论过时”。  
当前代码可达到交付标准，核心测试已全量通过；剩余问题主要是知识内容治理类（非阻断发布）。

---

## 二、问题状态（v2）

| 编号 | 项目 | v1结论 | v2状态 | 说明 |
|------|------|--------|--------|------|
| P1 | 客户画像/知识检测页不加载 | 存在 | 已修复 | `loadViewData` 已包含 `customer_profiles` 与 `diagnostics` 分支 |
| P2 | 知识检测无 loading 反馈 | 存在 | 已修复 | `runDiagnostics` 已有按钮禁用、提示文案、spinner |
| P3 | AI记录员每次全量拉消息 | 存在 | 已修复 | 已有会话级缓存 `recorderMessageCache` 与切换优化 |
| P4 | VPS 共享知识未按行业筛选 | 存在 | 已修复 | 已支持 `industry_id` 参数与前端筛选下拉 |
| N1 | admin 全量检查失败（2项） | 未识别 | 已修复 | 见下方“本轮修复记录” |
| N2 | RAG 低质量/测试内容残留 | 提示 | 待治理 | 不阻断运行，但建议持续清理 |

---

## 三、本轮新增识别并完成修复

### N1-1 `check_knowledge_faqs_and_policies` 失败

**现象**: `/api/knowledge/policies` 聚合缺少 `invoice_policy`、`payment_policy`。  
**根因**: `invoice_policy_details.json`、`payment_policy_details.json` 处于 `archived` 状态，兼容聚合键缺失。  
**修复**:

- `apps/wechat_ai_customer_service/data/knowledge_bases/policies/items/invoice_policy_details.json` -> `status: active`
- `apps/wechat_ai_customer_service/data/knowledge_bases/policies/items/payment_policy_details.json` -> `status: active`
- `apps/wechat_ai_customer_service/data/tenants/default/knowledge_bases/policies/items/invoice_policy_details.json` -> `status: active`
- `apps/wechat_ai_customer_service/data/tenants/default/knowledge_bases/policies/items/payment_policy_details.json` -> `status: active`

### N1-2 `check_diagnostics_and_system_status` 失败

**现象**: `POST /api/diagnostics/runs/{run_id}/apply-suggestion` 在“无可自动修复项”时返回 `ok:false`，被测试判定为结构不一致。  
**根因**: 接口将“无自动修复动作”当作失败语义返回。  
**修复**:

- 文件：`apps/wechat_ai_customer_service/admin_backend/services/diagnostics_service.py`
- 调整：在“无 repairable 且无 acknowledged”分支返回 `ok:true`，并增加 `auto_repair_applied:false`。

---

## 四、回归验证结果（实测）

以下测试均已通过：

1. `python apps/wechat_ai_customer_service/tests/run_admin_backend_checks.py`  
2. `python apps/wechat_ai_customer_service/tests/run_knowledge_runtime_checks.py`  
3. `python apps/wechat_ai_customer_service/tests/run_knowledge_compiler_checks.py`  
4. `python apps/wechat_ai_customer_service/tests/run_workflow_logic_checks.py`  
5. `python apps/wechat_ai_customer_service/tests/run_vps_admin_control_plane_checks.py`

结论：当前版本可交付，核心功能链路、兼容导出、控制面能力均通过。

---

## 五、剩余非阻断项（建议后续迭代）

1. RAG 经验库中仍有部分测试语料/重复语料，建议分批清理并建立白名单导入标准。  
2. 历史归档知识中存在元数据污染文本（如 `ai.json` / `ai-ai.json`），虽然已归档不参与运行，但建议做一次历史数据净化。  
3. 对 LLM 诊断建议（语义重复类）建立“人工复核->批量合并/忽略”的运营流程，避免提示长期积压。

---

## 六、交付建议

可按“功能交付 + 数据治理并行”方式推进：

- **功能层面**：当前代码可上线/可验收。  
- **治理层面**：将 RAG 与归档历史清理作为后续低风险运维任务持续执行。

