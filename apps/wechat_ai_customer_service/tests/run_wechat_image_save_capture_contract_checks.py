from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
for path in (PROJECT_ROOT, APP_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from apps.wechat_ai_customer_service.optional_plugins.vision.capture.wechat import (  # noqa: E402
    _fine_grid_confirms_separate_stacked_surfaces,
    detect_visual_image_bubbles,
    execute_wechat_clipboard_image_copy,
    find_copy_menu_item,
)
from apps.wechat_ai_customer_service.adapters import wechat_win32_ocr_sidecar  # noqa: E402
from apps.wechat_ai_customer_service.adapters.wechat_win32_ocr import window_layout  # noqa: E402
from apps.wechat_ai_customer_service.adapters.wechat_win32_ocr.geometry import session_split_x  # noqa: E402
from apps.wechat_ai_customer_service.optional_plugins.vision.capture.surface import (  # noqa: E402
    image_candidates_without_reliable_typed_message_conflicts,
    messages_outside_image_bubbles,
    self_visual_image_messages_from_current_surface,
)


def main() -> int:
    checks = [
        check_structure_locator_excludes_self_image,
        check_structure_locator_ignores_clipped_boundary_image,
        check_fine_grid_splits_stacked_voice_surfaces,
        check_expanded_voice_surface_is_rejected_before_image_output,
        check_reliable_message_type_wins_over_false_image_surface,
        check_self_structural_observation_is_metadata_only,
        check_sidecar_has_no_retired_image_export,
        check_current_copy_transaction_has_no_file_artifact,
        check_self_copy_transaction_selects_only_self_side,
        check_current_copy_requires_clipboard_generation_change,
        check_retired_image_exports_are_removed,
        check_legacy_sidecar_action_rejects_before_platform_probe,
    ]
    results: list[dict[str, Any]] = []
    for check in checks:
        try:
            check()
            results.append({"name": check.__name__, "ok": True})
        except Exception as exc:  # pragma: no cover - test harness
            results.append({"name": check.__name__, "ok": False, "error": repr(exc)})
            break
    failures = [item for item in results if not item.get("ok")]
    print(json.dumps({"ok": not failures, "count": len(results), "failures": failures, "results": results}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


def _draw_layout_chrome(image: Image.Image) -> None:
    width, height = image.size
    nav = max(56, int(width * 0.071))
    split = max(nav + 180, int(width * 0.378))
    header = max(72, int(height * 0.105))
    input_top = min(height - 72, int(height * 0.883))
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, nav, height], fill=(224, 224, 224))
    draw.rectangle([nav + 1, 0, split, header], fill=(210, 210, 210))
    draw.rectangle([nav + 1, header + 1, split, height], fill=(240, 240, 240))
    draw.rectangle([split + 1, 0, width - 1, header], fill=(238, 238, 238))
    draw.rectangle([split + 1, header + 1, width - 1, input_top], fill=(255, 255, 255))
    draw.rectangle([split + 1, input_top + 1, width - 1, height - 1], fill=(242, 242, 242))
    draw.line([(nav, 0), (nav, height - 1)], fill=(110, 110, 110), width=2)
    draw.line([(split, 0), (split, height - 1)], fill=(110, 110, 110), width=2)
    draw.line([(nav, header), (width - 1, header)], fill=(110, 110, 110), width=2)
    draw.line([(split, input_top), (width - 1, input_top)], fill=(110, 110, 110), width=2)


def _message_viewport(image: Image.Image) -> list[int]:
    structural = window_layout.build_structural_layout_regions(image)
    assert_true(structural.get("ok") is True, f"fixture layout must resolve through production builder: {structural}")
    return list((structural.get("regions") or {}).get("message_viewport_bounds") or [])


def _customer_image_surface() -> Image.Image:
    image = Image.new("RGB", (980, 860), (247, 247, 247))
    _draw_layout_chrome(image)
    draw = ImageDraw.Draw(image)
    split = session_split_x(980)
    draw.rectangle([split + 42, 260, split + 282, 480], fill=(30, 120, 190))
    draw.rectangle([760, 500, 940, 660], fill=(190, 80, 50))
    return image


def check_structure_locator_excludes_self_image() -> None:
    surface = _customer_image_surface()
    bubbles = detect_visual_image_bubbles(
        surface,
        messages=[],
        max_images=8,
        side_filter="customer",
        message_viewport_bounds=_message_viewport(surface),
    )
    assert_true(bool(bubbles), f"customer image needs a structural target: {bubbles}")
    assert_true(all(item.get("side") == "customer" for item in bubbles), f"self image must never be a customer target: {bubbles}")


def check_structure_locator_ignores_clipped_boundary_image() -> None:
    for width, height in ((980, 860), (1200, 1000)):
        image = Image.new("RGB", (width, height), (242, 242, 242))
        _draw_layout_chrome(image)
        draw = ImageDraw.Draw(image)
        viewport = _message_viewport(image)
        media_left = viewport[0] + max(90, int((viewport[2] - viewport[0]) * 0.16))
        chat_top = max(90, min(150, int(height * 0.12)))
        for y in range(chat_top, chat_top + 160, 8):
            for x in range(media_left, media_left + 200, 8):
                draw.rectangle(
                    (x, y, x + 7, y + 7),
                    fill=((x + y) % 220, 120, 70),
                )
        complete_top = chat_top + 320
        for y in range(complete_top, complete_top + 190, 8):
            for x in range(media_left, media_left + 230, 8):
                draw.rectangle(
                    (x, y, x + 7, y + 7),
                    fill=((x * 3 + y) % 255, (x + y * 2) % 255, 80),
                )
        try:
            bubbles = detect_visual_image_bubbles(
                image,
                messages=[],
                side_filter="all",
                message_viewport_bounds=_message_viewport(image),
            )
        finally:
            image.close()
        assert_equal(len(bubbles), 1, "only the complete current-screen image is actionable")
        assert_true(
            int(bubbles[0]["bounds"][1]) > chat_top,
            f"clipped boundary image must be ignored: {bubbles}",
        )


def check_fine_grid_splits_stacked_voice_surfaces() -> None:
    coarse_cells = []
    for y, width in enumerate([7, 7, 7, 7, 16, 16, 16], start=34):
        coarse_cells.extend((x, y) for x in range(7, 7 + width))

    small = Image.new("RGB", (220, 246), (250, 250, 250))
    draw = ImageDraw.Draw(small)
    draw.rectangle((35, 170, 69, 188), fill=(242, 242, 242))
    draw.rectangle((35, 191, 114, 204), fill=(242, 242, 242))
    try:
        split = _fine_grid_confirms_separate_stacked_surfaces(
            small,
            coarse_cells=coarse_cells,
            coarse_block=5,
            background=[250.0, 250.0, 250.0],
            side="customer",
            minimum_media_height=34.0,
        )
    finally:
        small.close()
    assert_true(
        split,
        "block=2 must restore the pixel gap between duration and transcript",
    )

    equal_width_cells = [
        (x, y)
        for y in range(34, 41)
        for x in range(7, 18)
    ]
    equal_width = Image.new("RGB", (220, 246), (250, 250, 250))
    equal_draw = ImageDraw.Draw(equal_width)
    equal_draw.rectangle((35, 170, 89, 188), fill=(242, 242, 242))
    equal_draw.rectangle((35, 191, 89, 204), fill=(242, 242, 242))
    try:
        equal_split = _fine_grid_confirms_separate_stacked_surfaces(
            equal_width,
            coarse_cells=equal_width_cells,
            coarse_block=5,
            background=[250.0, 250.0, 250.0],
            side="customer",
            minimum_media_height=34.0,
        )
    finally:
        equal_width.close()
    assert_true(
        equal_split,
        "equal-width voice and transcript rows must also be separated",
    )

    tall_media_cells = [
        (x, y)
        for y in range(20, 41)
        for x in range(7, 23)
    ]
    tall_media = Image.new("RGB", (220, 246), (250, 250, 250))
    tall_draw = ImageDraw.Draw(tall_media)
    tall_draw.rectangle((35, 100, 114, 139), fill=(242, 242, 242))
    tall_draw.rectangle((35, 142, 114, 181), fill=(242, 242, 242))
    try:
        tall_split = _fine_grid_confirms_separate_stacked_surfaces(
            tall_media,
            coarse_cells=tall_media_cells,
            coarse_block=5,
            background=[250.0, 250.0, 250.0],
            side="customer",
            minimum_media_height=34.0,
        )
    finally:
        tall_media.close()
    assert_true(
        not tall_split,
        "two tall image surfaces must not be suppressed as chat rows",
    )


def check_expanded_voice_surface_is_rejected_before_image_output() -> None:
    screenshot = Image.new("RGB", (974, 853), (242, 242, 242))
    _draw_layout_chrome(screenshot)
    draw = ImageDraw.Draw(screenshot)
    surface_bounds = (476, 559, 690, 653)
    draw.rectangle(surface_bounds, fill=(242, 242, 242))
    for y in range(571, 642, 18):
        draw.rectangle((492, y, 660, y + 5), fill=(220, 226, 232))
    for y in range(559, 604, 5):
        for x in range(408, 453, 5):
            tone = 55 if ((x + y) // 5) % 2 else 205
            draw.rectangle(
                (x, y, x + 4, y + 4),
                fill=(tone, 110, 170),
            )
    reliable_voice = {
        "type": "voice",
        "sender_role": "customer",
        "content": "我们吃完啦，准备回家。",
        "bubble_rect": [486, 619, 690, 653],
        "parent_voice_anchor_key": "voice-stable:connected-surface",
    }
    diagnostics: list[dict[str, Any]] = []
    try:
        assert_equal(
            len(
                detect_visual_image_bubbles(
                    screenshot,
                    messages=[],
                    side_filter="all",
                    message_viewport_bounds=_message_viewport(screenshot),
                )
            ),
            1,
            "fixture must first reproduce the structural false image",
        )
        candidates = detect_visual_image_bubbles(
            screenshot,
            messages=[reliable_voice],
            side_filter="all",
            diagnostics=diagnostics,
            message_viewport_bounds=_message_viewport(screenshot),
        )
    finally:
        screenshot.close()
    assert_equal(
        candidates,
        [],
        "reliable voice evidence must veto the structural image candidate",
    )
    assert_equal(
        diagnostics[0].get("event"),
        "structural_image_candidate_rejected_by_reliable_message_type",
        "the detector must emit the formal reliable-type veto diagnostic",
    )


def check_reliable_message_type_wins_over_false_image_surface() -> None:
    image = {"bounds": [476, 559, 690, 653], "side": "customer"}
    reliable_voice = {
        "type": "voice",
        "sender_role": "customer",
        "content": "我们吃完啦，准备回家。",
        "parent_voice_anchor_key": "voice-stable:contract",
        "voice_anchor": {
            "anchor_key": "voice-anchor:contract",
            "anchor_stable_key": "voice-stable:contract",
            "anchor_structural_key": "voice-structural:contract",
            "item": {
                "sender_role": "customer",
                "parser_bubble_rect": [486, 619, 534, 645],
            },
        },
    }
    action_attempt = {
        "attempt_index": 1,
        "action_phase": "confirmed",
        "effective_success": True,
        "click": {"ok": True},
        "processed_anchor_keys": ["voice-stable:contract"],
        "context_anchor": {"anchor_stable_key": "voice-stable:contract"},
    }
    action_variants = [
        [action_attempt],
        [{**action_attempt, "click": {"ok": False}}],
        [{
            **action_attempt,
            "action_phase": "not_attempted",
            "effective_success": False,
            "processed_anchor_keys": [],
        }],
        [],
    ]
    for attempts in action_variants:
        assert_equal(
            image_candidates_without_reliable_typed_message_conflicts(
                [image],
                [reliable_voice],
                attempts,
            ),
            [],
            "message type arbitration must not depend on action success",
        )

    untranscribed_voice = {
        "type": "voice",
        "sender_role": "customer",
        "sender_role_source": "same_row_avatar",
        "content": '[语音] 3"',
        "bubble_rect": [486, 619, 534, 645],
        "quality_flags": ["untranscribed_voice_placeholder"],
    }
    assert_equal(
        image_candidates_without_reliable_typed_message_conflicts(
            [image],
            [untranscribed_voice],
            [],
        ),
        [],
        "trusted untranscribed voice structure must veto image",
    )

    for role, candidate_bounds, text_bounds in (
        ("self", [489, 411, 878, 532], [510, 419, 858, 531]),
        ("customer", [470, 411, 820, 532], [490, 419, 800, 531]),
    ):
        candidate = {
            "bounds": candidate_bounds,
            "side": role,
            "role_facing_edge_surface_continuity": 0.98,
        }
        reliable_text = {
            "id": f"confirmed-{role}-long-text",
            "type": "text",
            "sender_role": role,
            "sender_role_source": "same_row_avatar",
            "content": "你好，10万左右可以先按你的用车需求筛选合适车型。",
            "bubble_rect": text_bounds,
            "avatar_alignment": {"role": role},
        }
        assert_equal(
            image_candidates_without_reliable_typed_message_conflicts(
                [candidate],
                [reliable_text],
                [],
            ),
            [],
            f"reliable {role} text must veto a continuous structural image",
        )
        assert_equal(
            messages_outside_image_bubbles(
                [reliable_text],
                [
                    {
                        "type": "image",
                        "sender_role": role,
                        "bubble_rect": candidate_bounds,
                    }
                ],
            ),
            [reliable_text],
            f"final merge must preserve reliable {role} text",
        )

    invalid_cases = [
        ({**reliable_voice, "voice_anchor": {"item": {"sender_role": "customer"}}}, image),
        ({"type": "voice", "sender_role": "customer", "content": "疑似语音但没有结构证据"}, image),
        (reliable_voice, {**image, "side": "self"}),
        (reliable_voice, {**image, "bounds": [476, 300, 690, 400]}),
    ]
    for voice, candidate in invalid_cases:
        assert_equal(
            image_candidates_without_reliable_typed_message_conflicts(
                [candidate],
                [voice],
                [],
            ),
            [candidate],
            "missing type, role, geometry or overlap proof must preserve image",
        )


def check_self_structural_observation_is_metadata_only() -> None:
    surface = _customer_image_surface()
    messages = self_visual_image_messages_from_current_surface(
        surface,
        [],
        [],
        target="Customer A",
        message_viewport_bounds=_message_viewport(surface),
    )
    assert_equal(len(messages), 1, "a self-side structural image needs one context envelope")
    message = messages[0]
    assert_equal(message.get("sender"), "self", "structural image must be attributed to self")
    assert_equal(message.get("type"), "image", "structural image retains image modality")
    assert_true(bool(message.get("is_self_image")), "structural image must be explicit for the context-only route")
    forbidden = {"bounds", "anchor", "path", "image", "screenshot", "sha256", "bytes"}
    assert_true(not (forbidden & set(message)), f"image envelope may not expose visual artifact data: {message}")


def check_sidecar_has_no_retired_image_export() -> None:
    source = Path(wechat_win32_ocr_sidecar.__file__).read_text(encoding="utf-8")
    assert_true(
        "wechat_image_save_capture" not in source
        and "detect_visual_image_bubbles" not in source
        and "extract_chat_time_markers" not in source,
        "Sidecar must not import or execute the Vision detector",
    )
    assert_true(
        not hasattr(wechat_win32_ocr_sidecar, "self_visual_image_messages_from_current_surface"),
        "retired Sidecar image symbol must be removed, not kept as a facade",
    )


class _Win32Con:
    VK_ESCAPE = 0x1B


class ClipboardCopyOps:
    win32con = _Win32Con()

    def __init__(self, *, generations: list[int]) -> None:
        self.generations = list(generations)
        self.capture_dirs: list[str | None] = []
        self.right_clicks = 0
        self.menu_clicks = 0
        self.surface = _customer_image_surface()
        self.menu = self.surface.copy()
        self._layout_snapshots: dict[int, dict[str, Any]] = {}
        self._popup_layout_snapshot: dict[str, Any] | None = None

    def layout_snapshot_for_image(self, image: Image.Image) -> dict[str, Any]:
        cached = self._layout_snapshots.get(id(image))
        if cached is not None:
            return dict(cached)
        structural = window_layout.build_structural_layout_regions(image)
        snapshot = window_layout.build_layout_snapshot(
            hwnd=100,
            frame_id=window_layout.new_frame_id(100),
            capture_mode=window_layout.CAPTURE_MODE_WINDOW_VISIBLE_SCREEN,
            image_size=image.size,
            capture_screen_origin=[0, 0],
            window_rect=[0, 0, image.size[0], image.size[1]],
            client_rect=[0, 0, image.size[0], image.size[1]],
            client_screen_origin=[0, 0],
            dpi_scale=1.0,
            regions=structural.get("regions") or {},
            anchors=structural.get("anchors") or [],
            confidence=float(structural.get("confidence") or 0.0),
            conflicts=structural.get("conflicts") or [],
            executable=bool(structural.get("ok")),
        )
        self._layout_snapshots[id(image)] = snapshot
        return dict(snapshot)

    def capture_wechat(self, _hwnd: int, *, artifact_dir: str | None = None, label: str = "") -> tuple[Image.Image, str]:
        self.capture_dirs.append(artifact_dir)
        return self.surface, ""

    def capture_wechat_window_visible_screen(self, _hwnd: int, *, artifact_dir: str | None = None, label: str = "") -> tuple[Image.Image, str]:
        self.capture_dirs.append(artifact_dir)
        return self.menu, ""

    def run_ocr(self, image: Image.Image) -> list[dict[str, Any]]:
        if image is self.menu:
            return [{"text": "复制", "left": 600, "top": 488, "right": 636, "bottom": 508, "center_x": 618, "center_y": 498, "confidence": 0.95}]
        return []

    @staticmethod
    def get_window_geometry(_hwnd: int) -> dict[str, int]:
        return {"width": 980, "height": 860}

    @staticmethod
    def parse_messages_from_ocr(
        _items: list[dict[str, Any]],
        _image_size: tuple[int, int],
        *,
        target: str = "",
        screenshot: Image.Image | None = None,
    ) -> list[dict[str, Any]]:
        return []

    @staticmethod
    def blocking_screen_reason(_items: list[dict[str, Any]]) -> str:
        return ""

    def clipboard_sequence_number(self) -> int:
        if len(self.generations) > 1:
            return self.generations.pop(0)
        return self.generations[0]

    def human_window_image_right_click_in_bounds(
        self,
        _hwnd: int,
        x: int,
        y: int,
        *,
        bounds: list[int],
        action_name: str = "",
        expected_snapshot_id: str,
    ) -> dict[str, Any]:
        assert_true(bool(expected_snapshot_id), "right click requires a current layout snapshot")
        self.right_clicks += 1
        return {
            "ok": True,
            "x": x,
            "y": y,
            "screen_x": x,
            "screen_y": y,
            "bounds": bounds,
            "action_name": action_name,
        }

    def human_window_image_click_in_bounds(
        self,
        _hwnd: int,
        x: int,
        y: int,
        *,
        bounds: list[int],
        action_name: str = "",
        expected_snapshot_id: str,
    ) -> dict[str, Any]:
        assert_true(bool(expected_snapshot_id), "menu click requires a popup layout snapshot")
        self.menu_clicks += 1
        return {"ok": True, "x": x, "y": y, "bounds": bounds, "action_name": action_name}

    @staticmethod
    def wait_for_wechat_context_menu_stable() -> int:
        return 180

    def observe_wechat_context_menu(
        self,
        _hwnd: int,
        *,
        anchor_screen: tuple[int, int],
        artifact_dir: str | None,
        label: str,
    ) -> dict[str, Any]:
        assert_true(artifact_dir is None and bool(label), "menu observation must remain transient")
        if self._popup_layout_snapshot is None:
            width, height = self.menu.size
            self._popup_layout_snapshot = window_layout.build_layout_snapshot(
                hwnd=200,
                frame_id=window_layout.new_frame_id(200),
                capture_mode=window_layout.CAPTURE_MODE_WINDOW_VISIBLE_SCREEN,
                image_size=self.menu.size,
                capture_screen_origin=[0, 0],
                window_rect=[0, 0, width, height],
                client_rect=[0, 0, width, height],
                client_screen_origin=[0, 0],
                dpi_scale=1.0,
                regions={"surface_bounds": [0, 0, width, height]},
                confidence=1.0,
                conflicts=[],
                executable=True,
                surface_kind="popup",
                required_region_names=window_layout.POPUP_LAYOUT_REGION_NAMES,
            )
        return {
            "ok": True,
            "menu_hwnd": 200,
            "layout_snapshot_id": str(self._popup_layout_snapshot.get("layout_snapshot_id") or ""),
            "image_size": self.menu.size,
            "local_ocr_items": self.run_ocr(self.menu),
            "anchor_screen": list(anchor_screen),
        }

    @staticmethod
    def humanized_action_sleep(_minimum: int, _maximum: int) -> None:
        return None

    def human_screen_click(self, x: int, y: int, *, action_name: str = "") -> dict[str, Any]:
        self.menu_clicks += 1
        return {"ok": True, "screen_x": x, "screen_y": y, "action_name": action_name}


def check_current_copy_transaction_has_no_file_artifact() -> None:
    ops = ClipboardCopyOps(generations=[70, 71])
    result = execute_wechat_clipboard_image_copy(
        hwnd=100,
        probe={"ok": True},
        target_name="Customer A",
        session_key="wx:copy-contract",
        pending_signal_id="image-1",
        sidecar_ops=ops,
    )
    assert_true(result.get("ok") is True, f"copy transaction should succeed: {result}")
    assert_equal(result.get("state"), "image_clipboard_copied", "copy state is stable")
    assert_equal(result.get("assets"), [], "transaction may not create an image asset")
    assert_equal(result.get("messages"), [], "transaction may not create an image message")
    assert_equal(ops.capture_dirs, [None], "screenshots are transient and may not get an artifact directory")
    transaction = result.get("transaction") or {}
    assert_equal(transaction.get("clipboard_sequence_after"), 71, "new clipboard generation proves the copy")
    assert_true("path" not in json.dumps(result).lower(), "copy result may not expose a filesystem path")


def check_self_copy_transaction_selects_only_self_side() -> None:
    ops = ClipboardCopyOps(generations=[80, 81])
    result = execute_wechat_clipboard_image_copy(
        hwnd=100,
        probe={"ok": True},
        target_name="Customer A",
        session_key="wx:self-copy-contract",
        pending_signal_id="self-image-1",
        side_filter="self",
        sidecar_ops=ops,
    )
    assert_true(result.get("ok") is True, f"self-side copy transaction should succeed: {result}")
    assert_equal((result.get("transaction") or {}).get("visual_side"), "self", "copy target must retain self-side proof until the in-memory consumer returns")
    assert_equal(ops.right_clicks, 1, "self image must cause one bounded context click")
    assert_equal(ops.capture_dirs, [None], "self-side geometry screenshots remain transient")


def check_current_copy_requires_clipboard_generation_change() -> None:
    ops = ClipboardCopyOps(generations=[70])
    result = execute_wechat_clipboard_image_copy(
        hwnd=100,
        probe={"ok": True},
        target_name="Customer A",
        sidecar_ops=ops,
    )
    assert_equal(result.get("ok"), False, "unchanged clipboard must be rejected")
    assert_equal(result.get("reason"), "clipboard_sequence_unchanged_after_copy", "no stale clipboard fallback is allowed")


def check_retired_image_exports_are_removed() -> None:
    capture_module = __import__(
        "apps.wechat_ai_customer_service.optional_plugins.vision.capture.wechat",
        fromlist=["capture"],
    )
    retired = (
        "file_sha256",
        "image_dimensions",
        "wait_for_file_stable",
        "save_visual_bubble_crop",
        "save_clipboard_image_to_path",
        "build_saved_image_asset",
        "build_image_saved_payload",
        "build_visual_bubble_archive_payload",
        "execute_wechat_image_save",
    )
    for name in retired:
        assert_true(not hasattr(capture_module, name), f"retired Vision image export remains: {name}")
    assert_true(
        not (APP_ROOT / "adapters" / "wechat_image_save_capture.py").exists(),
        "retired image adapter module must be removed",
    )


def check_legacy_sidecar_action_rejects_before_platform_probe() -> None:
    original_probe = wechat_win32_ocr_sidecar.ensure_visible_wechat_window

    def forbidden_probe(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("legacy image-save must not begin a window probe")

    wechat_win32_ocr_sidecar.ensure_visible_wechat_window = forbidden_probe
    try:
        result = wechat_win32_ocr_sidecar.run_action(
            argparse.Namespace(action="image-save", target="Customer A", session_key="wx:legacy")
        )
    finally:
        wechat_win32_ocr_sidecar.ensure_visible_wechat_window = original_probe
    assert_equal(result.get("state"), "unsupported_action", "retired sidecar action is absent before platform work")


def assert_true(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def assert_equal(actual: Any, expected: Any, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


if __name__ == "__main__":
    raise SystemExit(main())
