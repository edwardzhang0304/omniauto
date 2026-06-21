from __future__ import annotations

import os
import sys
import time
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import two_visible_session_customer_service_live as base  # noqa: E402


THREE_VISIBLE_TARGETS = ["许聪", "新数据测试", "文件传输助手"]
SEARCH_PREFLIGHT_TARGET = "文件传输助手"
ALLOW_SEARCH_PREFLIGHT_ARG = "--allow-search-preflight"
SEARCH_PREFLIGHT_ONLY_ARG = "--search-preflight-only"
THREE_SESSION_PROMPT_SCENARIOS = [
    {
        "许聪": "你好，我想看一台省心代步的小车，预算先按6万以内，你直接给我方向。",
        "新数据测试": "晚上好，我想给老婆看一台不太大的二手车，预算10万左右，先推荐方向。",
        "文件传输助手": "你好，请用一句话确认三会话调度是否正常。",
    },
    {
        "许聪": "如果我主要市区开，你从刚才方向里挑一台最稳的，理由简单说。",
        "新数据测试": "我不太懂车，你别让我选太多，直接说哪类更适合家用。",
        "文件传输助手": "继续三会话自测，这次请简短回复收到。",
    },
]


base.TARGETS = THREE_VISIBLE_TARGETS
base.PROMPT_LABEL = "三会话长测"
base.ARTIFACT_ROOT = (
    base.PROJECT_ROOT
    / "runtime"
    / "apps"
    / "wechat_ai_customer_service"
    / "test_artifacts"
    / "three_visible_session_customer_service_live"
)
base.SCENARIO_SETS["three_interleaved"] = THREE_SESSION_PROMPT_SCENARIOS


def _pop_flag(argv: list[str], flag: str) -> bool:
    found = False
    while flag in argv:
        argv.remove(flag)
        found = True
    return found


def _arg_value(argv: list[str], name: str, default: str) -> str:
    prefix = f"{name}="
    for index, value in enumerate(argv):
        if value == name and index + 1 < len(argv):
            return str(argv[index + 1])
        if value.startswith(prefix):
            return value[len(prefix) :]
    return default


def _restore_env(snapshot: dict[str, str | None]) -> None:
    for key, value in snapshot.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _compact_sessions(payload: dict[str, object]) -> list[dict[str, object]]:
    return [
        {
            "name": item.get("name"),
            "session_key": item.get("session_key"),
            "conversation_type": item.get("conversation_type"),
            "unread_signal": item.get("unread_signal"),
            "content": item.get("content"),
        }
        for item in (payload.get("sessions") or [])
        if isinstance(item, dict)
    ]


def _visible_names(payload: dict[str, object]) -> set[str]:
    return {str(item.get("name") or "") for item in _compact_sessions(payload)}


def _compact_message_probe(payload: dict[str, object]) -> dict[str, object]:
    compact: dict[str, object] = {}
    for key in (
        "ok",
        "state",
        "reason",
        "error",
        "target",
        "exact",
        "opened",
        "adapter",
        "transport_priority",
        "online",
        "ocr_count",
    ):
        if key in payload:
            compact[key] = payload.get(key)
    messages = payload.get("messages") if isinstance(payload, dict) else []
    compact["message_count"] = len(messages) if isinstance(messages, list) else 0
    for key in (
        "open_chat",
        "open_chat_timing",
        "target_ready",
        "window_probe",
        "guard",
        "validation",
        "rpa_lock",
        "wxauto4_reserve_status",
        "loopback_fallback",
    ):
        value = payload.get(key)
        if isinstance(value, dict):
            compact[key] = value
    return compact


def _search_preflight_emergency_stop_reason(payload: dict[str, object]) -> str:
    if not isinstance(payload, dict):
        return ""

    def _text_contains_blank(value: object) -> bool:
        return "blank" in str(value or "").lower()

    def _payload_has_blank_stop(value: object) -> bool:
        if not isinstance(value, dict):
            return False
        for key in ("state", "reason", "error"):
            if _text_contains_blank(value.get(key)):
                return True
        for key in (
            "guard",
            "surface",
            "open_chat",
            "open_chat_timing",
            "open_chat_search_clear_result",
            "open_chat_search_input_result",
            "open_chat_retry_surface",
            "primary_status",
        ):
            if _payload_has_blank_stop(value.get(key)):
                return True
        return False

    state = str(payload.get("state") or "")
    reason = str(payload.get("reason") or payload.get("error") or "")
    if "service_container_wrong_target" in reason or state == "wrong_target_service_container_detected":
        return "service_container_wrong_target"
    guard = payload.get("guard") if isinstance(payload.get("guard"), dict) else {}
    guard_state = str(guard.get("state") or "")
    guard_reason = str(guard.get("reason") or "")
    if "service_container_wrong_target" in guard_reason or guard_state == "wrong_target_service_container_detected":
        return "service_container_wrong_target"
    timing = payload.get("open_chat_timing") if isinstance(payload.get("open_chat_timing"), dict) else {}
    timing_reason = str(timing.get("reason") or "")
    if "service_container" in timing_reason or "wrong_target" in timing_reason:
        return "service_container_wrong_target"
    if _payload_has_blank_stop(payload):
        return "blank_render_detected"
    return ""


def _missing_search_preflight_target_stop(before_sessions: dict[str, object]) -> dict[str, object]:
    if SEARCH_PREFLIGHT_TARGET in _visible_names(before_sessions):
        return {}
    return {
        "error": "target_not_visible_in_session_scan",
        "reason": "interactive_search_click_blocked_after_blank_render_evidence",
        "interactive_search_blocked": True,
        "target_search_fallback_allowed": False,
    }


def run_search_preflight(run_id: str) -> dict[str, object]:
    run_dir = base.ARTIFACT_ROOT / f"{run_id}_search_preflight"
    progress_path = run_dir / "progress.jsonl"
    artifact_dir = run_dir / "rpa"
    result: dict[str, object] = {
        "ok": False,
        "mode": "search_preflight_only",
        "target": SEARCH_PREFLIGHT_TARGET,
        "run_id": run_id,
        "run_dir": str(run_dir),
        "started_at": base.now_text(),
    }
    env_overrides = {
        "WECHAT_KNOWLEDGE_TENANT": base.TENANT_ID,
        "WECHAT_ENABLE_WXAUTO4": "0",
        "WECHAT_DISABLE_WXAUTO4": "1",
        "WECHAT_WIN32_OCR_DAEMON_ENABLED": "0",
        "WECHAT_WIN32_OCR_TARGET_SEARCH_FALLBACK": "0",
        "WECHAT_WIN32_OCR_TARGET_SEARCH_ENTER_FALLBACK": "0",
        "WECHAT_WIN32_OCR_TARGET_SEARCH_RETRY_AFTER_SEARCH": "0",
        "WECHAT_WIN32_OCR_TARGET_SEARCH_INPUT_METHOD": "clipboard",
        "WECHAT_WIN32_OCR_ALLOW_BLIND_FILE_TRANSFER_SEND": "0",
        "WECHAT_WIN32_OCR_PASSIVE_PROBE": "1",
        "WECHAT_WIN32_OCR_ARTIFACT_DIR": str(artifact_dir),
        "WECHAT_RPA_LOCK_TIMEOUT_MESSAGES_SECONDS": "45",
        "WECHAT_RPA_LOCK_TIMEOUT_SESSIONS_SECONDS": "25",
        "WECHAT_RPA_LOCK_TIMEOUT_STATUS_SECONDS": "20",
        "WECHAT_RPA_LOCK_TIMEOUT_CAPABILITIES_SECONDS": "20",
        "WECHAT_RPA_OPERATOR_GUARD_ENABLED": "1",
        "WECHAT_RPA_OPERATOR_GUARD_BLOCK_MANUAL_INPUT": "1",
        "WECHAT_RPA_OPERATOR_GUARD_FLOATING_INDICATOR_ENABLED": "1",
        "WECHAT_RPA_OPERATOR_GUARD_CONTROL_HOTKEY": "f8",
    }
    snapshot = {key: os.environ.get(key) for key in env_overrides}
    guard_started = False
    try:
        os.environ.update(env_overrides)
        config_path = base.build_config(run_dir)
        base.configure_settings()
        connector = base.WeChatConnector()
        guard = base.launch_guard(base.read_json(config_path))
        guard_started = True
        result["operator_guard"] = guard
        base.append_jsonl(progress_path, {"event": "operator_guard_launch", "guard": guard, "created_at": base.now_text()})
        if not guard.get("ok"):
            result["error"] = "operator_guard_failed"
            return result

        time.sleep(1.0)
        preflight = connector.capabilities(interactive=True)
        before_sessions = connector.list_sessions(fresh=True)
        result["preflight"] = base.compact_status(preflight)
        result["before_sessions"] = _compact_sessions(before_sessions)
        base.append_jsonl(
            progress_path,
            {
                "event": "search_preflight_before",
                "preflight": result["preflight"],
                "sessions": result["before_sessions"],
                "created_at": base.now_text(),
            },
        )
        reason = base.hard_status_reason(preflight)
        if reason:
            result["error"] = reason
            return result

        if SEARCH_PREFLIGHT_TARGET in _visible_names(before_sessions):
            result["ok"] = True
            result["skipped_search"] = True
            result["reason"] = "target_already_visible"
            return result

        missing_target_stop = _missing_search_preflight_target_stop(before_sessions)
        if missing_target_stop:
            result.update(missing_target_stop)
            return result

        read_result = connector.get_messages(SEARCH_PREFLIGHT_TARGET, exact=True, history_load_times=0)
        result["read_result"] = _compact_message_probe(read_result)
        base.append_jsonl(
            progress_path,
            {
                "event": "search_preflight_get_messages",
                "result": result["read_result"],
                "created_at": base.now_text(),
            },
        )
        emergency_reason = _search_preflight_emergency_stop_reason(result["read_result"])
        if emergency_reason:
            result["error"] = emergency_reason
            result["emergency_stop"] = True
            result["reason"] = "stop_after_search_preflight_get_messages"
            return result

        status_after = connector.status(interactive=False)
        after_sessions = connector.list_sessions(fresh=True)
        result["post_status"] = base.compact_status(status_after)
        result["after_sessions"] = _compact_sessions(after_sessions)
        base.append_jsonl(
            progress_path,
            {
                "event": "search_preflight_after",
                "post_status": result["post_status"],
                "sessions": result["after_sessions"],
                "created_at": base.now_text(),
            },
        )
        hard_reason = base.hard_status_reason(status_after)
        if hard_reason:
            result["error"] = hard_reason
            return result
        if not read_result.get("ok"):
            result["error"] = str(read_result.get("reason") or read_result.get("error") or "search_preflight_messages_failed")
            return result
        if SEARCH_PREFLIGHT_TARGET not in _visible_names(after_sessions):
            result["error"] = "search_preflight_target_not_visible_after_open"
            return result
        result["ok"] = True
        result["reason"] = "search_preflight_passed"
        return result
    except Exception as exc:  # pragma: no cover - live diagnostic safety net
        result["error"] = "search_preflight_exception"
        result["exception"] = repr(exc)
        return result
    finally:
        if guard_started:
            base.stop_guard("three_visible_session_search_preflight_complete")
        _restore_env(snapshot)
        result["finished_at"] = base.now_text()
        base.write_json(run_dir / "search_preflight_result.json", result)


def run_self_check() -> bool:
    if base.TARGETS != THREE_VISIBLE_TARGETS:
        return False
    if base.PROMPT_LABEL != "三会话长测":
        return False
    prompts = base.round_prompts("unit", 1, scenario_set="three_interleaved")
    if set(prompts) != set(THREE_VISIBLE_TARGETS):
        return False
    if base.ARTIFACT_ROOT.name != "three_visible_session_customer_service_live":
        return False
    service_stop = _search_preflight_emergency_stop_reason(
        {
            "ok": False,
            "state": "target_not_confirmed_for_messages",
            "guard": {
                "ok": False,
                "state": "wrong_target_service_container_detected",
                "reason": "service_container_wrong_target",
            },
        }
    )
    if service_stop != "service_container_wrong_target":
        return False
    blank_stop = _search_preflight_emergency_stop_reason(
        {"ok": False, "state": "blank_render_detected", "reason": "blank_render"}
    )
    if blank_stop != "blank_render_detected":
        return False
    nested_blank_stop = _search_preflight_emergency_stop_reason(
        {
            "ok": False,
            "open_chat_timing": {
                "open_chat_search_clear_result": {
                    "ok": False,
                    "reason": "blank_render",
                    "surface": {"state": "blank_render_detected"},
                }
            },
        }
    )
    if nested_blank_stop != "blank_render_detected":
        return False
    missing_target_stop = _missing_search_preflight_target_stop({"sessions": [{"name": "许聪"}]})
    if not missing_target_stop.get("interactive_search_blocked"):
        return False
    visible_target_stop = _missing_search_preflight_target_stop({"sessions": [{"name": SEARCH_PREFLIGHT_TARGET}]})
    if visible_target_stop:
        return False
    return True


def main() -> int:
    if "--self-check" in sys.argv:
        ok = run_self_check()
        base.print_json({"ok": ok})
        return 0 if ok else 1
    allow_search_preflight = _pop_flag(sys.argv, ALLOW_SEARCH_PREFLIGHT_ARG)
    search_preflight_only = _pop_flag(sys.argv, SEARCH_PREFLIGHT_ONLY_ARG)
    run_id = _arg_value(sys.argv, "--run-id", base.datetime.now().strftime("%Y%m%d_%H%M%S"))
    if search_preflight_only and not allow_search_preflight:
        base.print_json({"ok": False, "error": "search_preflight_requires_allow_flag"})
        return 1
    if allow_search_preflight:
        preflight = run_search_preflight(run_id)
        if search_preflight_only:
            base.print_json(preflight)
            return 0 if preflight.get("ok") else 1
        if not preflight.get("ok"):
            base.print_json({"ok": False, "error": "search_preflight_failed", "search_preflight": preflight})
            return 1
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
