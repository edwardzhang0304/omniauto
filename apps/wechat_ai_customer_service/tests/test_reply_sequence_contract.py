"""Optional Brain contract; no provider or physical WeChat dependency."""
from apps.wechat_ai_customer_service.adapters.reply_sequence import pack_reply_sequence
from apps.wechat_ai_customer_service.workflows.customer_service_brain_contract import (
    normalize_brain_plan, normalize_reply_segments, verify_brain_reply_quality,
)
import pytest


def test_optional_normalization_keeps_complete_repeated_units_and_legacy_default():
    units = ["保留条件。", "说明安排。", "其他要求。", "保留条件。"]
    assert normalize_reply_segments(units, preserve_all=True) == units
    assert normalize_brain_plan({"reply_segments": units}, preserve_all_segments=True)["reply_segments"] == units
    assert normalize_reply_segments(units) == units[:3]


@pytest.mark.parametrize("action", ["send_reply", "reply_then_handoff"])
def test_enabled_sequence_limit_is_hard_and_never_slices_a_unit(action):
    settings = {"reply_sequence_version": 1, "reply_sequence_max_chars": 108,
                "reply_sequence_max_segments": 3, "quality_verifier_enabled": False}
    plan = {"recommended_action": action, "reply_segments": ["啊" * 109]}
    assert verify_brain_reply_quality(plan, current_message="介绍一下", settings=settings)["errors"] == ["reply_sequence_rewrite_required"]
    assert plan["reply_segments"] == ["啊" * 109]
    plan["reply_segments"] = ["啊" * 108] * 3
    assert verify_brain_reply_quality(plan, current_message="介绍一下", settings=settings)["ok"]


def test_packing_preserves_guard_text_including_units_conditions_and_punctuation():
    units = ["标价12.88万元，是否有优惠需销售确认。" * 3, "不保证一定能够获批，具体须审核。" * 4]
    assert pack_reply_sequence(" ".join(units), units, max_chars=108, max_segments=3) == units
    with pytest.raises(ValueError, match="REPLY_SEQUENCE_REWRITE_REQUIRED"):
        pack_reply_sequence(" ".join(units), units[:-1], max_chars=108, max_segments=3)
