"""Contract checks for Win32/OCR render diagnostics extraction."""

from __future__ import annotations

from pathlib import Path
import sys

from PIL import Image, ImageDraw


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.wechat_ai_customer_service.adapters import wechat_win32_ocr_sidecar as sidecar  # noqa: E402
from apps.wechat_ai_customer_service.adapters.wechat_win32_ocr import render_diagnostics  # noqa: E402


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_render_diagnostics_module_exports_expected_helpers() -> None:
    for name in ("detect_blank_render", "image_information_score", "likely_foreign_overlay_capture"):
        assert_true(callable(getattr(render_diagnostics, name, None)), f"render helper missing: {name}")


def test_blank_render_detection_matches_sidecar() -> None:
    samples = [
        (Image.new("RGB", (980, 860), "white"), [], {"width": 980, "height": 860}),
        (Image.new("RGB", (980, 860), "black"), [], {"width": 980, "height": 860}),
        (Image.new("RGB", (300, 200), "white"), [], {"width": 300, "height": 200}),
        (Image.new("RGB", (980, 860), "white"), [{"text": "微信"}], {"width": 980, "height": 860}),
    ]
    noisy = Image.new("RGB", (980, 860), "white")
    draw = ImageDraw.Draw(noisy)
    draw.rectangle((20, 20, 260, 160), fill="black")
    samples.append((noisy, [], {"width": 980, "height": 860}))
    for screenshot, ocr_items, geometry in samples:
        assert_true(
            render_diagnostics.detect_blank_render(screenshot, ocr_items, geometry=geometry)
            == sidecar.detect_blank_render(screenshot, ocr_items, geometry=geometry),
            f"blank render mismatch: {(ocr_items, geometry)}",
        )


def test_image_information_score_matches_sidecar() -> None:
    images = [
        Image.new("RGB", (120, 80), "white"),
        Image.new("RGB", (120, 80), "black"),
    ]
    contrast = Image.new("RGB", (120, 80), "white")
    draw = ImageDraw.Draw(contrast)
    draw.rectangle((10, 10, 70, 50), fill="black")
    images.append(contrast)
    for image in images:
        assert_true(
            render_diagnostics.image_information_score(image) == sidecar.image_information_score(image),
            "image information score mismatch",
        )


def test_foreign_overlay_detection_matches_sidecar() -> None:
    samples = [
        [],
        [{"text": "文件传输助手"}, {"text": "搜索"}],
        [{"text": "apps/wechat_ai_customer_servic"}, {"text": "文件已更改"}],
        [{"text": "serverchan"}, {"text": "要求后续变更"}, {"text": "展开显示"}],
    ]
    for items in samples:
        assert_true(
            render_diagnostics.likely_foreign_overlay_capture(items) == sidecar.likely_foreign_overlay_capture(items),
            f"foreign overlay mismatch: {items}",
        )


def main() -> int:
    tests = [
        test_render_diagnostics_module_exports_expected_helpers,
        test_blank_render_detection_matches_sidecar,
        test_image_information_score_matches_sidecar,
        test_foreign_overlay_detection_matches_sidecar,
    ]
    passed = 0
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
        passed += 1
    print(f"All {passed} WeChat Win32/OCR render diagnostics checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
