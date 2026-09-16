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
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

PROVIDERS: list[dict] = [
    # ``models`` are the suggestions shown before the provider's own list is fetched (from the docs, 2026-09-16);
    # ``list_url`` is the provider's model-listing endpoint, used by list_models().
    {"id": "deepseek", "label": "DeepSeek", "prefix": "deepseek/", "key_env": "DEEPSEEK_API_KEY", "base_env": "DEEPSEEK_API_BASE",
     "models": ["deepseek-v4-pro", "deepseek-flash"], "site": "https://platform.deepseek.com",
     "list_url": "https://api.deepseek.com/models"},
    {"id": "openai", "label": "OpenAI", "prefix": "openai/", "key_env": "OPENAI_API_KEY", "base_env": "OPENAI_API_BASE",
     "models": ["gpt-6-astra", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"], "site": "https://platform.openai.com",
     "list_url": "https://api.openai.com/v1/models"},
    {"id": "anthropic", "label": "Anthropic", "prefix": "anthropic/", "key_env": "ANTHROPIC_API_KEY", "base_env": "ANTHROPIC_API_BASE",
     "models": ["claude-fable-5-1", "claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"], "site": "https://console.anthropic.com",
     "list_url": "https://api.anthropic.com/v1/models"},
    {"id": "gemini", "label": "Google Gemini", "prefix": "gemini/", "key_env": "GEMINI_API_KEY", "base_env": "GEMINI_API_BASE",
     "models": ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.1-pro-preview", "gemini-2.5-pro"], "site": "https://aistudio.google.com",
     "list_url": "https://generativelanguage.googleapis.com/v1beta/models"},
    {"id": "dashscope", "label": "阿里云百炼 (Qwen)", "prefix": "dashscope/", "key_env": "DASHSCOPE_API_KEY", "base_env": "DASHSCOPE_API_BASE",
     "models": ["qwen3.8-max", "qwen3.8-flash", "qwen3.7-plus"], "site": "https://bailian.console.aliyun.com",
     "list_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/models"},
    {"id": "moonshot", "label": "Moonshot (Kimi)", "prefix": "moonshot/", "key_env": "MOONSHOT_API_KEY", "base_env": "MOONSHOT_API_BASE",
     "models": ["kimi-k3", "kimi-k2.7-code", "kimi-k2.6"], "site": "https://platform.kimi.com",
     "list_url": "https://api.moonshot.cn/v1/models"},
    {"id": "openai_compatible", "label": "OpenAI 兼容接口", "prefix": "openai/", "key_env": "OPENAI_API_KEY", "base_env": "OPENAI_API_BASE",
     "models": [], "needs_base": True, "site": "", "list_url": None},
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


# Model ids that are not chat models, whatever the provider (embeddings, speech, images, moderation, ...).
_NOT_CHAT = re.compile(r"embed|tts|whisper|transcribe|audio|realtime|live|image|dall-e|vision-exp|moderation|rerank|omni|search|sora|video|asr|ocr|wan|imagen|veo|aqa|bison|gecko", re.I)


def list_models(values: dict) -> dict:
    """The provider's own model list, fetched with the given (or stored) key: {ok, models|error, source}."""
    r = resolve({**values, "model": values.get("model") or "x"})
    if r is None:
        return {"ok": False, "error": "请先选择提供商"}
    spec = PROVIDER_BY_ID[r["provider"]]
    if not r["api_key"]:
        return {"ok": False, "error": "没有 API Key，无法拉取列表"}
    if spec["id"] == "openai_compatible":
        url = r["base_url"].rstrip("/") + "/models"
    else:
        url = (r["base_url"].rstrip("/") + ("/v1/models" if spec["id"] in ("openai", "anthropic", "moonshot", "dashscope") else "/models")) if r["base_url"] else spec["list_url"]
    headers = {"User-Agent": "rd-agent-studio"}
    if spec["id"] == "anthropic":
        headers.update({"x-api-key": r["api_key"], "anthropic-version": "2023-06-01"})
    elif spec["id"] == "gemini":
        url += ("&" if "?" in url else "?") + "key=" + r["api_key"] + "&pageSize=200"
    else:
        headers["Authorization"] = "Bearer " + r["api_key"]
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", "replace")[:200]
        return {"ok": False, "error": f"HTTP {error.code}: {body}"}
    except Exception as error:  # noqa: BLE001
        return {"ok": False, "error": str(error)[:200]}
    items = payload.get("data") or payload.get("models") or []
    names = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if spec["id"] == "gemini":
            methods = item.get("supportedGenerationMethods") or []
            if methods and "generateContent" not in methods:
                continue
        name = str(item.get("id") or item.get("name") or "")
        name = name.split("/", 1)[1] if name.startswith("models/") else name
        if name and not _NOT_CHAT.search(name):
            names.append(name)
    names = sorted(dict.fromkeys(names), reverse=True)
    return {"ok": True, "models": names, "source": url.split("?")[0]}
