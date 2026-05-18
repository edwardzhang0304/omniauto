"""WeChat session monitor: detect unread messages via content-digest comparison.

wxauto4 does not expose unread counts, so we compare the SHA256 digest of each
session's latest content preview across polls. A changed digest (or newer time)
indicates potential new messages.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from apps.wechat_ai_customer_service.knowledge_paths import active_tenant_id, tenant_runtime_root


@dataclass
class SessionState:
    name: str
    last_content_digest: str = ""
    last_message_time: str = ""
    unread_detected: bool = False
    priority_score: int = 0
    first_seen_at: str = ""
    last_seen_at: str = ""


@dataclass
class ActiveTarget:
    name: str
    exact: bool = True
    priority_score: int = 0
    unread_detected: bool = False
    session_age_seconds: int = 0
    conversation_type: str = "unknown"


class SessionMonitor:
    """Polls WeChat session list and detects changes."""

    def __init__(
        self,
        *,
        tenant_id: str | None = None,
        state_path: Path | None = None,
        whitelist: set[str] | None = None,
        blacklist: set[str] | None = None,
        max_targets_per_iteration: int = 5,
        min_switch_interval_seconds: int = 2,
    ) -> None:
        self.tenant_id = active_tenant_id(tenant_id)
        self.state_path = state_path or (
            tenant_runtime_root(self.tenant_id) / "customer_profiles" / "session_monitor_state.json"
        )
        self.whitelist = whitelist or set()
        self.blacklist = blacklist or set()
        self.max_targets_per_iteration = max(1, max_targets_per_iteration)
        self.min_switch_interval_seconds = max(1, min_switch_interval_seconds)
        self._last_switch_at: float = 0.0
        self._sessions: dict[str, SessionState] = {}
        self._load_state()

    def _load_state(self) -> None:
        if not self.state_path.exists():
            self._sessions = {}
            return
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._sessions = {}
            return
        if not isinstance(payload, dict):
            self._sessions = {}
            return
        raw = payload.get("sessions", {})
        self._sessions = {
            str(name): SessionState(
                name=str(name),
                last_content_digest=str(data.get("last_content_digest") or ""),
                last_message_time=str(data.get("last_message_time") or ""),
                unread_detected=bool(data.get("unread_detected", False)),
                priority_score=int(data.get("priority_score", 0) or 0),
                first_seen_at=str(data.get("first_seen_at") or ""),
                last_seen_at=str(data.get("last_seen_at") or ""),
            )
            for name, data in raw.items()
            if isinstance(data, dict)
        }

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "tenant_id": self.tenant_id,
            "last_poll_at": datetime.now().isoformat(timespec="seconds"),
            "sessions": {
                name: {
                    "last_content_digest": s.last_content_digest,
                    "last_message_time": s.last_message_time,
                    "unread_detected": s.unread_detected,
                    "priority_score": s.priority_score,
                    "first_seen_at": s.first_seen_at,
                    "last_seen_at": s.last_seen_at,
                }
                for name, s in self._sessions.items()
            },
        }
        temp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, self.state_path)

    def poll(self, connector: Any) -> list[ActiveTarget]:
        """Poll WeChat sessions and return prioritized list of changed targets."""
        result = connector.list_sessions()
        if not result.get("ok"):
            return []

        sessions_data = result.get("sessions", []) or []
        now_iso = datetime.now().isoformat(timespec="seconds")
        now_ts = time.time()
        active: list[ActiveTarget] = []

        for raw in sessions_data:
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name") or "").strip()
            if not name:
                continue

            # Skip sessions not in whitelist if whitelist is set
            if self.whitelist and name not in self.whitelist:
                continue
            if self.blacklist and name in self.blacklist:
                continue

            content = str(raw.get("content") or "").strip()
            msg_time = str(raw.get("time") or "").strip()
            digest = _digest(content) if content else ""
            conversation_type = _infer_conversation_type(name, raw)

            existing = self._sessions.get(name)
            if existing is None:
                # New session seen for the first time
                self._sessions[name] = SessionState(
                    name=name,
                    last_content_digest=digest,
                    last_message_time=msg_time,
                    unread_detected=bool(digest),
                    priority_score=50 if digest else 0,
                    first_seen_at=now_iso,
                    last_seen_at=now_iso,
                )
                if digest:
                    active.append(ActiveTarget(
                        name=name,
                        exact=True,
                        priority_score=50,
                        unread_detected=True,
                        session_age_seconds=0,
                        conversation_type=conversation_type,
                    ))
            else:
                changed = False
                if digest and digest != existing.last_content_digest:
                    changed = True
                elif msg_time and msg_time != existing.last_message_time and not digest:
                    # Content empty but time updated — still flag as changed
                    changed = True
                elif msg_time and msg_time != existing.last_message_time:
                    # Time changed even if digest same (same content sent again)
                    changed = True

                if changed:
                    # Bump priority based on how long since last contact
                    age_seconds = 0
                    try:
                        last = datetime.fromisoformat(existing.last_seen_at.replace("Z", "+00:00"))
                        age_seconds = int((datetime.now() - last).total_seconds())
                    except Exception:
                        pass
                    priority = min(100, 50 + age_seconds // 60)
                    existing.unread_detected = True
                    existing.priority_score = priority
                    existing.last_content_digest = digest
                    existing.last_message_time = msg_time
                    existing.last_seen_at = now_iso
                    active.append(ActiveTarget(
                        name=name,
                        exact=True,
                        priority_score=priority,
                        unread_detected=True,
                        session_age_seconds=age_seconds,
                        conversation_type=conversation_type,
                    ))
                else:
                    existing.last_seen_at = now_iso
                    existing.unread_detected = False
                    existing.priority_score = max(0, existing.priority_score - 5)

        self._save_state()

        # Sort by priority descending, then by session_age (older = higher priority)
        active.sort(key=lambda t: (-t.priority_score, -t.session_age_seconds))
        return active[: self.max_targets_per_iteration]

    def pick_next_target(self, active: list[ActiveTarget]) -> ActiveTarget | None:
        """Respect min_switch_interval and return the highest-priority target."""
        if not active:
            return None
        now_ts = time.time()
        elapsed = now_ts - self._last_switch_at
        if elapsed < self.min_switch_interval_seconds:
            return None
        self._last_switch_at = now_ts
        return active[0]

    def all_sessions(self) -> list[dict[str, Any]]:
        """Return all known sessions for admin UI."""
        return [
            {
                "name": s.name,
                "last_content_digest": s.last_content_digest,
                "last_message_time": s.last_message_time,
                "unread_detected": s.unread_detected,
                "priority_score": s.priority_score,
                "first_seen_at": s.first_seen_at,
                "last_seen_at": s.last_seen_at,
            }
            for s in self._sessions.values()
        ]

    def reset_unread(self, name: str) -> None:
        """Mark a session as read after processing."""
        if name in self._sessions:
            self._sessions[name].unread_detected = False
            self._sessions[name].priority_score = 0
            self._save_state()


def _digest(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:32]


def _infer_conversation_type(name: str, session: dict[str, Any]) -> str:
    explicit = str(session.get("conversation_type") or session.get("type") or "").strip().lower()
    if explicit in {"private", "group", "file_transfer", "system"}:
        return explicit
    if name in {"文件传输助手", "File Transfer"}:
        return "file_transfer"
    if "群" in name or "chatroom" in name.lower() or "room" in name.lower():
        return "group"
    if any(keyword in name for keyword in ("微信团队", "系统消息", "服务通知", "订阅号")):
        return "system"
    return "private"
