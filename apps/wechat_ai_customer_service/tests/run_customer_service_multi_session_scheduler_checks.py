"""Offline checks for customer-service multi-session scheduling primitives."""

from __future__ import annotations

import json
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
WORKFLOWS_ROOT = APP_ROOT / "workflows"
ADAPTERS_ROOT = APP_ROOT / "adapters"
for path in (PROJECT_ROOT, APP_ROOT, WORKFLOWS_ROOT, ADAPTERS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from apps.wechat_ai_customer_service.admin_backend.services.customer_service_scheduler_state import (  # noqa: E402
    SchedulerConfig,
    SchedulerStateStore,
    complete_llm_task,
    enqueue_llm_task,
    enqueue_pending_session,
    mark_capture_started,
    mark_llm_started,
    mark_reply_sent,
    record_capture_result,
    record_session_signal,
    select_capture_sessions,
    select_ready_replies,
    state_summary,
)
from apps.wechat_ai_customer_service.admin_backend.services.customer_service_scheduler import (  # noqa: E402
    CapturedMessagesConnector,
    CustomerServiceSchedulerRuntime,
    ManagedListenerSchedulerBridge,
    plan_reply_with_listen_workflow,
)
from apps.wechat_ai_customer_service.admin_backend.services.customer_profile_store import CustomerProfileStore  # noqa: E402
from apps.wechat_ai_customer_service.admin_backend.services.session_monitor import SessionMonitor  # noqa: E402
from apps.wechat_ai_customer_service.customer_service_live_safety import apply_customer_service_live_safety_guard  # noqa: E402
from apps.wechat_ai_customer_service.workflows.llm_intent_router import route_intent  # noqa: E402
from apps.wechat_ai_customer_service.scripts.run_customer_service_listener import load_concurrency_scheduler_enabled  # noqa: E402
from listen_and_reply import TargetConfig, load_config, load_rules, maybe_enrich_messages_with_history  # noqa: E402


def assert_true(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def assert_equal(actual: Any, expected: Any, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


def empty_state() -> dict[str, Any]:
    return {
        "version": 1,
        "tenant_id": "unit",
        "sessions": {},
        "captures": {},
        "llm_tasks": {},
        "ready_replies": {},
        "send_sequence": 0,
        "events": [],
    }


class FakeSessionConnector:
    def __init__(self, sessions: list[dict[str, Any]]) -> None:
        self.sessions = sessions

    def list_sessions(self) -> dict[str, Any]:
        return {"ok": True, "sessions": self.sessions}


class FakeBridgeConnector:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.messages = {
            "customer_a": [
                {
                    "id": "bridge-a-1",
                    "type": "text",
                    "sender": "customer",
                    "content": "这台车还能优惠吗",
                    "time": "2026-05-25T10:00:00",
                }
            ]
        }

    def list_sessions(self) -> dict[str, Any]:
        return {
            "ok": True,
            "sessions": [{"name": "customer_a", "content": "这台车还能优惠吗", "time": "10:00", "conversation_type": "private"}],
        }

    def get_messages(self, target: str, exact: bool = True, history_load_times: int = 0) -> dict[str, Any]:
        return {"ok": True, "target": target, "exact": exact, "messages": list(self.messages.get(target, []))}

    def send_text_and_verify(self, target: str, text: str, exact: bool = True) -> dict[str, Any]:
        self.sent.append({"target": target, "text": text, "exact": exact})
        return {"ok": True, "verified": True, "adapter": "win32_ocr", "state": "sent"}


def message(target: str, index: int, content: str | None = None) -> dict[str, Any]:
    return {
        "id": f"{target}-m-{index}",
        "type": "text",
        "sender": "customer",
        "content": content or f"{target} 问题 {index}",
        "time": f"2026-05-25T10:{index:02d}:00",
    }


def check_pending_sessions_survive_round_limit() -> None:
    state = empty_state()
    for index in range(10):
        enqueue_pending_session(state, f"客户{index}", reason="unit_burst", now=f"2026-05-25T10:{index:02d}:00")
    first_round = select_capture_sessions(state, limit=3)
    assert_equal(len(first_round), 3, "round should select only the configured capture limit")
    for item in first_round:
        mark_capture_started(state, item["target_name"], now="2026-05-25T10:30:00")
    remaining = select_capture_sessions(state, limit=20)
    remaining_names = {item["target_name"] for item in remaining}
    assert_equal(len(remaining_names), 7, "unselected pending sessions must remain pending")
    assert_true("客户3" in remaining_names and "客户9" in remaining_names, "later pending sessions should survive truncation")


def check_no_change_signal_does_not_clear_pending() -> None:
    state = empty_state()
    record_session_signal(
        state,
        {"name": "客户A", "content": "第一条", "time": "10:00", "conversation_type": "private"},
        now="2026-05-25T10:00:00",
    )
    assert_true(bool(state["sessions"]["客户A"].get("pending_capture")), "changed signal should enqueue pending")
    record_session_signal(
        state,
        {"name": "客户A", "content": "第一条", "time": "10:00", "conversation_type": "private"},
        now="2026-05-25T10:01:00",
    )
    assert_true(bool(state["sessions"]["客户A"].get("pending_capture")), "unchanged signal must not clear pending")


def check_unread_signal_without_preview_enters_pending() -> None:
    state = empty_state()
    record_session_signal(
        state,
        {"name": "客户无预览", "unread_detected": True, "conversation_type": "private"},
        now="2026-05-25T10:02:00",
    )
    session = state["sessions"]["客户无预览"]
    assert_true(bool(session.get("pending_capture")), "unread badge/signal without preview must enqueue pending")
    assert_equal(session.get("status"), "capture_pending", "unread-only signal should be capture pending")


def check_context_version_marks_old_llm_task_stale() -> None:
    state = empty_state()
    capture1 = record_capture_result(
        state,
        "客户A",
        messages=[message("A", 1)],
        batch=[message("A", 1)],
        now="2026-05-25T10:00:00",
    )
    task1 = enqueue_llm_task(state, capture1["capture_id"], now="2026-05-25T10:00:01")
    mark_llm_started(state, task1["task_id"], now="2026-05-25T10:00:02")
    capture2 = record_capture_result(
        state,
        "客户A",
        messages=[message("A", 1), message("A", 2)],
        batch=[message("A", 2)],
        now="2026-05-25T10:00:03",
    )
    assert_equal(capture2["context_version"], 2, "second capture should advance context version")
    result = complete_llm_task(
        state,
        task1["task_id"],
        reply_text="旧回复",
        now="2026-05-25T10:00:04",
    )
    assert_equal(result["status"], "stale", "old LLM task must become stale after newer context")
    assert_equal(state_summary(state)["reply_ready"], 0, "stale task must not create ready reply")


def check_duplicate_active_capture_does_not_stale_llm_task() -> None:
    state = empty_state()
    first_message = message("A", 1)
    capture1 = record_capture_result(
        state,
        "客户A",
        messages=[first_message],
        batch=[first_message],
        now="2026-05-25T10:00:00",
    )
    task1 = enqueue_llm_task(state, capture1["capture_id"], now="2026-05-25T10:00:01")
    mark_llm_started(state, task1["task_id"], now="2026-05-25T10:00:02")
    duplicate_capture = record_capture_result(
        state,
        "客户A",
        messages=[first_message],
        batch=[first_message],
        now="2026-05-25T10:00:03",
    )
    assert_equal(duplicate_capture["status"], "empty", "same active input should not create a new capture")
    assert_equal(duplicate_capture["context_version"], 1, "same active input must not advance context version")
    completed = complete_llm_task(
        state,
        task1["task_id"],
        reply_text="当前回复",
        now="2026-05-25T10:00:04",
    )
    assert_equal(completed["status"], "completed", "duplicate active capture must not stale the original LLM task")
    assert_equal(state_summary(state)["reply_ready"], 1, "original LLM task should still create one ready reply")


def check_ready_reply_fifo_and_same_session_latest_only() -> None:
    state = empty_state()
    capture_a = record_capture_result(state, "客户A", messages=[message("A", 1)], batch=[message("A", 1)], now="2026-05-25T10:00:00")
    capture_b = record_capture_result(state, "客户B", messages=[message("B", 1)], batch=[message("B", 1)], now="2026-05-25T10:00:01")
    task_a = enqueue_llm_task(state, capture_a["capture_id"], now="2026-05-25T10:00:02")
    task_b = enqueue_llm_task(state, capture_b["capture_id"], now="2026-05-25T10:00:03")
    mark_llm_started(state, task_a["task_id"], now="2026-05-25T10:00:04")
    mark_llm_started(state, task_b["task_id"], now="2026-05-25T10:00:05")
    complete_llm_task(state, task_b["task_id"], reply_text="B先完成", now="2026-05-25T10:00:06")
    complete_llm_task(state, task_a["task_id"], reply_text="A后完成", now="2026-05-25T10:00:07")
    selected = select_ready_replies(state, limit=2)
    assert_equal([item["target_name"] for item in selected], ["客户B", "客户A"], "ready replies should be FIFO by ready_at")

    mark_reply_sent(state, selected[0]["reply_id"], now="2026-05-25T10:00:08")
    capture_b2 = record_capture_result(state, "客户B", messages=[message("B", 2)], batch=[message("B", 2)], now="2026-05-25T10:00:09")
    task_b2 = enqueue_llm_task(state, capture_b2["capture_id"], now="2026-05-25T10:00:10")
    mark_llm_started(state, task_b2["task_id"], now="2026-05-25T10:00:11")
    complete_llm_task(state, task_b2["task_id"], reply_text="B新版", now="2026-05-25T10:00:12")
    selected_after_new_context = select_ready_replies(state, limit=5)
    b_replies = [item for item in selected_after_new_context if item["target_name"] == "客户B"]
    assert_equal(len(b_replies), 1, "same target should expose only the latest ready reply")
    assert_equal(b_replies[0]["reply_text"], "B新版", "latest context reply should win")


def check_customer_profile_store_concurrent_json_writes() -> None:
    with tempfile.TemporaryDirectory(prefix="profile_store_concurrent_") as tmp:
        root = Path(tmp) / "customer_profiles"
        tenant_id = "scheduler_profile_concurrent"

        def worker(index: int) -> dict[str, Any] | None:
            store = CustomerProfileStore(tenant_id=tenant_id, root=root)
            return store.increment_message_stats(target_name=f"客户{index % 3}", is_reply=index % 2 == 0)

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(worker, index) for index in range(40)]
            results = [future.result() for future in as_completed(futures)]

        assert_equal(len(results), 40, "all concurrent profile writes should complete")
        assert_true(root.joinpath("profiles.json").exists(), "profiles file should be written")
        profiles = json.loads(root.joinpath("profiles.json").read_text(encoding="utf-8"))
        assert_true(isinstance(profiles, list), "profiles JSON should stay valid after concurrent writes")
        names = {str(item.get("target_name") or "") for item in profiles if isinstance(item, dict)}
        assert_true({"客户0", "客户1", "客户2"} <= names, "all concurrent targets should be present")


def check_session_monitor_keeps_overflow_pending(tmp_dir: Path | None = None) -> None:
    state_path = (tmp_dir or (PROJECT_ROOT / "runtime" / "apps" / "wechat_ai_customer_service" / "test_artifacts")) / "session_monitor_overflow_unit.json"
    try:
        state_path.unlink()
    except FileNotFoundError:
        pass
    monitor = SessionMonitor(state_path=state_path, max_targets_per_iteration=3)
    sessions = [
        {"name": f"客户{idx}", "content": f"新消息{idx}", "time": f"10:{idx:02d}", "conversation_type": "private"}
        for idx in range(6)
    ]
    first = monitor.poll(FakeSessionConnector(sessions))
    assert_equal(len(first), 3, "monitor should return only max targets per iteration")
    pending_after_first = monitor.pending_targets()
    assert_equal(len(pending_after_first), 6, "monitor should expose every pending session, not only the visible round limit")
    for item in first:
        monitor.reset_unread(item.name)
    second = monitor.poll(FakeSessionConnector(sessions))
    second_names = {item.name for item in second}
    assert_equal(len(second_names), 3, "unreturned active sessions should remain pending for next poll")
    assert_true({"客户3", "客户4", "客户5"}.issubset(second_names), "overflow active sessions should be returned next")


def check_session_monitor_empty_preview_does_not_clear_pending(tmp_dir: Path | None = None) -> None:
    state_path = (tmp_dir or (PROJECT_ROOT / "runtime" / "apps" / "wechat_ai_customer_service" / "test_artifacts")) / "session_monitor_empty_preview_unit.json"
    try:
        state_path.unlink()
    except FileNotFoundError:
        pass
    monitor = SessionMonitor(state_path=state_path, max_targets_per_iteration=3)
    first = monitor.poll(
        FakeSessionConnector([
            {"name": "客户A", "content": "刚发的新消息", "time": "10:00", "conversation_type": "private"}
        ])
    )
    assert_equal([item.name for item in first], ["客户A"], "initial signal should mark active")
    second = monitor.poll(
        FakeSessionConnector([
            {"name": "客户A", "content": "", "time": "", "conversation_type": "private"}
        ])
    )
    assert_equal([item.name for item in second], ["客户A"], "empty preview without reset must not clear pending")


def check_session_monitor_visual_unread_badge_retriggers_after_reset(tmp_dir: Path | None = None) -> None:
    state_path = (tmp_dir or (PROJECT_ROOT / "runtime" / "apps" / "wechat_ai_customer_service" / "test_artifacts")) / "session_monitor_visual_badge_unit.json"
    try:
        state_path.unlink()
    except FileNotFoundError:
        pass
    monitor = SessionMonitor(state_path=state_path, max_targets_per_iteration=3)
    initial = monitor.poll(
        FakeSessionConnector([
            {"name": "客户A", "content": "", "time": "", "unread_badge": "", "conversation_type": "private"},
            {"name": "客户B", "content": "", "time": "", "unread_badge": "", "conversation_type": "private"},
        ])
    )
    assert_equal(initial, [], "empty previews without badges should stay idle")
    red = monitor.poll(
        FakeSessionConnector([
            {"name": "客户A", "content": "", "time": "", "unread_badge": "visual_red_dot", "conversation_type": "private"},
            {"name": "客户B", "content": "", "time": "", "unread_badge": "visual_red_dot", "conversation_type": "private"},
        ])
    )
    assert_equal([item.name for item in red], ["客户A", "客户B"], "visual red badges should activate every unread session")
    for item in red:
        monitor.reset_unread(item.name)
    cleared = monitor.poll(
        FakeSessionConnector([
            {"name": "客户A", "content": "", "time": "", "unread_badge": "", "conversation_type": "private"},
            {"name": "客户B", "content": "", "time": "", "unread_badge": "", "conversation_type": "private"},
        ])
    )
    assert_equal(cleared, [], "cleared visual badges should not stay pending after reset")
    red_again = monitor.poll(
        FakeSessionConnector([
            {"name": "客户A", "content": "", "time": "", "unread_badge": "visual_red_dot", "conversation_type": "private"},
            {"name": "客户B", "content": "", "time": "", "unread_badge": "", "conversation_type": "private"},
        ])
    )
    assert_equal([item.name for item in red_again], ["客户A"], "a new visual badge after reset should retrigger capture")


def check_runtime_tick_does_not_wait_for_slow_llm() -> None:
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "scheduler_state.json"
        store = SchedulerStateStore(tenant_id="unit", path=path)
        messages_by_target = {
            "客户A": [message("A", 1)],
            "客户B": [message("B", 1)],
        }

        def capture_fn(session: dict[str, Any]) -> dict[str, Any]:
            target = str(session.get("target_name") or "")
            return {"messages": messages_by_target[target], "batch": messages_by_target[target]}

        def planner(capture: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
            if capture.get("target_name") == "客户A":
                time.sleep(0.25)
            else:
                time.sleep(0.02)
            return {"ok": True, "reply_text": f"回复 {capture.get('target_name')}", "decision": {"rule_name": "unit"}}

        runtime = CustomerServiceSchedulerRuntime(
            store=store,
            config=SchedulerConfig(enabled=True, capture_max_sessions_per_round=2, llm_max_concurrency=2, send_max_replies_per_round=1),
            capture_fn=capture_fn,
            plan_reply_fn=planner,
        )
        try:
            started = time.time()
            result = runtime.tick(
                session_signals=[
                    {"name": "客户A", "content": "A新消息", "time": "10:00"},
                    {"name": "客户B", "content": "B新消息", "time": "10:00"},
                ],
                allow_send=False,
                now="2026-05-25T10:00:00",
            )
            duration = time.time() - started
            assert_true(duration < 0.15, f"tick should submit LLM tasks without waiting for slow worker, got {duration:.3f}s")
            assert_equal(result["summary"]["llm_running"], 2, "both LLM tasks should be running after first tick")
            time.sleep(0.06)
            second = runtime.tick(allow_send=False, now="2026-05-25T10:00:01")
            assert_true(second["summary"]["reply_ready"] >= 1, "fast LLM task should become ready while slow task may still run")
            time.sleep(0.25)
            third = runtime.tick(allow_send=False, now="2026-05-25T10:00:02")
            assert_equal(third["summary"]["reply_ready"], 2, "both LLM tasks should eventually be ready")
        finally:
            runtime.shutdown()


def check_runtime_repeated_unread_signal_does_not_stale_same_batch() -> None:
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "scheduler_state.json"
        store = SchedulerStateStore(tenant_id="unit", path=path)
        first_message = message("A", 1)

        def capture_fn(session: dict[str, Any]) -> dict[str, Any]:
            return {"messages": [first_message], "batch": [first_message]}

        def planner(capture: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
            time.sleep(0.08)
            return {"ok": True, "reply_text": "稳定回复", "decision": {"rule_name": "unit"}}

        runtime = CustomerServiceSchedulerRuntime(
            store=store,
            config=SchedulerConfig(enabled=True, capture_max_sessions_per_round=1, llm_max_concurrency=1, send_max_replies_per_round=1),
            capture_fn=capture_fn,
            plan_reply_fn=planner,
        )
        try:
            runtime.tick(session_signals=[{"name": "客户A", "unread_detected": True}], allow_send=False, now="2026-05-25T10:00:00")
            runtime.tick(session_signals=[{"name": "客户A", "unread_detected": True}], allow_send=False, now="2026-05-25T10:00:01")
            time.sleep(0.1)
            result = runtime.tick(session_signals=[{"name": "客户A", "unread_detected": True}], allow_send=False, now="2026-05-25T10:00:02")
            assert_equal(result["summary"]["reply_ready"], 1, "repeated unread-only signal should leave one ready reply")
            assert_equal(result["summary"].get("reply_stale", 0), 0, "same batch must not become stale from repeated unread-only polling")
        finally:
            runtime.shutdown()


def check_runtime_send_runner_stales_before_send() -> None:
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "scheduler_state.json"
        store = SchedulerStateStore(tenant_id="unit", path=path)
        sent: list[str] = []

        def capture_fn(session: dict[str, Any]) -> dict[str, Any]:
            return {"messages": [message("A", 1)], "batch": [message("A", 1)]}

        def planner(capture: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
            return {"ok": True, "reply_text": "旧回复", "decision": {"rule_name": "unit"}}

        def freshness(reply: dict[str, Any]) -> dict[str, Any]:
            return {"ok": True, "stale": True, "reason": "newer_message_arrived_during_reply_build"}

        def sender(reply: dict[str, Any]) -> dict[str, Any]:
            sent.append(str(reply.get("reply_text") or ""))
            return {"ok": True, "verified": True}

        runtime = CustomerServiceSchedulerRuntime(
            store=store,
            config=SchedulerConfig(enabled=True, capture_max_sessions_per_round=1, llm_max_concurrency=1, send_max_replies_per_round=1),
            capture_fn=capture_fn,
            plan_reply_fn=planner,
            freshness_fn=freshness,
            send_fn=sender,
        )
        try:
            runtime.tick(session_signals=[{"name": "客户A", "content": "A新消息", "time": "10:00"}], allow_send=False, now="2026-05-25T10:00:00")
            time.sleep(0.03)
            runtime.tick(allow_send=False, now="2026-05-25T10:00:01")
            result = runtime.tick(allow_send=True, now="2026-05-25T10:00:02")
            assert_equal(sent, [], "stale freshness result must block send")
            assert_equal(result["summary"]["reply_stale"], 1, "reply should be marked stale")
            events = result.get("events") or []
            recaptured = any(item.get("event") == "capture_completed" and item.get("target_name") == "客户A" for item in events)
            assert_true(
                result["summary"]["pending_sessions"] == 1 or recaptured,
                "stale reply should requeue the target or recapture it in the same optimized tick",
            )
        finally:
            runtime.shutdown()


def check_runtime_same_tick_fast_llm_send_has_capture_snapshot() -> None:
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "scheduler_state.json"
        store = SchedulerStateStore(tenant_id="unit", path=path)
        sent: list[str] = []

        def capture_fn(session: dict[str, Any]) -> dict[str, Any]:
            return {"messages": [message("A", 1)], "batch": [message("A", 1)]}

        def planner(capture: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
            return {"ok": True, "reply_text": "快速回复", "decision": {"rule_name": "unit"}}

        def freshness(reply: dict[str, Any]) -> dict[str, Any]:
            assert_true(isinstance(reply.get("_capture"), dict), "same-tick freshness callback should receive capture snapshot")
            return {"ok": True, "stale": False}

        def sender(reply: dict[str, Any]) -> dict[str, Any]:
            assert_true(isinstance(reply.get("_capture"), dict), "same-tick sender callback should receive capture snapshot")
            sent.append(str(reply.get("reply_text") or ""))
            return {"ok": True, "verified": True}

        runtime = CustomerServiceSchedulerRuntime(
            store=store,
            config=SchedulerConfig(enabled=True, capture_max_sessions_per_round=1, llm_max_concurrency=1, send_max_replies_per_round=1),
            capture_fn=capture_fn,
            plan_reply_fn=planner,
            freshness_fn=freshness,
            send_fn=sender,
        )
        try:
            runtime.tick(session_signals=[{"name": "客户A", "content": "A新消息", "time": "10:00"}], allow_send=True, now="2026-05-25T10:00:00")
            time.sleep(0.03)
            runtime.tick(allow_send=True, now="2026-05-25T10:00:01")
            assert_equal(sent, ["快速回复"], "fast same-tick/next-tick reply should send once")
        finally:
            runtime.shutdown()


def check_runtime_send_runner_fifo() -> None:
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "scheduler_state.json"
        store = SchedulerStateStore(tenant_id="unit", path=path)
        sent: list[str] = []

        def capture_fn(session: dict[str, Any]) -> dict[str, Any]:
            target = str(session.get("target_name") or "")
            prefix = "A" if target == "客户A" else "B"
            return {"messages": [message(prefix, 1)], "batch": [message(prefix, 1)]}

        def planner(capture: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
            return {"ok": True, "reply_text": f"回复{capture.get('target_name')}", "decision": {"rule_name": "unit"}}

        def sender(reply: dict[str, Any]) -> dict[str, Any]:
            sent.append(str(reply.get("target_name") or ""))
            return {"ok": True, "verified": True}

        runtime = CustomerServiceSchedulerRuntime(
            store=store,
            config=SchedulerConfig(enabled=True, capture_max_sessions_per_round=2, llm_max_concurrency=2, send_max_replies_per_round=2),
            capture_fn=capture_fn,
            plan_reply_fn=planner,
            send_fn=sender,
        )
        try:
            runtime.tick(
                session_signals=[
                    {"name": "客户A", "content": "A新消息", "time": "10:00"},
                    {"name": "客户B", "content": "B新消息", "time": "10:00"},
                ],
                allow_send=False,
                now="2026-05-25T10:00:00",
            )
            time.sleep(0.05)
            runtime.tick(allow_send=False, now="2026-05-25T10:00:01")
            runtime.tick(allow_send=True, now="2026-05-25T10:00:02")
            assert_equal(sent, ["客户A", "客户B"], "send runner should consume ready replies in FIFO order")
        finally:
            runtime.shutdown()


def check_runtime_prioritizes_ready_send_before_new_capture() -> None:
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "scheduler_state.json"
        store = SchedulerStateStore(tenant_id="unit", path=path)
        state = store.load()
        capture_ready = record_capture_result(
            state,
            "客户已完成",
            messages=[message("R", 1)],
            batch=[message("R", 1)],
            now="2026-05-25T10:00:00",
        )
        task_ready = enqueue_llm_task(state, capture_ready["capture_id"], now="2026-05-25T10:00:01")
        mark_llm_started(state, task_ready["task_id"], now="2026-05-25T10:00:02")
        complete_llm_task(
            state,
            task_ready["task_id"],
            reply_text="已生成回复",
            decision={"rule_name": "unit"},
            now="2026-05-25T10:00:03",
        )
        enqueue_pending_session(state, "客户新消息", reason="unit_pending", now="2026-05-25T10:00:04")
        store.save(state)
        action_order: list[str] = []

        def capture_fn(session: dict[str, Any]) -> dict[str, Any]:
            action_order.append(f"capture:{session.get('target_name')}")
            return {"messages": [message("N", 1)], "batch": [message("N", 1)]}

        def planner(capture: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
            return {"ok": True, "reply_text": "新回复", "decision": {"rule_name": "unit"}}

        def sender(reply: dict[str, Any]) -> dict[str, Any]:
            action_order.append(f"send:{reply.get('target_name')}")
            return {"ok": True, "verified": True}

        runtime = CustomerServiceSchedulerRuntime(
            store=store,
            config=SchedulerConfig(enabled=True, capture_max_sessions_per_round=1, llm_max_concurrency=1, send_max_replies_per_round=1),
            capture_fn=capture_fn,
            plan_reply_fn=planner,
            send_fn=sender,
        )
        try:
            result = runtime.tick(allow_send=True, now="2026-05-25T10:00:05")
            assert_equal(action_order[:2], ["send:客户已完成", "capture:客户新消息"], "ready replies should be sent before starting new RPA capture")
            assert_true(result["summary"]["reply_sent"] >= 1, "pre-existing ready reply should be marked sent before any new capture")
        finally:
            runtime.shutdown()


def check_runtime_recovers_orphaned_running_llm_task_after_restart() -> None:
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "scheduler_state.json"
        store = SchedulerStateStore(tenant_id="unit", path=path)
        state = store.load()
        capture = record_capture_result(
            state,
            "客户A",
            messages=[message("A", 1)],
            batch=[message("A", 1)],
            now="2026-05-25T10:00:00",
        )
        task = enqueue_llm_task(state, capture["capture_id"], now="2026-05-25T10:00:01")
        mark_llm_started(state, task["task_id"], now="2026-05-25T10:00:02")
        store.save(state)

        def capture_fn(session: dict[str, Any]) -> dict[str, Any]:
            return {"messages": [message("A", 2)], "batch": [message("A", 2)]}

        def planner(capture_payload: dict[str, Any], task_payload: dict[str, Any]) -> dict[str, Any]:
            return {"ok": True, "reply_text": "重启后恢复回复", "decision": {"rule_name": "unit"}}

        runtime = CustomerServiceSchedulerRuntime(
            store=store,
            config=SchedulerConfig(enabled=True, capture_max_sessions_per_round=1, llm_max_concurrency=1, send_max_replies_per_round=1),
            capture_fn=capture_fn,
            plan_reply_fn=planner,
        )
        try:
            first = runtime.tick(allow_send=False, now="2026-05-25T10:00:03")
            assert_true(
                any(item.get("event") == "llm_task_orphan_requeued" for item in first.get("events") or []),
                f"orphaned running task should be requeued: {first}",
            )
            time.sleep(0.03)
            second = runtime.tick(allow_send=False, now="2026-05-25T10:00:04")
            assert_equal(second["summary"]["reply_ready"], 1, "recovered LLM task should complete into ready reply")
        finally:
            runtime.shutdown()


def check_captured_messages_connector_accepts_history_kwargs() -> None:
    capture = {
        "capture_id": "capture-history-kwargs",
        "target_name": "客户A",
        "context_version": 1,
        "messages": [message("A", 1)],
        "history_backfill": {"enabled": True, "mode": "anchor_until_found", "gap_risk": False},
    }
    connector = CapturedMessagesConnector(capture)
    payload = connector.get_messages(
        "客户A",
        exact=True,
        history_load_times=0,
        history_mode="anchor_until_found",
        anchor_content_keys=["unit"],
        max_scroll_steps=3,
    )
    assert_true(payload.get("ok") is True, f"captured connector should ignore RPA history kwargs safely: {payload}")
    assert_equal(payload.get("scheduler_capture_id"), "capture-history-kwargs", "capture id should be preserved")


def check_scheduler_planner_reuses_capture_history_backfill_verdict() -> None:
    capture = {
        "capture_id": "capture-history-reuse",
        "target_name": "客户A",
        "context_version": 1,
        "messages": [message("A", 1)],
        "history_backfill": {
            "enabled": True,
            "mode": "anchor_until_found",
            "reason": "visible_anchor_found_no_scroll",
            "gap_risk": False,
        },
    }
    connector = CapturedMessagesConnector(capture)
    payload = connector.get_messages("客户A", exact=True)
    target = TargetConfig(name="客户A", enabled=True, exact=True, allow_self_for_test=False, max_batch_messages=3)
    enriched = maybe_enrich_messages_with_history(
        connector=connector,
        target=target,
        config={"history_backfill": {"enabled": True, "mode": "anchor_until_found"}},
        payload=payload,
        target_state={"processed_message_ids": ["anchor-old"], "processed_content_keys": ["anchor-key"]},
    )
    history = enriched.get("_history_backfill") if isinstance(enriched.get("_history_backfill"), dict) else {}
    assert_true(history.get("planner_reused_scheduler_capture") is True, f"planner should trust scheduler capture history verdict: {history}")
    assert_true(history.get("gap_risk") is False, f"scheduler capture gap verdict should remain false: {history}")


def check_workflow_planner_uses_captured_messages_without_sending() -> None:
    config = load_config(APP_ROOT / "configs" / "file_transfer_smoke.example.json")
    config.setdefault("operator_alert", {})["enabled"] = False
    config.setdefault("raw_messages", {})["enabled"] = False
    config.setdefault("customer_profiles", {})["enabled"] = False
    rules = load_rules(Path(config["rules_path"]))
    target = TargetConfig(
        name="文件传输助手",
        enabled=True,
        exact=True,
        allow_self_for_test=True,
        max_batch_messages=3,
    )
    capture = {
        "capture_id": "capture-unit-greeting",
        "target_name": "文件传输助手",
        "context_version": 1,
        "messages": [{"id": "unit-greet-1", "type": "text", "sender": "self", "content": "你好"}],
        "history_backfill": {"enabled": False},
    }
    planned = plan_reply_with_listen_workflow(
        capture,
        {"task_id": "task-unit-greeting"},
        target_config=target,
        config=config,
        rules=rules,
        workflow_state={"targets": {}},
        allow_fallback_send=True,
    )
    assert_true(bool(planned.get("ok")), f"workflow planner should build reply from captured messages: {planned}")
    assert_true("你好" in str(planned.get("reply_text") or ""), "planned reply should come from existing greeting rule")
    event = planned.get("event") or {}
    assert_equal(event.get("action"), "planned", "planner must not send through captured connector")


def check_scheduler_planner_applies_final_visible_polish_without_sending() -> None:
    config = load_config(APP_ROOT / "configs" / "file_transfer_smoke.example.json")
    config.setdefault("operator_alert", {})["enabled"] = False
    config.setdefault("raw_messages", {})["enabled"] = False
    config.setdefault("customer_profiles", {})["enabled"] = False
    config["final_visible_llm_polish"] = {
        "enabled": True,
        "required_for_send": True,
        "provider": "manual_json",
        "candidate": {
            "reply": "您好，这边在的，您直接说需求就行。",
            "confidence": 1.0,
            "reason": "unit test scheduler final polish",
        },
    }
    rules = load_rules(Path(config["rules_path"]))
    target = TargetConfig(
        name="文件传输助手",
        enabled=True,
        exact=True,
        allow_self_for_test=True,
        max_batch_messages=3,
    )
    capture = {
        "capture_id": "capture-unit-polish",
        "target_name": "文件传输助手",
        "context_version": 1,
        "messages": [{"id": "unit-polish-1", "type": "text", "sender": "self", "content": "你好"}],
        "history_backfill": {"enabled": False},
    }
    planned = plan_reply_with_listen_workflow(
        capture,
        {"task_id": "task-unit-polish"},
        target_config=target,
        config=config,
        rules=rules,
        workflow_state={"targets": {}},
        allow_fallback_send=True,
    )
    assert_true(bool(planned.get("ok")), f"scheduler planner should pass final polish: {planned}")
    reply_text = str(planned.get("reply_text") or "")
    assert_true(reply_text.endswith("您好，这边在的，您直接说需求就行。"), f"planned reply should include final polished body: {planned}")
    decision = planned.get("decision") if isinstance(planned.get("decision"), dict) else {}
    polish = decision.get("final_visible_llm_polish") if isinstance(decision.get("final_visible_llm_polish"), dict) else {}
    assert_true(polish.get("passed") is True, f"final polish metadata should be retained: {planned}")
    event = planned.get("event") if isinstance(planned.get("event"), dict) else {}
    assert_true("send_result" not in event, f"planner must still avoid RPA send: {event}")


def check_listener_scheduler_config_gate() -> None:
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.json"
        path.write_text(json.dumps({"targets": []}, ensure_ascii=False), encoding="utf-8")
        assert_true(
            not load_concurrency_scheduler_enabled(path),
            "scheduler should stay off when neither explicit enable nor live low-risk guard exists",
        )
        path.write_text(json.dumps({"concurrency_scheduler": {"enabled": True}}, ensure_ascii=False), encoding="utf-8")
        assert_true(load_concurrency_scheduler_enabled(path), "scheduler should enable only on explicit true")
        live_low_risk = {
            "targets": [{"name": "客户A", "enabled": True, "exact": True}],
            "multi_target": {"enabled": True, "rpa_low_risk_mode": True},
            "live_safety_guard": {
                "enabled": True,
                "allowed_targets": ["客户A"],
                "require_recent_bootstrap": False,
            },
        }
        path.write_text(json.dumps(live_low_risk, ensure_ascii=False), encoding="utf-8")
        assert_true(
            load_concurrency_scheduler_enabled(path),
            "live low-risk RPA guard should infer scheduler enable when not explicitly disabled",
        )
        live_low_risk["concurrency_scheduler"] = {"enabled": False}
        path.write_text(json.dumps(live_low_risk, ensure_ascii=False), encoding="utf-8")
        assert_true(
            not load_concurrency_scheduler_enabled(path),
            "explicit scheduler false should remain the rollback switch",
        )


def check_live_safety_applies_backend_scheduler_defaults() -> None:
    raw = {
        "targets": [{"name": "客户A", "enabled": True, "exact": True}],
        "multi_target": {"enabled": True, "rpa_low_risk_mode": True},
        "live_safety_guard": {
            "enabled": True,
            "allowed_targets": ["客户A"],
            "require_recent_bootstrap": False,
        },
    }
    merged = apply_customer_service_live_safety_guard(raw, settings={})
    scheduler = merged.get("concurrency_scheduler") if isinstance(merged.get("concurrency_scheduler"), dict) else {}
    assert_true(scheduler.get("enabled") is True, "live safety should turn on backend scheduler defaults")
    assert_equal(scheduler.get("llm_max_concurrency"), 2, "scheduler should use conservative concurrent LLM default")
    raw["concurrency_scheduler"] = {"enabled": False}
    rollback = apply_customer_service_live_safety_guard(raw, settings={})
    rollback_scheduler = rollback.get("concurrency_scheduler") if isinstance(rollback.get("concurrency_scheduler"), dict) else {}
    assert_true(rollback_scheduler.get("enabled") is False, "explicit scheduler false should survive live safety normalization")


def check_managed_bridge_capture_send_marks_workflow_state() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        config_path = root / "listener_config.json"
        state_path = root / "workflow_state.json"
        audit_path = root / "audit.jsonl"
        config = {
            "state_path": str(state_path),
            "audit_log_path": str(audit_path),
            "targets": [
                {
                    "name": "customer_a",
                    "enabled": True,
                    "exact": True,
                    "allow_self_for_test": False,
                    "max_batch_messages": 3,
                }
            ],
            "history_backfill": {"enabled": False},
            "raw_messages": {"enabled": False},
            "customer_profiles": {"enabled": False},
            "concurrency_scheduler": {
                "enabled": True,
                "capture_max_sessions_per_round": 1,
                "llm_max_concurrency": 1,
                "send_max_replies_per_round": 1,
            },
        }
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        bridge = ManagedListenerSchedulerBridge(
            tenant_id="unit_bridge",
            config_path=config_path,
            allow_send=True,
            write_data=False,
        )
        fake = FakeBridgeConnector()
        bridge.connector = fake
        bridge.store = SchedulerStateStore(tenant_id="unit_bridge", path=root / "scheduler_state.json")
        if bridge.runtime is not None:
            bridge.runtime.shutdown()
        bridge.runtime = CustomerServiceSchedulerRuntime(
            store=bridge.store,
            config=bridge.scheduler_config,
            capture_fn=bridge._capture_session,
            plan_reply_fn=lambda capture, task: {"ok": True, "reply_text": "可以谈，您方便说下预算吗？", "decision": {"rule_name": "unit"}},
            freshness_fn=lambda reply: {"ok": True, "stale": False},
            send_fn=bridge._send_reply,
            capture_done_fn=bridge._capture_done,
        )
        try:
            bridge.runtime.tick(session_signals=[{"name": "customer_a", "unread_detected": True}], allow_send=True, now="2026-05-25T10:00:00")
            time.sleep(0.03)
            bridge.runtime.tick(allow_send=True, now="2026-05-25T10:00:01")
        finally:
            bridge.shutdown()
        assert_equal(len(fake.sent), 1, "bridge sender should send exactly one verified reply")
        workflow_state = json.loads(state_path.read_text(encoding="utf-8"))
        target_state = workflow_state.get("targets", {}).get("customer_a", {})
        assert_true("bridge-a-1" in target_state.get("processed_message_ids", []), "send success must mark original workflow state processed")
        assert_true(audit_path.exists(), "send success should append scheduler audit event")


def check_mixed_greeting_budget_intent_prefers_product() -> None:
    config = {"intent_router": {"heuristic_first": True, "cache_seconds": 0}}
    mixed = route_intent(
        "你好，我预算12到15万，想买省心家用二手车，主要上下班和接娃，南京能看车吗？",
        config=config,
        target_state={},
    )
    assert_equal(mixed.intent, "product_inquiry", "greeting plus concrete used-car need must not be treated as pure greeting")
    pure = route_intent("你好，在吗", config=config, target_state={})
    assert_equal(pure.intent, "greeting", "standalone greeting should still route as greeting")


def run_checks() -> dict[str, Any]:
    checks = [
        check_pending_sessions_survive_round_limit,
        check_no_change_signal_does_not_clear_pending,
        check_unread_signal_without_preview_enters_pending,
        check_context_version_marks_old_llm_task_stale,
        check_duplicate_active_capture_does_not_stale_llm_task,
        check_ready_reply_fifo_and_same_session_latest_only,
        check_customer_profile_store_concurrent_json_writes,
        check_session_monitor_keeps_overflow_pending,
        check_session_monitor_empty_preview_does_not_clear_pending,
        check_session_monitor_visual_unread_badge_retriggers_after_reset,
        check_runtime_tick_does_not_wait_for_slow_llm,
        check_runtime_repeated_unread_signal_does_not_stale_same_batch,
        check_runtime_send_runner_stales_before_send,
        check_runtime_same_tick_fast_llm_send_has_capture_snapshot,
        check_runtime_send_runner_fifo,
        check_runtime_prioritizes_ready_send_before_new_capture,
        check_runtime_recovers_orphaned_running_llm_task_after_restart,
        check_captured_messages_connector_accepts_history_kwargs,
        check_scheduler_planner_reuses_capture_history_backfill_verdict,
        check_workflow_planner_uses_captured_messages_without_sending,
        check_scheduler_planner_applies_final_visible_polish_without_sending,
        check_listener_scheduler_config_gate,
        check_live_safety_applies_backend_scheduler_defaults,
        check_managed_bridge_capture_send_marks_workflow_state,
        check_mixed_greeting_budget_intent_prefers_product,
    ]
    results = []
    for check in checks:
        try:
            check()
            results.append({"name": check.__name__, "ok": True})
        except Exception as exc:  # noqa: BLE001
            results.append({"name": check.__name__, "ok": False, "error": repr(exc)})
    failures = [item for item in results if not item.get("ok")]
    return {"ok": not failures, "count": len(results), "failures": failures, "results": results}


def main() -> int:
    result = run_checks()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
