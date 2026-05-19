"""Shared LLM provider configuration for the WeChat customer-service app."""

from __future__ import annotations

import json
import os
import ssl
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any


DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_PRO_MODEL = "deepseek-v4-pro"
DEFAULT_DEEPSEEK_FLASH_MODEL = "deepseek-v4-flash"
DEFAULT_DEEPSEEK_MODEL = DEFAULT_DEEPSEEK_FLASH_MODEL
DEFAULT_DEEPSEEK_CONTEXT_WINDOW_TOKENS = 1_000_000
DEFAULT_DEEPSEEK_TIMEOUT_SECONDS = 120
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_OPENAI_FLASH_MODEL = "gpt-4o-mini"
DEFAULT_OPENAI_PRO_MODEL = "gpt-4.1"
DEFAULT_LLM_PROVIDER = "deepseek"
LLM_REASONING_EFFORT_OPTIONS = ("", "none", "minimal", "low", "medium", "high", "xhigh")


LLM_PROVIDER_PRESETS: dict[str, dict[str, Any]] = {
    "deepseek": {
        "label": "DeepSeek",
        "api_key_env": "DEEPSEEK_API_KEY",
        "base_url_env": "DEEPSEEK_BASE_URL",
        "model_env": "DEEPSEEK_MODEL",
        "flash_model_env": "DEEPSEEK_FLASH_MODEL",
        "pro_model_env": "DEEPSEEK_PRO_MODEL",
        "flash_reasoning_effort_env": "DEEPSEEK_FLASH_REASONING_EFFORT",
        "pro_reasoning_effort_env": "DEEPSEEK_PRO_REASONING_EFFORT",
        "allow_insecure_tls_env": "DEEPSEEK_ALLOW_INSECURE_TLS",
        "default_base_url": DEFAULT_DEEPSEEK_BASE_URL,
        "default_flash_model": DEFAULT_DEEPSEEK_FLASH_MODEL,
        "default_pro_model": DEFAULT_DEEPSEEK_PRO_MODEL,
        "model_options": [
            DEFAULT_DEEPSEEK_FLASH_MODEL,
            DEFAULT_DEEPSEEK_PRO_MODEL,
            "deepseek-chat",
            "deepseek-reasoner",
        ],
        "aliases": ("deepseek", "deepseek-chat"),
    },
    "openai": {
        "label": "OpenAI / ChatGPT",
        "api_key_env": "OPENAI_API_KEY",
        "base_url_env": "OPENAI_BASE_URL",
        "model_env": "OPENAI_MODEL",
        "flash_model_env": "OPENAI_FLASH_MODEL",
        "pro_model_env": "OPENAI_PRO_MODEL",
        "flash_reasoning_effort_env": "OPENAI_FLASH_REASONING_EFFORT",
        "pro_reasoning_effort_env": "OPENAI_PRO_REASONING_EFFORT",
        "allow_insecure_tls_env": "OPENAI_ALLOW_INSECURE_TLS",
        "default_base_url": DEFAULT_OPENAI_BASE_URL,
        "default_flash_model": DEFAULT_OPENAI_FLASH_MODEL,
        "default_pro_model": DEFAULT_OPENAI_PRO_MODEL,
        "model_options": ["gpt-5.5", "gpt-5.4", "gpt-5.2", "gpt-4o-mini", "gpt-4.1-mini", "gpt-4.1", "gpt-4o"],
        "aliases": ("openai", "gpt", "chatgpt"),
    },
    "openai_compatible": {
        "label": "OpenAI Compatible / Custom",
        "api_key_env": "OPENAI_COMPATIBLE_API_KEY",
        "base_url_env": "OPENAI_COMPATIBLE_BASE_URL",
        "model_env": "OPENAI_COMPATIBLE_MODEL",
        "flash_model_env": "OPENAI_COMPATIBLE_FLASH_MODEL",
        "pro_model_env": "OPENAI_COMPATIBLE_PRO_MODEL",
        "flash_reasoning_effort_env": "OPENAI_COMPATIBLE_FLASH_REASONING_EFFORT",
        "pro_reasoning_effort_env": "OPENAI_COMPATIBLE_PRO_REASONING_EFFORT",
        "allow_insecure_tls_env": "OPENAI_COMPATIBLE_ALLOW_INSECURE_TLS",
        "default_base_url": "",
        "default_flash_model": "",
        "default_pro_model": "",
        "model_options": [],
        "aliases": ("openai-compatible", "openai_compatible", "compatible", "custom", "third_party", "third-party"),
    },
    "qwen": {
        "label": "Alibaba Qwen",
        "api_key_env": "QWEN_API_KEY",
        "base_url_env": "QWEN_BASE_URL",
        "model_env": "QWEN_MODEL",
        "flash_model_env": "QWEN_FLASH_MODEL",
        "pro_model_env": "QWEN_PRO_MODEL",
        "flash_reasoning_effort_env": "QWEN_FLASH_REASONING_EFFORT",
        "pro_reasoning_effort_env": "QWEN_PRO_REASONING_EFFORT",
        "allow_insecure_tls_env": "QWEN_ALLOW_INSECURE_TLS",
        "default_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_flash_model": "qwen-plus",
        "default_pro_model": "qwen-max",
        "model_options": ["qwen-plus", "qwen-max", "qwen-turbo"],
        "aliases": ("qwen", "dashscope", "aliyun", "alibaba"),
    },
    "moonshot": {
        "label": "Moonshot / Kimi",
        "api_key_env": "MOONSHOT_API_KEY",
        "base_url_env": "MOONSHOT_BASE_URL",
        "model_env": "MOONSHOT_MODEL",
        "flash_model_env": "MOONSHOT_FLASH_MODEL",
        "pro_model_env": "MOONSHOT_PRO_MODEL",
        "flash_reasoning_effort_env": "MOONSHOT_FLASH_REASONING_EFFORT",
        "pro_reasoning_effort_env": "MOONSHOT_PRO_REASONING_EFFORT",
        "allow_insecure_tls_env": "MOONSHOT_ALLOW_INSECURE_TLS",
        "default_base_url": "https://api.moonshot.cn/v1",
        "default_flash_model": "moonshot-v1-8k",
        "default_pro_model": "moonshot-v1-32k",
        "model_options": ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"],
        "aliases": ("moonshot", "kimi"),
    },
    "zhipu": {
        "label": "Zhipu GLM",
        "api_key_env": "ZHIPU_API_KEY",
        "base_url_env": "ZHIPU_BASE_URL",
        "model_env": "ZHIPU_MODEL",
        "flash_model_env": "ZHIPU_FLASH_MODEL",
        "pro_model_env": "ZHIPU_PRO_MODEL",
        "flash_reasoning_effort_env": "ZHIPU_FLASH_REASONING_EFFORT",
        "pro_reasoning_effort_env": "ZHIPU_PRO_REASONING_EFFORT",
        "allow_insecure_tls_env": "ZHIPU_ALLOW_INSECURE_TLS",
        "default_base_url": "https://open.bigmodel.cn/api/paas/v4",
        "default_flash_model": "glm-4-flash",
        "default_pro_model": "glm-4-plus",
        "model_options": ["glm-4-flash", "glm-4-plus", "glm-4"],
        "aliases": ("zhipu", "bigmodel", "glm"),
    },
    "siliconflow": {
        "label": "SiliconFlow",
        "api_key_env": "SILICONFLOW_API_KEY",
        "base_url_env": "SILICONFLOW_BASE_URL",
        "model_env": "SILICONFLOW_MODEL",
        "flash_model_env": "SILICONFLOW_FLASH_MODEL",
        "pro_model_env": "SILICONFLOW_PRO_MODEL",
        "flash_reasoning_effort_env": "SILICONFLOW_FLASH_REASONING_EFFORT",
        "pro_reasoning_effort_env": "SILICONFLOW_PRO_REASONING_EFFORT",
        "allow_insecure_tls_env": "SILICONFLOW_ALLOW_INSECURE_TLS",
        "default_base_url": "https://api.siliconflow.cn/v1",
        "default_flash_model": "",
        "default_pro_model": "",
        "model_options": [],
        "aliases": ("siliconflow", "silicon_flow", "silicon-flow"),
    },
}

_PROVIDER_ALIASES = {
    alias: provider_id
    for provider_id, preset in LLM_PROVIDER_PRESETS.items()
    for alias in (provider_id, *preset.get("aliases", ()))
}


_LLM_CONFIG_PATH: Path | None = None


def llm_config_path() -> Path:
    global _LLM_CONFIG_PATH
    if _LLM_CONFIG_PATH is None:
        root = Path(__file__).resolve().parent
        _LLM_CONFIG_PATH = root.parents[1] / "runtime" / "apps" / "wechat_ai_customer_service" / "llm_config.json"
    return _LLM_CONFIG_PATH


def load_llm_config() -> dict[str, str]:
    path = llm_config_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return {str(k): str(v) for k, v in payload.items() if isinstance(v, str)}
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def save_llm_config(config: dict[str, str]) -> None:
    path = llm_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


SecretReader = Callable[[str], str]


def read_secret(name: str) -> str:
    """Read a secret from config file first, then process env, then Windows registry."""
    config = load_llm_config()
    if name == "DEEPSEEK_API_KEY":
        provider = active_llm_provider(config=config)
        if provider != "deepseek":
            return resolve_llm_api_key(provider=provider, config=config)
    if name == "DEEPSEEK_BASE_URL":
        provider = active_llm_provider(config=config)
        if provider != "deepseek":
            return resolve_llm_base_url(provider=provider, config=config)
    if name in {"DEEPSEEK_MODEL", "DEEPSEEK_FLASH_MODEL"}:
        provider = active_llm_provider(config=config)
        if provider != "deepseek":
            return resolve_llm_tier_model(provider=provider, tier="flash", config=config)
    if name == "DEEPSEEK_PRO_MODEL":
        provider = active_llm_provider(config=config)
        if provider != "deepseek":
            return resolve_llm_tier_model(provider=provider, tier="pro", config=config)
    if name == "DEEPSEEK_FLASH_REASONING_EFFORT":
        provider = active_llm_provider(config=config)
        if provider != "deepseek":
            return resolve_llm_reasoning_effort(provider=provider, tier="flash", config=config)
    if name == "DEEPSEEK_PRO_REASONING_EFFORT":
        provider = active_llm_provider(config=config)
        if provider != "deepseek":
            return resolve_llm_reasoning_effort(provider=provider, tier="pro", config=config)
    return _read_named_value(name, config=config)


def normalize_llm_provider(provider: Any) -> str:
    text = str(provider or "").strip().lower().replace("-", "_")
    if not text:
        return DEFAULT_LLM_PROVIDER
    return _PROVIDER_ALIASES.get(text, text if text in LLM_PROVIDER_PRESETS else "openai_compatible")


def active_llm_provider(*, config: dict[str, str] | None = None) -> str:
    return configured_llm_provider(config=config) or DEFAULT_LLM_PROVIDER


def configured_llm_provider(*, config: dict[str, str] | None = None) -> str:
    config = config if config is not None else load_llm_config()
    value = (
        config.get("LLM_PROVIDER")
        or config.get("ACTIVE_LLM_PROVIDER")
        or os.getenv("LLM_PROVIDER")
        or os.getenv("ACTIVE_LLM_PROVIDER")
        or _read_registry_value("LLM_PROVIDER")
        or _read_registry_value("ACTIVE_LLM_PROVIDER")
    )
    return normalize_llm_provider(value) if value else ""


def resolve_effective_llm_provider(
    explicit_provider: Any = None,
    *,
    read_secret_fn: SecretReader | None = read_secret,
) -> str:
    explicit = str(explicit_provider or "").strip()
    if explicit.lower() == "manual_json":
        return "manual_json"
    if read_secret_fn is read_secret:
        configured = configured_llm_provider()
        if configured:
            return configured
    if explicit:
        return normalize_llm_provider(explicit)
    return DEFAULT_LLM_PROVIDER


def active_provider_overrides_explicit(
    explicit_provider: Any = None,
    effective_provider: Any | None = None,
    *,
    config: dict[str, str] | None = None,
    read_secret_fn: SecretReader | None = read_secret,
) -> bool:
    """Return True when the global active provider intentionally overrides a module default.

    Tenant configs often keep provider-scoped defaults such as
    ``provider=deepseek`` and ``model=deepseek-v4-flash``. When the operator
    switches the active provider to OpenAI, those provider-scoped values should
    not keep leaking into individual modules.
    """
    explicit = str(explicit_provider or "").strip()
    if not explicit or explicit.lower() == "manual_json":
        return False
    if read_secret_fn is not read_secret:
        return False
    configured = configured_llm_provider(config=config)
    if not configured:
        return False
    explicit_id = normalize_llm_provider(explicit)
    effective_id = normalize_llm_provider(effective_provider or configured)
    return bool(effective_id == configured and explicit_id != configured)


def llm_provider_preset(provider: Any) -> dict[str, Any]:
    provider_id = normalize_llm_provider(provider)
    return LLM_PROVIDER_PRESETS.get(provider_id, LLM_PROVIDER_PRESETS[DEFAULT_LLM_PROVIDER])


def explicit_model_matches_provider(provider: Any, model: Any) -> bool:
    """Guard against stale provider-scoped model names after provider switches."""
    provider_id = normalize_llm_provider(provider)
    if provider_id == "openai_compatible":
        return True
    detected = detect_provider_from_model_name(model)
    return not detected or detected == provider_id


def detect_provider_from_model_name(model: Any) -> str:
    text = str(model or "").strip().lower()
    if not text:
        return ""
    provider_prefixes = {
        "deepseek": ("deepseek",),
        "openai": ("gpt-", "o1", "o3", "o4", "o5"),
        "qwen": ("qwen",),
        "moonshot": ("moonshot", "kimi"),
        "zhipu": ("glm", "charglm"),
    }
    for provider_id, prefixes in provider_prefixes.items():
        if any(text.startswith(prefix) for prefix in prefixes):
            return provider_id
    return ""


def explicit_base_url_matches_provider(provider: Any, base_url: Any) -> bool:
    """Allow custom gateways, but ignore URLs that clearly belong to another provider."""
    provider_id = normalize_llm_provider(provider)
    if provider_id == "openai_compatible":
        return True
    detected = detect_provider_from_base_url(base_url)
    return not detected or detected == provider_id


def detect_provider_from_base_url(base_url: Any) -> str:
    text = str(base_url or "").strip().lower()
    if not text:
        return ""
    provider_domains = {
        "deepseek": ("deepseek.com",),
        "openai": ("openai.com",),
        "qwen": ("dashscope.aliyuncs.com", "aliyuncs.com"),
        "moonshot": ("moonshot.cn",),
        "zhipu": ("bigmodel.cn",),
        "siliconflow": ("siliconflow.cn",),
    }
    for provider_id, domains in provider_domains.items():
        if any(domain in text for domain in domains):
            return provider_id
    return ""


def llm_provider_options(*, config: dict[str, str] | None = None) -> list[dict[str, Any]]:
    config = config if config is not None else load_llm_config()
    options = []
    for provider_id, preset in LLM_PROVIDER_PRESETS.items():
        options.append(
            {
                "id": provider_id,
                "label": str(preset.get("label") or provider_id),
                "base_url": resolve_llm_base_url(provider=provider_id, config=config),
                "flash_model": resolve_llm_tier_model(provider=provider_id, tier="flash", config=config),
                "pro_model": resolve_llm_tier_model(provider=provider_id, tier="pro", config=config),
                "flash_reasoning_effort": resolve_llm_reasoning_effort(provider=provider_id, tier="flash", config=config),
                "pro_reasoning_effort": resolve_llm_reasoning_effort(provider=provider_id, tier="pro", config=config),
                "model_options": list(preset.get("model_options") or []),
                "api_key_configured": bool(resolve_llm_api_key(provider=provider_id, config=config)),
                "allow_insecure_tls": resolve_llm_allow_insecure_tls(provider=provider_id, config=config),
            }
        )
    return options


def resolve_llm_api_key(
    *,
    provider: Any | None = None,
    config: dict[str, str] | None = None,
    read_secret_fn: SecretReader | None = None,
) -> str:
    provider_id = normalize_llm_provider(provider or active_llm_provider(config=config))
    preset = llm_provider_preset(provider_id)
    names = [str(preset.get("api_key_env") or "")]
    if provider_id == "openai_compatible":
        names.append("LLM_API_KEY")
    return _first_value(names, config=config, read_secret_fn=read_secret_fn)


def resolve_llm_base_url(
    *,
    provider: Any | None = None,
    explicit_base_url: str | None = None,
    config: dict[str, str] | None = None,
    read_secret_fn: SecretReader | None = None,
) -> str:
    explicit = normalize_llm_base_url(explicit_base_url)
    provider_id = normalize_llm_provider(provider or active_llm_provider(config=config))
    if explicit and explicit_base_url_matches_provider(provider_id, explicit):
        return explicit
    preset = llm_provider_preset(provider_id)
    names = [str(preset.get("base_url_env") or "")]
    if provider_id == "openai_compatible":
        names.append("LLM_BASE_URL")
    configured = normalize_llm_base_url(_first_value(names, config=config, read_secret_fn=read_secret_fn))
    return configured or str(preset.get("default_base_url") or "").strip()


def resolve_llm_model(
    *,
    provider: Any | None = None,
    explicit_model: str | None = None,
    config: dict[str, str] | None = None,
    read_secret_fn: SecretReader | None = None,
) -> str:
    explicit = str(explicit_model or "").strip()
    provider_id = normalize_llm_provider(provider or active_llm_provider(config=config))
    if explicit and explicit_model_matches_provider(provider_id, explicit):
        return explicit
    preset = llm_provider_preset(provider_id)
    names = [str(preset.get("model_env") or ""), str(preset.get("flash_model_env") or "")]
    if provider_id == "openai_compatible":
        names.extend(["LLM_MODEL", "LLM_FLASH_MODEL"])
    configured = _first_value(names, config=config, read_secret_fn=read_secret_fn).strip()
    return configured or str(preset.get("default_flash_model") or "").strip()


def resolve_llm_tier_model(
    *,
    provider: Any | None = None,
    tier: str,
    explicit_model: str | None = None,
    config: dict[str, str] | None = None,
    read_secret_fn: SecretReader | None = None,
) -> str:
    explicit = str(explicit_model or "").strip()
    provider_id = normalize_llm_provider(provider or active_llm_provider(config=config))
    if explicit and explicit_model_matches_provider(provider_id, explicit):
        return explicit
    preset = llm_provider_preset(provider_id)
    normalized = normalize_deepseek_model_tier(tier)
    if normalized == "pro":
        names = [str(preset.get("pro_model_env") or ""), str(preset.get("model_env") or "")]
        if provider_id == "openai_compatible":
            names.extend(["LLM_PRO_MODEL", "LLM_MODEL"])
        configured = _first_value(names, config=config, read_secret_fn=read_secret_fn).strip()
        return configured or str(preset.get("default_pro_model") or preset.get("default_flash_model") or "").strip()
    names = [str(preset.get("flash_model_env") or ""), str(preset.get("model_env") or "")]
    if provider_id == "openai_compatible":
        names.extend(["LLM_FLASH_MODEL", "LLM_MODEL"])
    configured = _first_value(names, config=config, read_secret_fn=read_secret_fn).strip()
    return configured or str(preset.get("default_flash_model") or "").strip()


def normalize_llm_reasoning_effort(value: Any) -> str:
    text = str(value or "").strip().lower().replace("_", "-")
    aliases = {
        "auto": "",
        "default": "",
        "inherit": "",
        "off": "",
        "disabled": "",
        "disable": "",
        "x-high": "xhigh",
        "extra-high": "xhigh",
        "extra": "xhigh",
    }
    text = aliases.get(text, text).replace("-", "")
    return text if text in LLM_REASONING_EFFORT_OPTIONS else ""


def resolve_llm_reasoning_effort(
    *,
    provider: Any | None = None,
    tier: str,
    explicit_value: Any | None = None,
    config: dict[str, str] | None = None,
    read_secret_fn: SecretReader | None = None,
) -> str:
    if explicit_value is not None:
        return normalize_llm_reasoning_effort(explicit_value)
    provider_id = normalize_llm_provider(provider or active_llm_provider(config=config))
    preset = llm_provider_preset(provider_id)
    normalized = normalize_deepseek_model_tier(tier)
    if normalized == "pro":
        names = [str(preset.get("pro_reasoning_effort_env") or "")]
        if provider_id == "openai_compatible":
            names.append("LLM_PRO_REASONING_EFFORT")
    else:
        names = [str(preset.get("flash_reasoning_effort_env") or "")]
        if provider_id == "openai_compatible":
            names.append("LLM_FLASH_REASONING_EFFORT")
    return normalize_llm_reasoning_effort(_first_value(names, config=config, read_secret_fn=read_secret_fn))


def apply_llm_reasoning_effort(
    payload: dict[str, Any],
    *,
    provider: Any | None = None,
    tier: str = "flash",
    explicit_value: Any | None = None,
    config: dict[str, str] | None = None,
    read_secret_fn: SecretReader | None = read_secret,
) -> str:
    effort = resolve_llm_reasoning_effort(
        provider=provider or _legacy_provider_for_reader(read_secret_fn) if read_secret_fn else provider,
        tier=tier,
        explicit_value=explicit_value,
        config=config,
        read_secret_fn=read_secret_fn,
    )
    if effort:
        payload["reasoning_effort"] = effort
    return effort


def resolve_llm_allow_insecure_tls(
    *,
    provider: Any | None = None,
    explicit_value: Any | None = None,
    config: dict[str, str] | None = None,
    read_secret_fn: SecretReader | None = None,
) -> bool:
    if explicit_value is not None:
        return parse_bool(explicit_value, default=False)
    provider_id = normalize_llm_provider(provider or active_llm_provider(config=config))
    preset = llm_provider_preset(provider_id)
    names = [str(preset.get("allow_insecure_tls_env") or "")]
    if provider_id == "openai_compatible":
        names.append("LLM_ALLOW_INSECURE_TLS")
    return parse_bool(_first_value(names, config=config, read_secret_fn=read_secret_fn), default=False)


def llm_urlopen(
    request: urllib.request.Request,
    *,
    timeout: int | float,
    provider: Any | None = None,
    allow_insecure_tls: Any | None = None,
):
    if resolve_llm_allow_insecure_tls(provider=provider, explicit_value=allow_insecure_tls):
        context = ssl._create_unverified_context()
        return urllib.request.urlopen(request, timeout=timeout, context=context)
    return urllib.request.urlopen(request, timeout=timeout)


def normalize_llm_base_url(value: str | None) -> str:
    text = str(value or "").strip().rstrip("/")
    lower = text.lower()
    for suffix in ("/chat/completions", "/models"):
        if lower.endswith(suffix):
            text = text[: -len(suffix)].rstrip("/")
            lower = text.lower()
    return text


def _legacy_provider_for_reader(read_secret_fn: SecretReader) -> str:
    if read_secret_fn is read_secret:
        return active_llm_provider()
    return DEFAULT_LLM_PROVIDER


def _first_value(
    names: list[str],
    *,
    config: dict[str, str] | None = None,
    read_secret_fn: SecretReader | None = None,
) -> str:
    for name in names:
        if not name:
            continue
        if read_secret_fn is not None and read_secret_fn is not read_secret:
            value = str(read_secret_fn(name) or "").strip()
        else:
            value = _read_named_value(name, config=config)
        if value:
            return value
    return ""


def _read_named_value(name: str, *, config: dict[str, str] | None = None) -> str:
    if not name:
        return ""
    payload = config if config is not None else load_llm_config()
    value = payload.get(name)
    if value:
        return value
    value = os.getenv(name)
    if value:
        return value
    return _read_registry_value(name)


def _read_registry_value(name: str) -> str:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            registry_value, _ = winreg.QueryValueEx(key, name)
            return str(registry_value)
    except Exception:
        return ""


def resolve_deepseek_model(
    *,
    explicit_model: str | None = None,
    read_secret_fn: SecretReader = read_secret,
) -> str:
    return (
        resolve_llm_model(
            provider=_legacy_provider_for_reader(read_secret_fn),
            explicit_model=explicit_model,
            read_secret_fn=read_secret_fn,
        )
        or DEFAULT_DEEPSEEK_MODEL
    )


def resolve_deepseek_tier_model(
    *,
    tier: str,
    explicit_model: str | None = None,
    read_secret_fn: SecretReader = read_secret,
) -> str:
    """Resolve the model for a quality tier.

    `DEEPSEEK_MODEL` remains a legacy global override. Flash and Pro can be
    configured independently with `DEEPSEEK_FLASH_MODEL` and
    `DEEPSEEK_PRO_MODEL` so cost routing does not accidentally collapse back to
    one global model.
    """
    normalized = normalize_deepseek_model_tier(tier)
    default = DEFAULT_DEEPSEEK_FLASH_MODEL if normalized == "flash" else DEFAULT_DEEPSEEK_PRO_MODEL
    return (
        resolve_llm_tier_model(
            provider=_legacy_provider_for_reader(read_secret_fn),
            tier=normalized,
            explicit_model=explicit_model,
            read_secret_fn=read_secret_fn,
        )
        or default
    )


def normalize_deepseek_model_tier(value: str | None) -> str:
    text = str(value or "").strip().lower()
    if text in {"flash", "fast", "cheap", "economy", "lite"}:
        return "flash"
    if text in {"pro", "quality", "reasoning", "deep"}:
        return "pro"
    return "flash"


def resolve_deepseek_base_url(
    *,
    explicit_base_url: str | None = None,
    read_secret_fn: SecretReader = read_secret,
) -> str:
    return (
        resolve_llm_base_url(
            provider=_legacy_provider_for_reader(read_secret_fn),
            explicit_base_url=explicit_base_url,
            read_secret_fn=read_secret_fn,
        )
        or DEFAULT_DEEPSEEK_BASE_URL
    )


def resolve_deepseek_max_tokens(
    default: int,
    *,
    read_secret_fn: SecretReader = read_secret,
) -> int:
    return positive_int(read_secret_fn("DEEPSEEK_MAX_TOKENS"), default)


def resolve_deepseek_timeout(
    default: int = DEFAULT_DEEPSEEK_TIMEOUT_SECONDS,
    *,
    read_secret_fn: SecretReader = read_secret,
) -> int:
    return positive_int(read_secret_fn("DEEPSEEK_TIMEOUT_SECONDS"), default)


def positive_int(value: str | int | None, default: int) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return max(1, int(default))
    return parsed if parsed > 0 else max(1, int(default))


def parse_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if not text:
        return bool(default)
    if text in {"1", "true", "yes", "y", "on", "allow", "allowed", "insecure"}:
        return True
    if text in {"0", "false", "no", "n", "off", "deny", "denied", "secure"}:
        return False
    return bool(default)
