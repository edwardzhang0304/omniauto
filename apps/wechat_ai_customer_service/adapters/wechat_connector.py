"""Connector wrapper for the wxauto4 WeChat sidecar.

The connector is the stable boundary the workflow layer should use. It keeps
WeChat-specific Python 3.12/wxauto4 details outside the OmniAuto Python 3.13
process and returns plain dictionaries that are easy to validate and persist.

Daemon mode caching: a single sidecar process is spawned and reused across
multiple calls to avoid the ~2-5 second overhead of starting Python 3.12 and
importing wxauto4 on every WeChat operation.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psutil


ROOT = Path(__file__).resolve().parents[3]
SIDECAR_PYTHON = ROOT / "runtime/tool_envs/wxauto4-py312/Scripts/python.exe"
SIDECAR_SCRIPT = ROOT / "apps/wechat_ai_customer_service/adapters/wxauto4_sidecar.py"
COMPAT_SIDECAR_SCRIPT = ROOT / "apps/wechat_ai_customer_service/adapters/wechat_win32_ocr_sidecar.py"
COMPAT_SIDECAR_PYTHON = ROOT / ".venv/Scripts/python.exe"
WECHAT_EXE = Path(r"C:\Program Files (x86)\Tencent\Weixin\Weixin.exe")
FILE_TRANSFER_ASSISTANT = "".join(chr(c) for c in [0x6587, 0x4EF6, 0x4F20, 0x8F93, 0x52A9, 0x624B])
WECHAT_RPA_LOCK_PATH = ROOT / "runtime" / "wechat_rpa.lock"

# Global daemon process cache to avoid repeated subprocess spawn overhead.
_daemon_proc: subprocess.Popen | None = None
_daemon_lock = threading.Lock()


class WeChatConnectorError(RuntimeError):
    """Raised when the connector cannot complete a guarded operation."""


@dataclass(frozen=True)
class WeChatConnector:
    sidecar_python: Path = SIDECAR_PYTHON
    sidecar_script: Path = SIDECAR_SCRIPT
    compat_sidecar_script: Path = COMPAT_SIDECAR_SCRIPT
    compat_sidecar_python: Path = COMPAT_SIDECAR_PYTHON
    root: Path = ROOT
    timeout_seconds: int = 120

    def status(self) -> dict[str, Any]:
        with wechat_rpa_lock("status"):
            primary = self.call_sidecar(["status"], allow_failure=True)
            if primary.get("ok") and primary.get("online"):
                primary.setdefault("adapter", "wxauto4")
                return primary
            fallback = self.call_compat_sidecar(["status"], allow_failure=True, primary_payload=primary)
            if fallback.get("ok") and fallback.get("online"):
                return fallback
            return primary

    def capabilities(self) -> dict[str, Any]:
        """Detect the active WeChat transport before starting a long-running loop."""
        with wechat_rpa_lock("capabilities"):
            try:
                primary = self.call_sidecar(["status"], allow_failure=True)
            except Exception as exc:
                primary = {
                    "ok": False,
                    "online": False,
                    "adapter": "wxauto4",
                    "state": "primary_status_failed",
                    "error": repr(exc),
                }
            if primary.get("ok") and primary.get("online"):
                return {
                    "ok": True,
                    "online": True,
                    "adapter": "wxauto4",
                    "scheme": "wxauto4",
                    "state": "primary_adapter_ready",
                    "receive": {"ok": True, "method": "wxauto4.GetAllMessage"},
                    "send": {"ok": True, "preferred_mode": "wxauto4", "method": "wxauto4.ChatBox controls"},
                    "primary_status": primary,
                    "message": "wxauto4 adapter is available.",
                }

            try:
                fallback = self.call_compat_sidecar(["capabilities"], allow_failure=True, primary_payload=primary)
            except Exception as exc:
                fallback = {
                    "ok": False,
                    "online": False,
                    "adapter": "win32_ocr",
                    "state": "compat_capabilities_failed",
                    "error": repr(exc),
                }
            if fallback.get("online"):
                fallback.setdefault("adapter", "win32_ocr")
                fallback.setdefault("primary_status", primary)
                fallback.setdefault("compat_reason", "primary_adapter_failed")
                return fallback

            return {
                "ok": False,
                "online": False,
                "adapter": "none",
                "scheme": "wechat_not_ready",
                "state": "no_supported_wechat_transport",
                "receive": {"ok": False},
                "send": {"ok": False},
                "primary_status": primary,
                "fallback_status": fallback,
                "weixin_process_running": any_weixin_process(),
                "message": "No logged-in WeChat main window is available.",
            }

    def wait_online(self, seconds: int = 60) -> dict[str, Any]:
        deadline = time.time() + max(1, seconds)
        latest: dict[str, Any] = {}
        while time.time() <= deadline:
            latest = self.status()
            if latest.get("ok") and latest.get("online"):
                return latest
            time.sleep(3)
        return latest

    def list_sessions(self, *, fresh: bool = False) -> dict[str, Any]:
        args = ["sessions"]
        if fresh:
            args.append("--fresh")
        with wechat_rpa_lock("sessions"):
            primary = self.call_sidecar(args, allow_failure=True)
            if primary.get("ok"):
                primary.setdefault("adapter", "wxauto4")
                return primary
            return self.call_compat_sidecar(args, allow_failure=True, primary_payload=primary)

    def get_messages(self, target: str, exact: bool = True, history_load_times: int = 0) -> dict[str, Any]:
        args = ["messages", "--target", target]
        if exact:
            args.append("--exact")
        if history_load_times:
            try:
                load_times = max(0, int(history_load_times))
            except (TypeError, ValueError):
                load_times = 0
            if load_times:
                args.extend(["--history-load-times", str(load_times)])
        with wechat_rpa_lock("messages"):
            primary = self.call_sidecar(args, allow_failure=True)
            if primary.get("ok"):
                primary.setdefault("adapter", "wxauto4")
                return primary
            return self.call_compat_sidecar(args, allow_failure=True, primary_payload=primary)

    def send_text(self, target: str, text: str, exact: bool = True) -> dict[str, Any]:
        if not target:
            raise WeChatConnectorError("target is required")
        if not text:
            raise WeChatConnectorError("text is required")
        args = ["send", "--target", target, "--text", text]
        if exact:
            args.append("--exact")
        with wechat_rpa_lock("send"):
            primary = self.call_sidecar(args, allow_failure=True)
            if primary.get("ok"):
                primary.setdefault("adapter", "wxauto4")
                return primary
            return self.call_compat_sidecar(args, allow_failure=True, primary_payload=primary)

    def send_text_and_verify(self, target: str, text: str, exact: bool = True) -> dict[str, Any]:
        send_result = self.send_text(target, text, exact=exact)
        if not send_result.get("ok"):
            return {"ok": False, "send": send_result, "verified": False}
        messages: dict[str, Any] = {}
        verified = False
        for attempt in range(6):
            if attempt:
                time.sleep(1)
            messages = self.get_messages(target, exact=exact)
            verified = any(
                item.get("sender") == "self" and item.get("content") == text
                for item in messages.get("messages", []) or []
            )
            if verified:
                break
        return {
            "ok": bool(verified),
            "send": send_result,
            "messages": messages,
            "verified": bool(verified),
        }

    def require_online(self) -> dict[str, Any]:
        status = self.status()
        if not status.get("ok") or not status.get("online"):
            raise WeChatConnectorError(
                "WeChat is not online; open and log in to the main window first. "
                f"status={status!r}"
            )
        return status

    def ensure_wechat_started(self) -> None:
        """Compatibility helper; startup is deliberately manual."""
        status = self.status()
        if status.get("ok") and status.get("online"):
            return
        raise WeChatConnectorError(
            "Automatic WeChat startup is disabled. Open WeChat, finish login manually, "
            "and keep the main window visible before running the workflow."
        )

    def call_sidecar(self, args: list[str], allow_failure: bool = False) -> dict[str, Any]:
        if not self.sidecar_python.exists():
            raise FileNotFoundError(str(self.sidecar_python))
        if not self.sidecar_script.exists():
            raise FileNotFoundError(str(self.sidecar_script))
        return self._call_daemon(args, allow_failure)

    def call_compat_sidecar(
        self,
        args: list[str],
        *,
        allow_failure: bool = False,
        primary_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.compat_sidecar_script.exists():
            payload = {
                "ok": False,
                "online": False,
                "adapter": "win32_ocr",
                "state": "compat_sidecar_missing",
                "error": f"compat sidecar missing: {self.compat_sidecar_script}",
            }
            if primary_payload is not None:
                payload["primary_status"] = primary_payload
            if not allow_failure:
                payload.setdefault("error", "compat_sidecar_missing")
            return payload

        python = self.compat_sidecar_python if self.compat_sidecar_python.exists() else Path(sys.executable)
        cmd = [str(python), str(self.compat_sidecar_script), *compat_args(args)]
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env["PYTHONPATH"] = str(self.root)
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(self.root),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=min(max(10, self.timeout_seconds), 120),
            )
        except Exception as exc:
            payload = {"ok": False, "online": False, "adapter": "win32_ocr", "state": "compat_call_failed", "error": repr(exc)}
            if primary_payload is not None:
                payload["primary_status"] = primary_payload
            return payload

        payload = parse_json_object(proc.stdout)
        if not isinstance(payload, dict):
            payload = {
                "ok": False,
                "online": False,
                "adapter": "win32_ocr",
                "state": "compat_invalid_response",
                "error": "compat sidecar did not return JSON",
                "stdout": proc.stdout[-2000:],
                "stderr": proc.stderr[-2000:],
                "returncode": proc.returncode,
            }
        payload.setdefault("adapter", "win32_ocr")
        if primary_payload is not None:
            payload["primary_status"] = primary_payload
            payload.setdefault("compat_reason", "primary_adapter_failed")
        if proc.returncode != 0 and payload.get("ok"):
            payload["returncode_warning"] = proc.returncode
        elif proc.returncode != 0:
            payload.setdefault("returncode", proc.returncode)
            if proc.stderr:
                payload.setdefault("stderr", proc.stderr[-2000:])
        if not payload.get("ok") and not allow_failure:
            payload.setdefault("error", "compat_command_failed")
        return payload

    def _call_daemon(self, args: list[str], allow_failure: bool = False) -> dict[str, Any]:
        global _daemon_proc
        with _daemon_lock:
            proc = _ensure_daemon(self.sidecar_python, self.sidecar_script, self.root)

            request = _args_to_request(args)
            request_line = json.dumps(request, ensure_ascii=False) + "\n"

            try:
                proc.stdin.write(request_line.encode("utf-8"))
                proc.stdin.flush()
                payload = _read_json_response(proc, timeout=25)
            except Exception:
                # Daemon may have died; kill, restart, and retry once.
                _kill_daemon()
                proc = _ensure_daemon(self.sidecar_python, self.sidecar_script, self.root)
                proc.stdin.write(request_line.encode("utf-8"))
                proc.stdin.flush()
                payload = _read_json_response(proc, timeout=25)

            if not payload.get("ok") and not allow_failure:
                payload.setdefault("error", "daemon_command_failed")
            return payload


@contextmanager
def wechat_rpa_lock(action: str, *, timeout_seconds: float = 90.0, stale_seconds: float = 180.0):
    """Serialize desktop WeChat RPA/OCR calls across processes.

    wxauto4 and the Win32/OCR fallback both manipulate the same foreground
    WeChat window. Without a process-wide lock, recorder screenshots can race
    with automated sends and produce missed or partial captures.
    """
    if os.getenv("WECHAT_RPA_LOCK_DISABLED", "").strip().lower() in {"1", "true", "yes", "on"}:
        yield
        return
    lock_path = WECHAT_RPA_LOCK_PATH
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + max(1.0, float(timeout_seconds))
    payload = {"pid": os.getpid(), "action": action, "created_at": time.time()}
    acquired = False
    while time.time() <= deadline:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.write(fd, json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            finally:
                os.close(fd)
            acquired = True
            break
        except FileExistsError:
            if should_break_wechat_rpa_lock(lock_path, stale_seconds=stale_seconds):
                try:
                    lock_path.unlink()
                except FileNotFoundError:
                    pass
                except OSError:
                    time.sleep(0.2)
                    continue
            else:
                time.sleep(0.2)
    if not acquired:
        raise TimeoutError(f"WeChat RPA lock timeout for action={action}")
    try:
        yield
    finally:
        try:
            current = json.loads(lock_path.read_text(encoding="utf-8"))
        except Exception:
            current = {}
        if int(current.get("pid") or 0) == os.getpid():
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass


def should_break_wechat_rpa_lock(path: Path, *, stale_seconds: float) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return True
    pid = int(payload.get("pid") or 0)
    created_at = float(payload.get("created_at") or 0)
    if pid and not psutil.pid_exists(pid):
        return True
    if created_at and time.time() - created_at > stale_seconds:
        return True
    return False


def _read_json_response(proc: subprocess.Popen, timeout: int = 25) -> dict[str, Any]:
    output: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)

    def read_worker() -> None:
        try:
            while True:
                if proc.poll() is not None:
                    output.put(("error", RuntimeError("daemon_process_died")))
                    return
                line = proc.stdout.readline()
                if not line:
                    output.put(("error", RuntimeError("daemon_stdout_closed")))
                    return
                clean = line.decode("utf-8", errors="replace").strip()
                if not clean:
                    continue
                try:
                    output.put(("payload", json.loads(clean)))
                    return
                except json.JSONDecodeError:
                    # Skip non-JSON lines (e.g., library warnings on startup)
                    continue
        except Exception as exc:
            output.put(("error", exc))

    thread = threading.Thread(target=read_worker, daemon=True)
    thread.start()
    try:
        kind, value = output.get(timeout=max(1, timeout))
    except queue.Empty as exc:
        raise TimeoutError("daemon_response_timeout") from exc
    if kind == "payload":
        return value
    if isinstance(value, Exception):
        raise value
    raise RuntimeError(str(value))


def _ensure_daemon(
    sidecar_python: Path,
    sidecar_script: Path,
    root: Path,
) -> subprocess.Popen:
    global _daemon_proc
    if _daemon_proc is not None:
        if _daemon_proc.poll() is None:
            return _daemon_proc
        _kill_daemon()

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    _daemon_proc = subprocess.Popen(
        [str(sidecar_python), str(sidecar_script), "--daemon"],
        cwd=str(root),
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return _daemon_proc


def _kill_daemon() -> None:
    global _daemon_proc
    if _daemon_proc is not None:
        try:
            _daemon_proc.stdin.write(b'{"action": "exit"}\n')
            _daemon_proc.stdin.flush()
            _daemon_proc.wait(timeout=2)
        except Exception:
            _daemon_proc.kill()
        _daemon_proc = None


def reset_wxauto_sidecar_daemon() -> None:
    """Force the cached wxauto4 sidecar to restart on the next connector call."""
    _kill_daemon()


def _args_to_request(args: list[str]) -> dict[str, Any]:
    request: dict[str, Any] = {"resize": True}
    if not args:
        request["action"] = "status"
        return request
    if args[0] == "status":
        request["action"] = "status"
    elif args[0] == "sessions":
        request["action"] = "sessions"
        if "--fresh" in args:
            request["fresh"] = True
    elif args[0] == "messages":
        request["action"] = "messages"
        for i, arg in enumerate(args):
            if arg == "--target" and i + 1 < len(args):
                request["target"] = args[i + 1]
            elif arg == "--exact":
                request["exact"] = True
            elif arg == "--history-load-times" and i + 1 < len(args):
                try:
                    request["history_load_times"] = max(0, int(args[i + 1]))
                except ValueError:
                    request["history_load_times"] = 0
    elif args[0] == "send":
        request["action"] = "send"
        for i, arg in enumerate(args):
            if arg == "--target" and i + 1 < len(args):
                request["target"] = args[i + 1]
            elif arg == "--text" and i + 1 < len(args):
                request["text"] = args[i + 1]
            elif arg == "--exact":
                request["exact"] = True
    return request


def compat_args(args: list[str]) -> list[str]:
    """Convert connector args to the one-shot Win32/OCR fallback CLI.

    The compatibility sidecar does not maintain a daemon cache, so ``--fresh``
    is implicit and omitted.
    """
    converted: list[str] = []
    skip_next = False
    for index, arg in enumerate(args):
        if skip_next:
            skip_next = False
            continue
        if arg == "--fresh":
            continue
        converted.append(arg)
        if arg in {"--target", "--text", "--history-load-times"} and index + 1 < len(args):
            converted.append(args[index + 1])
            skip_next = True
    return converted


def parse_json_object(text: str) -> dict[str, Any] | None:
    clean = str(text or "").strip()
    if not clean:
        return None
    try:
        payload = json.loads(clean)
        return payload if isinstance(payload, dict) else None
    except json.JSONDecodeError:
        pass

    # Some OCR libraries may print initialization lines. Parse the last JSON
    # object from stdout instead of failing the entire fallback path.
    start = clean.rfind("{")
    while start >= 0:
        candidate = clean[start:]
        try:
            payload = json.loads(candidate)
            return payload if isinstance(payload, dict) else None
        except json.JSONDecodeError:
            start = clean.rfind("{", 0, start)
    return None


def any_weixin_process() -> bool:
    for proc in psutil.process_iter(["name"]):
        try:
            if str(proc.info.get("name") or "").lower() == "weixin.exe":
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False
