"""Persistent state primitives for customer-service multi-session scheduling.

The scheduler state is deliberately transport-agnostic. It tracks which WeChat
sessions need capture, which captured batches need reply generation, and which
planned replies are ready for the single RPA sender.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from apps.wechat_ai_customer_service.knowledge_paths import active_tenant_id, tenant_runtime_root


STATE_VERSION = 2
DEFAULT_PENDING_SESSION_TTL_SECONDS = 1800
DEFAULT_READY_REPLY_TTL_SECONDS = 900
DEFAULT_READY_REPLY_HISTORY_RETENTION_SECONDS = 7 * 24 * 60 * 60
DEFAULT_MAX_STORED_READY_REPLIES = 500
MAX_STORED_EVENTS = 500


def utcnow_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _iso_to_ts(value: Any) -> float:
    text = str(value or "").strip()
    if not text:
        return 0.0
    try:
        return datetime.fromisoformat(text).timestamp()
    except (TypeError, ValueError, OSError):
        return 0.0


def stable_id(prefix: str, *parts: Any) -> str:
    seed = json.dumps([str(item) for item in parts], ensure_ascii=False, sort_keys=True)
    return f"{prefix}_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20]


def normalize_target_name(name: Any) -> str:
    return str(name or "").strip()


def message_content_key(message: dict[str, Any]) -> str:
    if message_has_repeatable_probe_content(message):
        return ""
    sender = str(message.get("sender") or "")
    content = " ".join(str(message.get("content") or "").split())
    msg_type = str(message.get("type") or "")
    if not content:
        return ""
    return hashlib.sha256(f"{sender}|{msg_type}|{content}".encode("utf-8")).hexdigest()[:24]


def normalize_repeatable_probe_text(text: Any) -> str:
    compact = re.sub(r"[\s，。,.！？!、~～：:；;“”\"'（）()]+", "", str(text or "")).lower()
    return compact.strip()


def message_has_repeatable_probe_content(message: dict[str, Any]) -> bool:
    compact = normalize_repeatable_probe_text(message.get("content"))
    if not compact:
        return False
    if len(compact) <= 7:
        return True
    if compact in {"你好", "您好", "在吗", "有人吗", "老板在吗", "hello", "hi", "哈喽", "嗨", "在", "在不", "在么", "在嘛", "在呢"}:
        return True
    return compact.startswith("在") and len(compact) <= 3


def message_identity(message: dict[str, Any]) -> str:
    message_id = str(message.get("id") or "").strip()
    if message_id:
        return message_id
    return message_content_key(message)


@dataclass(frozen=True)
class SchedulerConfig:
    enabled: bool = False
    capture_max_sessions_per_round: int = 3
    llm_max_concurrency: int = 2
    planner_max_concurrency: int = 2
    polish_max_concurrency: int = 2
    send_max_replies_per_round: int = 1
    same_session_single_inflight: bool = True
    stale_reply_policy: str = "discard_and_requeue"
    pending_session_ttl_seconds: int = DEFAULT_PENDING_SESSION_TTL_SECONDS
    reply_ready_ttl_seconds: int = DEFAULT_READY_REPLY_TTL_SECONDS
    max_pending_sessions: int = 30
    max_pending_messages_per_session: int = 80

    @classmethod
    def from_config(cls, config: dict[str, Any] | None) -> "SchedulerConfig":
        raw = (config or {}).get("concurrency_scheduler", {})
        if not isinstance(raw, dict):
            raw = {}

        def bounded_int(name: str, default: int, minimum: int = 1, maximum: int = 1000) -> int:
            try:
                value = int(raw.get(name, default) or default)
            except (TypeError, ValueError):
                value = default
            return max(minimum, min(maximum, value))

        legacy_llm_concurrency = bounded_int("llm_max_concurrency", 2, 1, 10)
        return cls(
            enabled=raw.get("enabled", False) is True,
            capture_max_sessions_per_round=bounded_int("capture_max_sessions_per_round", 3, 1, 20),
            llm_max_concurrency=legacy_llm_concurrency,
            planner_max_concurrency=bounded_int("planner_max_concurrency", legacy_llm_concurrency, 1, 12),
            polish_max_concurrency=bounded_int("polish_max_concurrency", legacy_llm_concurrency, 1, 12),
            send_max_replies_per_round=bounded_int("send_max_replies_per_round", 1, 1, 10),
            same_session_single_inflight=raw.get("same_session_single_inflight", True) is not False,
            stale_reply_policy=str(raw.get("stale_reply_policy") or "discard_and_requeue"),
            pending_session_ttl_seconds=bounded_int("pending_session_ttl_seconds", DEFAULT_PENDING_SESSION_TTL_SECONDS, 60, 86400),
            reply_ready_ttl_seconds=bounded_int("reply_ready_ttl_seconds", DEFAULT_READY_REPLY_TTL_SECONDS, 30, 86400),
            max_pending_sessions=bounded_int("max_pending_sessions", 30, 1, 1000),
            max_pending_messages_per_session=bounded_int("max_pending_messages_per_session", 80, 1, 1000),
        )


class SchedulerStateLock:
    """Small cross-process lock for scheduler state files."""

    def __init__(self, path: Path, timeout_seconds: float = 10.0, stale_seconds: float = 120.0) -> None:
        self.path = path
        self.timeout_seconds = max(0.1, float(timeout_seconds))
        self.stale_seconds = max(1.0, float(stale_seconds))
        self.fd: int | None = None

    def __enter__(self) -> "SchedulerStateLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.time() + self.timeout_seconds
        while True:
            self._remove_stale()
            try:
                self.fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                payload = f"pid={os.getpid()}\ncreated_at={utcnow_iso()}\n"
                os.write(self.fd, payload.encode("utf-8"))
                return self
            except FileExistsError:
                if time.time() >= deadline:
                    raise TimeoutError(f"Scheduler state is locked: {self.path}")
                time.sleep(0.05)

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass

    def _remove_stale(self) -> None:
        try:
            age = time.time() - self.path.stat().st_mtime
        except FileNotFoundError:
            return
        if age >= self.stale_seconds:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass


class SchedulerStateStore:
    """Read/update helper for multi-session scheduler state."""

    def __init__(self, *, tenant_id: str | None = None, path: Path | None = None) -> None:
        self.tenant_id = active_tenant_id(tenant_id)
        self.path = path or (
            tenant_runtime_root(self.tenant_id) / "state" / "customer_service_scheduler_state.json"
        )
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")

    def empty_state(self) -> dict[str, Any]:
        now = utcnow_iso()
        return {
            "version": STATE_VERSION,
            "tenant_id": self.tenant_id,
            "created_at": now,
            "updated_at": now,
            "sessions": {},
            "captures": {},
            "llm_tasks": {},
            "polish_tasks": {},
            "ready_replies": {},
            "send_sequence": 0,
            "events": [],
        }

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self.empty_state()
        try:
            state = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            state = self.empty_state()
            state["recovered_from_corrupt_state"] = True
            return state
        if not isinstance(state, dict):
            return self.empty_state()
        state.setdefault("version", STATE_VERSION)
        state.setdefault("tenant_id", self.tenant_id)
        state.setdefault("sessions", {})
        state.setdefault("captures", {})
        state.setdefault("llm_tasks", {})
        state.setdefault("polish_tasks", {})
        state.setdefault("ready_replies", {})
        state.setdefault("send_sequence", 0)
        state.setdefault("events", [])
        return state

    def save(self, state: dict[str, Any]) -> None:
        payload = copy.deepcopy(state)
        payload["updated_at"] = utcnow_iso()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, self.path)

    def update(self, mutator: Callable[[dict[str, Any]], Any]) -> Any:
        with SchedulerStateLock(self.lock_path):
            state = self.load()
            result = mutator(state)
            self.save(state)
            return result


def ensure_session(
    state: dict[str, Any],
    target_name: str,
    *,
    exact: bool = True,
    conversation_type: str = "unknown",
    now: str | None = None,
) -> dict[str, Any]:
    name = normalize_target_name(target_name)
    if not name:
        raise ValueError("target_name is required")
    sessions = state.setdefault("sessions", {})
    session = sessions.get(name)
    now = now or utcnow_iso()
    if not isinstance(session, dict):
        session = {
            "session_id": stable_id("session", name),
            "target_name": name,
            "exact": bool(exact),
            "conversation_type": conversation_type or "unknown",
            "status": "idle",
            "context_version": 0,
            "pending_message_count": 0,
            "pending_capture": False,
            "pending_since": "",
            "last_detected_at": "",
            "last_dispatched_at": "",
            "last_capture_at": "",
            "oldest_unreplied_at": "",
            "llm_inflight_task_id": "",
            "polish_inflight_task_id": "",
            "ready_reply_ids": [],
            "processed_message_ids": [],
            "processed_content_keys": [],
            "risk_state": {},
            "created_at": now,
            "updated_at": now,
        }
        sessions[name] = session
    session["target_name"] = name
    session["exact"] = bool(exact)
    if conversation_type:
        session["conversation_type"] = conversation_type
    session["updated_at"] = now
    return session


def append_event(state: dict[str, Any], event: str, **payload: Any) -> dict[str, Any]:
    item = {"event": event, "created_at": utcnow_iso(), **payload}
    events = state.setdefault("events", [])
    events.append(item)
    state["events"] = events[-MAX_STORED_EVENTS:]
    return item


def seconds_since(value: Any, *, now: str | None = None) -> float:
    ts = _iso_to_ts(value)
    if ts <= 0:
        return 0.0
    now_ts = _iso_to_ts(now) if now else time.time()
    if now_ts <= 0:
        now_ts = time.time()
    return max(0.0, now_ts - ts)


def cleanup_scheduler_state(
    state: dict[str, Any],
    *,
    config: SchedulerConfig | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """Lightly prune stale scheduler noise without deleting recent audit data.

    The hot path should not carry old reply ids inside session records forever:
    that makes each tick do extra stale bookkeeping and obscures live state.  We
    keep recent reply objects for audit/summary, but session ``ready_reply_ids``
    only tracks replies that can still affect sending.
    """

    cfg = config or SchedulerConfig()
    replies = state.setdefault("ready_replies", {})
    if not isinstance(replies, dict):
        state["ready_replies"] = {}
        replies = state["ready_replies"]
    active_statuses = {"ready", "sending"}
    for session in (state.get("sessions", {}) or {}).values():
        if not isinstance(session, dict):
            continue
        ids = [str(item) for item in (session.get("ready_reply_ids") or []) if str(item)]
        active_ids = [
            reply_id
            for reply_id in ids
            if isinstance(replies.get(reply_id), dict)
            and str(replies[reply_id].get("status") or "") in active_statuses
        ]
        if active_ids != ids:
            session["ready_reply_ids"] = active_ids[-20:]

    retention_seconds = max(
        DEFAULT_READY_REPLY_HISTORY_RETENTION_SECONDS,
        int(getattr(cfg, "reply_ready_ttl_seconds", DEFAULT_READY_REPLY_TTL_SECONDS) or DEFAULT_READY_REPLY_TTL_SECONDS),
    )
    removable_statuses = {"sent", "stale", "send_failed"}
    removable: list[tuple[float, str]] = []
    for reply_id, reply in list(replies.items()):
        if not isinstance(reply, dict):
            removable.append((0.0, reply_id))
            continue
        status = str(reply.get("status") or "")
        if status not in removable_statuses:
            continue
        stamp = reply.get("sent_at") or reply.get("stale_at") or reply.get("ready_at")
        age = seconds_since(stamp, now=now)
        if age >= retention_seconds:
            removable.append((age, reply_id))

    # Keep storage bounded even on very long-running nodes, but never prune
    # active ready/sending replies.
    historical = [
        (
            _iso_to_ts(reply.get("sent_at") or reply.get("stale_at") or reply.get("ready_at")),
            reply_id,
        )
        for reply_id, reply in replies.items()
        if isinstance(reply, dict) and str(reply.get("status") or "") in removable_statuses
    ]
    overflow_count = max(0, len(replies) - DEFAULT_MAX_STORED_READY_REPLIES)
    if overflow_count > 0:
        for _, reply_id in sorted(historical)[:overflow_count]:
            removable.append((retention_seconds, reply_id))

    removed_ids: list[str] = []
    for _, reply_id in removable:
        if reply_id in replies:
            replies.pop(reply_id, None)
            removed_ids.append(reply_id)
    if removed_ids:
        append_event(
            state,
            "scheduler_state_cleanup",
            removed_ready_reply_count=len(removed_ids),
            removed_ready_reply_ids=removed_ids[:20],
        )
    return {
        "removed_ready_reply_count": len(removed_ids),
        "session_ready_reply_refs_cleaned": True,
    }


def has_active_session_work(state: dict[str, Any], target_name: str) -> bool:
    """Return True when a target already has unsent/in-flight scheduler work."""

    name = normalize_target_name(target_name)
    if not name:
        return False
    session = (state.get("sessions", {}) or {}).get(name)
    if isinstance(session, dict):
        inflight = str(session.get("llm_inflight_task_id") or "")
        if inflight:
            task = (state.get("llm_tasks", {}) or {}).get(inflight)
            if isinstance(task, dict) and task.get("status") in {"queued", "running"}:
                return True
        polish_inflight = str(session.get("polish_inflight_task_id") or "")
        if polish_inflight:
            task = (state.get("polish_tasks", {}) or {}).get(polish_inflight)
            if isinstance(task, dict) and task.get("status") in {"queued", "running"}:
                return True
        if str(session.get("status") or "") in {"capturing", "sending"}:
            return True
    for task in (state.get("llm_tasks", {}) or {}).values():
        if (
            isinstance(task, dict)
            and str(task.get("target_name") or "") == name
            and task.get("status") in {"queued", "running"}
        ):
            return True
    for task in (state.get("polish_tasks", {}) or {}).values():
        if (
            isinstance(task, dict)
            and str(task.get("target_name") or "") == name
            and task.get("status") in {"queued", "running"}
        ):
            return True
    for reply in (state.get("ready_replies", {}) or {}).values():
        if (
            isinstance(reply, dict)
            and str(reply.get("target_name") or "") == name
            and reply.get("status") in {"ready", "sending"}
        ):
            return True
    return False


def active_input_identity_sets(state: dict[str, Any], target_name: str) -> tuple[set[str], set[str]]:
    """Message ids/content keys already owned by in-flight tasks or ready replies."""

    name = normalize_target_name(target_name)
    ids: set[str] = set()
    keys: set[str] = set()
    if not name:
        return ids, keys
    for task in (state.get("llm_tasks", {}) or {}).values():
        if (
            isinstance(task, dict)
            and str(task.get("target_name") or "") == name
            and task.get("status") in {"queued", "running"}
        ):
            ids.update(str(item) for item in task.get("input_message_ids", []) if str(item))
            keys.update(str(item) for item in task.get("input_content_keys", []) if str(item))
    for task in (state.get("polish_tasks", {}) or {}).values():
        if (
            isinstance(task, dict)
            and str(task.get("target_name") or "") == name
            and task.get("status") in {"queued", "running"}
        ):
            ids.update(str(item) for item in task.get("input_message_ids", []) if str(item))
            keys.update(str(item) for item in task.get("input_content_keys", []) if str(item))
    for reply in (state.get("ready_replies", {}) or {}).values():
        if (
            isinstance(reply, dict)
            and str(reply.get("target_name") or "") == name
            and reply.get("status") in {"ready", "sending"}
        ):
            ids.update(str(item) for item in reply.get("input_message_ids", []) if str(item))
            keys.update(str(item) for item in reply.get("input_content_keys", []) if str(item))
    return ids, keys


def enqueue_pending_session(
    state: dict[str, Any],
    target_name: str,
    *,
    exact: bool = True,
    conversation_type: str = "unknown",
    reason: str = "manual",
    now: str | None = None,
) -> dict[str, Any]:
    now = now or utcnow_iso()
    session = ensure_session(state, target_name, exact=exact, conversation_type=conversation_type, now=now)
    if not session.get("pending_capture"):
        session["pending_since"] = now
    session["pending_capture"] = True
    session["last_detected_at"] = now
    session["status"] = "capture_pending"
    session["priority_score"] = int(session.get("priority_score") or 50)
    trace = session.get("latency_trace") if isinstance(session.get("latency_trace"), dict) else {}
    trace = {
        **trace,
        "unread_detected_at": trace.get("unread_detected_at") or now,
        "pending_enqueued_at": now,
    }
    session["latency_trace"] = trace
    append_event(state, "scheduler_capture_enqueued", target_name=session["target_name"], reason=reason)
    return session


def record_session_signal(
    state: dict[str, Any],
    session_payload: dict[str, Any],
    *,
    whitelist: set[str] | None = None,
    blacklist: set[str] | None = None,
    now: str | None = None,
) -> dict[str, Any] | None:
    name = normalize_target_name(session_payload.get("name") or session_payload.get("title"))
    if not name:
        return None
    if whitelist and name not in whitelist:
        return None
    if blacklist and name in blacklist:
        return None
    now = now or utcnow_iso()
    content = str(session_payload.get("content") or "").strip()
    msg_time = str(session_payload.get("time") or "").strip()
    unread_badge = str(session_payload.get("unread_badge") or session_payload.get("unread") or "").strip()
    conversation_type = str(session_payload.get("conversation_type") or session_payload.get("type") or "unknown")
    session = ensure_session(state, name, conversation_type=conversation_type, now=now)
    risk_state = session.get("risk_state") if isinstance(session.get("risk_state"), dict) else {}
    retry_not_before = str((risk_state or {}).get("capture_retry_not_before") or "")
    if retry_not_before:
        now_ts = _iso_to_ts(now)
        retry_ts = _iso_to_ts(retry_not_before)
        if retry_ts > 0 and now_ts > 0 and now_ts < retry_ts:
            session["last_detected_at"] = now
            session["status"] = "capture_cooldown"
            return session
    previous_digest = str(session.get("last_content_digest") or "")
    previous_time = str(session.get("last_message_time") or "")
    previous_badge = str(session.get("last_unread_badge") or "")
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:32] if content else ""
    unread_detected = bool(session_payload.get("unread_detected") or session_payload.get("pending"))
    has_signal = bool(digest or msg_time or unread_badge or unread_detected)
    unread_only_signal = bool(unread_detected and not digest and not msg_time and not unread_badge)
    if unread_only_signal and has_active_session_work(state, name):
        session["last_detected_at"] = now
        return session
    changed = bool(
        (digest and digest != previous_digest)
        or (msg_time and msg_time != previous_time)
        or (unread_badge and unread_badge != previous_badge)
        or unread_detected
    )
    if changed or (has_signal and not previous_digest and not previous_time and not previous_badge):
        session["last_content_digest"] = digest
        session["last_message_time"] = msg_time
        session["last_unread_badge"] = unread_badge
        enqueue_pending_session(
            state,
            name,
            exact=bool(session_payload.get("exact", True)),
            conversation_type=conversation_type,
            reason="session_signal_changed",
            now=now,
        )
    elif session.get("pending_capture"):
        # No change does not imply handled. Pending survives until capture/send.
        session["status"] = "capture_pending"
        session["last_detected_at"] = now
    else:
        session["status"] = session.get("status") or "idle"
    return session


def select_capture_sessions(
    state: dict[str, Any],
    *,
    limit: int,
    blocked_names: set[str] | None = None,
) -> list[dict[str, Any]]:
    blocked_names = blocked_names or set()
    candidates = [
        session
        for session in (state.get("sessions", {}) or {}).values()
        if isinstance(session, dict)
        and session.get("pending_capture")
        and str(session.get("target_name") or "") not in blocked_names
        and str(session.get("status") or "") not in {"paused", "capturing", "sending"}
        and not has_active_session_work(state, str(session.get("target_name") or ""))
    ]

    def sort_key(session: dict[str, Any]) -> tuple[str, int, str]:
        oldest = str(session.get("oldest_unreplied_at") or session.get("pending_since") or session.get("last_detected_at") or "")
        pending_count = int(session.get("pending_message_count") or 0)
        last_capture = str(session.get("last_capture_at") or "")
        return (oldest, -pending_count, last_capture)

    ordered = sorted(candidates, key=sort_key)
    return [copy.deepcopy(item) for item in ordered[: max(1, int(limit or 1))]]


def mark_capture_started(state: dict[str, Any], target_name: str, *, now: str | None = None) -> dict[str, Any]:
    now = now or utcnow_iso()
    session = ensure_session(state, target_name, now=now)
    session["status"] = "capturing"
    session["last_dispatched_at"] = now
    trace = session.get("latency_trace") if isinstance(session.get("latency_trace"), dict) else {}
    trace = {**trace, "capture_started_at": now}
    session["latency_trace"] = trace
    risk_state = session.get("risk_state") if isinstance(session.get("risk_state"), dict) else {}
    if risk_state:
        risk_state.pop("capture_retry_not_before", None)
    append_event(state, "scheduler_capture_started", target_name=session["target_name"])
    return session


def record_capture_result(
    state: dict[str, Any],
    target_name: str,
    *,
    messages: list[dict[str, Any]],
    batch: list[dict[str, Any]] | None = None,
    overflow_messages: list[dict[str, Any]] | None = None,
    history_backfill: dict[str, Any] | None = None,
    exact: bool = True,
    conversation_type: str = "unknown",
    now: str | None = None,
) -> dict[str, Any]:
    now = now or utcnow_iso()
    session = ensure_session(state, target_name, exact=exact, conversation_type=conversation_type, now=now)
    risk_state = session.get("risk_state") if isinstance(session.get("risk_state"), dict) else {}
    batch = list(batch if batch is not None else messages)
    overflow_messages = list(overflow_messages or [])
    existing_ids = set(session.get("processed_message_ids", []) or [])
    existing_keys = set(session.get("processed_content_keys", []) or [])
    active_ids, active_keys = active_input_identity_sets(state, session["target_name"])
    existing_ids.update(active_ids)
    existing_keys.update(active_keys)
    new_messages = [
        item
        for item in batch
        if message_identity(item)
        and message_identity(item) not in existing_ids
        and (not message_content_key(item) or message_content_key(item) not in existing_keys)
    ]
    if new_messages:
        session["context_version"] = int(session.get("context_version") or 0) + 1
        session["pending_message_count"] = len(new_messages) + len(overflow_messages)
        session["oldest_unreplied_at"] = str(new_messages[0].get("time") or now)
        session["status"] = "captured"
        session["pending_capture"] = False
        if risk_state:
            risk_state.pop("capture_fail_count", None)
            risk_state.pop("capture_retry_not_before", None)
            risk_state.pop("last_capture_failed_at", None)
    else:
        session["pending_message_count"] = 0
        session["pending_capture"] = False
        session["status"] = "idle"
    session["last_capture_at"] = now
    capture_id = stable_id("capture", target_name, session.get("context_version"), [message_identity(item) for item in batch], now)
    capture = {
        "capture_id": capture_id,
        "target_name": session["target_name"],
        "exact": bool(exact),
        "conversation_type": conversation_type,
        "context_version": int(session.get("context_version") or 0),
        "captured_at": now,
        "message_ids": [message_identity(item) for item in batch if message_identity(item)],
        "content_keys": [message_content_key(item) for item in batch if message_content_key(item)],
        "messages": copy.deepcopy(messages),
        "batch": copy.deepcopy(batch),
        "overflow_messages": copy.deepcopy(overflow_messages),
        "history_backfill": history_backfill or {},
        "status": "captured" if new_messages else "empty",
        "latency_trace": {
            **(session.get("latency_trace") if isinstance(session.get("latency_trace"), dict) else {}),
            "capture_finished_at": now,
        },
    }
    state.setdefault("captures", {})[capture_id] = capture
    append_event(
        state,
        "scheduler_capture_completed",
        target_name=session["target_name"],
        capture_id=capture_id,
        context_version=capture["context_version"],
        message_count=len(batch),
    )
    return capture


def enqueue_llm_task(
    state: dict[str, Any],
    capture_id: str,
    *,
    timeout_seconds: int = 30,
    now: str | None = None,
) -> dict[str, Any]:
    now = now or utcnow_iso()
    capture = state.setdefault("captures", {}).get(capture_id)
    if not isinstance(capture, dict):
        raise KeyError(f"capture not found: {capture_id}")
    target_name = str(capture.get("target_name") or "")
    session = ensure_session(state, target_name, exact=bool(capture.get("exact", True)), conversation_type=str(capture.get("conversation_type") or "unknown"), now=now)
    inflight = str(session.get("llm_inflight_task_id") or "")
    if inflight:
        task = state.setdefault("llm_tasks", {}).get(inflight)
        if isinstance(task, dict) and task.get("status") in {"queued", "running"}:
            return task
    task_id = stable_id("llm_task", target_name, capture_id, capture.get("context_version"), now)
    task = {
        "task_id": task_id,
        "target_name": target_name,
        "input_context_version": int(capture.get("context_version") or 0),
        "capture_ids": [capture_id],
        "input_message_ids": list(capture.get("message_ids") or []),
        "input_content_keys": list(capture.get("content_keys") or []),
        "status": "queued",
        "created_at": now,
        "started_at": "",
        "finished_at": "",
        "timeout_seconds": max(1, int(timeout_seconds or 30)),
        "attempt": 1,
        "result": None,
        "error": None,
        "latency_trace": {
            **(capture.get("latency_trace") if isinstance(capture.get("latency_trace"), dict) else {}),
            "brain_queued_at": now,
        },
    }
    state.setdefault("llm_tasks", {})[task_id] = task
    session["llm_inflight_task_id"] = task_id
    session["status"] = "llm_queued"
    append_event(state, "scheduler_llm_task_enqueued", target_name=target_name, task_id=task_id, context_version=task["input_context_version"])
    return task


def mark_llm_started(state: dict[str, Any], task_id: str, *, now: str | None = None) -> dict[str, Any]:
    now = now or utcnow_iso()
    task = state.setdefault("llm_tasks", {}).get(task_id)
    if not isinstance(task, dict):
        raise KeyError(f"llm task not found: {task_id}")
    task["status"] = "running"
    task["started_at"] = now
    trace = task.get("latency_trace") if isinstance(task.get("latency_trace"), dict) else {}
    task["latency_trace"] = {**trace, "brain_started_at": now}
    session = ensure_session(state, str(task.get("target_name") or ""), now=now)
    session["status"] = "llm_running"
    session["llm_inflight_task_id"] = task_id
    append_event(state, "scheduler_llm_task_started", target_name=session["target_name"], task_id=task_id)
    return task


def recover_orphaned_running_llm_tasks(
    state: dict[str, Any],
    *,
    active_task_ids: set[str],
    now: str | None = None,
) -> list[dict[str, Any]]:
    """Requeue running LLM tasks whose in-memory future was lost.

    The scheduler state is durable, but Python futures live only inside the
    current listener process. If the listener restarts while an LLM task is
    marked running, the persisted task would otherwise block that session
    forever. Requeueing is safe because RPA send still goes through freshness
    and context-version checks.
    """
    now = now or utcnow_iso()
    recovered: list[dict[str, Any]] = []
    for task_id, task in list((state.get("llm_tasks", {}) or {}).items()):
        if not isinstance(task, dict):
            continue
        normalized_task_id = str(task.get("task_id") or task_id)
        if task.get("status") != "running" or normalized_task_id in active_task_ids:
            continue
        task["status"] = "queued"
        task["requeued_at"] = now
        task["orphan_recovery_count"] = int(task.get("orphan_recovery_count") or 0) + 1
        target_name = str(task.get("target_name") or "")
        session = ensure_session(state, target_name, now=now)
        session["status"] = "llm_queued"
        session["llm_inflight_task_id"] = normalized_task_id
        append_event(
            state,
            "scheduler_llm_task_orphan_requeued",
            target_name=session["target_name"],
            task_id=normalized_task_id,
            orphan_recovery_count=task["orphan_recovery_count"],
        )
        recovered.append(copy.deepcopy(task))
    return recovered


def complete_llm_task(
    state: dict[str, Any],
    task_id: str,
    *,
    reply_text: str,
    decision: dict[str, Any] | None = None,
    result_payload: dict[str, Any] | None = None,
    create_ready_reply: bool = True,
    now: str | None = None,
) -> dict[str, Any]:
    now = now or utcnow_iso()
    task = state.setdefault("llm_tasks", {}).get(task_id)
    if not isinstance(task, dict):
        raise KeyError(f"llm task not found: {task_id}")
    target_name = str(task.get("target_name") or "")
    session = ensure_session(state, target_name, now=now)
    input_version = int(task.get("input_context_version") or 0)
    current_version = int(session.get("context_version") or 0)
    task["finished_at"] = now
    trace = task.get("latency_trace") if isinstance(task.get("latency_trace"), dict) else {}
    payload = copy.deepcopy(result_payload if isinstance(result_payload, dict) else {})
    result_trace = payload.get("latency_trace") if isinstance(payload.get("latency_trace"), dict) else {}
    task["latency_trace"] = {**trace, **result_trace, "brain_finished_at": now}
    payload["reply_text"] = reply_text
    payload["decision"] = decision or {}
    task["result"] = payload
    if input_version < current_version:
        task["status"] = "stale"
        if session.get("llm_inflight_task_id") == task_id:
            session["llm_inflight_task_id"] = ""
        append_event(state, "scheduler_llm_task_stale", target_name=target_name, task_id=task_id, input_context_version=input_version, current_context_version=current_version)
        return {"status": "stale", "task": task}

    task["status"] = "completed"
    if session.get("llm_inflight_task_id") == task_id:
        session["llm_inflight_task_id"] = ""
    if not create_ready_reply:
        session["status"] = "planner_done_waiting_polish"
        append_event(state, "scheduler_llm_task_completed", target_name=target_name, task_id=task_id, ready_reply_created=False)
        return {"status": "completed", "task": task, "reply": None}
    reply = enqueue_ready_reply(state, task_id, reply_text=reply_text, decision=decision or {}, now=now)
    append_event(state, "scheduler_llm_task_completed", target_name=target_name, task_id=task_id, reply_id=reply["reply_id"], ready_reply_created=True)
    return {"status": "completed", "task": task, "reply": reply}


def fail_llm_task(state: dict[str, Any], task_id: str, *, reason: str, now: str | None = None) -> dict[str, Any]:
    now = now or utcnow_iso()
    task = state.setdefault("llm_tasks", {}).get(task_id)
    if not isinstance(task, dict):
        raise KeyError(f"llm task not found: {task_id}")
    task["status"] = "failed"
    task["finished_at"] = now
    task["error"] = reason
    session = ensure_session(state, str(task.get("target_name") or ""), now=now)
    if session.get("llm_inflight_task_id") == task_id:
        session["llm_inflight_task_id"] = ""
    session["status"] = "failed"
    append_event(state, "scheduler_llm_task_failed", target_name=session["target_name"], task_id=task_id, reason=reason)
    return task


def enqueue_polish_task(
    state: dict[str, Any],
    planner_task_id: str,
    *,
    timeout_seconds: int = 15,
    now: str | None = None,
) -> dict[str, Any]:
    now = now or utcnow_iso()
    planner_task = state.setdefault("llm_tasks", {}).get(planner_task_id)
    if not isinstance(planner_task, dict):
        raise KeyError(f"llm task not found: {planner_task_id}")
    target_name = str(planner_task.get("target_name") or "")
    session = ensure_session(state, target_name, now=now)
    inflight = str(session.get("polish_inflight_task_id") or "")
    if inflight:
        task = state.setdefault("polish_tasks", {}).get(inflight)
        if isinstance(task, dict) and task.get("status") in {"queued", "running"}:
            return task
    result = planner_task.get("result") if isinstance(planner_task.get("result"), dict) else {}
    reply_text = str(result.get("reply_text") or "").strip()
    if not reply_text:
        raise ValueError(f"planner task missing reply_text: {planner_task_id}")
    task_id = stable_id("polish_task", target_name, planner_task_id, planner_task.get("input_context_version"), now)
    task = {
        "task_id": task_id,
        "planner_task_id": planner_task_id,
        "target_name": target_name,
        "input_context_version": int(planner_task.get("input_context_version") or 0),
        "capture_ids": list(planner_task.get("capture_ids") or []),
        "input_message_ids": list(planner_task.get("input_message_ids") or []),
        "input_content_keys": list(planner_task.get("input_content_keys") or []),
        "reply_text": reply_text,
        "decision": copy.deepcopy(result.get("decision") if isinstance(result.get("decision"), dict) else {}),
        "event": copy.deepcopy(result.get("event") if isinstance(result.get("event"), dict) else {}),
        "status": "queued",
        "created_at": now,
        "started_at": "",
        "finished_at": "",
        "timeout_seconds": max(1, int(timeout_seconds or 15)),
        "attempt": 1,
        "result": None,
        "error": None,
        "latency_trace": {
            **(planner_task.get("latency_trace") if isinstance(planner_task.get("latency_trace"), dict) else {}),
            "final_polish_queued_at": now,
        },
    }
    state.setdefault("polish_tasks", {})[task_id] = task
    session["polish_inflight_task_id"] = task_id
    session["status"] = "polish_queued"
    append_event(
        state,
        "scheduler_polish_task_enqueued",
        target_name=target_name,
        task_id=task_id,
        planner_task_id=planner_task_id,
        context_version=task["input_context_version"],
    )
    return task


def mark_polish_started(state: dict[str, Any], task_id: str, *, now: str | None = None) -> dict[str, Any]:
    now = now or utcnow_iso()
    task = state.setdefault("polish_tasks", {}).get(task_id)
    if not isinstance(task, dict):
        raise KeyError(f"polish task not found: {task_id}")
    task["status"] = "running"
    task["started_at"] = now
    trace = task.get("latency_trace") if isinstance(task.get("latency_trace"), dict) else {}
    task["latency_trace"] = {**trace, "final_polish_started_at": now}
    session = ensure_session(state, str(task.get("target_name") or ""), now=now)
    session["status"] = "polish_running"
    session["polish_inflight_task_id"] = task_id
    append_event(state, "scheduler_polish_task_started", target_name=session["target_name"], task_id=task_id)
    return task


def recover_orphaned_running_polish_tasks(
    state: dict[str, Any],
    *,
    active_task_ids: set[str],
    now: str | None = None,
) -> list[dict[str, Any]]:
    now = now or utcnow_iso()
    recovered: list[dict[str, Any]] = []
    for task_id, task in list((state.get("polish_tasks", {}) or {}).items()):
        if not isinstance(task, dict):
            continue
        normalized_task_id = str(task.get("task_id") or task_id)
        if task.get("status") != "running" or normalized_task_id in active_task_ids:
            continue
        task["status"] = "queued"
        task["requeued_at"] = now
        task["orphan_recovery_count"] = int(task.get("orphan_recovery_count") or 0) + 1
        target_name = str(task.get("target_name") or "")
        session = ensure_session(state, target_name, now=now)
        session["status"] = "polish_queued"
        session["polish_inflight_task_id"] = normalized_task_id
        append_event(
            state,
            "scheduler_polish_task_orphan_requeued",
            target_name=session["target_name"],
            task_id=normalized_task_id,
            orphan_recovery_count=task["orphan_recovery_count"],
        )
        recovered.append(copy.deepcopy(task))
    return recovered


def complete_polish_task(
    state: dict[str, Any],
    task_id: str,
    *,
    reply_text: str,
    decision: dict[str, Any] | None = None,
    result_payload: dict[str, Any] | None = None,
    degraded: bool = False,
    now: str | None = None,
) -> dict[str, Any]:
    now = now or utcnow_iso()
    task = state.setdefault("polish_tasks", {}).get(task_id)
    if not isinstance(task, dict):
        raise KeyError(f"polish task not found: {task_id}")
    target_name = str(task.get("target_name") or "")
    session = ensure_session(state, target_name, now=now)
    input_version = int(task.get("input_context_version") or 0)
    current_version = int(session.get("context_version") or 0)
    task["finished_at"] = now
    trace = task.get("latency_trace") if isinstance(task.get("latency_trace"), dict) else {}
    payload = copy.deepcopy(result_payload if isinstance(result_payload, dict) else {})
    polish_duration = payload.get("duration_seconds")
    result_trace = payload.get("latency_trace") if isinstance(payload.get("latency_trace"), dict) else {}
    if polish_duration is not None:
        result_trace = {**result_trace, "final_polish_duration_seconds": polish_duration}
    task["latency_trace"] = {**trace, **result_trace, "final_polish_finished_at": now}
    task["result"] = {"reply_text": reply_text, "decision": decision or {}, "degraded": bool(degraded), "polish_result": payload}
    if input_version < current_version:
        task["status"] = "stale"
        if session.get("polish_inflight_task_id") == task_id:
            session["polish_inflight_task_id"] = ""
        append_event(
            state,
            "scheduler_polish_task_stale",
            target_name=target_name,
            task_id=task_id,
            input_context_version=input_version,
            current_context_version=current_version,
        )
        return {"status": "stale", "task": task}

    task["status"] = "degraded" if degraded else "completed"
    if session.get("polish_inflight_task_id") == task_id:
        session["polish_inflight_task_id"] = ""
    reply = _enqueue_ready_reply_from_payload(
        state,
        source_task_id=task_id,
        source_task_kind="polish",
        target_name=target_name,
        input_context_version=input_version,
        capture_ids=list(task.get("capture_ids") or []),
        input_message_ids=list(task.get("input_message_ids") or []),
        input_content_keys=list(task.get("input_content_keys") or []),
        reply_text=reply_text,
        decision=decision or {},
        now=now,
    )
    append_event(
        state,
        "scheduler_polish_task_completed",
        target_name=target_name,
        task_id=task_id,
        reply_id=reply["reply_id"],
        degraded=bool(degraded),
    )
    return {"status": "completed", "task": task, "reply": reply}


def fail_polish_task(state: dict[str, Any], task_id: str, *, reason: str, now: str | None = None) -> dict[str, Any]:
    now = now or utcnow_iso()
    task = state.setdefault("polish_tasks", {}).get(task_id)
    if not isinstance(task, dict):
        raise KeyError(f"polish task not found: {task_id}")
    task["status"] = "failed"
    task["finished_at"] = now
    task["error"] = reason
    session = ensure_session(state, str(task.get("target_name") or ""), now=now)
    if session.get("polish_inflight_task_id") == task_id:
        session["polish_inflight_task_id"] = ""
    session["status"] = "failed"
    append_event(state, "scheduler_polish_task_failed", target_name=session["target_name"], task_id=task_id, reason=reason)
    return task


def _enqueue_ready_reply_from_payload(
    state: dict[str, Any],
    *,
    source_task_id: str,
    source_task_kind: str,
    target_name: str,
    input_context_version: int,
    capture_ids: list[str],
    input_message_ids: list[str],
    input_content_keys: list[str],
    reply_text: str,
    decision: dict[str, Any] | None,
    now: str | None = None,
) -> dict[str, Any]:
    now = now or utcnow_iso()
    sequence = int(state.get("send_sequence") or 0) + 1
    state["send_sequence"] = sequence
    reply_id = stable_id("reply", target_name, source_task_id, sequence)
    reply = {
        "reply_id": reply_id,
        "task_id": source_task_id,
        "task_kind": source_task_kind,
        "target_name": target_name,
        "input_context_version": int(input_context_version or 0),
        "capture_ids": list(capture_ids or []),
        "input_message_ids": list(input_message_ids or []),
        "input_content_keys": list(input_content_keys or []),
        "reply_text": reply_text,
        "decision": decision or {},
        "status": "ready",
        "ready_at": now,
        "send_attempts": 0,
        "last_send_error": "",
        "freshness_check": None,
        "priority": {"ready_sequence": sequence},
        "latency_trace": {
            **(
                (
                    state.get("polish_tasks", {}).get(source_task_id, {})
                    if source_task_kind == "polish"
                    else state.get("llm_tasks", {}).get(source_task_id, {})
                ).get("latency_trace", {})
                if isinstance(
                    state.get("polish_tasks", {}).get(source_task_id, {})
                    if source_task_kind == "polish"
                    else state.get("llm_tasks", {}).get(source_task_id, {}),
                    dict,
                )
                else {}
            ),
            "ready_at": now,
        },
    }
    state.setdefault("ready_replies", {})[reply_id] = reply
    session = ensure_session(state, target_name, now=now)
    ids = list(session.get("ready_reply_ids") or [])
    if reply_id not in ids:
        ids.append(reply_id)
    session["ready_reply_ids"] = ids[-20:]
    session["status"] = "reply_ready"
    append_event(
        state,
        "scheduler_reply_ready",
        target_name=target_name,
        task_id=source_task_id,
        task_kind=source_task_kind,
        reply_id=reply_id,
        context_version=reply["input_context_version"],
    )
    return reply


def enqueue_ready_reply(
    state: dict[str, Any],
    task_id: str,
    *,
    reply_text: str,
    decision: dict[str, Any] | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    now = now or utcnow_iso()
    task = state.setdefault("llm_tasks", {}).get(task_id)
    if not isinstance(task, dict):
        raise KeyError(f"llm task not found: {task_id}")
    return _enqueue_ready_reply_from_payload(
        state,
        source_task_id=task_id,
        source_task_kind="planner",
        target_name=str(task.get("target_name") or ""),
        input_context_version=int(task.get("input_context_version") or 0),
        capture_ids=list(task.get("capture_ids") or []),
        input_message_ids=list(task.get("input_message_ids") or []),
        input_content_keys=list(task.get("input_content_keys") or []),
        reply_text=reply_text,
        decision=decision or {},
        now=now,
    )


def select_ready_replies(state: dict[str, Any], *, limit: int) -> list[dict[str, Any]]:
    replies = [
        reply
        for reply in (state.get("ready_replies", {}) or {}).values()
        if isinstance(reply, dict) and reply.get("status") == "ready"
    ]
    replies.sort(key=lambda item: (str(item.get("ready_at") or ""), int((item.get("priority") or {}).get("ready_sequence") or 0)))
    selected: list[dict[str, Any]] = []
    seen_targets: set[str] = set()
    for reply in replies:
        target = str(reply.get("target_name") or "")
        session = (state.get("sessions", {}) or {}).get(target, {})
        if int(reply.get("input_context_version") or 0) < int((session or {}).get("context_version") or 0):
            mark_reply_stale(state, str(reply.get("reply_id") or ""), reason="context_version_advanced_before_send")
            continue
        if target in seen_targets:
            continue
        selected.append(copy.deepcopy(reply))
        seen_targets.add(target)
        if len(selected) >= max(1, int(limit or 1)):
            break
    return selected


def mark_reply_sending(state: dict[str, Any], reply_id: str, *, now: str | None = None) -> dict[str, Any]:
    now = now or utcnow_iso()
    reply = state.setdefault("ready_replies", {}).get(reply_id)
    if not isinstance(reply, dict):
        raise KeyError(f"reply not found: {reply_id}")
    reply["status"] = "sending"
    reply["send_started_at"] = now
    trace = reply.get("latency_trace") if isinstance(reply.get("latency_trace"), dict) else {}
    reply["latency_trace"] = {**trace, "send_started_at": now}
    reply["send_attempts"] = int(reply.get("send_attempts") or 0) + 1
    session = ensure_session(state, str(reply.get("target_name") or ""), now=now)
    session["status"] = "sending"
    append_event(state, "scheduler_send_started", target_name=session["target_name"], reply_id=reply_id)
    return reply


def mark_reply_sent(state: dict[str, Any], reply_id: str, *, send_result: dict[str, Any] | None = None, now: str | None = None) -> dict[str, Any]:
    now = now or utcnow_iso()
    reply = state.setdefault("ready_replies", {}).get(reply_id)
    if not isinstance(reply, dict):
        raise KeyError(f"reply not found: {reply_id}")
    reply["status"] = "sent"
    reply["sent_at"] = now
    trace = reply.get("latency_trace") if isinstance(reply.get("latency_trace"), dict) else {}
    reply["latency_trace"] = {**trace, "send_finished_at": now}
    reply["send_result"] = send_result or {}
    target_name = str(reply.get("target_name") or "")
    session = ensure_session(state, target_name, now=now)
    pending_after_send = bool(session.get("pending_capture"))
    if pending_after_send:
        # Preserve queued follow-up signals that arrived while this reply was in flight.
        session["status"] = "capture_pending"
        session["pending_capture"] = True
        session["pending_message_count"] = max(1, int(session.get("pending_message_count") or 0))
        if not str(session.get("pending_since") or ""):
            session["pending_since"] = now
        if not str(session.get("last_detected_at") or ""):
            session["last_detected_at"] = now
        if not str(session.get("oldest_unreplied_at") or ""):
            session["oldest_unreplied_at"] = now
    else:
        session["status"] = "sent"
        session["pending_capture"] = False
        session["pending_message_count"] = 0
        session["oldest_unreplied_at"] = ""
    processed = list(session.get("processed_message_ids") or [])
    for message_id in reply.get("input_message_ids") or []:
        if message_id and message_id not in processed:
            processed.append(message_id)
    session["processed_message_ids"] = processed[-500:]
    processed_keys = list(session.get("processed_content_keys") or [])
    for content_key in reply.get("input_content_keys") or []:
        if content_key and content_key not in processed_keys:
            processed_keys.append(content_key)
    session["processed_content_keys"] = processed_keys[-500:]
    append_event(
        state,
        "scheduler_send_completed",
        target_name=target_name,
        reply_id=reply_id,
        pending_capture_after_send=pending_after_send,
    )
    return reply


def mark_reply_stale(state: dict[str, Any], reply_id: str, *, reason: str, now: str | None = None) -> dict[str, Any]:
    now = now or utcnow_iso()
    reply = state.setdefault("ready_replies", {}).get(reply_id)
    if not isinstance(reply, dict):
        raise KeyError(f"reply not found: {reply_id}")
    reply["status"] = "stale"
    reply["stale_at"] = now
    trace = reply.get("latency_trace") if isinstance(reply.get("latency_trace"), dict) else {}
    reply["latency_trace"] = {**trace, "stale_at": now}
    reply["stale_reason"] = reason
    session = ensure_session(state, str(reply.get("target_name") or ""), now=now)
    session["status"] = "captured" if session.get("pending_message_count") else "idle"
    append_event(state, "scheduler_send_freshness_stale", target_name=session["target_name"], reply_id=reply_id, reason=reason)
    return reply


def mark_reply_failed(state: dict[str, Any], reply_id: str, *, reason: str, send_result: dict[str, Any] | None = None, now: str | None = None) -> dict[str, Any]:
    now = now or utcnow_iso()
    reply = state.setdefault("ready_replies", {}).get(reply_id)
    if not isinstance(reply, dict):
        raise KeyError(f"reply not found: {reply_id}")
    reply["status"] = "send_failed"
    reply["last_send_error"] = reason
    reply["send_result"] = send_result or {}
    session = ensure_session(state, str(reply.get("target_name") or ""), now=now)
    session["status"] = "failed"
    append_event(state, "scheduler_send_failed", target_name=session["target_name"], reply_id=reply_id, reason=reason)
    return reply


def state_summary(state: dict[str, Any]) -> dict[str, Any]:
    sessions = [item for item in (state.get("sessions", {}) or {}).values() if isinstance(item, dict)]
    planner_tasks = [item for item in (state.get("llm_tasks", {}) or {}).values() if isinstance(item, dict)]
    polish_tasks = [item for item in (state.get("polish_tasks", {}) or {}).values() if isinstance(item, dict)]
    replies = [item for item in (state.get("ready_replies", {}) or {}).values() if isinstance(item, dict)]
    planner_queued = sum(1 for item in planner_tasks if item.get("status") == "queued")
    planner_running = sum(1 for item in planner_tasks if item.get("status") == "running")
    polish_queued = sum(1 for item in polish_tasks if item.get("status") == "queued")
    polish_running = sum(1 for item in polish_tasks if item.get("status") == "running")
    pending_ages = [
        seconds_since(item.get("pending_since") or item.get("last_detected_at"))
        for item in sessions
        if item.get("pending_capture")
    ]
    ready_ages = [
        seconds_since(item.get("ready_at"))
        for item in replies
        if item.get("status") == "ready"
    ]
    active_lock_reason = ""
    if planner_running or polish_running:
        active_lock_reason = "llm_or_polish_running"
    elif any(item.get("status") == "sending" for item in replies):
        active_lock_reason = "reply_sending"
    elif any(item.get("status") == "capturing" for item in sessions):
        active_lock_reason = "capture_running"
    return {
        "sessions": len(sessions),
        "pending_sessions": sum(1 for item in sessions if item.get("pending_capture")),
        "planner_queued": planner_queued,
        "planner_running": planner_running,
        "polish_queued": polish_queued,
        "polish_running": polish_running,
        "llm_queued": planner_queued + polish_queued,
        "llm_running": planner_running + polish_running,
        "reply_ready": sum(1 for item in replies if item.get("status") == "ready"),
        "reply_stale": sum(1 for item in replies if item.get("status") == "stale"),
        "reply_sent": sum(1 for item in replies if item.get("status") == "sent"),
        "reply_failed": sum(1 for item in replies if item.get("status") == "send_failed"),
        "pending_age_seconds_max": round(max(pending_ages), 3) if pending_ages else 0.0,
        "oldest_ready_age_seconds": round(max(ready_ages), 3) if ready_ages else 0.0,
        "active_lock_reason": active_lock_reason,
    }
