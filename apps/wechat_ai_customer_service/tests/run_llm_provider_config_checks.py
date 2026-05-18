"""Focused checks for multi-provider LLM configuration."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("WECHAT_CLOUD_REQUIRED", "0")
os.environ.setdefault("WECHAT_CLOUD_STRICT_ONLINE", "0")
os.environ.setdefault("WECHAT_VPS_BASE_URL", "http://localhost:8000")
os.environ.setdefault("WECHAT_CLOUD_REQUIRE_NODE_VERIFIED", "0")

from apps.wechat_ai_customer_service import llm_config as llm_config_module  # noqa: E402
from apps.wechat_ai_customer_service.auth.models import AuthContext, AuthSession, AuthUser, Role  # noqa: E402
from apps.wechat_ai_customer_service.auth.permissions import can_access  # noqa: E402
from apps.wechat_ai_customer_service.admin_backend.app import create_app  # noqa: E402
from apps.wechat_ai_customer_service.admin_backend.auth_context import action_for_request, resource_for_path  # noqa: E402


def assert_equal(actual: Any, expected: Any, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


def assert_true(value: Any, message: str) -> None:
    if not value:
        raise AssertionError(message)


class FakeResponse:
    status = 200

    def __init__(self, body: dict[str, Any] | None = None) -> None:
        self.body = body or {"choices": [{"message": {"content": "OK"}}]}

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.body).encode("utf-8")


def run_checks() -> dict[str, Any]:
    old_path = llm_config_module._LLM_CONFIG_PATH
    old_urlopen = llm_config_module.urllib.request.urlopen
    calls: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="omniauto-llm-config-") as temp_dir:
        llm_config_module._LLM_CONFIG_PATH = Path(temp_dir) / "llm_config.json"

        def fake_urlopen(request: Any, timeout: int = 0, **kwargs: Any) -> FakeResponse:
            calls.append(
                {
                    "url": request.full_url,
                    "headers": dict(request.header_items()),
                    "body": json.loads(request.data.decode("utf-8")) if request.data else None,
                    "timeout": timeout,
                    "kwargs": kwargs,
                }
            )
            if str(request.full_url).endswith("/models"):
                return FakeResponse({"data": [{"id": "gpt-4o-mini"}, {"id": "gpt-4.1"}]})
            return FakeResponse()

        llm_config_module.urllib.request.urlopen = fake_urlopen
        try:
            check_legacy_deepseek_defaults()
            check_openai_compatible_roundtrip_and_probe(calls)
            check_llm_config_permissions_allow_all_authenticated_users()
        finally:
            llm_config_module.urllib.request.urlopen = old_urlopen
            llm_config_module._LLM_CONFIG_PATH = old_path
    return {"ok": True, "checks": 3}


def check_legacy_deepseek_defaults() -> None:
    llm_config_module.save_llm_config({})
    assert_equal(
        llm_config_module.resolve_deepseek_tier_model(tier="flash", read_secret_fn=lambda name: ""),
        "deepseek-v4-flash",
        "legacy DeepSeek flash default should stay stable",
    )
    assert_equal(
        llm_config_module.resolve_deepseek_tier_model(tier="pro", read_secret_fn=lambda name: ""),
        "deepseek-v4-pro",
        "legacy DeepSeek pro default should stay stable",
    )


def check_openai_compatible_roundtrip_and_probe(calls: list[dict[str, Any]]) -> None:
    client = TestClient(create_app())
    response = client.put(
        "/api/system/llm-config",
        json={
            "provider": "openai_compatible",
            "base_url": "https://relay.example/v1/chat/completions",
            "flash_model": "gpt-4o-mini",
            "pro_model": "gpt-4.1",
            "flash_reasoning_effort": "low",
            "pro_reasoning_effort": "high",
            "allow_insecure_tls": True,
            "api_key": "sk-test-provider",
        },
    )
    assert_equal(response.status_code, 200, "save status")
    saved = response.json()
    assert_true(saved.get("ok"), "save should succeed")
    assert_equal(saved.get("provider"), "openai_compatible", "provider should be saved")
    assert_equal(saved.get("base_url"), "https://relay.example/v1", "base URL should be normalized")
    assert_equal(saved.get("flash_model"), "gpt-4o-mini", "flash model should roundtrip")
    assert_equal(saved.get("pro_model"), "gpt-4.1", "pro model should roundtrip")
    assert_equal(saved.get("flash_reasoning_effort"), "low", "flash reasoning effort should roundtrip")
    assert_equal(saved.get("pro_reasoning_effort"), "high", "pro reasoning effort should roundtrip")
    assert_true("medium" in saved.get("reasoning_effort_options", []), "reasoning effort options should be exposed")
    assert_equal(saved.get("available_models"), ["gpt-4o-mini", "gpt-4.1"], "live model options should be exposed")
    assert_true(saved.get("allow_insecure_tls"), "insecure TLS option should roundtrip")
    assert_true(saved.get("api_key_configured"), "API key should be recorded as configured")
    assert_true("sk-test-provider" not in json.dumps(saved), "saved payload must not leak raw API key")

    assert_equal(llm_config_module.read_secret("DEEPSEEK_API_KEY"), "sk-test-provider", "legacy key read should map to active provider")
    assert_equal(llm_config_module.resolve_deepseek_base_url(), "https://relay.example/v1", "legacy base URL should map to active provider")
    assert_equal(
        llm_config_module.resolve_deepseek_tier_model(tier="flash"),
        "gpt-4o-mini",
        "legacy flash model should map to active provider",
    )

    probe = client.post("/api/system/llm-config/test", json={})
    assert_equal(probe.status_code, 200, "probe status")
    payload = probe.json()
    assert_true(payload.get("ok"), "probe should succeed through fake urlopen")
    assert_equal(payload.get("provider"), "openai_compatible", "probe should use active provider")
    assert_equal(calls[-1]["url"], "https://relay.example/v1/chat/completions", "probe should call chat completions")
    assert_equal(calls[-1]["body"]["model"], "gpt-4o-mini", "probe should use flash model")
    assert_equal(calls[-1]["body"]["reasoning_effort"], "low", "probe should send flash reasoning effort")
    assert_equal(calls[-1]["headers"].get("Authorization"), "Bearer sk-test-provider", "probe should send bearer key")

    pro_probe = client.post("/api/system/llm-config/test", json={"route": "pro"})
    assert_equal(pro_probe.status_code, 200, "pro probe status")
    pro_payload = pro_probe.json()
    assert_true(pro_payload.get("ok"), "pro probe should succeed through fake urlopen")
    assert_equal(calls[-1]["body"]["model"], "gpt-4.1", "pro probe should use pro model")
    assert_equal(calls[-1]["body"]["reasoning_effort"], "high", "pro probe should send pro reasoning effort")


def check_llm_config_permissions_allow_all_authenticated_users() -> None:
    assert_equal(resource_for_path("/api/system/llm-config"), "llm_config", "llm config route should use relaxed resource")
    assert_equal(resource_for_path("/api/system/llm-config/test"), "llm_config", "llm config test route should use relaxed resource")
    assert_equal(action_for_request("/api/system/llm-config", "PUT"), "write", "llm config save is a write action")
    assert_equal(action_for_request("/api/system/llm-config/test", "POST"), "write", "llm config test is a write action")
    for role in (Role.ADMIN, Role.CUSTOMER, Role.GUEST):
        context = AuthContext(
            session=AuthSession(
                session_id=f"{role.value}_session",
                user=AuthUser(user_id=f"{role.value}_user", role=role),
            ),
            tenant_id="default",
            authenticated=True,
        )
        assert_true(can_access(context, resource="llm_config", action="read"), f"{role.value} can read llm config")
        assert_true(can_access(context, resource="llm_config", action="write"), f"{role.value} can write llm config")
    guest_context = AuthContext(
        session=AuthSession(
            session_id="local_guest_session",
            user=AuthUser(user_id="local_guest_user", role=Role.GUEST),
        ),
        tenant_id="default",
        authenticated=False,
    )
    assert_true(can_access(guest_context, resource="llm_config", action="write"), "local implicit/dev users can write llm config")


def main() -> int:
    try:
        result = run_checks()
    except Exception as exc:
        print(json.dumps({"ok": False, "error": repr(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
