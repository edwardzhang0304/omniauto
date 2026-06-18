# verification 目录说明

这里存放真实验收脚本，不是 `pytest` 自动化测试。

## 子目录

- `browser/`
  - 浏览器类验收脚本。
- `marketplaces/`
  - 电商/平台类验收脚本。
- `general/`
  - 跨项目治理和通用验收脚本。
- `wechat_customer_service/`
  - 微信 AI 客服真实环境验收脚本。

## 命名规则

- 优先使用 `*_smoke.py`
- 表示这是手动或真实环境下的冒烟验收脚本
- 避免和 `platform/tests/` 里的 `test_*.py` 混淆

## 产物存放规则

- 验收脚本产生的截图、临时文件和调试产物，统一放到 `runtime/test_artifacts/`
- 不再写入项目根目录
- 如需细分，优先使用 `runtime/test_artifacts/verification/...`

## Runtime 清理治理

Runtime Git 跟踪治理使用：

```powershell
.\.venv\Scripts\python.exe workflows\verification\general\runtime_artifact_guard.py audit
.\.venv\Scripts\python.exe workflows\verification\general\runtime_artifact_guard.py check-staged
```

- `audit` 只生成本地清理归档清单，输出到 `runtime/cleanup_archive/`。
- `check-staged` 只检查暂存区是否误带 runtime 运行产物。
- 两个命令都不会删除文件，也不会执行 `git rm --cached`。
