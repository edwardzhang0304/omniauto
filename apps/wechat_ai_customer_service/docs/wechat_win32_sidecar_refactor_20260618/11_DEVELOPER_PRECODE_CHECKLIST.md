# Developer Precode Checklist

> Customer-visible reply ownership baseline: [../customer_visible_reply_ownership_baseline.md](../customer_visible_reply_ownership_baseline.md)

这份清单给后续每一次第五点落代码前使用。先复制填写，再动代码。

## 变更单模板

```text
change title:
phase:
date:
owner:

goal:

files to change:

files explicitly not to change:

public contract touched:
  CLI action names: no/yes
  CLI flags: no/yes
  JSON fields: no/yes
  route constants: no/yes
  artifact scopes: no/yes
  WeChatConnector behavior: no/yes

expected behavior change:
  none / describe

tests before:

tests after:

rollback plan:

known unrelated worktree changes:

stop conditions:
```

## 落代码前必须回答

1. 这次是纯结构拆分，还是行为优化？
2. 是否会影响 `add-friend-entry-click-plan`？
3. 是否会影响 `send` 或双会话客服？
4. 是否会影响真实鼠标键盘动作？
5. 是否需要用户确认实盘？
6. 是否可能生成 runtime artifact？
7. 是否有稳定 fixture 需要迁到 `tests/fixtures`？

如果答案不清楚，不要动代码。

## 禁止清单

不允许：

- 未经确认改 route/CLI/JSON 字段名。
- 一次性重写 sidecar 大段逻辑。
- 把测试失败用放宽 guard 掩盖。
- 删除 operator guard。
- 删除 target confirmation。
- 删除 post-send validation。
- 删除 humanized pacing。
- 将运行产物提交到 Git。
- 在未确认状态下真实发送消息或加好友。

## 每步最小改动原则

每一步只做一种事：

```text
新增测试
或
提取纯函数
或
提取窗口 helper
或
提取 parser
或
提取 send helper
或
提取 add_friend helper
```

不要在同一 commit 里同时做：

- 提取模块 + 改算法。
- 改 route + 改 artifact。
- 改发送 + 改 Brain。
- 改 runtime cleanup + 改 sidecar。

## 文档同步要求

每个阶段落代码后更新：

```text
对应 phase 文档的执行记录
10_TEST_AND_ACCEPTANCE_PLAN.md 中的测试结果，如有新增测试
.codex-longrun/progress.md
.codex-longrun/test-log.md
```

如变更 contract，必须同时更新：

```text
03_CONTRACT_FREEZE_AND_COMPATIBILITY_GUARD.md
apps/wechat_ai_customer_service/tests/run_add_friend_package_smoke.py
apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_compat_checks.py
AGENTS.md 相关规则，若确实改变协作契约
```

## Staging 前审计

```powershell
git status --short
git diff --name-status
git diff --cached --name-status
.\.venv\Scripts\python.exe workflows\verification\general\runtime_artifact_guard.py check-staged
```

检查：

- 是否混入第四点 runtime cleanup 之外的新 runtime 产物。
- 是否混入 AGENTS.md 或记录员 F8 未计划改动。
- 是否混入临时调试文件。
- 是否误 stage secrets/local env。

## 测试记录模板

```text
command:
result:
duration:
failures:
if failed, suspected cause:
fix attempted:
rerun:
decision:
```

## 回滚策略

优先级：

1. 回退本阶段 facade 委托，让 sidecar 使用旧实现。
2. 保留新模块但不接入。
3. 回退本阶段新增测试中错误假设。
4. 不要回退用户或其他主题的改动。

## 实盘测试前清单

```text
user confirmed live operation:
wechat logged in:
target session/account:
floating-ball operator guard enabled:
manual mouse/keyboard interference blocked:
dry-run passed:
runtime artifact dir:
stop condition:
```

实盘期间：

- 一旦识别不确定，停止。
- 一旦目标会话不匹配，停止。
- 一旦 operator guard 不可用，停止。
- 不重复机械点击同一点。

## 完成判定

一次第五点阶段开发只有在以下条件都满足时才能说完成：

- 代码变化符合对应 phase 文档。
- 契约没有未经确认变化。
- 必跑测试通过。
- runtime guard 通过。
- 文档和长任务状态已更新。
- 如使用 long-running-task，已发 ServerChan 验收提醒。
