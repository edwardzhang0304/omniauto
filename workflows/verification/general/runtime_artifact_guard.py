#!/usr/bin/env python3
"""Audit and guard Git-tracked runtime artifacts.

This tool is intentionally conservative:

- it never deletes files;
- it never runs ``git rm``;
- audit outputs are written under ignored ``runtime/cleanup_archive``;
- staged checks fail closed for generated runtime artifacts.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[3]
DOC_PATH = "docs/RUNTIME_ARTIFACT_TRACKING_CLEANUP_PLAN_20260618.md"
ARCHIVE_ROOT = ROOT / "runtime" / "cleanup_archive"

ALLOWED_RUNTIME_PATHS = {
    "runtime/README.md",
    "runtime/test_artifacts/README.md",
}

BLOCKED_RUNTIME_SUFFIXES = {
    ".bak",
    ".csv",
    ".db",
    ".jsonl",
    ".lock",
    ".log",
    ".png",
    ".sqlite",
    ".tmp",
    ".txt",
    ".xlsx",
    ".zip",
}

SENSITIVE_MARKERS = (
    "account",
    "auth",
    "cache",
    "conversation",
    "customer_profiles",
    "diagnostics",
    "handoff",
    "latest",
    "live",
    "logs",
    "message",
    "profile",
    "raw_messages",
    "session",
    "state",
    "tenant",
    "token",
    "upload",
)


@dataclass(frozen=True)
class GitStatus:
    code: str
    path: str
    original_path: str = ""


def run_git(args: list[str], *, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {message}")
    return result.stdout


def normalize_path(path: str) -> str:
    return path.replace("\\", "/").strip().strip('"')


def parse_status_porcelain(output: str) -> list[GitStatus]:
    statuses: list[GitStatus] = []
    for raw in output.splitlines():
        if not raw:
            continue
        code = raw[:2]
        body = raw[3:] if len(raw) > 3 else ""
        original_path = ""
        if " -> " in body:
            original_path, body = body.split(" -> ", 1)
            original_path = normalize_path(original_path)
        path = normalize_path(body)
        statuses.append(GitStatus(code=code, path=path, original_path=original_path))
    return statuses


def is_runtime_path(path: str) -> bool:
    return normalize_path(path).startswith("runtime/")


def is_allowed_runtime_path(path: str) -> bool:
    path = normalize_path(path)
    if path in ALLOWED_RUNTIME_PATHS:
        return True
    if path.startswith("runtime/cleanup_archive/"):
        return False
    return False


def classify_path(path: str) -> tuple[str, str, str]:
    path = normalize_path(path)
    suffix = Path(path).suffix.lower()
    lower = path.lower()

    if is_allowed_runtime_path(path):
        return ("A_keep_tracked", "allowlisted stable runtime documentation", "none")
    if path.startswith("runtime/apps/"):
        return ("C_untrack_generated", "runtime app artifact/state path", "git rm --cached after review")
    if path.startswith("runtime/cleanup_archive/"):
        return ("C_local_archive_only", "local cleanup archive must remain ignored", "do not stage")
    if suffix in BLOCKED_RUNTIME_SUFFIXES:
        return ("C_untrack_generated", f"generated artifact suffix {suffix}", "git rm --cached after review")
    if path.startswith("runtime/test_artifacts/"):
        return ("B_review_fixture", "test artifact may need fixture migration", "review and migrate if stable")
    if any(marker in lower for marker in SENSITIVE_MARKERS):
        return ("C_review_sensitive_runtime", "path contains runtime/sensitive marker", "review before tracking")
    return ("B_review", "runtime path requires manual classification", "manual review")


def tracked_runtime_paths() -> list[str]:
    return [
        normalize_path(line)
        for line in run_git(["ls-files", "runtime"]).splitlines()
        if line.strip()
    ]


def runtime_statuses() -> list[GitStatus]:
    return [
        status
        for status in parse_status_porcelain(run_git(["status", "--short", "runtime"]))
        if is_runtime_path(status.path)
    ]


def staged_statuses() -> list[GitStatus]:
    output = run_git(["diff", "--cached", "--name-status", "--diff-filter=ACMRTD"])
    statuses: list[GitStatus] = []
    for raw in output.splitlines():
        if not raw.strip():
            continue
        parts = raw.split("\t")
        code = parts[0]
        if code.startswith("R") and len(parts) >= 3:
            statuses.append(
                GitStatus(code=code, path=normalize_path(parts[2]), original_path=normalize_path(parts[1]))
            )
        elif len(parts) >= 2:
            statuses.append(GitStatus(code=code, path=normalize_path(parts[1])))
    return statuses


def staged_runtime_delete_count() -> int:
    return sum(
        1
        for status in staged_statuses()
        if status.code == "D" and is_runtime_path(status.path)
    )


def current_branch() -> str:
    return run_git(["rev-parse", "--abbrev-ref", "HEAD"]).strip()


def current_head() -> str:
    return run_git(["rev-parse", "HEAD"]).strip()


def remote_master_head() -> str:
    output = run_git(["ls-remote", "origin", "refs/heads/master"], check=False).strip()
    if not output:
        return ""
    return output.split()[0]


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def build_tracked_rows(paths: Iterable[str]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path in paths:
        category, reason, action = classify_path(path)
        rows.append(
            {
                "path": path,
                "extension": Path(path).suffix.lower(),
                "category": category,
                "reason": reason,
                "recommended_action": action,
            }
        )
    return rows


def build_status_rows(statuses: Iterable[GitStatus]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for status in statuses:
        category, reason, action = classify_path(status.path)
        rows.append(
            {
                "code": status.code,
                "path": status.path,
                "original_path": status.original_path,
                "category": category,
                "reason": reason,
                "recommended_action": action,
            }
        )
    return rows


def command_audit(args: argparse.Namespace) -> int:
    timestamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d_%H%M%S")
    batch_dir = ARCHIVE_ROOT / f"{timestamp}_{args.purpose}"
    batch_dir.mkdir(parents=True, exist_ok=False)

    tracked = tracked_runtime_paths()
    statuses = runtime_statuses()
    tracked_rows = build_tracked_rows(tracked)
    status_rows = build_status_rows(statuses)

    manifest = {
        "created_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "purpose": args.purpose,
        "branch": current_branch(),
        "head": current_head(),
        "origin_master_head": remote_master_head(),
        "doc": DOC_PATH,
        "archive_dir": str(batch_dir.relative_to(ROOT)).replace("\\", "/"),
        "tracked_runtime_count": len(tracked_rows),
        "runtime_status_count": len(status_rows),
        "staged_runtime_delete_count": staged_runtime_delete_count(),
        "destructive_actions_performed": False,
        "git_rm_cached_performed": False,
    }

    (batch_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_csv(
        batch_dir / "tracked_runtime_inventory.csv",
        ["path", "extension", "category", "reason", "recommended_action"],
        tracked_rows,
    )
    write_csv(
        batch_dir / "worktree_runtime_status.csv",
        ["code", "path", "original_path", "category", "reason", "recommended_action"],
        status_rows,
    )
    (batch_dir / "restore_notes.md").write_text(
        "\n".join(
            [
                "# Runtime Cleanup Restore Notes",
                "",
                f"- Archive batch: `{batch_dir.relative_to(ROOT)}`",
                f"- Git HEAD at audit time: `{manifest['head']}`",
                f"- Origin master HEAD at audit time: `{manifest['origin_master_head']}`",
                "",
                "No files were deleted and no files were removed from the Git index by this audit.",
                "",
                "If a later cleanup only used `git rm --cached`, restore tracking with:",
                "",
                "```powershell",
                "git add -- <path>",
                "```",
                "",
                "Restore committed file contents from GitHub/Git history with:",
                "",
                "```powershell",
                f"git show {manifest['head']}:<path> > <restore-target>",
                "```",
                "",
                "For local untracked runtime files, use the local filesystem copy or a separate manual backup.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    print(f"Audit archive written: {batch_dir.relative_to(ROOT)}")
    print(f"Tracked runtime files: {len(tracked_rows)}")
    print(f"Runtime worktree status rows: {len(status_rows)}")
    return 0


def command_check_staged(_: argparse.Namespace) -> int:
    offending: list[tuple[str, str]] = []
    for status in staged_statuses():
        path = status.path
        if not is_runtime_path(path):
            continue
        if status.code == "D":
            continue
        if is_allowed_runtime_path(path):
            continue
        category, reason, _ = classify_path(path)
        offending.append((path, f"{status.code} {category}: {reason}"))

    if not offending:
        print("Runtime artifact guard passed: no blocked staged runtime paths.")
        return 0

    print("Runtime artifact guard failed: blocked staged runtime paths detected.")
    print(f"See {DOC_PATH}")
    for path, reason in offending:
        print(f"- {path} ({reason})")
    return 1


def command_self_check(_: argparse.Namespace) -> int:
    cases = {
        "runtime/README.md": "A_keep_tracked",
        "runtime/test_artifacts/README.md": "A_keep_tracked",
        "runtime/apps/wechat_ai_customer_service/logs/live.log": "C_untrack_generated",
        "runtime/apps/wechat_ai_customer_service/state/session.json": "C_untrack_generated",
        "runtime/cleanup_archive/20260618/manifest.json": "C_local_archive_only",
        "runtime/test_artifacts/wechat/result.json": "B_review_fixture",
        "runtime/wechat_probe.png": "C_untrack_generated",
    }
    failures: list[str] = []
    for path, expected in cases.items():
        actual, reason, _ = classify_path(path)
        if actual != expected:
            failures.append(f"{path}: expected {expected}, got {actual} ({reason})")

    if failures:
        print("Runtime artifact guard self-check failed.")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("Runtime artifact guard self-check passed.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit = subparsers.add_parser("audit", help="write local runtime cleanup archive inventory")
    audit.add_argument(
        "--purpose",
        default="runtime_tracking_cleanup",
        help="short label used in the archive directory name",
    )
    audit.set_defaults(func=command_audit)

    check = subparsers.add_parser("check-staged", help="fail if staged changes include runtime artifacts")
    check.set_defaults(func=command_check_staged)

    self_check = subparsers.add_parser("self-check", help="run internal classification assertions")
    self_check.set_defaults(func=command_self_check)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
