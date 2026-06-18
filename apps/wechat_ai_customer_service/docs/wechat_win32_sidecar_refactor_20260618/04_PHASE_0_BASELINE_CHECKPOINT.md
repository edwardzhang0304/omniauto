# Phase 0 Baseline Checkpoint

> Customer-visible reply ownership baseline: [../customer_visible_reply_ownership_baseline.md](../customer_visible_reply_ownership_baseline.md)

Phase 0 是落代码前的准备阶段。它的目标不是改代码，而是建立可回滚、可比较、可证明没破坏现有能力的基线。

## 前置原则

在开始第五点代码拆分前，先处理工作区状态：

1. 第四点 runtime cleanup 已经 staged，应优先单独 commit 成 checkpoint。
2. AGENTS.md 的命名规则修改、记录员 F8 修复等其他主题不要混入第五点。
3. 如果暂时不 commit，也必须在第五点文档或进度里明确哪些 staged/unstaged 不属于本次拆分。

推荐 checkpoint commit：

```text
chore: stop tracking generated runtime artifacts
```

第五点的每个阶段也建议单独 commit：

```text
docs: plan win32 sidecar refactor
test: guard win32 sidecar contracts
refactor: extract win32 sidecar pure helpers
refactor: extract win32 sidecar capture and layout helpers
refactor: extract win32 sidecar send helpers
refactor: extract add friend windows adapter glue
```

## 必查工作区

```powershell
git status --short
git diff --cached --name-status
git diff --name-status
```

需要确认：

- 是否有第四点 runtime cleanup 暂存。
- 是否有记录员 F8 未暂存。
- 是否有 AGENTS.md 未暂存。
- 是否有运行测试产生的新 runtime 文件。

不要做：

- 不要 `git reset --hard`。
- 不要清空 runtime 本机文件。
- 不要把其他主题强行合并进第五点。

## 基线测试命令

代码拆分前，先跑一次基线：

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_add_friend_package_smoke.py
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_compat_checks.py
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_customer_service_multi_session_scheduler_checks.py
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_workflow_logic_checks.py
.\.venv\Scripts\python.exe workflows\verification\general\runtime_artifact_guard.py check-staged
```

可选但推荐：

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_brain_first_static_architecture_audit.py
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_cloud_auth_required_checks.py
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_vps_local_two_port_shared_sync_checks.py
```

## 基线输出记录

每次进入第五点开发前，在阶段记录里写：

```text
baseline date/time:
branch:
HEAD:
staged unrelated changes:
unstaged unrelated changes:
tests passed:
tests failed:
known unrelated failures:
decision:
```

## 不通过时如何处理

### add_friend smoke 不通过

停止，不进入拆分。先修复或确认当前主分支已经坏了。

### win32 OCR compat 不通过

停止。这个测试直接保护 sidecar public helpers。

### workflow logic 不通过

如果第五点还没开始改代码，应先判断是否是已有无关失败。无关也要记录清楚。

### runtime guard 不通过

先修 staged runtime 产物，不要开始 sidecar 拆分。

## Phase 0 完成条件

- 工作区主题边界清楚。
- 第四点最好已形成 checkpoint。
- 基线测试结果记录清楚。
- 没有阻止第五点开始的失败。
- 后续每个阶段都能和这个基线比较。
