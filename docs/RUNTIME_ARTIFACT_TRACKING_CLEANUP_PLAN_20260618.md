# Runtime 运行产物 Git 跟踪治理方案

日期：2026-06-18

## 背景

当前主分支已经和 GitHub 远端 `origin/master` 对齐：

- 本地分支：`master`
- 本地 HEAD：`cd5a2c8688cb36de80b2c49b1470040eec7dcec0`
- GitHub `origin/master` HEAD：`cd5a2c8688cb36de80b2c49b1470040eec7dcec0`

这意味着：已经提交到 Git 历史里的源码和已跟踪文件，在 GitHub 上有备份。

需要特别区分的是：

- 已跟踪文件：GitHub 上有对应提交版本，可以回退。
- 本地未跟踪文件：不在 GitHub 提交里，不能视为已备份。
- 本地已修改但未提交的 runtime 文件：GitHub 上有旧版本，但没有当前本机变更版本。

因此，本治理方案的第一原则是：先建立规则和审计清单，不直接删除本机 runtime 现场文件；后续如果要清理，只做 `git rm --cached` 取消跟踪，保留本机文件。

## 清理归档原则

所有 runtime 清理工作必须先保留可恢复痕迹，再执行清理动作。

固定归档位置：

- 本地归档根目录：`runtime/cleanup_archive/`
- 推荐批次目录：`runtime/cleanup_archive/YYYYMMDD_HHMMSS_<purpose>/`

归档目录默认不进入 Git。它用于保存本机清理过程中的现场清单、manifest、dry-run 结果、恢复说明和必要的补充备份索引。

每次清理前至少生成：

- `manifest.json`：本批次元数据，包括 Git HEAD、分支、远端 HEAD、执行时间、目标范围。
- `tracked_runtime_inventory.csv`：已跟踪 runtime 文件清单。
- `worktree_runtime_status.csv`：当前 runtime 工作区状态清单。
- `restore_notes.md`：恢复说明，说明如何从 GitHub 提交版本、本地文件、或人工备份中恢复。

禁止直接删除 runtime 文件。确需从 Git 中清理历史运行产物时，只允许使用 `git rm --cached` 取消跟踪，并在执行前生成本地归档清单。

如果清理动作涉及大量文件，必须单独提交，不和业务代码、RPA 逻辑、AI 客服逻辑混在同一个提交里。

## 当前问题

当前 `runtime` 目录中有大量运行现场文件被 Git 跟踪：

- `git ls-files runtime` 统计：2974 个已跟踪文件。
- 其中 `runtime/apps/wechat_ai_customer_service` 统计：2964 个已跟踪文件。
- 当前 `runtime` 工作区变更统计：约 305 项，其中包括 modified、deleted、untracked。
- 已跟踪 runtime 文件类型集中在 `.json`、`.txt`、`.xlsx`、`.png`、`.zip`、`.jsonl`、`.log` 等运行产物。

这些文件大多属于：

- 实盘运行日志；
- 微信窗口截图；
- OCR/RPA 诊断输出；
- 本地登录态、session、auth 状态；
- 租户运行状态；
- 测试报告和 latest artifact；
- Excel 导出；
- 临时调试脚本或现场快照。

这些内容会随着实盘测试、自检、微信 AI 客服运行、加好友测试而频繁变化。如果继续被 Git 跟踪，会导致代码改动和运行现场混在一起，影响复盘、审查、合并和协作。

## 根因分析

### 1. 源码、测试样本、运行现场没有边界

`runtime` 本应主要承载本机运行输出，但历史上部分测试样本、调试产物、运行状态一起被提交进 Git。随着微信 AI 客服和加好友模块频繁实盘，目录内容越来越像“本机现场”，而不是“项目源码”。

### 2. `.gitignore` 已有规则，但对历史已跟踪文件无效

当前 `.gitignore` 已经包含：

- `runtime/apps/`
- `runtime/logs/`
- `runtime/state/`
- `runtime/outputs/`
- `runtime/test_artifacts/*`
- `runtime/cleanup_archive/`

但是 `.gitignore` 只能阻止新的未跟踪文件进入 Git，不能让已经被 Git 跟踪的文件自动停止跟踪。因此，历史已跟踪的 runtime 文件仍会继续出现在 `git status` 里。

### 3. 测试脚本和实盘流程会写入同一批 runtime 路径

当前很多测试、诊断、验收流程默认把输出写到 `runtime/...`。这对本地排障是有用的，但如果输出路径被 Git 跟踪，就会造成每次测试都污染工作区。

### 4. 缺少提交前防线

目前没有强制检查来阻止 PR 或提交误带 runtime 产物。只靠人工看 `git status`，在文件数量很多时非常容易漏掉。

## 治理目标

1. 保留 GitHub 上已有备份和历史可回退能力。
2. 不破坏当前本机运行环境，不删除本地 runtime 现场文件。
3. 让后续代码提交只包含源码、文档、测试 fixture 和必要模板。
4. 将运行产物从 Git 跟踪中剥离，减少复盘噪音。
5. 为微信 AI 客服、加好友、RPA 实盘测试保留本地诊断能力。
6. 建立提交前检查，避免问题反复发生。

## 非目标

本方案暂不处理以下事项：

- 不重构微信 AI 客服业务逻辑。
- 不重构 add friend RPA 逻辑。
- 不删除本地 runtime 文件。
- 不清理本地账号、session、tenant 状态。
- 不把本地未跟踪文件自动上传到 GitHub。

如果需要对本地未跟踪 runtime 现场做备份，应另行执行压缩备份或私有存储备份。

## 文件分类规则

### A 类：应继续跟踪

这些文件可以保留在 Git 中：

- `runtime/README.md`
- `runtime/test_artifacts/README.md`
- 明确用于说明目录用途的 `.md` 文档
- 必要的 `.gitkeep`
- 明确、稳定、去敏的测试 fixture
- 用于开发者复现的最小样例

要求：

- 内容稳定；
- 不包含本地账号/session/token；
- 不随实盘运行自动变化；
- 有清楚用途说明。

### B 类：应迁移到测试 fixtures

这些文件如果确实用于自动化测试，应从 `runtime` 迁移到模块内测试目录，例如：

- `apps/wechat_ai_customer_service/tests/fixtures/...`
- `apps/wechat_ai_customer_service/tests/golden/...`

典型对象：

- OCR 样例输入；
- 结构化 JSON 黄金样例；
- 固定测试用小型 Excel；
- 去敏后的标准诊断样本。

迁移要求：

- 测试脚本同步更新读取路径；
- 样本要去敏；
- 文件名体现用途；
- 不使用 `latest`、日期流水号作为 fixture 名称。

### C 类：应取消 Git 跟踪并忽略

这些文件应保留在本地，但不应进入 Git：

- `.log`
- `.jsonl`
- 运行状态 `.json`
- session/auth/local account 文件
- 本地 tenant runtime state
- 截图 `.png`
- 导出 `.xlsx`
- 压缩包 `.zip`
- latest report
- live probe 输出目录
- add friend 实盘探测目录
- 微信窗口布局探测目录
- 本地诊断脚本的输出结果

处理方式：

- 用 `git rm --cached` 从 Git 索引移除；
- 不删除本地文件；
- 由 `.gitignore` 阻止后续重新进入 Git。

## 建议执行阶段

### 阶段 0：确认备份和冻结范围

已确认：

- 本地 `master` 与 GitHub `origin/master` 均为 `cd5a2c8688cb36de80b2c49b1470040eec7dcec0`。
- 已提交版本在 GitHub 上有备份。

执行前还应确认：

- 本地是否有必须长期保留但未提交的 runtime 现场。
- 是否需要把本地未跟踪 runtime 目录额外压缩备份。
- 是否要创建一个 Git tag，例如 `backup-before-runtime-cleanup-20260618`。

### 阶段 1：先加护栏，不清理历史

新增检查脚本或测试，检查提交中是否包含不允许的 runtime 变更。

建议规则：

- 默认禁止新增或修改 `runtime/apps/**`。
- 允许 `runtime/README.md`。
- 允许 `runtime/test_artifacts/README.md`。
- 允许明确列入 allowlist 的 fixture。
- 检查失败时输出具体文件和治理文档链接。
- 新增本地归档检查能力，默认把审计清单写入 `runtime/cleanup_archive/`。

这样可以先阻止问题继续扩大，同时不影响当前运行现场。

### 阶段 2：生成 runtime 跟踪清单

生成一份机器可读清单，用于审查每个已跟踪 runtime 文件属于 A/B/C 哪一类。

建议输出：

- 文件路径；
- 文件扩展名；
- 当前 Git 状态；
- 建议分类；
- 是否包含敏感字段风险；
- 建议处理动作。

该清单必须放在 `runtime/cleanup_archive/<batch>/`，不要直接提交到 Git。清单里可能包含手机号、联系人名、租户名、登录态文件名或本地路径，默认按本地敏感现场处理。

### 阶段 3：迁移真正需要的 fixture

对少量确实需要进 Git 的测试样本：

1. 迁移到对应模块的 `tests/fixtures`。
2. 修改测试脚本读取路径。
3. 保留兼容说明。
4. 跑相关测试。

原则：先迁移少量确定有用的样本，不把整批 runtime 内容搬进 fixtures。

### 阶段 4：取消跟踪 C 类文件

经确认后，执行类似：

```powershell
git rm --cached -- <path>
```

注意：

- 只取消 Git 跟踪；
- 不删除本地文件；
- 不使用 `git rm` 直接删除本机 runtime；
- 不使用 `git reset --hard`；
- 不批量处理未审查路径。

阶段 4 建议单独提交，提交信息明确说明：

```text
chore: stop tracking generated runtime artifacts
```

## 2026-06-18 第一轮执行记录

本轮按“小心、不破坏结构、可恢复”的原则执行了第一批治理：

1. 新增本地清理归档规则，固定使用 `runtime/cleanup_archive/` 保存清单、manifest 和恢复说明。
2. 新增 runtime 护栏脚本：`workflows/verification/general/runtime_artifact_guard.py`。
3. `.gitignore` 增加 `runtime/cleanup_archive/` 和 runtime 根目录默认忽略规则，防止新生成的 runtime 现场继续刷屏。
4. 清理前生成本地归档：
   - `runtime/cleanup_archive/20260618_112241_issue4_runtime_tracking_phase1/`
   - 清理前已跟踪 runtime 文件：2974 个。
   - 清理前 runtime 工作区状态：305 条。
5. 第一轮候选清单：
   - `runtime/cleanup_archive/20260618_112241_issue4_runtime_tracking_phase1/phase1_untrack_candidates.txt`
   - 共 2964 个明显运行产物。
   - 本轮只处理非 `.py` / `.md` 文件。
6. 执行 `git rm --cached --pathspec-from-file=...`，只取消 Git 跟踪，不删除本机文件。
7. 清理后生成本地归档：
   - `runtime/cleanup_archive/20260618_113401_issue4_runtime_tracking_after_untrack/`
   - 清理后已跟踪 runtime 文件：10 个。
   - 当前暂存的 runtime 索引删除：2964 个。
8. 已验证样例 runtime 文件仍存在于本机：
   - `runtime/apps/wechat_ai_customer_service/admin/audit.jsonl`
   - `runtime/apps/wechat_ai_customer_service/admin/admin_backend_stdout.log`
   - `runtime/wechat_window_probe.png`

第一轮保留未动的 10 个 runtime 已跟踪文件：

- `runtime/README.md`
- `runtime/test_artifacts/README.md`
- `runtime/two_visible_session_customer_service_live.py`
- `runtime/apps/wechat_ai_customer_service/README.md`
- `runtime/apps/wechat_ai_customer_service/manual_upload_samples/20260426_round2/03_chat_records_new_energy_storage.md`
- `runtime/apps/wechat_ai_customer_service/manual_upload_samples/20260426_round2/README_UPLOAD_TESTS.md`
- `runtime/apps/wechat_ai_customer_service/test_artifacts/jiangsu_chejin_used_car/demo_materials/CHEJIN_DEMO_20260503_203628/chats_CHEJIN_DEMO_20260503_203628.md`
- `runtime/apps/wechat_ai_customer_service/test_artifacts/jiangsu_chejin_used_car/demo_materials/CHEJIN_DEMO_20260503_203628/manual_CHEJIN_DEMO_20260503_203628.md`
- `runtime/apps/wechat_ai_customer_service/test_artifacts/jiangsu_chejin_used_car/demo_materials/CHEJIN_DEMO_20260503_203628/policies_CHEJIN_DEMO_20260503_203628.md`
- `runtime/apps/wechat_ai_customer_service/test_artifacts/jiangsu_chejin_used_car/demo_materials/CHEJIN_DEMO_20260503_203628/products_CHEJIN_DEMO_20260503_203628.md`

这些 `.py` / `.md` 文件可能承担说明、样本或实盘测试入口职责，不在第一轮一刀切取消跟踪。后续如要继续治理，应单独审查并迁移到更合适的位置，例如 `apps/.../tests/fixtures/`、`workflows/verification/...` 或正式文档目录。

## 2026-06-18 第二轮收束记录

第二轮继续处理第一轮留下的 10 个文件，原则仍然是：源码和稳定样例迁到正式目录，runtime 旧文件只取消 Git 跟踪，不删除本机现场。

已迁移的正式入口：

- `workflows/verification/wechat_customer_service/two_visible_session_customer_service_live.py`

已迁移的稳定样例：

- `apps/wechat_ai_customer_service/tests/fixtures/manual_upload_samples/20260426_round2/`
- `apps/wechat_ai_customer_service/tests/fixtures/demo_materials/CHEJIN_DEMO_20260503_203628/`

旧 runtime 路径不再作为 Git 跟踪源码或 fixture 入口：

- `runtime/two_visible_session_customer_service_live.py`
- `runtime/apps/wechat_ai_customer_service/README.md`
- `runtime/apps/wechat_ai_customer_service/manual_upload_samples/20260426_round2/`
- `runtime/apps/wechat_ai_customer_service/test_artifacts/jiangsu_chejin_used_car/demo_materials/CHEJIN_DEMO_20260503_203628/`

第二轮清理前归档：

- `runtime/cleanup_archive/20260618_224942_issue4_remaining_runtime_sources_before_untrack/`

第二轮后，Git 仍跟踪的 runtime 文件只保留目录说明：

- `runtime/README.md`
- `runtime/test_artifacts/README.md`

### 阶段 5：验证

执行后至少验证：

- `git status --short runtime` 不再被实盘运行产物大面积污染。
- 微信 AI 客服启动流程仍能创建 runtime 输出。
- 加好友测试仍能创建 runtime 输出。
- 运行产物不会重新出现在 `git status`。
- 必要 fixture 测试仍通过。

## 建议检查脚本规则

提交前检查可以先做轻量版本：

1. 读取 `git diff --cached --name-only`。
2. 如果路径匹配 `runtime/apps/**`，默认失败。
3. 如果路径匹配 `runtime/**/*.log`、`runtime/**/*.jsonl`、`runtime/**/*.png`、`runtime/**/*.xlsx`、`runtime/**/*.zip`，默认失败。
4. allowlist 文件放在脚本内或独立配置中。
5. 输出治理文档路径。

后续可以升级为 CI 检查。

推荐命令：

```powershell
.\.venv\Scripts\python.exe workflows\verification\general\runtime_artifact_guard.py audit
.\.venv\Scripts\python.exe workflows\verification\general\runtime_artifact_guard.py check-staged
```

其中：

- `audit` 只生成本地归档清单，不删除、不取消跟踪。
- `check-staged` 只检查暂存区，不改文件。

## 风险和应对

### 风险 1：误把有用测试样本取消跟踪

应对：

- 先生成清单；
- 对疑似 fixture 的文件人工确认；
- 真正需要的样本迁移到 `tests/fixtures`。

### 风险 2：本地未跟踪现场没有 GitHub 备份

应对：

- 清理前不删除本地文件；
- 如需保存当前现场，先压缩备份整个 `runtime` 或关键子目录；
- 文档和脚本都明确区分“GitHub 已备份的已提交版本”和“本地未跟踪现场”。

### 风险 3：测试依赖 runtime 中的历史路径

应对：

- 迁移 fixture 时同步更新测试；
- 对短期无法迁移的路径加临时 allowlist，并标注清理期限；
- 不在同一个 PR 内同时大规模改业务逻辑。

### 风险 4：协作者继续误提交 runtime

应对：

- 加检查脚本；
- 更新 AGENTS.md 或开发说明；
- PR 审查时把 runtime 变更作为高风险项。

## 验收标准

问题 4 治理完成的标准：

1. `runtime/apps/**` 运行产物不再被 Git 跟踪。
2. 新一轮微信 AI 客服浅测试后，运行输出不会污染代码 diff。
3. 新一轮加好友浅测试后，运行输出不会污染代码 diff。
4. 必要测试 fixture 已迁移到测试目录，并且测试可通过。
5. 提交前检查能阻止新增日志、截图、session、状态文件进入 Git。
6. 本机 runtime 现场文件仍然存在，不因治理被删除。

## 推荐下一步

建议下一步先做阶段 1：

- 新增 runtime 提交检查脚本；
- 增加 allowlist；
- 不执行大规模 `git rm --cached`；
- 先验证检查脚本不会影响正常开发。

等护栏通过后，再进入阶段 2 和阶段 3，审计并迁移少量真正有价值的 fixture。最后才执行阶段 4，把历史 runtime 运行产物从 Git 索引里移除。
