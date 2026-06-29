"""Non-live safety checks for the File Transfer Assistant live-regression runner."""

from __future__ import annotations

import json
import os
import sys
from argparse import Namespace
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
TESTS_ROOT = APP_ROOT / "tests"
for path in (PROJECT_ROOT, APP_ROOT, TESTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from run_file_transfer_live_regression import (  # noqa: E402
    BLIND_FILE_TRANSFER_SEND_ENV_KEY,
    FILE_TRANSFER_ASSISTANT,
    LIVE_REGRESSION_RPA_ENV_DEFAULTS,
    TARGET_SEARCH_FALLBACK_ENV_KEYS,
    apply_live_regression_rpa_safety_env,
    assert_scenario,
    build_result_payload,
    compact_output,
    run_isolated_workflow,
    restore_live_regression_rpa_safety_env,
    workflow_transport_backoff_seconds,
    workflow_module,
)


def main() -> int:
    results = [
        check_env_safety_defaults_block_inherited_risky_fallbacks(),
        check_env_safety_explicit_allow_preserves_inherited_values(),
        check_run_isolated_workflow_suppresses_local_settings_overlay(),
        check_result_payload_exposes_rpa_safety_scope(),
        check_live_regression_applies_low_risk_rpa_runtime_defaults(),
        check_assert_scenario_supports_contains_any_groups(),
        check_assert_scenario_supports_contains_min_groups(),
        check_compact_output_separates_decision_and_intent_handoff_flags(),
        check_nested_guard_rate_backoff_is_detected(),
        check_runner_source_keeps_file_transfer_target_isolation(),
    ]
    failures = [item for item in results if not item.get("ok")]
    payload = {"ok": not failures, "failures": failures, "results": results}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


def check_env_safety_defaults_block_inherited_risky_fallbacks() -> dict[str, Any]:
    keys = [*TARGET_SEARCH_FALLBACK_ENV_KEYS, BLIND_FILE_TRANSFER_SEND_ENV_KEY]
    original = {key: os.environ.get(key) for key in keys}
    try:
        for key in keys:
            os.environ[key] = "1"
        snapshot = apply_live_regression_rpa_safety_env(
            Namespace(allow_target_search_fallback=False, allow_blind_file_transfer_send=False)
        )
        blocked = {key: os.environ.get(key) for key in keys}
        restore_live_regression_rpa_safety_env(snapshot)
        restored = {key: os.environ.get(key) for key in keys}
        ok = all(value == "0" for value in blocked.values()) and all(value == "1" for value in restored.values())
        return {"name": "env_safety_defaults_block_inherited_risky_fallbacks", "ok": ok, "blocked": blocked, "restored": restored}
    finally:
        _restore_env(original)


def check_env_safety_explicit_allow_preserves_inherited_values() -> dict[str, Any]:
    keys = [*TARGET_SEARCH_FALLBACK_ENV_KEYS, BLIND_FILE_TRANSFER_SEND_ENV_KEY]
    original = {key: os.environ.get(key) for key in keys}
    try:
        for key in keys:
            os.environ[key] = "1"
        snapshot = apply_live_regression_rpa_safety_env(
            Namespace(allow_target_search_fallback=True, allow_blind_file_transfer_send=True)
        )
        preserved = {key: os.environ.get(key) for key in keys}
        restore_live_regression_rpa_safety_env(snapshot)
        restored = {key: os.environ.get(key) for key in keys}
        ok = all(value == "1" for value in preserved.values()) and all(value == "1" for value in restored.values())
        return {"name": "env_safety_explicit_allow_preserves_inherited_values", "ok": ok, "preserved": preserved, "restored": restored}
    finally:
        _restore_env(original)


def check_runner_source_keeps_file_transfer_target_isolation() -> dict[str, Any]:
    source_path = TESTS_ROOT / "run_file_transfer_live_regression.py"
    source = source_path.read_text(encoding="utf-8")
    expectations = {
        "two_workflow_calls_are_target_scoped": source.count("target=[FILE_TRANSFER_ASSISTANT]") >= 2,
        "both_workflow_calls_use_isolated_wrapper": source.count("run_isolated_workflow(") >= 3,
        "suppresses_local_target_scope": "target_scoped_local_customer_service_settings_overlay" in source,
        "does_not_save_customer_service_settings": ".save(" not in source,
    }
    return {
        "name": "runner_source_keeps_file_transfer_target_isolation",
        "ok": all(expectations.values()),
        "expectations": expectations,
    }


def check_result_payload_exposes_rpa_safety_scope() -> dict[str, Any]:
    args = Namespace(
        send=True,
        config=Path("config.json"),
        scenarios=Path("scenarios.json"),
        start_index=1,
        end_index=None,
        only=[],
        resume=False,
        allow_target_search_fallback=False,
        allow_blind_file_transfer_send=False,
    )
    payload = build_result_payload(args, {}, {"enabled": False, "count": 0}, "run", {"ok": True}, [], [], 0)
    safety = payload.get("rpa_safety") if isinstance(payload.get("rpa_safety"), dict) else {}
    ok = (
        safety.get("target") == FILE_TRANSFER_ASSISTANT
        and safety.get("local_customer_service_settings_overlay") == "target_scope_suppressed"
        and safety.get("target_search_fallback_allowed") is False
        and safety.get("blind_file_transfer_send_allowed") is False
        and safety.get("input_method") == "clipboard_chunks"
        and safety.get("typing_typo_probability") == 0.0
        and safety.get("typing_typo_max") == 0
        and safety.get("send_trigger_mode") == "enter_only"
        and safety.get("send_input_confirm_attempts") == 1
    )
    return {"name": "result_payload_exposes_rpa_safety_scope", "ok": ok, "rpa_safety": safety}


def check_live_regression_applies_low_risk_rpa_runtime_defaults() -> dict[str, Any]:
    keys = list(LIVE_REGRESSION_RPA_ENV_DEFAULTS)
    original = {key: os.environ.get(key) for key in keys}
    try:
        os.environ["WECHAT_WIN32_OCR_HUMANIZED_INPUT_METHOD"] = "sendinput_unicode"
        os.environ["WECHAT_WIN32_OCR_HUMANIZED_TYPING_TYPO_PROBABILITY"] = "0.22"
        os.environ["WECHAT_WIN32_OCR_HUMANIZED_TYPING_TYPO_MAX"] = "1"
        snapshot = apply_live_regression_rpa_safety_env(
            Namespace(allow_target_search_fallback=False, allow_blind_file_transfer_send=False)
        )
        applied = {key: os.environ.get(key) for key in keys}
        restore_live_regression_rpa_safety_env(snapshot)
        restored = {key: os.environ.get(key) for key in keys}
        ok = applied == LIVE_REGRESSION_RPA_ENV_DEFAULTS and restored.get("WECHAT_WIN32_OCR_HUMANIZED_INPUT_METHOD") == "sendinput_unicode"
        return {"name": "live_regression_applies_low_risk_rpa_runtime_defaults", "ok": ok, "applied": applied, "restored": restored}
    finally:
        _restore_env(original)


def check_assert_scenario_supports_contains_any_groups() -> dict[str, Any]:
    output = {
        "workflow": {"ok": True},
        "event": {
            "action": "sent",
            "decision": {"reply_text": "[OmniAuto自测] 在的，您说。"},
        },
    }
    scenario = {
        "expect_action": "sent",
        "expect_reply_contains_any": [["您好", "在", "可以"]],
        "expect_reply_not_contains": ["商用冰箱", "净水器滤芯"],
    }
    try:
        assert_scenario(scenario, output)
    except Exception as exc:
        return {"name": "assert_scenario_supports_contains_any_groups", "ok": False, "error": repr(exc)}
    return {"name": "assert_scenario_supports_contains_any_groups", "ok": True}


def check_assert_scenario_supports_contains_min_groups() -> dict[str, Any]:
    output = {
        "workflow": {"ok": True},
        "event": {
            "action": "sent",
            "decision": {"reply_text": "商用冰箱 BX-200、静音空气净化器 AP-88、智能指纹门锁 FL-920 都可以看。"},
        },
    }
    scenario = {
        "expect_action": "sent",
        "expect_reply_contains_min": [
            {
                "min": 3,
                "items": ["商用冰箱", "人体工学办公椅", "净水器滤芯", "静音空气净化器", "智能指纹门锁"],
            }
        ],
    }
    try:
        assert_scenario(scenario, output)
    except Exception as exc:
        return {"name": "assert_scenario_supports_contains_min_groups", "ok": False, "error": repr(exc)}
    return {"name": "assert_scenario_supports_contains_min_groups", "ok": True}


def check_compact_output_separates_decision_and_intent_handoff_flags() -> dict[str, Any]:
    output = {
        "event": {
            "action": "sent",
            "decision": {
                "reply_text": "可以看这几款。",
                "rule_name": "customer_service_brain_reply",
                "reason": "guard_passed",
                "need_handoff": False,
            },
            "intent_assist": {
                "intent": "unknown",
                "needs_handoff": True,
                "evidence": {"safety": {"must_handoff": False, "reasons": [], "allowed_auto_reply": True}},
            },
        }
    }
    compact = compact_output(output)
    ok = (
        compact.get("needs_handoff") is False
        and compact.get("decision_need_handoff") is False
        and compact.get("intent_assist_needs_handoff") is True
    )
    return {"name": "compact_output_separates_decision_and_intent_handoff_flags", "ok": ok, "compact": compact}


def check_nested_guard_rate_backoff_is_detected() -> dict[str, Any]:
    payload = {
        "ok": False,
        "send_result": {
            "send": {
                "state": "send_rate_limited",
                "guard": {
                    "rate": {
                        "ok": False,
                        "reason": "min_interval_not_elapsed",
                        "wait_seconds": 3.03,
                    }
                },
            }
        },
    }
    seconds = workflow_transport_backoff_seconds(payload)
    return {
        "name": "nested_guard_rate_backoff_is_detected",
        "ok": seconds == 3.03,
        "seconds": seconds,
    }


def check_run_isolated_workflow_suppresses_local_settings_overlay() -> dict[str, Any]:
    original_run_workflow = workflow_module.run_workflow
    original_overlay = workflow_module.apply_local_customer_service_settings
    try:
        def noisy_overlay(config: dict[str, Any]) -> dict[str, Any]:
            changed = dict(config)
            changed["targets"] = [{"name": "许聪", "enabled": True}]
            changed["multi_target"] = {"enabled": True}
            changed["reply"] = {"prefix": "kept"}
            return changed

        def fake_run_workflow(args: Namespace) -> dict[str, Any]:
            config = {
                "targets": [
                    {
                        "name": FILE_TRANSFER_ASSISTANT,
                        "enabled": True,
                        "exact": True,
                        "allow_self_for_test": True,
                    }
                ],
                "multi_target": {"enabled": False},
            }
            resolved = workflow_module.apply_local_customer_service_settings(config)
            return {
                "ok": True,
                "targets": [item.get("name") for item in resolved.get("targets", [])],
                "multi_target": resolved.get("multi_target"),
                "reply": resolved.get("reply"),
            }

        workflow_module.apply_local_customer_service_settings = noisy_overlay
        workflow_module.run_workflow = fake_run_workflow
        result = run_isolated_workflow(Namespace())
        restored_overlay = workflow_module.apply_local_customer_service_settings is noisy_overlay
        ok = (
            result.get("targets") == [FILE_TRANSFER_ASSISTANT]
            and result.get("multi_target") == {"enabled": False}
            and result.get("reply") == {"prefix": "kept"}
            and restored_overlay
        )
        return {
            "name": "run_isolated_workflow_suppresses_local_settings_overlay",
            "ok": ok,
            "result": result,
            "restored_overlay": restored_overlay,
        }
    finally:
        workflow_module.run_workflow = original_run_workflow
        workflow_module.apply_local_customer_service_settings = original_overlay


def _restore_env(snapshot: dict[str, str | None]) -> None:
    for key, value in snapshot.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
