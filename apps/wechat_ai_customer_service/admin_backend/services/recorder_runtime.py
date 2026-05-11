"""Runtime process control for the AI smart recorder capture loop."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import psutil

from apps.wechat_ai_customer_service.admin_backend.services.recorder_service import RecorderService
from apps.wechat_ai_customer_service.admin_backend.services.work_queue import WorkQueueService
from apps.wechat_ai_customer_service.knowledge_paths import active_tenant_id, tenant_runtime_logs_root, tenant_runtime_root


PROJECT_ROOT = Path(__file__).resolve().parents[4]
APP_ROOT = PROJECT_ROOT / "apps" / "wechat_ai_customer_service"
RECORDER_SCRIPT_NAME = "recorder_loop.py"
WORKER_SCRIPT_NAME = "background_worker.py"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def recorder_runtime_dir(tenant_id: str | None = None) -> Path:
    return tenant_runtime_root(tenant_id) / "recorder"


def recorder_runtime_status_path(tenant_id: str | None = None) -> Path:
    return recorder_runtime_dir(tenant_id) / "runtime_status.json"


def recorder_runtime_pid_path(tenant_id: str | None = None) -> Path:
    return recorder_runtime_dir(tenant_id) / "loop.pid.json"


def recorder_worker_pid_path(tenant_id: str | None = None) -> Path:
    return recorder_runtime_dir(tenant_id) / "worker.pid.json"


def recorder_runtime_log_path(tenant_id: str | None = None) -> Path:
    return tenant_runtime_logs_root(tenant_id) / "recorder_managed_loop.log"


class RecorderRuntime:
    """Start/stop/status wrapper for one tenant recorder loop + export worker."""

    def __init__(self, *, tenant_id: str | None = None) -> None:
        self.tenant_id = active_tenant_id(tenant_id)

    def status(self) -> dict[str, Any]:
        pid_record = self._read_pid_record()
        pid = int(pid_record.get("pid") or 0)
        running = self._pid_alive(pid)
        if not running and not pid_record:
            scanned = self._scan_loop_running_pids(self.tenant_id)
            if scanned:
                pid = max(scanned)
                running = True

        worker_record = self._read_worker_pid_record()
        worker_pid = int(worker_record.get("pid") or 0)
        worker_running = self._pid_alive(worker_pid)
        if not worker_running and not worker_record:
            scanned_workers = self._scan_worker_running_pids(self.tenant_id, queue_name="recorder_exports")
            if scanned_workers:
                worker_pid = max(scanned_workers)
                worker_running = True

        status_payload = self._read_status_payload()
        queue_summary = WorkQueueService(tenant_id=self.tenant_id).summary()
        if not running:
            status_payload["state"] = "stopped"
            status_payload["message"] = "AI智能记录员监听已停止。"
        status_payload.update(
            {
                "running": running,
                "pid": pid if running else None,
                "worker_running": worker_running,
                "worker_pid": worker_pid if worker_running else None,
                "queue_summary": queue_summary,
                "log_path": str(recorder_runtime_log_path(self.tenant_id)),
                "tenant_id": self.tenant_id,
            }
        )
        return status_payload

    def start(self) -> dict[str, Any]:
        current = self.status()
        if current.get("running"):
            return {"ok": True, "message": "AI智能记录员已经在运行。", "item": self.status()}

        settings = RecorderService(tenant_id=self.tenant_id).settings()
        if settings.get("enabled", True) is False:
            self._write_status_payload(
                {
                    "ok": True,
                    "state": "stopped",
                    "message": "AI智能记录员总开关已关闭，请先开启后再启动监听。",
                    "updated_at": now_iso(),
                    "tenant_id": self.tenant_id,
                }
            )
            return {
                "ok": False,
                "detail": "recorder_disabled",
                "message": "AI智能记录员总开关已关闭，请先在记录员设置中开启。",
                "item": self.status(),
            }

        recorder_script = APP_ROOT / "workflows" / "recorder_loop.py"
        if not recorder_script.exists():
            return {"ok": False, "message": f"缺少记录员脚本：{recorder_script}", "item": current}
        interval = max(5, int(settings.get("capture_interval_seconds", 30) or 30))
        self._write_status_payload(
            {
                "ok": True,
                "state": "thinking",
                "message": "AI智能记录员正在启动。",
                "updated_at": now_iso(),
                "tenant_id": self.tenant_id,
            }
        )

        env = dict(os.environ)
        env["WECHAT_KNOWLEDGE_TENANT"] = self.tenant_id
        creationflags = 0
        if os.name == "nt":
            creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            creationflags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.Popen(
            [
                str(self._python_executable()),
                str(recorder_script),
                "--tenant-id",
                self.tenant_id,
                "--forever",
                "--interval-seconds",
                str(interval),
                "--discover",
            ],
            cwd=str(PROJECT_ROOT),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        self._write_pid_record(
            {
                "pid": proc.pid,
                "tenant_id": self.tenant_id,
                "script": str(recorder_script),
                "started_at": now_iso(),
                "interval_seconds": interval,
                "log_path": str(recorder_runtime_log_path(self.tenant_id)),
            }
        )
        self._write_status_payload(
            {
                "ok": True,
                "state": "idle",
                "message": "AI智能记录员正在运行。",
                "updated_at": now_iso(),
                "tenant_id": self.tenant_id,
                "last_start_at": now_iso(),
            }
        )
        return {"ok": True, "message": "AI智能记录员已启动。", "item": self.status()}

    def stop(self) -> dict[str, Any]:
        loop_pids = set()
        pid_record = self._read_pid_record()
        pid = int(pid_record.get("pid") or 0)
        if pid:
            loop_pids.add(pid)
        loop_pids.update(self._scan_loop_running_pids(self.tenant_id))
        for item in sorted(loop_pids):
            if item and self._pid_alive(item):
                self._terminate_tree(item)

        worker_pids = set()
        worker_record = self._read_worker_pid_record()
        worker_pid = int(worker_record.get("pid") or 0)
        if worker_pid:
            worker_pids.add(worker_pid)
        worker_pids.update(self._scan_worker_running_pids(self.tenant_id, queue_name="recorder_exports"))
        for item in sorted(worker_pids):
            if item and self._pid_alive(item):
                self._terminate_tree(item)

        self._clear_pid_record()
        self._clear_worker_pid_record()
        self._write_status_payload(
            {
                "ok": True,
                "state": "stopped",
                "message": "AI智能记录员监听已手动停止。",
                "updated_at": now_iso(),
                "tenant_id": self.tenant_id,
            }
        )
        return {"ok": True, "message": "AI智能记录员监听已停止。", "item": self.status()}

    def ensure_export_worker(self) -> dict[str, Any]:
        """Ensure recorder export worker process is alive for async export runs."""
        result = self._ensure_worker_running()
        return {
            **result,
            "item": self.status(),
        }

    def _ensure_worker_running(self) -> dict[str, Any]:
        current = self._read_worker_pid_record()
        pid = int(current.get("pid") or 0)
        if pid and self._pid_alive(pid):
            return {"ok": True, "message": "导出 worker 已在运行。", "worker_pid": pid}
        scanned = self._scan_worker_running_pids(self.tenant_id, queue_name="recorder_exports")
        if scanned:
            worker_pid = max(scanned)
            self._write_worker_pid_record(
                {
                    "pid": worker_pid,
                    "tenant_id": self.tenant_id,
                    "queue": "recorder_exports",
                    "started_at": now_iso(),
                }
            )
            return {"ok": True, "message": "导出 worker 已在运行。", "worker_pid": worker_pid}

        worker_script = APP_ROOT / "scripts" / "background_worker.py"
        if not worker_script.exists():
            return {"ok": False, "message": f"缺少后台 worker 脚本：{worker_script}"}

        env = dict(os.environ)
        env["WECHAT_KNOWLEDGE_TENANT"] = self.tenant_id
        creationflags = 0
        if os.name == "nt":
            creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            creationflags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.Popen(
            [
                str(self._python_executable()),
                str(worker_script),
                "--tenant-id",
                self.tenant_id,
                "--queue",
                "recorder_exports",
                "--interval-seconds",
                "5",
                "--limit",
                "2",
            ],
            cwd=str(PROJECT_ROOT),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        time.sleep(0.3)
        self._write_worker_pid_record(
            {
                "pid": proc.pid,
                "tenant_id": self.tenant_id,
                "queue": "recorder_exports",
                "started_at": now_iso(),
            }
        )
        return {"ok": True, "message": "导出 worker 已启动。", "worker_pid": proc.pid}

    def _read_pid_record(self) -> dict[str, Any]:
        path = recorder_runtime_pid_path(self.tenant_id)
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write_pid_record(self, payload: dict[str, Any]) -> None:
        path = recorder_runtime_pid_path(self.tenant_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, path)

    def _clear_pid_record(self) -> None:
        try:
            recorder_runtime_pid_path(self.tenant_id).unlink()
        except FileNotFoundError:
            pass

    def _read_worker_pid_record(self) -> dict[str, Any]:
        path = recorder_worker_pid_path(self.tenant_id)
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write_worker_pid_record(self, payload: dict[str, Any]) -> None:
        path = recorder_worker_pid_path(self.tenant_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, path)

    def _clear_worker_pid_record(self) -> None:
        try:
            recorder_worker_pid_path(self.tenant_id).unlink()
        except FileNotFoundError:
            pass

    def _read_status_payload(self) -> dict[str, Any]:
        path = recorder_runtime_status_path(self.tenant_id)
        if not path.exists():
            return {
                "ok": True,
                "state": "stopped",
                "message": "AI智能记录员监听已停止。",
                "updated_at": "",
                "tenant_id": self.tenant_id,
            }
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        state = str(payload.get("state") or "stopped")
        if state not in {"idle", "thinking", "stopped"}:
            state = "stopped"
        return {
            **payload,
            "ok": payload.get("ok", True) is not False,
            "state": state,
            "message": str(payload.get("message") or "AI智能记录员状态未知。"),
            "tenant_id": str(payload.get("tenant_id") or self.tenant_id),
        }

    def _write_status_payload(self, payload: dict[str, Any]) -> None:
        path = recorder_runtime_status_path(self.tenant_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, path)

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            return psutil.Process(pid).is_running()
        except psutil.NoSuchProcess:
            return False

    @staticmethod
    def _terminate_tree(pid: int) -> None:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        try:
            os.kill(pid, 15)
        except OSError:
            pass

    @staticmethod
    def _cmdline_has_script(cmdline: list[str], script_name: str) -> bool:
        for arg in cmdline:
            normalized = os.path.normpath(str(arg))
            if os.path.basename(normalized) == script_name:
                return True
        return False

    @staticmethod
    def _scan_loop_running_pids(tenant_id: str) -> list[int]:
        my_pid = os.getpid()
        pids: set[int] = set()
        for proc in psutil.process_iter(["pid", "cmdline", "name"]):
            try:
                pid = int(proc.info.get("pid") or 0)
                cmdline = [str(item) for item in (proc.info.get("cmdline") or [])]
                name = str(proc.info.get("name") or "").lower()
                if pid <= 0 or pid == my_pid or "python" not in name:
                    continue
                if not RecorderRuntime._cmdline_has_script(cmdline, RECORDER_SCRIPT_NAME):
                    continue
                if f"--tenant-id {tenant_id}" not in " ".join(cmdline):
                    continue
                if RecorderRuntime._pid_alive(pid):
                    pids.add(pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return sorted(pids)

    @staticmethod
    def _scan_worker_running_pids(tenant_id: str, *, queue_name: str) -> list[int]:
        my_pid = os.getpid()
        pids: set[int] = set()
        for proc in psutil.process_iter(["pid", "cmdline", "name"]):
            try:
                pid = int(proc.info.get("pid") or 0)
                cmdline = [str(item) for item in (proc.info.get("cmdline") or [])]
                name = str(proc.info.get("name") or "").lower()
                if pid <= 0 or pid == my_pid or "python" not in name:
                    continue
                if not RecorderRuntime._cmdline_has_script(cmdline, WORKER_SCRIPT_NAME):
                    continue
                cmd_str = " ".join(cmdline)
                if f"--tenant-id {tenant_id}" not in cmd_str:
                    continue
                if f"--queue {queue_name}" not in cmd_str:
                    continue
                if RecorderRuntime._pid_alive(pid):
                    pids.add(pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return sorted(pids)

    @staticmethod
    def _python_executable() -> Path:
        override = str(os.getenv("WECHAT_RUNTIME_PYTHON") or "").strip()
        if override:
            override_path = Path(override)
            if override_path.exists():
                return override_path
        current = Path(sys.executable)
        if current.exists():
            return current
        venv_python = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
        return venv_python if venv_python.exists() else current
