# 微信AI客服系统优化方案（v2）

**版本**: v2（与 `diagnosis_report_20260508.md` 对齐）  
**目标**: 以“可交付稳定性”为主线，补齐剩余治理项，避免重复返工。

---

## 一、总体策略

采用“两条线并行”：

1. **交付线（阻断问题）**：接口语义、核心策略聚合、回归测试必须全绿。  
2. **治理线（非阻断问题）**：RAG 质量、历史归档污染、知识去重按批次持续优化。

---

## 二、本轮已完成（已落地）

### 1) 诊断修复接口语义统一

- 文件：`apps/wechat_ai_customer_service/admin_backend/services/diagnostics_service.py`
- 改动：`apply_suggestion` 在“无可自动修复项”时返回 `ok:true` + `auto_repair_applied:false`。
- 价值：前端与测试统一按“调用成功”处理，避免误报失败。

### 2) 核心 policy 聚合恢复完整

- 文件：
  - `apps/wechat_ai_customer_service/data/knowledge_bases/policies/items/invoice_policy_details.json`
  - `apps/wechat_ai_customer_service/data/knowledge_bases/policies/items/payment_policy_details.json`
  - `apps/wechat_ai_customer_service/data/tenants/default/knowledge_bases/policies/items/invoice_policy_details.json`
  - `apps/wechat_ai_customer_service/data/tenants/default/knowledge_bases/policies/items/payment_policy_details.json`
- 改动：`status` 从 `archived` 改为 `active`。
- 价值：`/api/knowledge/policies` 恢复 `invoice_policy`、`payment_policy` 聚合键，兼容能力完整。

### 3) 全量回归通过

- `run_admin_backend_checks` 通过  
- `run_knowledge_runtime_checks` 通过  
- `run_knowledge_compiler_checks` 通过  
- `run_workflow_logic_checks` 通过  
- `run_vps_admin_control_plane_checks` 通过

---

## 三、下一阶段执行清单（建议 1-3 天）

### A. RAG 经验治理（优先级 P1）

1. 清理明显测试内容/重复内容经验条目（按 experience_id 批量归档）。  
2. 保留高质量高复用经验，建立“可检索经验白名单”基线。  
3. 在诊断页增加“批量忽略/批量归档”辅助操作，降低人工维护成本。

### B. 历史归档净化（优先级 P2）

1. 清理归档知识中的元数据污染文本（如 `风险等级：...` 拼接到 `service_reply`）。  
2. 保留审计元数据到 `metadata`，避免污染业务字段。  
3. 输出一次性清理日志，确保可回溯。

### C. 文档与操作规程固化（优先级 P1）

1. 将“本地双端口联调（客户端+服务端）为默认验证路径”写入长期文档。  
2. 将“测试密钥可明文保留（仅本项目本地迁移场景）”规则放入项目级规范。  
3. 在发布清单中固定“5个核心回归脚本”作为准入门槛。

---

## 四、验收标准（v2）

1. 阻断项全部通过：5 个核心测试脚本全绿。  
2. 核心接口稳定：`/api/knowledge/policies` 包含 4 个核心 section。  
3. 诊断交互一致：`apply_suggestion` 在无自动修复时返回成功结构。  
4. 数据治理可追踪：RAG 清理与归档净化有明确变更记录。

---

## 五、风险与回滚

1. **风险**: policy 细节恢复为 active 后，若内容过时可能引入旧配置。  
   **缓解**: 通过诊断页 + 运营复核更新 `*_policy_details` 内容，不再直接归档关键 section。  

2. **风险**: RAG 批量清理过度导致检索召回下降。  
   **缓解**: 分批执行、每批后跑 `run_workflow_logic_checks` 与真实问答抽样验证。  

3. **回滚点**: 所有数据文件变更可通过 Git 回退到变更前提交；接口语义变更可单文件回滚。

---

## 六、执行结论

当前系统已满足交付条件。  
后续重点应从“修功能”转为“做治理”，用可追踪、低风险的批量流程持续提升知识质量。

