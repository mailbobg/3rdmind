"""LLM settings for research runs: provider, model, API key and base URL, kept in studio_data/llm.json.

RD-Agent reads its model through LiteLLM (``CHAT_MODEL`` like ``deepseek/deepseek-chat``) and the provider's
key from the provider's own environment variable. The server starts with whatever the .env file supplied; a
saved Studio setting takes over for every research process started afterwards (it is applied to the child's
environment before rdagent's settings modules import), so switching provider needs no restart. Keys stay in
the local file, mode 0600, and are never sent back to the browser beyond their last four characters.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

PROVIDERS: list[dict] = [
    {"id": "deepseek", "label": "DeepSeek", "prefix": "deepseek/", "key_env": "DEEPSEEK_API_KEY", "base_env": "DEEPSEEK_API_BASE",
     "models": ["deepseek-chat", "deepseek-reasoner"], "site": "https://platform.deepseek.com"},
    {"id": "openai", "label": "OpenAI", "prefix": "openai/", "key_env": "OPENAI_API_KEY", "base_env": "OPENAI_API_BASE",
     "models": ["gpt-5", "gpt-5-mini", "gpt-4.1", "gpt-4o"], "site": "https://platform.openai.com"},
    {"id": "anthropic", "label": "Anthropic", "prefix": "anthropic/", "key_env": "ANTHROPIC_API_KEY", "base_env": "ANTHROPIC_API_BASE",
     "models": ["claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5-20251001"], "site": "https://console.anthropic.com"},
    {"id": "gemini", "label": "Google Gemini", "prefix": "gemini/", "key_env": "GEMINI_API_KEY", "base_env": "GEMINI_API_BASE",
     "models": ["gemini-2.5-pro", "gemini-2.5-flash"], "site": "https://aistudio.google.com"},
    {"id": "dashscope", "label": "阿里云百炼 (Qwen)", "prefix": "dashscope/", "key_env": "DASHSCOPE_API_KEY", "base_env": "DASHSCOPE_API_BASE",
     "models": ["qwen3-max", "qwen-plus", "qwen3-coder-plus"], "site": "https://bailian.console.aliyun.com"},
    {"id": "moonshot", "label": "Moonshot (Kimi)", "prefix": "moonshot/", "key_env": "MOONSHOT_API_KEY", "base_env": "MOONSHOT_API_BASE",
     "models": ["kimi-k2-0905-preview", "kimi-k2-turbo-preview"], "site": "https://platform.moonshot.cn"},
    {"id": "openai_compatible", "label": "OpenAI 兼容接口", "prefix": "openai/", "key_env": "OPENAI_API_KEY", "base_env": "OPENAI_API_BASE",
     "models": [], "needs_base": True, "site": ""},
]
PROVIDER_BY_ID = {p["id"]: p for p in PROVIDERS}

_settings_path: Path | None = None


def configure(settings_path: Path) -> None:
    global _settings_path
    _settings_path = settings_path


def _load() -> dict:
    if _settings_path is None or not _settings_path.is_file():
        return {}
    try:
        return json.loads(_settings_path.read_text())
    except (OSError, ValueError):
        return {}


def _write(data: dict) -> None:
    assert _settings_path is not None
    _settings_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _settings_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    os.chmod(tmp, 0o600)
    tmp.replace(_settings_path)


def _hint(key: str | None) -> str:
    key = key or ""
    return f"…{key[-4:]}" if len(key) >= 8 else ("已设置" if key else "")


def _provider_from_model(model: str) -> str | None:
    for p in PROVIDERS:
        if p["id"] != "openai_compatible" and model.startswith(p["prefix"]):
            return p["id"]
    return None


def env_settings() -> dict:
    """What the server process itself inherited from .env, as a settings-like record (never exposes the key)."""
    model = os.environ.get("LITELLM_CHAT_MODEL") or os.environ.get("CHAT_MODEL") or ""
    provider_id = _provider_from_model(model)
    if provider_id is None and model:
        provider_id = "openai_compatible" if os.environ.get("OPENAI_API_BASE") else ("openai" if os.environ.get("OPENAI_API_KEY") else None)
    provider = PROVIDER_BY_ID.get(provider_id or "")
    key = os.environ.get(provider["key_env"], "") if provider else ""
    return {
        "provider": provider_id, "model": model.split("/", 1)[1] if provider and provider["id"] != "openai_compatible" and "/" in model else model,
        "base_url": os.environ.get(provider["base_env"], "") if provider else "",
        "key_hint": _hint(key), "has_key": bool(key),
        "max_retry": int(os.environ.get("LITELLM_MAX_RETRY") or os.environ.get("MAX_RETRY") or 10),
    }


def status() -> dict:
    """Current settings for the UI: the saved Studio record if any, else what .env gave the server."""
    saved = _load()
    keys = saved.get("keys") or {}
    if saved.get("provider"):
        provider = saved["provider"]
        # A provider without a stored key falls back to the key the server inherited from .env, if any.
        key = keys.get(provider) or os.environ.get(PROVIDER_BY_ID[provider]["key_env"], "") if provider in PROVIDER_BY_ID else ""
        current = {
            "provider": provider, "model": saved.get("model", ""), "base_url": saved.get("base_url", ""),
            "key_hint": _hint(key), "has_key": bool(key), "key_from_env": bool(key) and not keys.get(provider),
            "max_retry": int(saved.get("max_retry") or 10), "source": "studio", "updated": saved.get("updated"),
        }
    else:
        current = {**env_settings(), "source": "env", "updated": None}
    current["saved_keys"] = {p["id"]: _hint(keys.get(p["id"])) for p in PROVIDERS if keys.get(p["id"])}
    return {"current": current, "providers": PROVIDERS, "path": str(_settings_path) if _settings_path else None}


def save(values: dict) -> dict:
    """Merge ``values`` (provider, model, api_key, base_url, max_retry) into the file. An empty api_key keeps the
    provider's stored key; ``clear_key`` drops it."""
    provider = str(values.get("provider") or "").strip()
    if provider not in PROVIDER_BY_ID:
        raise ValueError(f"未知的提供商 {provider!r}")
    spec = PROVIDER_BY_ID[provider]
    model = str(values.get("model") or "").strip()
    if not model:
        raise ValueError("请填写模型名")
    base_url = str(values.get("base_url") or "").strip()
    if spec.get("needs_base") and not base_url:
        raise ValueError("OpenAI 兼容接口需要填写 Base URL")
    try:
        max_retry = int(values.get("max_retry") or 10)
    except (TypeError, ValueError) as error:
        raise ValueError("最大重试次数必须是整数") from error
    if not 1 <= max_retry <= 50:
        raise ValueError("最大重试次数应在 1–50 之间")
    data = _load()
    keys = dict(data.get("keys") or {})
    api_key = str(values.get("api_key") or "").strip()
    if api_key:
        keys[provider] = api_key
    elif values.get("clear_key"):
        keys.pop(provider, None)
    data.update({"provider": provider, "model": model, "base_url": base_url, "max_retry": max_retry, "keys": keys,
                 "updated": time.strftime("%Y-%m-%d %H:%M:%S")})
    _write(data)
    return status()


def resolve(values: dict | None = None) -> dict | None:
    """The effective {model, api_key, base_url, key_env, base_env, max_retry} for a run, from ``values`` (a form
    being tested, falling back to the stored key) or from the saved settings; None when nothing is saved."""
    saved = _load()
    keys = saved.get("keys") or {}
    source = dict(values) if values else saved
    provider = source.get("provider")
    spec = PROVIDER_BY_ID.get(provider or "")
    if spec is None or not source.get("model"):
        return None
    model = str(source["model"])
    if spec["id"] != "openai_compatible" and "/" not in model:
        model = spec["prefix"] + model
    elif spec["id"] == "openai_compatible" and "/" not in model:
        model = spec["prefix"] + model
    api_key = str(source.get("api_key") or "") or keys.get(provider, "") or os.environ.get(spec["key_env"], "")
    return {"provider": provider, "model": model, "api_key": api_key, "base_url": str(source.get("base_url") or ""),
            "key_env": spec["key_env"], "base_env": spec["base_env"], "max_retry": int(source.get("max_retry") or saved.get("max_retry") or 10)}


def env() -> dict[str, str]:
    """Environment variables that make a research process use the saved settings; empty when none are saved."""
    r = resolve()
    if r is None:
        return {}
    out = {"CHAT_MODEL": r["model"], "LITELLM_CHAT_MODEL": r["model"], "MAX_RETRY": str(r["max_retry"]), "LITELLM_MAX_RETRY": str(r["max_retry"])}
    if r["api_key"]:
        out[r["key_env"]] = r["api_key"]
    if r["base_url"]:
        out[r["base_env"]] = r["base_url"]
        if r["provider"] == "openai_compatible":
            out["OPENAI_BASE_URL"] = r["base_url"]
    return out


def test_connection(values: dict) -> dict:
    """One tiny completion with the given (or saved) settings; returns {ok, reply|error, seconds, model}."""
    r = resolve(values)
    if r is None:
        return {"ok": False, "error": "请先选择提供商并填写模型名"}
    if not r["api_key"]:
        return {"ok": False, "error": "没有 API Key"}
    import litellm  # heavy; imported on demand

    started = time.monotonic()
    try:
        kwargs = {"model": r["model"], "api_key": r["api_key"], "max_tokens": 64, "timeout": 40,
                  "messages": [{"role": "user", "content": "Reply with the single word OK."}]}
        if r["base_url"]:
            kwargs["api_base"] = r["base_url"]
        response = litellm.completion(**kwargs)
        reply = (response.choices[0].message.content or "").strip()
        return {"ok": True, "reply": reply, "seconds": round(time.monotonic() - started, 2), "model": r["model"]}
    except Exception as error:  # noqa: BLE001
        return {"ok": False, "error": str(error).splitlines()[0][:300], "seconds": round(time.monotonic() - started, 2), "model": r["model"]}
