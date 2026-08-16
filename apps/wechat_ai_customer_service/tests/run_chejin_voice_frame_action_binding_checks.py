"""Focused regression for the CheJin voice frame-action binding contract."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.wechat_ai_customer_service.adapters import (  # noqa: E402
    wechat_win32_ocr_sidecar as sidecar,
)


def _real_observations() -> list[dict]:
    anchor = {
        "source": "parser_voice_message_context_menu_anchor",
        "click_bounds": [488, 220, 536, 248],
        "item": {
            "text": '3"',
            "voice_duration_text": '3"',
            "left": 488,
            "top": 220,
            "right": 536,
            "bottom": 248,
            "center_x": 512,
            "center_y": 234,
            "sender_role": "customer",
            "parser_bubble_rect": [488, 220, 536, 248],
        },
    }
    transcript = {
        "id": "voice-post",
        "type": "voice",
        "sender": "customer",
        "sender_role": "customer",
        "content": "你好，我想咨询一下",
        "content_clean": "你好，我想咨询一下",
        "content_raw_ocr": '3"\n你好，我想咨询一下',
        "voice_duration_text": '3"',
        "bubble_rect": [488, 220, 700, 294],
        "quality_flags": ["voice_duration_prefix_removed"],
    }
    bound = sidecar._bind_voice_transcripts_for_action(
        [transcript],
        anchor,
        (965, 852),
        canonical_voice_action_id="action-1",
        reserved_worker_stable_id="worker-message-5",
        selected_action_token="token-1",
        pre_observation_id="voice-pre",
    )
    assert len(bound) == 1
    return sidecar.build_message_observations_v3(bound)


def test_real_builder_keeps_binding_outside_formal_source() -> None:
    observations = _real_observations()
    assert len(observations) == 1
    source = observations[0]["source_message"]
    assert "canonical_voice_action_id" not in source
    assert "reserved_worker_stable_id" not in source
    assert observations[0]["frame_action_binding"] == {
        "canonical_voice_action_id": "action-1",
        "reserved_worker_stable_id": "worker-message-5",
        "selected_action_token": "token-1",
        "pre_observation_id": "voice-pre",
        "post_observation_id": "voice-post",
        "binding_confirmed": True,
    }


def test_exact_binding_selects_one_post_observation() -> None:
    observations = _real_observations()
    confirmed = sidecar.confirmed_voice_frame_action_observations(
        observations,
        canonical_voice_action_id="action-1",
        reserved_worker_stable_id="worker-message-5",
        selected_action_token="token-1",
        pre_observation_id="voice-pre",
    )
    assert [item["observation_id"] for item in confirmed] == ["voice-post"]


def test_missing_mismatched_or_multiple_bindings_fail_closed() -> None:
    observations = _real_observations()
    selectors = {
        "canonical_voice_action_id": "action-1",
        "reserved_worker_stable_id": "worker-message-5",
        "selected_action_token": "token-1",
        "pre_observation_id": "voice-pre",
    }
    missing = deepcopy(observations)
    missing[0].pop("frame_action_binding")
    assert not sidecar.confirmed_voice_frame_action_observations(
        missing, **selectors
    )

    for field, value in (
        ("canonical_voice_action_id", "action-other"),
        ("reserved_worker_stable_id", "worker-message-6"),
        ("selected_action_token", "token-other"),
        ("pre_observation_id", "voice-other"),
        ("post_observation_id", "voice-other"),
    ):
        invalid = deepcopy(observations)
        invalid[0]["frame_action_binding"][field] = value
        assert not sidecar.confirmed_voice_frame_action_observations(
            invalid, **selectors
        )

    duplicate = observations + [deepcopy(observations[0])]
    assert len(
        sidecar.confirmed_voice_frame_action_observations(
            duplicate, **selectors
        )
    ) == 2

    empty_token = deepcopy(observations)
    empty_token[0]["frame_action_binding"]["selected_action_token"] = ""
    assert not sidecar.confirmed_voice_frame_action_observations(
        empty_token,
        **{**selectors, "selected_action_token": ""},
    )


def main() -> int:
    tests = (
        test_real_builder_keeps_binding_outside_formal_source,
        test_exact_binding_selects_one_post_observation,
        test_missing_mismatched_or_multiple_bindings_fail_closed,
    )
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"All {len(tests)} voice frame-action binding checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
