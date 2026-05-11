"""Runtime process control for the local WeChat customer-service listener."""

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

from apps.wechat_ai_customer_service.cloud_gate import cloud_gate_status, cloud_required_enabled
from apps.wechat_ai_customer_service.knowledge_paths import active_tenant_id, tenant_runtime_root
from apps.wechat_ai_customer_service.sync import VpsLocalSyncService


PROJECT_ROOT = Path(__file__).resolve().parents[4]
APP_ROOT = PROJECT_ROOT / "apps" / "wechat_ai_customer_service"
DEFAULT_CHEJIN_TENANT_ID = "jiangsu_chejin_usedcar_customer_20260501"
DEFAULT_CHEJIN_CONFIG = APP_ROOT / "configs" / "jiangsu_chejin_xucong_live.example.json"

RUNTIME_STATES = {"idle", "thinking", "stopped"}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def runtime_dir(tenant_id: str | None = None) -> Path:
    return tenant_runtime_root(tenant_id) / "customer_service"


def runtime_status_path(tenant_id: str | None = None) -> Path:
    return runtime_dir(tenant_id) / "runtime_status.json"


def runtime_pid_path(tenant_id: str | None = None) -> Path:
    return runtime_dir(tenant_id) / "listener.pid.json"


def worker_pid_path(tenant_id: str | None = None) -> Path:
    return runtime_dir(tenant_id) / "worker.pid.json"


def runtime_log_path(tenant_id: str | None = None) -> Path:
    return tenant_runtime_root(tenant_id) / "logs" / "customer_service_managed_listener.log"


def write_runtime_status(
    state: str,
    message: str = "",
    *,
    tenant_id: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Write the compact status consumed by the floating console widget."""
    normalized = state if state in RUNTIME_STATES else "idle"
    payload: dict[str, Any] = {
        "ok": True,
        "state": normalized,
        "message": message or status_default_message(normalized),
        "updated_at": now_iso(),
        "tenant_id": active_tenant_id(tenant_id),
    }
    payload.update({key: value for key, value in extra.items() if value is not None})
    path = runtime_status_path(tenant_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)
    return payload


def read_runtime_status(tenant_id: str | None = None) -> dict[str, Any]:
    path = runtime_status_path(tenant_id)
    if not path.exists():
        return {
            "ok": True,
            "state": "stopped",
            "message": status_default_message("stopped"),
            "updated_at": "",
            "tenant_id": active_tenant_id(tenant_id),
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "ok": False,
            "state": "stopped",
            "message": "状态文件读取失败，请重新启动客服监听。",
            "updated_at": "",
            "tenant_id": active_tenant_id(tenant_id),
        }
    if not isinstance(payload, dict):
        payload = {}
    state = str(payload.get("state") or "stopped")
    if state not in RUNTIME_STATES:
        state = "stopped"
    return {
        **payload,
        "ok": payload.get("ok", True) is not False,
        "state": state,
        "message": str(payload.get("message") or status_default_message(state)),
        "tenant_id": str(payload.get("tenant_id") or active_tenant_id(tenant_id)),
    }


def status_default_message(state: str) -> str:
    return {
        "idle": "自动客服正在运行，当前没有正在处理的消息。",
        "thinking": "自动客服正在读取微信消息或调用大模型。",
        "stopped": "自动客服监听已停止。",
    }.get(state, "自动客服状态未知。")


def summarize_listener_result(result: dict[str, Any]) -> dict[str, Any]:
    events = [item for item in result.get("events", []) or [] if isinstance(item, dict)]
    last_event = events[-1] if events else {}
    synthesis = last_event.get("llm_reply_synthesis") if isinstance(last_event.get("llm_reply_synthesis"), dict) else {}
    rag = last_event.get("rag_reply") if isinstance(last_event.get("rag_reply"), dict) else {}
    evidence_summary = synthesis.get("evidence_summary") if isinstance(synthesis.get("evidence_summary"), dict) else {}
    return {
        "last_action": last_event.get("action"),
        "last_target": last_event.get("target"),
        "last_reason": last_event.get("reason") or synthesis.get("reason") or rag.get("reason"),
        "last_reply_preview": str(((last_event.get("decision") or {}).get("reply_text") if isinstance(last_event.get("decision"), dict) else "") or "")[:180],
        "model_tier": synthesis.get("model_tier"),
        "model": synthesis.get("model"),
        "rag_hit_count": evidence_summary.get("rag_hit_count"),
        "structured_evidence_count": evidence_summary.get("structured_evidence_count"),
    }


class CustomerServiceRuntime:
    """Start/stop/status wrapper for one tenant's managed WeChat listener."""

    def __init__(self, *, tenant_id: str | None = None) -> None:
        self.tenant_id = active_tenant_id(tenant_id)

    def status(self) -> dict[str, Any]:
        pid_record = self._read_pid_record()
        pid = int(pid_record.get("pid") or 0)
        running = self._pid_alive(pid)
        if not running and not pid_record:
            running, scanned_pid = self._scan_listener_running(self.tenant_id)
            if running:
                pid = scanned_pid
                pid_record = {"pid": pid, "tenant_id": self.tenant_id}
        status = read_runtime_status(self.tenant_id)
        gate = cloud_gate_status() if cloud_required_enabled() else {"ok": True, "required": False}
        worker_pid_record = self._read_worker_pid_record()
        worker_pid = int(worker_pid_record.get("pid") or 0)
        worker_running = self._pid_alive(worker_pid)
        queue_summary = {}
        try:
            from apps.wechat_ai_customer_service.admin_backend.services.work_queue import WorkQueueService
            queue_summary = WorkQueueService(tenant_id=self.tenant_id).summary()
        except Exception:
            pass
        status.update(
            {
                "running": running,
                "pid": pid if running else None,
                "started_at": pid_record.get("started_at") if running else "",
                "config_path": str(pid_record.get("config_path") or self._config_path_or_empty()),
                "log_path": str(runtime_log_path(self.tenant_id)),
                "cloud_gate": gate,
                "worker_pid": worker_pid if worker_running else None,
                "worker_running": worker_running,
                "queue_summary": queue_summary,
            }
        )
        if not running:
            status["state"] = "stopped"
            status["message"] = status_default_message("stopped")
        status["other_listeners"] = self._scan_all_listener_tenants()
        return status

    @staticmethod
    def _scan_all_listener_tenants() -> list[dict[str, Any]]:
        """Scan for running listeners across all tenants (dedupe launcher parent/child pairs)."""
        listeners = CustomerServiceRuntime._list_listener_processes()
        return [{"pid": item["pid"], "tenant_id": item["tenant_id"] or "unknown"} for item in listeners]

    def start(self, *, token: str = "") -> dict[str, Any]:
        current = self.status()
        if current.get("running"):
            return {"ok": True, "message": "自动客服已经在运行。", "item": current}
        if cloud_required_enabled():
            refresh = VpsLocalSyncService().fetch_shared_knowledge_snapshot(
                token=token,
                tenant_id=self.tenant_id,
                force=True,
            )
            if refresh.get("ok") is not True:
                message = "无法从服务端刷新共享行业知识库，自动客服已锁定。请恢复服务端连接后重试。"
                write_runtime_status("stopped", message, tenant_id=self.tenant_id)
                return {
                    "ok": False,
                    "message": message,
                    "detail": "cloud_snapshot_refresh_failed",
                    "sync_result": refresh,
                    "item": self.status(),
                }
            gate = cloud_gate_status()
            if not gate.get("ok"):
                message = "云端授权未通过，自动客服已锁定。请先连接服务端并刷新共享行业知识库。"
                write_runtime_status("stopped", message, tenant_id=self.tenant_id)
                return {"ok": False, "message": message, "detail": "cloud_authoritative_access_required", "cloud_gate": gate, "item": self.status()}
        try:
            config_path = self._resolve_config_path()
        except FileNotFoundError as exc:
            write_runtime_status("stopped", str(exc), tenant_id=self.tenant_id)
            return {"ok": False, "message": str(exc), "item": self.status()}
        script_path = APP_ROOT / "scripts" / "run_customer_service_listener.py"
        if not script_path.exists():
            return {"ok": False, "message": f"缺少监听脚本：{script_path}", "item": current}
        log_path = runtime_log_path(self.tenant_id)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        env["WECHAT_KNOWLEDGE_TENANT"] = self.tenant_id
        if token:
            env["WECHAT_RUNTIME_SYNC_TOKEN"] = token
        write_runtime_status("thinking", "正在启动微信自动客服监听。", tenant_id=self.tenant_id)
        creationflags = 0
        if os.name == "nt":
            creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            creationflags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.Popen(
            [
                str(self._python_executable()),
                str(script_path),
                "--tenant-id",
                self.tenant_id,
                "--config",
                str(config_path),
                "--interval-seconds",
                "3",
                "--send",
                "--write-data",
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
                "config_path": str(config_path),
                "started_at": now_iso(),
                "log_path": str(log_path),
            }
        )
        # Start background worker
        worker_result = self._start_worker()
        time.sleep(0.8)
        result = {"ok": True, "message": "自动客服监听已启动。", "item": self.status()}
        if not worker_result.get("ok"):
            result["worker_warning"] = worker_result.get("message", "worker start warning")
        return result

    def stop(self) -> dict[str, Any]:
        pid_record = self._read_pid_record()
        pid = int(pid_record.get("pid") or 0)
        if pid and self._pid_alive(pid):
            self._terminate_tree(pid)
        self._stop_worker()
        write_runtime_status("stopped", "自动客服监听已手动停止。", tenant_id=self.tenant_id)
        self._clear_pid_record()
        return {"ok": True, "message": "自动客服监听已停止。", "item": self.status()}

    def _config_path_or_empty(self) -> str:
        try:
            return str(self._resolve_config_path())
        except FileNotFoundError:
            return ""

    def _resolve_config_path(self) -> Path:
        candidates = [
            runtime_dir(self.tenant_id) / "listener_config.json",
            APP_ROOT / "configs" / f"{self.tenant_id}.json",
            APP_ROOT / "configs" / f"{self.tenant_id}.example.json",
        ]
        if self.tenant_id == DEFAULT_CHEJIN_TENANT_ID:
            candidates.append(DEFAULT_CHEJIN_CONFIG)
        for path in candidates:
            if path.exists():
                return path
        raise FileNotFoundError(
            "当前客户账号还没有配置微信监听目标。请先为该账号创建 listener_config.json，或在后台为该账号完成微信自动客服配置。"
        )

    def _python_executable(self) -> Path:
        override = str(os.getenv("WECHAT_RUNTIME_PYTHON") or "").strip()
        if override:
            override_path = Path(override)
            if override_path.exists():
                return override_path
        current = Path(sys.executable)
        if current.exists():
            return current
        venv_python = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
        if venv_python.exists():
            return venv_python
        return current

    def _read_pid_record(self) -> dict[str, Any]:
        path = runtime_pid_path(self.tenant_id)
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write_pid_record(self, payload: dict[str, Any]) -> None:
        path = runtime_pid_path(self.tenant_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, path)

    def _clear_pid_record(self) -> None:
        try:
            runtime_pid_path(self.tenant_id).unlink()
        except FileNotFoundError:
            pass

    _LISTENER_SCRIPT_NAME = "run_customer_service_listener.py"
    _WORKER_SCRIPT_NAME = "background_worker.py"

    @staticmethod
    def _cmdline_has_script(cmdline: list[str], script_name: str) -> bool:
        target = script_name
        for arg in cmdline:
            arg_norm = os.path.normpath(str(arg))
            if os.path.basename(arg_norm) == target:
                return True
        return False

    @staticmethod
    def _cmdline_has_listener_script(cmdline: list[str]) -> bool:
        """Return True if cmdline actually executes the listener script (not just mentions it)."""
        return CustomerServiceRuntime._cmdline_has_script(cmdline, CustomerServiceRuntime._LISTENER_SCRIPT_NAME)

    @staticmethod
    def _scan_listener_running(tenant_id: str) -> tuple[bool, int]:
        """Fallback: scan process list for a running listener matching tenant_id."""
        for listener in CustomerServiceRuntime._list_listener_processes():
            if listener.get("tenant_id") == tenant_id:
                return True, int(listener.get("pid") or 0)
        return False, 0

    @staticmethod
    def _extract_tenant_from_cmdline(cmdline: list[str]) -> str:
        for index, part in enumerate(cmdline):
            if str(part) == "--tenant-id" and index + 1 < len(cmdline):
                return str(cmdline[index + 1]).strip()
        return ""

    @staticmethod
    def _list_listener_processes() -> list[dict[str, Any]]:
        my_pid = os.getpid()
        candidates: dict[int, dict[str, Any]] = {}
        for proc in psutil.process_iter(["pid", "ppid", "cmdline", "name"]):
            try:
                pid = int(proc.info.get("pid") or 0)
                cmdline = [str(item) for item in (proc.info.get("cmdline") or [])]
                name = str(proc.info.get("name") or "").lower()
                if pid <= 0 or pid == my_pid or "python" not in name:
                    continue
                if not CustomerServiceRuntime._cmdline_has_listener_script(cmdline):
                    continue
                if not CustomerServiceRuntime._pid_alive(pid):
                    continue
                candidates[pid] = {
                    "pid": pid,
                    "ppid": int(proc.info.get("ppid") or 0),
                    "tenant_id": CustomerServiceRuntime._extract_tenant_from_cmdline(cmdline),
                    "cmdline": cmdline,
                }
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        if not candidates:
            return []
        child_map: dict[int, list[dict[str, Any]]] = {}
        for info in candidates.values():
            parent = int(info.get("ppid") or 0)
            if parent in candidates:
                child_map.setdefault(parent, []).append(info)
        effective: list[dict[str, Any]] = []
        for info in candidates.values():
            children = child_map.get(int(info["pid"]), [])
            if not children:
                effective.append(info)
                continue
            parent_tenant = str(info.get("tenant_id") or "")
            has_same_listener_child = any(
                (not parent_tenant or parent_tenant == str(child.get("tenant_id") or ""))
                and CustomerServiceRuntime._cmdline_has_listener_script(child.get("cmdline") or [])
                for child in children
            )
            if not has_same_listener_child:
                effective.append(info)
        effective.sort(key=lambda item: int(item.get("pid") or 0))
        return effective

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

    # --- Background worker lifecycle ---

    def _read_worker_pid_record(self) -> dict[str, Any]:
        path = worker_pid_path(self.tenant_id)
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _start_worker(self) -> dict[str, Any]:
        worker_record = self._read_worker_pid_record()
        existing_pid = int(worker_record.get("pid") or 0)
        if existing_pid and self._pid_alive(existing_pid):
            return {"ok": True, "message": "后台 worker 已经在运行。"}
        scanned_worker_pids = self._scan_worker_running_pids(self.tenant_id)
        if scanned_worker_pids:
            worker_pid = max(scanned_worker_pids)
            path = worker_pid_path(self.tenant_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix(".json.tmp")
            temp.write_text(
                json.dumps(
                    {
                        "pid": worker_pid,
                        "tenant_id": self.tenant_id,
                        "queue": "customer_service",
                        "started_at": now_iso(),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            os.replace(temp, path)
            return {"ok": True, "message": "后台 worker 已经在运行。", "worker_pid": worker_pid}
        script_path = APP_ROOT / "scripts" / "background_worker.py"
        if not script_path.exists():
            return {"ok": False, "message": f"缺少后台 worker 脚本：{script_path}"}
        env = dict(os.environ)
        env["WECHAT_KNOWLEDGE_TENANT"] = self.tenant_id
        creationflags = 0
        if os.name == "nt":
            creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            creationflags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.Popen(
            [
                str(self._python_executable()),
                str(script_path),
                "--tenant-id",
                self.tenant_id,
                "--queue",
                "customer_service",
                "--interval-seconds",
                "5",
                "--limit",
                "3",
            ],
            cwd=str(PROJECT_ROOT),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        time.sleep(0.3)
        return {"ok": True, "message": "后台 worker 已启动。", "worker_pid": proc.pid}

    def _stop_worker(self) -> None:
        worker_record = self._read_worker_pid_record()
        pids = set(self._scan_worker_running_pids(self.tenant_id))
        pid = int(worker_record.get("pid") or 0)
        if pid:
            pids.add(pid)
        for worker_pid in sorted(pids):
            if worker_pid and self._pid_alive(worker_pid):
                self._terminate_tree(worker_pid)
        try:
            worker_pid_path(self.tenant_id).unlink()
        except FileNotFoundError:
            pass

    @staticmethod
    def _scan_worker_running_pids(tenant_id: str) -> list[int]:
        my_pid = os.getpid()
        pids: set[int] = set()
        for proc in psutil.process_iter(["pid", "cmdline", "name"]):
            try:
                pid = int(proc.info.get("pid") or 0)
                cmdline = proc.info.get("cmdline") or []
                name = str(proc.info.get("name") or "").lower()
                if pid <= 0 or pid == my_pid or "python" not in name:
                    continue
                if not CustomerServiceRuntime._cmdline_has_script(cmdline, CustomerServiceRuntime._WORKER_SCRIPT_NAME):
                    continue
                cmd_str = " ".join(str(item) for item in cmdline)
                if f"--tenant-id {tenant_id}" not in cmd_str:
                    continue
                if CustomerServiceRuntime._pid_alive(pid):
                    pids.add(pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return sorted(pids)
