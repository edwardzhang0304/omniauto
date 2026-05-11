"""Managed loop for the local WeChat customer-service listener."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import psutil


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
for path in (PROJECT_ROOT, APP_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from apps.wechat_ai_customer_service.admin_backend.services.customer_service_runtime import (  # noqa: E402
    runtime_log_path,
    summarize_listener_result,
    write_runtime_status,
)
from apps.wechat_ai_customer_service.cloud_gate import cloud_gate_status, cloud_required_enabled  # noqa: E402
from apps.wechat_ai_customer_service.sync import VpsLocalSyncService  # noqa: E402


def _ancestor_pids(pid: int) -> set[int]:
    """Return all ancestor PIDs of the given process."""
    ancestors: set[int] = set()
    try:
        proc = psutil.Process(pid)
        while True:
            parent = proc.parent()
            if parent is None:
                break
            ancestors.add(parent.pid)
            proc = parent
    except psutil.NoSuchProcess:
        pass
    return ancestors


def _cmdline_has_listener_script(cmdline: list[str]) -> bool:
    target = "run_customer_service_listener.py"
    for arg in cmdline:
        arg_norm = os.path.normpath(str(arg))
        if os.path.basename(arg_norm) == target:
            return True
    return False


def _already_running(tenant_id: str) -> bool:
    """Check if another managed listener for the same tenant is already running."""
    my_pid = os.getpid()
    ancestor_pids = _ancestor_pids(my_pid)
    for proc in psutil.process_iter(["pid", "cmdline", "name"]):
        try:
            pid = proc.info.get("pid")
            cmdline = proc.info.get("cmdline") or []
            name = str(proc.info.get("name") or "").lower()
            if (
                pid != my_pid
                and pid not in ancestor_pids
                and "python" in name
                and _cmdline_has_listener_script(cmdline)
                and f"--tenant-id {tenant_id}" in " ".join(str(item) for item in cmdline)
            ):
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--interval-seconds", type=float, default=3.0)
    parser.add_argument("--send", action="store_true")
    parser.add_argument("--write-data", action="store_true")
    args = parser.parse_args()

    tenant_id = str(args.tenant_id).strip()
    config_path = args.config.resolve()

    if _already_running(tenant_id):
        print(f"Managed listener for {tenant_id} is already running; exiting.", file=sys.stderr)
        return 0
    print(f"Managed listener for {tenant_id} starting with PID={os.getpid()}", file=sys.stderr)

    env = dict(os.environ)
    env["WECHAT_KNOWLEDGE_TENANT"] = tenant_id
    log_path = runtime_log_path(tenant_id)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    workflow = APP_ROOT / "workflows" / "listen_and_reply.py"

    # --- VPS console must be online before starting ---
    from apps.wechat_ai_customer_service.auth.vps_client import discover_vps_base_url

    vps_url = discover_vps_base_url()
    if not vps_url:
        message = "VPS控制台未配置或未启动，自动客服监听无法启动。请先启动VPS控制台。"
        write_runtime_status("stopped", message, tenant_id=tenant_id)
        append_log(log_path, {"event": "managed_listener_vps_missing", "tenant_id": tenant_id})
        print(message, file=sys.stderr)
        return 3
    vps_ok = False
    try:
        req = urllib.request.Request(vps_url.rstrip("/") + "/v1/health", headers={"Accept": "application/json"}, method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            vps_ok = 200 <= int(getattr(resp, "status", 0)) < 300
    except Exception:
        vps_ok = False
    if not vps_ok:
        message = "VPS控制台不可达，自动客服监听无法启动。请检查VPS控制台是否正常运行。"
        write_runtime_status("stopped", message, tenant_id=tenant_id)
        append_log(log_path, {"event": "managed_listener_vps_unhealthy", "tenant_id": tenant_id, "vps_url": vps_url})
        print(message, file=sys.stderr)
        return 3

    # --- Write PID record so admin backend can detect this listener ---
    from apps.wechat_ai_customer_service.admin_backend.services.customer_service_runtime import runtime_pid_path

    pid_record = {
        "pid": os.getpid(),
        "tenant_id": tenant_id,
        "config_path": str(config_path),
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "log_path": str(log_path),
    }
    pid_path = runtime_pid_path(tenant_id)
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    temp = pid_path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(pid_record, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, pid_path)

    import atexit

    def _cleanup_pid():
        try:
            pid_path.unlink()
        except FileNotFoundError:
            pass

    atexit.register(_cleanup_pid)

    append_log(log_path, {"event": "managed_listener_start", "tenant_id": tenant_id, "config": str(config_path)})
    write_runtime_status("idle", "自动客服监听已启动，等待微信消息。", tenant_id=tenant_id)
    sync_service = VpsLocalSyncService()
    cloud_sync_token = str(os.getenv("WECHAT_RUNTIME_SYNC_TOKEN") or "").strip()
    try:
        cloud_refresh_interval = max(5.0, float(os.getenv("WECHAT_CLOUD_REFRESH_INTERVAL_SECONDS") or "20"))
    except ValueError:
        cloud_refresh_interval = 20.0
    last_cloud_refresh_at = 0.0
    while True:
        if cloud_required_enabled():
            now_ts = time.monotonic()
            if now_ts - last_cloud_refresh_at >= cloud_refresh_interval:
                refresh = sync_service.fetch_shared_knowledge_snapshot(
                    token=cloud_sync_token,
                    tenant_id=tenant_id,
                    force=False,
                )
                last_cloud_refresh_at = now_ts
                if refresh.get("ok") is not True:
                    message = "共享行业知识库续租失败，自动客服监听已停止。请恢复服务端连接并重新启动。"
                    append_log(
                        log_path,
                        {
                            "event": "managed_listener_cloud_refresh_failed",
                            "tenant_id": tenant_id,
                            "cloud_sync": refresh,
                        },
                    )
                    write_runtime_status("stopped", message, tenant_id=tenant_id, cloud_sync=refresh)
                    return 2
            gate = cloud_gate_status()
            if not gate.get("ok"):
                message = "云端授权未通过，自动客服监听已停止。请连接服务端并刷新共享行业知识库。"
                append_log(log_path, {"event": "managed_listener_cloud_gate_stop", "tenant_id": tenant_id, "cloud_gate": gate})
                write_runtime_status("stopped", message, tenant_id=tenant_id, cloud_gate=gate)
                return 2
        command = [sys.executable, str(workflow), "--config", str(config_path), "--once"]
        if args.send:
            command.append("--send")
        if args.write_data:
            command.append("--write-data")
        write_runtime_status("thinking", "正在读取微信消息并准备回复。", tenant_id=tenant_id)
        started = time.time()
        result = run_once(command, env=env, cwd=PROJECT_ROOT, log_path=log_path)
        duration = round(time.time() - started, 2)
        summary = summarize_listener_result(result) if isinstance(result, dict) else {}
        message = status_message_from_result(result, duration)
        write_runtime_status(
            "idle",
            message,
            tenant_id=tenant_id,
            last_run_seconds=duration,
            **summary,
        )
        time.sleep(max(0.5, float(args.interval_seconds)))


def run_once(command: list[str], *, env: dict[str, str], cwd: Path, log_path: Path) -> dict:
    process = subprocess.run(command, cwd=str(cwd), env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    stdout = (process.stdout or "").strip()
    stderr = (process.stderr or "").strip()
    payload = parse_last_json(stdout)
    append_log(
        log_path,
        {
            "event": "listen_once_exit",
            "returncode": process.returncode,
            "stdout_tail": stdout[-3000:],
            "stderr_tail": stderr[-3000:],
        },
    )
    if payload:
        payload.setdefault("ok", process.returncode == 0)
        return payload
    return {"ok": process.returncode == 0, "error": stderr[-1000:] or stdout[-1000:] or f"exit={process.returncode}", "events": []}


def parse_last_json(text: str) -> dict:
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        return payload
    for line in reversed([item.strip() for item in text.splitlines() if item.strip()]):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    start = text.rfind("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            payload = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}
    return {}


def status_message_from_result(result: dict, duration: float) -> str:
    if not isinstance(result, dict) or result.get("ok") is False:
        return f"本轮处理没有成功，已等待下一轮自动重试。耗时 {duration} 秒。"
    events = [item for item in result.get("events", []) or [] if isinstance(item, dict)]
    if not events:
        return f"本轮未发现需要回复的新消息。耗时 {duration} 秒。"
    actions = {str(item.get("action") or "") for item in events}
    if "sent" in actions or "handoff_sent" in actions:
        return f"本轮已处理并发送回复。耗时 {duration} 秒。"
    if "skipped" in actions and actions <= {"skipped"}:
        return f"本轮没有可自动回复的新消息。耗时 {duration} 秒。"
    return f"本轮微信消息检查完成。耗时 {duration} 秒。"


def append_log(path: Path, payload: dict) -> None:
    record = {"created_at": datetime.now().isoformat(timespec="seconds"), **payload}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        import traceback
        crash_log = APP_ROOT / "logs" / "listener_crash.log"
        crash_log.parent.mkdir(parents=True, exist_ok=True)
        with crash_log.open("a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "created_at": datetime.now().isoformat(timespec="seconds"),
                        "event": "managed_listener_crash",
                        "error": str(exc),
                        "traceback": traceback.format_exc(),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
        raise
