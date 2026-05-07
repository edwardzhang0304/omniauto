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
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psutil


ROOT = Path(__file__).resolve().parents[3]
SIDECAR_PYTHON = ROOT / "runtime/tool_envs/wxauto4-py312/Scripts/python.exe"
SIDECAR_SCRIPT = ROOT / "apps/wechat_ai_customer_service/adapters/wxauto4_sidecar.py"
WECHAT_EXE = Path(r"C:\Program Files (x86)\Tencent\Weixin\Weixin.exe")
FILE_TRANSFER_ASSISTANT = "".join(chr(c) for c in [0x6587, 0x4EF6, 0x4F20, 0x8F93, 0x52A9, 0x624B])

# Global daemon process cache to avoid repeated subprocess spawn overhead.
_daemon_proc: subprocess.Popen | None = None
_daemon_lock = threading.Lock()


class WeChatConnectorError(RuntimeError):
    """Raised when the connector cannot complete a guarded operation."""


@dataclass(frozen=True)
class WeChatConnector:
    sidecar_python: Path = SIDECAR_PYTHON
    sidecar_script: Path = SIDECAR_SCRIPT
    root: Path = ROOT
    timeout_seconds: int = 120

    def status(self) -> dict[str, Any]:
        return self.call_sidecar(["status"], allow_failure=True)

    def wait_online(self, seconds: int = 60) -> dict[str, Any]:
        deadline = time.time() + max(1, seconds)
        latest: dict[str, Any] = {}
        while time.time() <= deadline:
            latest = self.status()
            if latest.get("ok") and latest.get("online"):
                return latest
            time.sleep(3)
        return latest

    def list_sessions(self) -> dict[str, Any]:
        self.require_online()
        return self.call_sidecar(["sessions"])

    def get_messages(self, target: str, exact: bool = True) -> dict[str, Any]:
        self.require_online()
        args = ["messages", "--target", target]
        if exact:
            args.append("--exact")
        return self.call_sidecar(args)

    def send_text(self, target: str, text: str, exact: bool = True) -> dict[str, Any]:
        if not target:
            raise WeChatConnectorError("target is required")
        if not text:
            raise WeChatConnectorError("text is required")
        self.require_online()
        args = ["send", "--target", target, "--text", text]
        if exact:
            args.append("--exact")
        return self.call_sidecar(args)

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


def _read_json_response(proc: subprocess.Popen, timeout: int = 25) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError("daemon_process_died")
        line = proc.stdout.readline().decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            # Skip non-JSON lines (e.g., library warnings on startup)
            continue
    raise TimeoutError("daemon_response_timeout")


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


def _args_to_request(args: list[str]) -> dict[str, Any]:
    request: dict[str, Any] = {"resize": True}
    if not args:
        request["action"] = "status"
        return request
    if args[0] == "status":
        request["action"] = "status"
    elif args[0] == "sessions":
        request["action"] = "sessions"
    elif args[0] == "messages":
        request["action"] = "messages"
        for i, arg in enumerate(args):
            if arg == "--target" and i + 1 < len(args):
                request["target"] = args[i + 1]
            elif arg == "--exact":
                request["exact"] = True
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


def any_weixin_process() -> bool:
    for proc in psutil.process_iter(["name"]):
        try:
            if str(proc.info.get("name") or "").lower() == "weixin.exe":
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False
