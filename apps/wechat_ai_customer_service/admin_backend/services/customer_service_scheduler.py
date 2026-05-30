"""Runtime orchestration for multi-session customer-service scheduling.

This module intentionally keeps WeChat operations behind callbacks:

- capture_fn: the only place that should read WeChat via RPA.
- plan_reply_fn: LLM/rule/RAG planning; must not call RPA.
- freshness_fn/send_fn: the only place that should send via RPA.

The runtime can therefore be tested offline while preserving the production
invariant that WeChat foreground automation remains serial.
"""

from __future__ import annotations

import copy
import os
import time
import traceback
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

from apps.wechat_ai_customer_service.admin_backend.services.customer_service_scheduler_state import (
    SchedulerConfig,
    SchedulerStateStore,
    complete_llm_task,
    enqueue_llm_task,
    enqueue_pending_session,
    fail_llm_task,
    mark_capture_started,
    mark_llm_started,
    mark_reply_failed,
    mark_reply_sending,
    mark_reply_sent,
    mark_reply_stale,
    recover_orphaned_running_llm_tasks,
    record_capture_result,
    record_session_signal,
    select_capture_sessions,
    select_ready_replies,
    state_summary,
)


CaptureFn = Callable[[dict[str, Any]], dict[str, Any]]
PlanReplyFn = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
FreshnessFn = Callable[[dict[str, Any]], dict[str, Any]]
SendFn = Callable[[dict[str, Any]], dict[str, Any]]
CaptureDoneFn = Callable[[dict[str, Any], dict[str, Any], dict[str, Any]], None]


def default_freshness_ok(reply: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, "stale": False, "reply_id": reply.get("reply_id")}


class CustomerServiceSchedulerRuntime:
    """Small persistent scheduler runtime with async LLM futures."""

    def __init__(
        self,
        *,
        store: SchedulerStateStore,
        config: SchedulerConfig,
        capture_fn: CaptureFn,
        plan_reply_fn: PlanReplyFn,
        freshness_fn: FreshnessFn | None = None,
        send_fn: SendFn | None = None,
        capture_done_fn: CaptureDoneFn | None = None,
    ) -> None:
        self.store = store
        self.config = config
        self.capture_fn = capture_fn
        self.plan_reply_fn = plan_reply_fn
        self.freshness_fn = freshness_fn or default_freshness_ok
        self.send_fn = send_fn
        self.capture_done_fn = capture_done_fn
        self._executor = ThreadPoolExecutor(max_workers=max(1, int(config.llm_max_concurrency)))
        self._futures: dict[str, Future[dict[str, Any]]] = {}

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=False)

    def tick(
        self,
        *,
        session_signals: list[dict[str, Any]] | None = None,
        allow_send: bool = False,
        now: str | None = None,
    ) -> dict[str, Any]:
        """Run one non-blocking scheduling tick."""
        started = time.time()
        state = self.store.load()
        events: list[dict[str, Any]] = []

        for signal in session_signals or []:
            session = record_session_signal(state, signal, now=now)
            if session and session.get("pending_capture"):
                events.append({"event": "signal_pending", "target_name": session.get("target_name")})

        recovered = recover_orphaned_running_llm_tasks(state, active_task_ids=set(self._futures), now=now)
        for task in recovered:
            events.append({"event": "llm_task_orphan_requeued", "task_id": task.get("task_id"), "target_name": task.get("target_name")})

        pre_sent = self._consume_send_queue(state, allow_send=allow_send, now=now)
        events.extend(pre_sent)

        captured = self._capture_pending(state, now=now)
        events.extend(captured)

        submitted = self._submit_llm_tasks(state, now=now)
        events.extend(submitted)

        completed = self._collect_llm_results(state, now=now)
        events.extend(completed)

        sent = self._consume_send_queue(state, allow_send=allow_send, now=now)
        events.extend(sent)

        self.store.save(state)
        summary = state_summary(state)
        return {
            "ok": True,
            "duration_seconds": round(time.time() - started, 4),
            "events": events,
            "summary": summary,
        }

    def _capture_pending(self, state: dict[str, Any], *, now: str | None = None) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        sessions = select_capture_sessions(state, limit=self.config.capture_max_sessions_per_round)
        for session in sessions:
            target_name = str(session.get("target_name") or "")
            mark_capture_started(state, target_name, now=now)
            try:
                result = self.capture_fn(copy.deepcopy(session))
            except Exception as exc:  # noqa: BLE001 - scheduler must keep other sessions moving
                mark_session_capture_failed(state, target_name, repr(exc), now=now)
                events.append({"event": "capture_failed", "target_name": target_name, "error": repr(exc)})
                continue
            if result.get("ok") is False and result.get("blocked"):
                mark_session_capture_failed(state, target_name, str(result.get("reason") or "capture_blocked"), now=now)
                events.append({"event": "capture_blocked", "target_name": target_name, "reason": result.get("reason")})
                continue
            messages = list(result.get("messages") or [])
            batch = list(result.get("batch") or messages)
            overflow = list(result.get("overflow_messages") or [])
            capture = record_capture_result(
                state,
                target_name,
                messages=messages,
                batch=batch,
                overflow_messages=overflow,
                history_backfill=result.get("history_backfill") if isinstance(result.get("history_backfill"), dict) else {},
                exact=bool(session.get("exact", True)),
                conversation_type=str(session.get("conversation_type") or "unknown"),
                now=now,
            )
            if self.capture_done_fn is not None:
                try:
                    self.capture_done_fn(copy.deepcopy(session), copy.deepcopy(result), copy.deepcopy(capture))
                except Exception as exc:  # noqa: BLE001
                    events.append({"event": "capture_done_callback_failed", "target_name": target_name, "error": repr(exc)})
            if capture.get("status") == "captured":
                task = enqueue_llm_task(state, str(capture.get("capture_id") or ""), now=now)
                events.append({"event": "capture_completed", "target_name": target_name, "capture_id": capture["capture_id"], "task_id": task["task_id"]})
            else:
                events.append({"event": "capture_empty", "target_name": target_name, "capture_id": capture["capture_id"]})
        return events

    def _submit_llm_tasks(self, state: dict[str, Any], *, now: str | None = None) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        running_count = sum(1 for future in self._futures.values() if not future.done())
        capacity = max(0, int(self.config.llm_max_concurrency) - running_count)
        if capacity <= 0:
            return events
        tasks = [
            task
            for task in (state.get("llm_tasks", {}) or {}).values()
            if isinstance(task, dict)
            and task.get("status") == "queued"
            and str(task.get("task_id") or "") not in self._futures
        ]
        tasks.sort(key=lambda item: str(item.get("created_at") or ""))
        captures = state.get("captures", {}) or {}
        for task in tasks[:capacity]:
            task_id = str(task.get("task_id") or "")
            capture_ids = [str(item) for item in task.get("capture_ids", []) if str(item)]
            capture = captures.get(capture_ids[-1] if capture_ids else "")
            if not isinstance(capture, dict):
                fail_llm_task(state, task_id, reason="capture_missing", now=now)
                events.append({"event": "llm_task_failed", "task_id": task_id, "reason": "capture_missing"})
                continue
            mark_llm_started(state, task_id, now=now)
            self._futures[task_id] = self._executor.submit(self.plan_reply_fn, copy.deepcopy(capture), copy.deepcopy(task))
            events.append({"event": "llm_task_submitted", "task_id": task_id, "target_name": task.get("target_name")})
        return events

    def _collect_llm_results(self, state: dict[str, Any], *, now: str | None = None) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for task_id, future in list(self._futures.items()):
            if not future.done():
                continue
            self._futures.pop(task_id, None)
            try:
                result = future.result()
            except Exception as exc:  # noqa: BLE001
                error = repr(exc)
                trace = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-4000:]
                task = fail_llm_task(state, task_id, reason=error, now=now)
                task["traceback"] = trace
                events.append({"event": "llm_task_failed", "task_id": task_id, "error": error, "traceback": trace})
                continue
            if result.get("ok") is False:
                fail_llm_task(state, task_id, reason=str(result.get("reason") or result.get("error") or "planner_failed"), now=now)
                events.append({"event": "llm_task_failed", "task_id": task_id, "reason": result.get("reason")})
                continue
            reply_text = str(result.get("reply_text") or "").strip()
            if not reply_text:
                fail_llm_task(state, task_id, reason="empty_reply_text", now=now)
                events.append({"event": "llm_task_failed", "task_id": task_id, "reason": "empty_reply_text"})
                continue
            completion = complete_llm_task(
                state,
                task_id,
                reply_text=reply_text,
                decision=result.get("decision") if isinstance(result.get("decision"), dict) else {},
                now=now,
            )
            events.append({"event": "llm_task_completed", "task_id": task_id, "status": completion.get("status")})
        return events

    def _consume_send_queue(self, state: dict[str, Any], *, allow_send: bool, now: str | None = None) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        if not allow_send or self.send_fn is None:
            return events
        replies = select_ready_replies(state, limit=self.config.send_max_replies_per_round)
        for reply in replies:
            reply_id = str(reply.get("reply_id") or "")
            mark_reply_sending(state, reply_id, now=now)
            callback_reply = self._reply_for_callbacks(state, reply)
            freshness = self.freshness_fn(copy.deepcopy(callback_reply))
            if freshness.get("stale") or freshness.get("has_newer_messages"):
                mark_reply_stale(state, reply_id, reason=str(freshness.get("reason") or "freshness_stale"), now=now)
                if self.config.stale_reply_policy == "discard_and_requeue":
                    enqueue_pending_session(
                        state,
                        str(reply.get("target_name") or ""),
                        exact=True,
                        conversation_type="unknown",
                        reason="reply_stale_before_send",
                        now=now,
                    )
                events.append({"event": "reply_stale", "reply_id": reply_id, "target_name": reply.get("target_name"), "freshness": freshness})
                continue
            try:
                send_result = self.send_fn(copy.deepcopy(callback_reply))
            except Exception as exc:  # noqa: BLE001
                mark_reply_failed(state, reply_id, reason=repr(exc), now=now)
                events.append({"event": "send_failed", "reply_id": reply_id, "error": repr(exc)})
                continue
            if send_result.get("ok") is False or send_result.get("verified") is False:
                mark_reply_failed(state, reply_id, reason=str(send_result.get("reason") or send_result.get("error") or "send_failed"), send_result=send_result, now=now)
                events.append({"event": "send_failed", "reply_id": reply_id, "send_result": send_result})
                continue
            mark_reply_sent(state, reply_id, send_result=send_result, now=now)
            events.append({"event": "send_completed", "reply_id": reply_id, "target_name": reply.get("target_name")})
        return events

    def _reply_for_callbacks(self, state: dict[str, Any], reply: dict[str, Any]) -> dict[str, Any]:
        enriched = copy.deepcopy(reply)
        capture_ids = [str(item) for item in enriched.get("capture_ids", []) if str(item)]
        if capture_ids:
            capture = (state.get("captures", {}) or {}).get(capture_ids[-1])
            if isinstance(capture, dict):
                enriched["_capture"] = copy.deepcopy(capture)
        return enriched


def mark_session_capture_failed(state: dict[str, Any], target_name: str, reason: str, *, now: str | None = None) -> None:
    from apps.wechat_ai_customer_service.admin_backend.services.customer_service_scheduler_state import append_event, ensure_session

    session = ensure_session(state, target_name, now=now)
    session["status"] = "capture_failed"
    session.setdefault("risk_state", {})["last_error"] = reason
    append_event(state, "scheduler_capture_failed", target_name=session["target_name"], reason=reason)


class CapturedMessagesConnector:
    """Connector facade for LLM planning from already-captured messages.

    It implements read-only message access so existing workflow planning can run
    without touching WeChat. Send methods intentionally fail closed.
    """

    def __init__(self, capture: dict[str, Any]) -> None:
        self.capture = copy.deepcopy(capture)
        self.send_attempts: list[dict[str, Any]] = []

    def get_messages(
        self,
        target: str,
        exact: bool = True,
        history_load_times: int = 0,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        messages = self.capture.get("messages") or []
        history_meta = self.capture.get("history_backfill") if isinstance(self.capture.get("history_backfill"), dict) else {}
        return {
            "ok": True,
            "target": target,
            "exact": exact,
            "messages": copy.deepcopy(messages),
            "_history_backfill": history_meta,
            "scheduler_capture_id": self.capture.get("capture_id"),
            "scheduler_context_version": self.capture.get("context_version"),
        }

    def send_text_and_verify(self, target: str, text: str, exact: bool = True) -> dict[str, Any]:
        self.send_attempts.append({"target": target, "text": text, "exact": exact})
        return {
            "ok": False,
            "verified": False,
            "state": "scheduler_planner_send_blocked",
            "error": "CapturedMessagesConnector is read-only; planner must not send via RPA.",
        }


def plan_reply_with_listen_workflow(
    capture: dict[str, Any],
    task: dict[str, Any],
    *,
    target_config: Any,
    config: dict[str, Any],
    rules: dict[str, Any],
    workflow_state: dict[str, Any],
    allow_fallback_send: bool = False,
) -> dict[str, Any]:
    """Reuse the existing reply planner without opening or sending WeChat."""

    import sys
    from pathlib import Path

    workflow_root = Path(__file__).resolve().parents[2] / "workflows"
    adapter_root = Path(__file__).resolve().parents[2] / "adapters"
    for path in (workflow_root, adapter_root):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    from apps.wechat_ai_customer_service.workflows.listen_and_reply import process_target
    from apps.wechat_ai_customer_service.workflows.listen_and_reply import (
        _apply_greeting,
        final_visible_polish_blocks_send,
        final_visible_polish_degraded,
        finalize_customer_visible_reply_with_llm,
        polish_customer_visible_reply_text,
        recent_customer_visible_reply_texts,
        sanitize_customer_visible_reply_text,
    )

    connector = CapturedMessagesConnector(capture)
    event = process_target(
        connector=connector,  # type: ignore[arg-type]
        target=target_config,
        config=config,
        rules=rules,
        state=workflow_state,
        send=False,
        write_data=False,
        allow_fallback_send=allow_fallback_send,
        mark_dry_run=False,
    )
    if connector.send_attempts:
        return {
            "ok": False,
            "reason": "planner_attempted_send",
            "send_attempts": connector.send_attempts,
            "event": event,
        }
    decision = event.get("decision") if isinstance(event.get("decision"), dict) else {}
    reply_text = str(decision.get("reply_text") or event.get("reply_text") or "").strip()
    combined = str(event.get("combined_content") or "")
    target_state = {}
    try:
        target_state = (workflow_state.get("targets", {}) or {}).get(str(target_config.name), {}) or {}
    except Exception:
        target_state = {}
    recent_reply_texts = recent_customer_visible_reply_texts(target_state)
    profile = {
        "target_name": str(target_config.name),
        "display_name": str(target_config.name),
        "basic_info": {},
        "tags": {},
        "conversation_summary": "",
        "greeting_preference": {},
    }
    if reply_text and event.get("action") not in {"blocked", "error"}:
        reply_text = _apply_greeting(
            reply_text,
            profile,
            config,
            target_state=target_state,
            combined=combined,
            recent_reply_texts=recent_reply_texts,
        )
        reply_text = sanitize_customer_visible_reply_text(
            reply_text,
            config=config,
            combined=combined,
            reason=str(event.get("reason") or decision.get("reason") or ""),
            force_handoff_style=False,
            recent_reply_texts=recent_reply_texts,
        )
        outbound_naturalness = polish_customer_visible_reply_text(
            reply_text,
            config=config,
            combined=combined,
            recent_reply_texts=recent_reply_texts,
        )
        event["outbound_naturalness"] = outbound_naturalness
        if outbound_naturalness.get("applied"):
            reply_text = str(outbound_naturalness.get("reply_text") or reply_text)
        final_polish = finalize_customer_visible_reply_with_llm(
            reply_text,
            config=config,
            combined=combined,
            recent_reply_texts=recent_reply_texts,
            source_channel=str(((event.get("reply_style_adapter") or {}) if isinstance(event.get("reply_style_adapter"), dict) else {}).get("source_channel") or "normal"),
            needs_handoff=False,
        )
        event["final_visible_llm_polish"] = final_polish
        if final_polish.get("passed"):
            reply_text = str(final_polish.get("reply_text") or reply_text)
        elif final_visible_polish_blocks_send(final_polish, config=config):
            return {"ok": False, "reason": "final_visible_llm_polish_failed", "event": event}
        elif final_visible_polish_degraded(final_polish, config=config):
            event["final_visible_llm_polish_degraded"] = True
        decision = {**decision, "reply_text": reply_text}
        event["decision"] = decision
    if event.get("action") in {"blocked", "error"}:
        return {"ok": False, "reason": str(event.get("reason") or event.get("action")), "event": event}
    if not reply_text:
        return {"ok": False, "reason": "empty_planned_reply", "event": event}
    return {
        "ok": True,
        "reply_text": reply_text,
        "decision": {
            **decision,
            "outbound_naturalness": event.get("outbound_naturalness"),
            "final_visible_llm_polish": event.get("final_visible_llm_polish"),
            "final_visible_llm_polish_degraded": event.get("final_visible_llm_polish_degraded", False),
        },
        "event": event,
        "task_id": task.get("task_id"),
        "capture_id": capture.get("capture_id"),
    }


class ManagedListenerSchedulerBridge:
    """Wire the persistent scheduler into the managed listener process.

    The bridge owns the real WeChat connector, so capture and send stay serial
    in the listener process. LLM planning receives only captured message
    snapshots through ``CapturedMessagesConnector``.
    """

    def __init__(
        self,
        *,
        tenant_id: str,
        config_path: Path,
        allow_send: bool,
        write_data: bool,
    ) -> None:
        self.tenant_id = str(tenant_id or "").strip()
        self.config_path = Path(config_path)
        self.allow_send = bool(allow_send)
        self.write_data = bool(write_data)
        self.config: dict[str, Any] = {}
        self.rules: dict[str, Any] = {}
        self.scheduler_config = SchedulerConfig()
        self.targets: list[Any] = []
        self.target_by_name: dict[str, Any] = {}
        self.respond_all_unread_sessions = False
        self.ignored_session_names: set[str] = set()
        self.use_multi_target = False
        self.state_path: Path | None = None
        self.audit_path: Path | None = None
        self.session_monitor: Any = None
        self.store = SchedulerStateStore(tenant_id=self.tenant_id)
        self.runtime: CustomerServiceSchedulerRuntime | None = None
        self.connector: Any = None
        self._workflow: dict[str, Any] = {}
        self._runtime_signature: tuple[Any, ...] | None = None
        self._load_workflow_symbols()
        self.reload()

    @property
    def enabled(self) -> bool:
        return bool(self.scheduler_config.enabled)

    def shutdown(self) -> None:
        if self.runtime is not None:
            self.runtime.shutdown()
            self.runtime = None

    def reload(self) -> None:
        wf = self._workflow
        with self._tenant_environment():
            config = wf["load_config"](self.config_path)
            config = wf["apply_local_customer_service_settings"](config)
        self.config = config
        self.scheduler_config = SchedulerConfig.from_config(config)
        session_routing = config.get("_local_customer_service_session_routing", {}) or {}
        if not isinstance(session_routing, dict):
            session_routing = {}
        self.respond_all_unread_sessions = bool(session_routing.get("respond_all_unread_sessions", False))
        self.ignored_session_names = {
            str(item).strip()
            for item in session_routing.get("ignored_names", []) or []
            if str(item).strip()
        }
        allow_empty_targets = bool(self.respond_all_unread_sessions or session_routing.get("managed", False))
        self.targets = wf["parse_targets"](config, allow_empty=allow_empty_targets)
        self.target_by_name = {str(target.name): target for target in self.targets}
        rules_path = config.get("rules_path")
        self.rules = wf["load_rules"](wf["resolve_path"](rules_path)) if rules_path else config
        self.state_path = wf["resolve_path"](config.get("state_path"))
        self.audit_path = wf["resolve_path"](config.get("audit_log_path"))
        multi_target_cfg = config.get("multi_target") if isinstance(config.get("multi_target"), dict) else {}
        self.use_multi_target = bool((multi_target_cfg or {}).get("enabled"))
        self._ensure_connector()
        self._ensure_session_monitor(multi_target_cfg or {})
        self._ensure_runtime()

    def tick(self, *, allow_send: bool | None = None, now: str | None = None) -> dict[str, Any]:
        self.reload()
        if not self.enabled:
            return {"ok": True, "scheduler_enabled": False, "events": [], "summary": {}}
        wf = self._workflow
        status: dict[str, Any]
        if wf["listener_skip_pre_status_check"]():
            status = {
                "ok": True,
                "online": True,
                "adapter": "win32_ocr",
                "state": "pre_status_check_skipped",
                "reason": "managed_scheduler_low_risk_mode",
            }
        else:
            status = self.connector.require_online()
        session_signals = self._collect_session_signals()
        runtime = self.runtime
        if runtime is None:
            raise RuntimeError("scheduler runtime is not initialized")
        result = runtime.tick(
            session_signals=session_signals,
            allow_send=self.allow_send if allow_send is None else bool(allow_send),
            now=now,
        )
        result.update(
            {
                "scheduler_enabled": True,
                "dry_run": not (self.allow_send if allow_send is None else bool(allow_send)),
                "status": status,
                "targets": [str(target.name) for target in self.targets],
                "active_session_signals": [str(item.get("name") or item.get("target_name") or "") for item in session_signals],
            }
        )
        return result

    def _load_workflow_symbols(self) -> None:
        import sys

        app_root = Path(__file__).resolve().parents[2]
        workflow_root = app_root / "workflows"
        adapter_root = app_root / "adapters"
        project_root = app_root.parents[1]
        for path in (project_root, app_root, workflow_root, adapter_root):
            if str(path) not in sys.path:
                sys.path.insert(0, str(path))

        from apps.wechat_ai_customer_service.adapters.wechat_connector import WeChatConnector
        from apps.wechat_ai_customer_service.admin_backend.services.session_monitor import SessionMonitor
        from apps.wechat_ai_customer_service.workflows.listen_and_reply import (
            StateLock,
            TargetConfig,
            append_audit,
            base_event,
            batch_selection_payload,
            build_reply_trace_id,
            default_max_batch_messages,
            detect_newer_messages_before_send,
            history_gap_risk_blocks_reply,
            listener_skip_pre_status_check,
            load_config,
            load_rules,
            load_state,
            mark_coalesced_messages,
            mark_processed,
            maybe_enrich_messages_with_history,
            parse_targets,
            record_reply_timestamp,
            resolve_path,
            save_state,
            select_batch_details,
            apply_local_customer_service_settings,
        )

        self._workflow = {
            "WeChatConnector": WeChatConnector,
            "SessionMonitor": SessionMonitor,
            "StateLock": StateLock,
            "TargetConfig": TargetConfig,
            "append_audit": append_audit,
            "base_event": base_event,
            "batch_selection_payload": batch_selection_payload,
            "build_reply_trace_id": build_reply_trace_id,
            "default_max_batch_messages": default_max_batch_messages,
            "detect_newer_messages_before_send": detect_newer_messages_before_send,
            "history_gap_risk_blocks_reply": history_gap_risk_blocks_reply,
            "listener_skip_pre_status_check": listener_skip_pre_status_check,
            "load_config": load_config,
            "load_rules": load_rules,
            "load_state": load_state,
            "mark_coalesced_messages": mark_coalesced_messages,
            "mark_processed": mark_processed,
            "maybe_enrich_messages_with_history": maybe_enrich_messages_with_history,
            "parse_targets": parse_targets,
            "record_reply_timestamp": record_reply_timestamp,
            "resolve_path": resolve_path,
            "save_state": save_state,
            "select_batch_details": select_batch_details,
            "apply_local_customer_service_settings": apply_local_customer_service_settings,
        }

    @contextmanager
    def _tenant_environment(self):
        previous = os.environ.get("WECHAT_KNOWLEDGE_TENANT")
        os.environ["WECHAT_KNOWLEDGE_TENANT"] = self.tenant_id
        try:
            yield
        finally:
            if previous is None:
                os.environ.pop("WECHAT_KNOWLEDGE_TENANT", None)
            else:
                os.environ["WECHAT_KNOWLEDGE_TENANT"] = previous

    def _ensure_connector(self) -> None:
        if self.connector is None:
            self.connector = self._workflow["WeChatConnector"]()

    def _ensure_session_monitor(self, multi_target_cfg: dict[str, Any]) -> None:
        if not self.use_multi_target:
            self.session_monitor = None
            return
        whitelist = set() if self.respond_all_unread_sessions else {str(target.name) for target in self.targets}
        max_targets = int(multi_target_cfg.get("max_targets_per_iteration", self.scheduler_config.max_pending_sessions) or self.scheduler_config.max_pending_sessions)
        min_switch = int(multi_target_cfg.get("min_switch_interval_seconds", 2) or 2)
        if self.session_monitor is None:
            self.session_monitor = self._workflow["SessionMonitor"](
                tenant_id=self.tenant_id,
                whitelist=whitelist,
                blacklist=self.ignored_session_names,
                max_targets_per_iteration=max(1, max_targets),
                min_switch_interval_seconds=max(1, min_switch),
            )
            return
        self.session_monitor.whitelist = whitelist
        self.session_monitor.blacklist = set(self.ignored_session_names)
        self.session_monitor.max_targets_per_iteration = max(1, max_targets)
        self.session_monitor.min_switch_interval_seconds = max(1, min_switch)

    def _ensure_runtime(self) -> None:
        signature = (
            self.scheduler_config.capture_max_sessions_per_round,
            self.scheduler_config.llm_max_concurrency,
            self.scheduler_config.send_max_replies_per_round,
            self.scheduler_config.stale_reply_policy,
        )
        if self.runtime is not None and self._runtime_signature == signature:
            return
        if self.runtime is not None:
            self.runtime.shutdown()
        self.runtime = CustomerServiceSchedulerRuntime(
            store=self.store,
            config=self.scheduler_config,
            capture_fn=self._capture_session,
            plan_reply_fn=self._plan_reply,
            freshness_fn=self._freshness_check,
            send_fn=self._send_reply,
            capture_done_fn=self._capture_done,
        )
        self._runtime_signature = signature

    def _collect_session_signals(self) -> list[dict[str, Any]]:
        if self.use_multi_target and self.session_monitor is not None:
            self.session_monitor.poll(self.connector)
            pending = self.session_monitor.pending_targets(limit=self.scheduler_config.max_pending_sessions)
            return [
                {
                    "name": item.name,
                    "exact": item.exact,
                    "unread_detected": item.unread_detected,
                    "conversation_type": item.conversation_type,
                }
                for item in pending
                if item.name not in self.ignored_session_names
            ]
        return [
            {
                "name": target.name,
                "exact": target.exact,
                "unread_detected": True,
                "conversation_type": "configured",
            }
            for target in self.targets
        ]

    def _target_for_name(self, name: str, *, exact: bool = True) -> Any:
        target = self.target_by_name.get(str(name))
        if target is not None:
            return target
        if not self.respond_all_unread_sessions:
            raise KeyError(f"target is not configured: {name}")
        default_batch = self._workflow["default_max_batch_messages"](self.config)
        return self._workflow["TargetConfig"](
            name=str(name),
            enabled=True,
            exact=bool(exact),
            allow_self_for_test=False,
            max_batch_messages=max(1, int(default_batch or 1)),
        )

    def _workflow_state_snapshot(self) -> dict[str, Any]:
        if self.state_path is None:
            return {"version": 1, "targets": {}}
        try:
            return self._workflow["load_state"](self.state_path)
        except Exception:
            return {"version": 1, "targets": {}}

    def _target_state(self, state: dict[str, Any], target_name: str) -> dict[str, Any]:
        return state.setdefault("targets", {}).setdefault(
            target_name,
            {
                "processed_message_ids": [],
                "processed_content_keys": [],
                "handoff_message_ids": [],
                "sent_replies": [],
                "reply_timestamps": [],
            },
        )

    def _capture_session(self, session: dict[str, Any]) -> dict[str, Any]:
        target = self._target_for_name(
            str(session.get("target_name") or session.get("name") or ""),
            exact=bool(session.get("exact", True)),
        )
        payload = self.connector.get_messages(target.name, exact=target.exact)
        if not payload.get("ok"):
            raise RuntimeError(f"get_messages failed for {target.name}: {payload}")
        workflow_state = self._workflow_state_snapshot()
        target_state = self._target_state(workflow_state, target.name)
        payload = self._workflow["maybe_enrich_messages_with_history"](
            connector=self.connector,
            target=target,
            config=self.config,
            payload=payload,
            target_state=target_state,
        )
        messages = list(payload.get("messages") or [])
        selection = self._workflow["select_batch_details"](
            messages,
            target_state=target_state,
            allow_self_for_test=target.allow_self_for_test,
            max_batch_messages=target.max_batch_messages,
            config=self.config,
        )
        history_meta = payload.get("_history_backfill", {}) if isinstance(payload.get("_history_backfill"), dict) else {}
        if self._workflow["history_gap_risk_blocks_reply"](history_meta, self.config) and selection.eligible_count > 0:
            return {
                "ok": False,
                "blocked": True,
                "reason": "history_backfill_gap_risk",
                "messages": messages,
                "batch": selection.batch,
                "overflow_messages": selection.overflow_messages,
                "history_backfill": history_meta,
            }
        return {
            "ok": True,
            "target_name": target.name,
            "exact": target.exact,
            "messages": messages,
            "batch": selection.batch,
            "overflow_messages": selection.overflow_messages,
            "history_backfill": history_meta,
            "batch_selection": self._workflow["batch_selection_payload"](selection),
        }

    def _capture_done(self, session: dict[str, Any], result: dict[str, Any], capture: dict[str, Any]) -> None:
        if self.session_monitor is None:
            return
        if result.get("ok") is False and result.get("blocked"):
            return
        target_name = str(capture.get("target_name") or session.get("target_name") or "")
        if target_name:
            self.session_monitor.reset_unread(target_name)

    def _plan_reply(self, capture: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
        target = self._target_for_name(str(capture.get("target_name") or ""), exact=bool(capture.get("exact", True)))
        with self._tenant_environment():
            planned = plan_reply_with_listen_workflow(
                capture,
                task,
                target_config=target,
                config=copy.deepcopy(self.config),
                rules=copy.deepcopy(self.rules),
                workflow_state=self._workflow_state_snapshot(),
                allow_fallback_send=bool((self.config.get("reply", {}) or {}).get("allow_fallback_send")),
            )
        event = planned.get("event") if isinstance(planned.get("event"), dict) else {}
        if isinstance(planned.get("decision"), dict) and event:
            planned["decision"] = {
                **planned["decision"],
                "scheduler_planner_event_action": event.get("action"),
                "scheduler_planner_event_reason": event.get("reason"),
            }
        return planned

    def _capture_for_reply(self, reply: dict[str, Any]) -> dict[str, Any] | None:
        inline_capture = reply.get("_capture")
        if isinstance(inline_capture, dict):
            return inline_capture
        capture_ids = [str(item) for item in reply.get("capture_ids", []) if str(item)]
        if not capture_ids:
            return None
        state = self.store.load()
        capture = (state.get("captures", {}) or {}).get(capture_ids[-1])
        return capture if isinstance(capture, dict) else None

    def _freshness_check(self, reply: dict[str, Any]) -> dict[str, Any]:
        capture = self._capture_for_reply(reply)
        if not capture:
            return {"ok": False, "stale": True, "reason": "capture_missing_before_send"}
        target = self._target_for_name(str(reply.get("target_name") or capture.get("target_name") or ""), exact=bool(capture.get("exact", True)))
        workflow_state = self._workflow_state_snapshot()
        target_state = self._target_state(workflow_state, target.name)
        freshness = self._workflow["detect_newer_messages_before_send"](
            connector=self.connector,
            target=target,
            target_state=target_state,
            batch=list(capture.get("batch") or []),
            config=self.config,
        )
        freshness["stale"] = bool(freshness.get("has_newer_messages") or freshness.get("gap_risk"))
        return freshness

    def _send_reply(self, reply: dict[str, Any]) -> dict[str, Any]:
        capture = self._capture_for_reply(reply)
        if not capture:
            return {"ok": False, "verified": False, "reason": "capture_missing_before_send"}
        target = self._target_for_name(str(reply.get("target_name") or ""), exact=bool(capture.get("exact", True)))
        reply_text = str(reply.get("reply_text") or "").strip()
        if not reply_text:
            return {"ok": False, "verified": False, "reason": "empty_reply_text"}
        verified = self.connector.send_text_and_verify(target.name, reply_text, exact=target.exact)
        if not verified.get("verified"):
            return {"ok": False, "verified": False, "reason": "send_not_verified", "send_result": verified}
        batch = list(capture.get("batch") or [])
        overflow = list(capture.get("overflow_messages") or [])
        reply_trace_id = self._workflow["build_reply_trace_id"](target.name, batch, reply_text)
        post_send_warning = ""
        if self.state_path is not None:
            try:
                lock_settings = self.config.get("state_lock", {}) if isinstance(self.config.get("state_lock"), dict) else {}
                with self._workflow["StateLock"](
                    self.state_path.with_suffix(self.state_path.suffix + ".lock"),
                    timeout_seconds=int(lock_settings.get("timeout_seconds", 120)),
                    stale_seconds=int(lock_settings.get("stale_seconds", 900)),
                ):
                    workflow_state = self._workflow["load_state"](self.state_path)
                    target_state = self._target_state(workflow_state, target.name)
                    self._workflow["mark_processed"](
                        target_state,
                        batch,
                        reply_text,
                        reply_trace_id=reply_trace_id,
                        send_result=verified,
                    )
                    self._workflow["mark_coalesced_messages"](
                        target_state,
                        overflow,
                        reply_trace_id=reply_trace_id,
                        reply_text=reply_text,
                        reason="scheduler_overflow_coalesced_after_customer_reply",
                    )
                    self._workflow["record_reply_timestamp"](target_state)
                    self._workflow["save_state"](self.state_path, workflow_state)
            except Exception as exc:  # noqa: BLE001 - never retry an already verified WeChat send
                post_send_warning = f"post_send_state_persist_failed: {exc!r}"
        decision_payload = reply.get("decision") if isinstance(reply.get("decision"), dict) else {}
        audit_event = {
            "ok": True,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "target": target.name,
            "action": "sent",
            "scheduler": {
                "enabled": True,
                "reply_id": reply.get("reply_id"),
                "task_id": reply.get("task_id"),
                "capture_ids": reply.get("capture_ids"),
                "context_version": reply.get("input_context_version"),
            },
            "message_ids": list(reply.get("input_message_ids") or []),
            "message_count": len(batch),
            "decision": {**decision_payload, "reply_text": reply_text},
            "send_result": verified,
            "verified": True,
        }
        for key in ("outbound_naturalness", "final_visible_llm_polish", "final_visible_llm_polish_degraded"):
            if key in decision_payload:
                audit_event[key] = decision_payload.get(key)
        if post_send_warning:
            audit_event["post_send_warning"] = post_send_warning
        if self.audit_path is not None:
            try:
                self._workflow["append_audit"](self.audit_path, audit_event)
            except Exception as exc:  # noqa: BLE001
                post_send_warning = f"{post_send_warning}; audit_append_failed: {exc!r}".strip("; ")
        return {
            "ok": True,
            "verified": True,
            "reply_trace_id": reply_trace_id,
            "send_result": verified,
            "audit_event": audit_event,
            "post_send_warning": post_send_warning,
        }
