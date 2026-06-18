# WeChat Win32 OCR Sidecar Refactor Docs 2026-06-18

> Customer-visible reply ownership baseline: [../customer_visible_reply_ownership_baseline.md](../customer_visible_reply_ownership_baseline.md)

本文档集用于解决第五点：`apps/wechat_ai_customer_service/adapters/wechat_win32_ocr_sidecar.py` 过大、职责混杂、后续继续维护容易互相踩坏的问题。

本轮只落开发前材料，不修改运行代码。后续落代码时，必须按本文档集分阶段执行、分阶段测试、分阶段复盘。

## 当前目标

把 `wechat_win32_ocr_sidecar.py` 从“一切都在一个文件里”的大脚本，逐步收束为：

```text
stable sidecar CLI facade
  -> action router
  -> Windows device/window/capture/OCR/input/session/send/add_friend modules
  -> existing public JSON contracts and Worker-facing commands unchanged
```

核心原则：

- 不改变 `add-friend-entry-click-plan` 等 Worker-facing CLI 契约。
- 不随便改变量名、常量名、route 名、JSON 字段名、文件路径契约。
- 不改变 Brain First 架构：sidecar 属于代码机制层，只负责 OCR/RPA/会话绑定/发送安全，不能生成客户可见回复。
- 不把第四点 runtime 清理、记录员 F8 修复、第五点 sidecar 拆分混成一个不可复盘的大改动。
- 先提取纯函数和只读模块，再提取有副作用的窗口/点击/发送模块。
- 每一步拆完都必须跑对应契约测试和 smoke 测试。

## 文档清单

1. [01_CURRENT_STATE_AND_RISK_AUDIT.md](01_CURRENT_STATE_AND_RISK_AUDIT.md)
   - 当前 `wechat_win32_ocr_sidecar.py` 职责地图、风险和已拆出的 add_friend 模块。
2. [02_TARGET_ARCHITECTURE_AND_BOUNDARIES.md](02_TARGET_ARCHITECTURE_AND_BOUNDARIES.md)
   - 目标模块结构、边界、依赖方向、sidecar facade 保留策略。
3. [03_CONTRACT_FREEZE_AND_COMPATIBILITY_GUARD.md](03_CONTRACT_FREEZE_AND_COMPATIBILITY_GUARD.md)
   - CLI、route、JSON、artifact、测试契约冻结规则。
4. [04_PHASE_0_BASELINE_CHECKPOINT.md](04_PHASE_0_BASELINE_CHECKPOINT.md)
   - 落代码前的 Git/checkpoint/基线测试要求。
5. [05_PHASE_1_CONTRACT_GUARDS.md](05_PHASE_1_CONTRACT_GUARDS.md)
   - 先补保护网，再动结构的实施材料。
6. [06_PHASE_2_PURE_EXTRACTION_GUIDE.md](06_PHASE_2_PURE_EXTRACTION_GUIDE.md)
   - 纯函数、常量、env/config、文本归一化等低风险提取步骤。
7. [07_PHASE_3_DEVICE_LAYOUT_CAPTURE_GUIDE.md](07_PHASE_3_DEVICE_LAYOUT_CAPTURE_GUIDE.md)
   - 窗口、DPI、截图、OCR、布局/profile 的中风险提取步骤。
8. [08_PHASE_4_SEND_SESSION_ACTION_GUIDE.md](08_PHASE_4_SEND_SESSION_ACTION_GUIDE.md)
   - 发送、会话切换、人类化输入、动作风控的高风险提取步骤。
9. [09_PHASE_5_ADD_FRIEND_ADAPTER_GUIDE.md](09_PHASE_5_ADD_FRIEND_ADAPTER_GUIDE.md)
   - add_friend 与 Windows sidecar 的边界收束步骤。
10. [10_TEST_AND_ACCEPTANCE_PLAN.md](10_TEST_AND_ACCEPTANCE_PLAN.md)
    - 每阶段必须跑的静态、契约、smoke、实盘验收矩阵。
11. [11_DEVELOPER_PRECODE_CHECKLIST.md](11_DEVELOPER_PRECODE_CHECKLIST.md)
    - 每次落代码前必须复制使用的变更说明模板、回滚说明和审计清单。

## 推荐执行顺序

```text
先提交第四点 runtime cleanup checkpoint
  -> Phase 0 建立第五点基线
  -> Phase 1 补契约 guard
  -> Phase 2 提取纯函数
  -> Phase 3 提取窗口/截图/OCR/布局
  -> Phase 4 提取发送/会话/动作风控
  -> Phase 5 收束 add_friend adapter 边界
  -> 最后一轮完整 smoke + 必要实盘
```

## 本文档集的完成条件

- 每个阶段都有明确的目标、可改文件、禁止事项、测试命令、停止条件。
- 文档中的所有路径能在当前仓库中定位，或明确标记为“拟新增”。
- 所有契约名与当前实现一致，尤其是 `add-friend-entry-click-plan`。
- 文档不要求一次性大拆，不鼓励行为重写。
- 审计后确认不会误导后续开发者破坏当前可用性。
