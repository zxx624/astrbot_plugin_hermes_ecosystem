"""
AstrBot Hermes Ecosystem Plugin

A publishable AstrBot plugin that connects Hermes Agent to AstrBot:
1. Registers `hermes_chat_completion` as a model provider adapter.
2. Keeps all user-editable connection values in the plugin configuration panel.
3. Provides commands to generate/sync/check the AstrBot provider entry.

No real URL, API key, token, or password is hardcoded in this source file.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import Provider
from astrbot.api.star import Context, Star
from astrbot.core.agent.message import ContentPart, Message
from astrbot.core.agent.tool import ToolSet
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.provider import register as provider_register_module
from astrbot.core.provider.entities import LLMResponse, ToolCallsResult
from astrbot.core.provider.register import register_provider_adapter

PLUGIN_NAME = "astrbot_plugin_hermes_ecosystem"
PROVIDER_TYPE = "hermes_chat_completion"
DEFAULT_MODEL = "hermes-agent"
DEFAULT_API_BASE = "http://127.0.0.1:8642/v1"
CONFIG_FILENAME = f"{PLUGIN_NAME}_config.json"


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on", "启用", "是"}


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _parse_json_object(value: Any, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if default is None:
        default = {}
    if isinstance(value, dict):
        return value
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else default
    except Exception:
        return default


def _json_object_error(value: Any, field_name: str) -> str | None:
    if isinstance(value, dict) or value is None or str(value).strip() == "":
        return None
    try:
        parsed = json.loads(str(value).strip())
    except Exception as exc:
        return f"{field_name} 不是合法 JSON：{exc}"
    if not isinstance(parsed, dict):
        return f"{field_name} 必须是 JSON 对象，例如 {{}} 或 {{\"X-Client\":\"AstrBot\"}}"
    return None


def _normalize_api_base(value: Any) -> str:
    text = str(value or DEFAULT_API_BASE).strip().rstrip("/")
    # 用户常会填 http://host:port；这里自动补 /v1，降低新手配置难度。
    if text and not text.endswith("/v1"):
        text = text + "/v1"
    return text


def _health_url_from_api_base(api_base: str) -> str:
    api_base = str(api_base or "").rstrip("/")
    if api_base.endswith("/v1"):
        return api_base[:-3] + "/health"
    return api_base + "/health"


def _validate_api_base(api_base: str) -> str | None:
    parsed = urlsplit(api_base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "api_base 必须是完整 HTTP 地址，例如 http://127.0.0.1:8642/v1"
    if not api_base.rstrip("/").endswith("/v1"):
        return "api_base 建议以 /v1 结尾；插件会自动补齐，但请优先填写 http://地址:端口/v1"
    return None


def _resolve_env_ref(value: str) -> str:
    """Resolve `$ENV_NAME` or `${ENV_NAME}` values, otherwise return the original string."""
    value = value or ""
    if value.startswith("${") and value.endswith("}") and len(value) > 3:
        return os.getenv(value[2:-1], "")
    if value.startswith("$") and len(value) > 1:
        return os.getenv(value[1:], "")
    return value


def _data_dir_from_file() -> Path:
    """Best-effort AstrBot data directory discovery from plugin file path."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if parent.name == "data" and (parent / "plugins").exists():
            return parent
    # Fallback for development/test environments.
    return current.parent.parent.parent


def _plugin_config_path() -> Path:
    return _data_dir_from_file() / "config" / CONFIG_FILENAME


def _cmd_config_path() -> Path:
    return _data_dir_from_file() / "cmd_config.json"


def _load_plugin_config() -> dict[str, Any]:
    path = _plugin_config_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        logger.warning("Failed to read Hermes plugin config %s: %s", path, exc)
        return {}


def _effective_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = dict(config or {})
    disk_cfg = _load_plugin_config()
    # Runtime config has priority when AstrBot passes it in; disk config is a fallback for provider instances.
    merged = {**disk_cfg, **{k: v for k, v in cfg.items() if v is not None}}
    return {
        "provider_id": str(merged.get("provider_id") or "hermes_agent"),
        "enable_provider": _as_bool(merged.get("enable_provider"), False),
        "api_base": _normalize_api_base(merged.get("api_base") or DEFAULT_API_BASE),
        "api_key": str(merged.get("api_key") or ""),
        "model": str(merged.get("model") or DEFAULT_MODEL),
        "timeout": _as_int(merged.get("timeout"), 300),
        "streaming_response": _as_bool(merged.get("streaming_response"), True),
        "temperature": _as_float(merged.get("temperature"), 0.7),
        "max_tokens": _as_int(merged.get("max_tokens"), 4096),
        "custom_headers": _parse_json_object(merged.get("custom_headers_json") or merged.get("custom_headers"), {}),
        "extra_body": _parse_json_object(merged.get("extra_body_json") or merged.get("extra_body"), {}),
        "auto_sync_provider_on_startup": _as_bool(merged.get("auto_sync_provider_on_startup"), False),
    }


def build_provider_config(config: dict[str, Any] | None = None, mask_secret: bool = False) -> dict[str, Any]:
    cfg = _effective_config(config)
    api_key = cfg["api_key"]
    if mask_secret and api_key and not api_key.startswith("$"):
        api_key = "***已隐藏***"
    provider_config = {
        "id": cfg["provider_id"],
        "type": PROVIDER_TYPE,
        "provider_type": "chat_completion",
        "provider": "hermes",
        "enable": cfg["enable_provider"],
        "key": [api_key] if api_key else [],
        "api_base": cfg["api_base"],
        "model": cfg["model"],
        "timeout": cfg["timeout"],
        "streaming_response": cfg["streaming_response"],
        "temperature": cfg["temperature"],
        "max_tokens": cfg["max_tokens"],
        "custom_headers": cfg["custom_headers"],
        "extra_body": cfg["extra_body"],
    }
    return provider_config


DEFAULT_PROVIDER_CONFIG = build_provider_config(
    {
        "provider_id": "hermes_agent",
        "enable_provider": False,
        "api_base": DEFAULT_API_BASE,
        "api_key": "$HERMES_API_KEY",
        "model": DEFAULT_MODEL,
        "timeout": 300,
        "streaming_response": True,
        "temperature": 0.7,
        "max_tokens": 4096,
    }
)


def _unregister_stale_provider_adapter(provider_type: str) -> None:
    """Remove a previously registered adapter with the same type during plugin reload.

    AstrBot keeps provider adapters in process-global registries. When a plugin is
    hot-reloaded, the old adapter entry can remain there and make the next import
    fail or force us to keep using stale provider code. Replacing our own adapter
    is safer than silently skipping registration.
    """
    old_meta = provider_register_module.provider_cls_map.pop(provider_type, None)
    if old_meta is None:
        return
    provider_register_module.provider_registry[:] = [
        meta for meta in provider_register_module.provider_registry if getattr(meta, "type", None) != provider_type
    ]
    logger.info("Replaced stale model provider adapter during plugin reload: %s", provider_type)


_unregister_stale_provider_adapter(PROVIDER_TYPE)


@register_provider_adapter(
    PROVIDER_TYPE,
    "Hermes Agent OpenAI-compatible Chat Completion provider adapter",
    default_config_tmpl=DEFAULT_PROVIDER_CONFIG.copy(),
    provider_display_name="Hermes Agent",
)
class HermesChatCompletionProvider(Provider):
    """Wrap Hermes Agent OpenAI-compatible API as an AstrBot model provider."""

    def __init__(self, provider_config: dict, provider_settings: dict) -> None:
        super().__init__(provider_config, provider_settings)
        fallback = _effective_config()
        self.api_keys = super().get_keys()
        raw_key = self.api_keys[0] if self.api_keys else str(fallback.get("api_key") or "")
        self.chosen_api_key = _resolve_env_ref(raw_key)
        self.api_base = _normalize_api_base(provider_config.get("api_base") or fallback["api_base"] or DEFAULT_API_BASE)
        self.timeout = float(provider_config.get("timeout") or fallback["timeout"] or 300)
        self.model_name = str(provider_config.get("model") or fallback["model"] or DEFAULT_MODEL)
        self.set_model(self.model_name)
        self.client = httpx.AsyncClient(timeout=self.timeout)

    def get_current_key(self) -> str:
        return self.chosen_api_key or ""

    def set_key(self, key: str) -> None:
        self.chosen_api_key = _resolve_env_ref(key or "")

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.chosen_api_key:
            headers["Authorization"] = f"Bearer {self.chosen_api_key}"
        custom_headers = self.provider_config.get("custom_headers") or _effective_config().get("custom_headers") or {}
        if isinstance(custom_headers, dict):
            for k, v in custom_headers.items():
                if k and v is not None:
                    headers[str(k)] = str(v)
        return headers

    async def terminate(self) -> None:
        await self.client.aclose()

    async def test(self) -> None:
        try:
            await self.get_models()
            return
        except Exception as first_error:
            logger.warning("Hermes /models check failed, trying chat check: %s", first_error)
        resp = await self.text_chat(prompt="ping", system_prompt="Reply with pong only.")
        if not (resp.completion_text or "").strip():
            raise RuntimeError("Hermes provider test failed: empty response")

    async def get_models(self) -> list[str]:
        if not self.api_base:
            return [self.model_name]
        url = f"{self.api_base}/models"
        r = await self.client.get(url, headers=self._headers())
        if r.status_code == 404:
            return [self.model_name]
        r.raise_for_status()
        data = r.json()
        models: list[str] = []
        if isinstance(data, dict):
            for item in data.get("data", []) or []:
                if isinstance(item, dict) and item.get("id"):
                    models.append(str(item["id"]))
        return models or [self.model_name]

    @staticmethod
    def _message_to_dict(message: Any) -> dict[str, Any] | None:
        if isinstance(message, dict):
            return {"role": message.get("role", "user"), "content": message.get("content") or ""}
        for method in ("to_openai_message", "to_dict"):
            fn = getattr(message, method, None)
            if callable(fn):
                try:
                    value = fn()
                    if isinstance(value, dict):
                        return {"role": value.get("role", "user"), "content": value.get("content") or ""}
                except Exception:
                    pass
        role = getattr(message, "role", "user")
        content = getattr(message, "content", None) or getattr(message, "text", None) or str(message)
        return {"role": role, "content": content}

    def _build_messages(
        self,
        prompt: str | None,
        contexts: list[Message] | list[dict] | None,
        system_prompt: str | None,
        extra_user_content_parts: list[ContentPart] | None,
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if contexts:
            for ctx in contexts:
                msg = self._message_to_dict(ctx)
                if msg:
                    messages.append(msg)
        if prompt:
            user_content = prompt
            if extra_user_content_parts:
                extra_text = "\n".join(str(part) for part in extra_user_content_parts if part is not None)
                if extra_text:
                    user_content += "\n" + extra_text
            messages.append({"role": "user", "content": user_content})
        if not messages:
            messages.append({"role": "user", "content": ""})
        return messages

    def _build_payload(
        self,
        prompt: str | None,
        contexts: list[Message] | list[dict] | None,
        system_prompt: str | None,
        model: str | None,
        extra_user_content_parts: list[ContentPart] | None,
        stream: bool = False,
        **kwargs,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model or self.get_model() or DEFAULT_MODEL,
            "messages": self._build_messages(prompt, contexts, system_prompt, extra_user_content_parts),
            "stream": stream,
        }
        for key in ("temperature", "top_p", "max_tokens", "presence_penalty", "frequency_penalty"):
            if key in kwargs and kwargs[key] is not None:
                payload[key] = kwargs[key]
            elif key in self.provider_config and self.provider_config[key] is not None:
                payload[key] = self.provider_config[key]
        extra_body = self.provider_config.get("extra_body") or _effective_config().get("extra_body") or {}
        if isinstance(extra_body, dict):
            payload.update(extra_body)
        return payload

    @staticmethod
    def _extract_text(data: dict[str, Any]) -> str:
        choices = data.get("choices") or []
        if not choices:
            return ""
        message = choices[0].get("message") or {}
        content = message.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    parts.append(str(item.get("text") or item.get("content") or ""))
                else:
                    parts.append(str(item))
            return "".join(parts)
        return str(content) if content is not None else ""

    async def text_chat(
        self,
        prompt: str | None = None,
        session_id: str | None = None,
        image_urls: list[str] | None = None,
        audio_urls: list[str] | None = None,
        func_tool: ToolSet | None = None,
        contexts: list[Message] | list[dict] | None = None,
        system_prompt: str | None = None,
        tool_calls_result: ToolCallsResult | list[ToolCallsResult] | None = None,
        model: str | None = None,
        extra_user_content_parts: list[ContentPart] | None = None,
        tool_choice: Literal["auto", "required"] = "auto",
        **kwargs,
    ) -> LLMResponse:
        if image_urls or audio_urls:
            logger.warning("Hermes provider passes text fields only; multimodal support depends on the Hermes API server.")
        payload = self._build_payload(prompt, contexts, system_prompt, model, extra_user_content_parts, stream=False, **kwargs)
        url = f"{self.api_base}/chat/completions"
        r = await self.client.post(url, headers=self._headers(), json=payload)
        r.raise_for_status()
        data = r.json()
        text = self._extract_text(data)
        return LLMResponse("assistant", result_chain=MessageChain().message(text), raw_completion=None)

    async def text_chat_stream(
        self,
        prompt: str | None = None,
        session_id: str | None = None,
        image_urls: list[str] | None = None,
        audio_urls: list[str] | None = None,
        func_tool: ToolSet | None = None,
        contexts: list[Message] | list[dict] | None = None,
        system_prompt: str | None = None,
        tool_calls_result: ToolCallsResult | list[ToolCallsResult] | None = None,
        model: str | None = None,
        extra_user_content_parts: list[ContentPart] | None = None,
        tool_choice: Literal["auto", "required"] = "auto",
        **kwargs,
    ) -> AsyncGenerator[LLMResponse, None]:
        payload = self._build_payload(prompt, contexts, system_prompt, model, extra_user_content_parts, stream=True, **kwargs)
        url = f"{self.api_base}/chat/completions"
        async with self.client.stream("POST", url, headers=self._headers(), json=payload) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line:
                    continue
                if line.startswith("data:"):
                    line = line[5:].strip()
                if line == "[DONE]":
                    break
                try:
                    chunk = json.loads(line)
                    delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
                    text = delta.get("content") or ""
                except Exception:
                    text = ""
                if text:
                    yield LLMResponse("assistant", completion_text=text, is_chunk=True)


class HermesEcosystemPlugin(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.config = config or {}

    async def initialize(self):
        cfg = _effective_config(self.config)
        if cfg["auto_sync_provider_on_startup"]:
            ok, msg = self._sync_provider_config()
            if ok:
                logger.info("Hermes provider config auto-synced: %s", msg)
            else:
                logger.warning("Hermes provider config auto-sync failed: %s", msg)

    def _cfg(self) -> dict[str, Any]:
        return _effective_config(self.config)

    def _sync_provider_config(self) -> tuple[bool, str]:
        path = _cmd_config_path()
        if not path.exists():
            return False, f"cmd_config.json not found: {path}"
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            return False, f"failed to read cmd_config.json: {exc}"
        sources = data.setdefault("provider_sources", [])
        if not isinstance(sources, list):
            return False, "provider_sources is not a list"
        new_item = build_provider_config(self.config, mask_secret=False)
        provider_id = new_item["id"]
        replaced = False
        for index, item in enumerate(sources):
            if isinstance(item, dict) and item.get("id") == provider_id:
                sources[index] = new_item
                replaced = True
                break
        if not replaced:
            sources.append(new_item)
        backup = path.with_suffix(path.suffix + ".bak.hermes")
        if not backup.exists():
            backup.write_text(path.read_text(encoding="utf-8-sig"), encoding="utf-8")
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        action = "updated" if replaced else "added"
        return True, f"{action} provider '{provider_id}' in {path}"

    @filter.command("hermes生态")
    async def hermes_ecosystem(self, event: AstrMessageEvent):
        text = (
            "Hermes 生态插件用途：\n"
            "1. 把 Hermes Agent 的 OpenAI-compatible API 注册成 AstrBot 模型提供商。\n"
            "2. 连接参数都在插件配置页填写：api_base、api_key、model、provider_id 等。\n"
            "3. AstrBot 负责 QQ/群聊/插件事件，Hermes 负责模型路由、skills、tools、多 Agent、定时任务等。\n"
            "4. 发布版源码不内置任何真实 URL、Key、Token。\n\n"
            "命令：/hermes配置、/hermes安装提供商、/hermes健康、/hermes生态\n"
            "提供商类型：hermes_chat_completion"
        )
        yield event.plain_result(text)

    @filter.command("hermes配置")
    async def hermes_config(self, event: AstrMessageEvent):
        sample = build_provider_config(self.config, mask_secret=True)
        cfg = self._cfg()
        warnings = []
        api_warning = _validate_api_base(cfg["api_base"])
        if api_warning:
            warnings.append(api_warning)
        for field, raw in (("custom_headers_json", self.config.get("custom_headers_json")), ("extra_body_json", self.config.get("extra_body_json"))):
            err = _json_object_error(raw, field)
            if err:
                warnings.append(err)
        warning_text = ("配置提醒：\n- " + "\n- ".join(warnings) + "\n\n") if warnings else ""
        text = (
            warning_text
            + "当前插件配置会生成下面这个 AstrBot Provider。\n"
            "如果 api_key 显示为空，请到插件配置页填写，或填 $HERMES_API_KEY 使用环境变量。\n"
            "```json\n"
            + json.dumps(sample, ensure_ascii=False, indent=2)
            + "\n```\n"
            "执行 /hermes安装提供商 可把它写入 cmd_config.json，然后重启 AstrBot 生效。"
        )
        yield event.plain_result(text)

    @filter.command("hermes安装提供商")
    async def hermes_install_provider(self, event: AstrMessageEvent):
        ok, msg = self._sync_provider_config()
        if ok:
            yield event.plain_result(
                "Hermes Provider 配置已写入。\n"
                f"{msg}\n"
                "请在 AstrBot WebUI 重启/重载，或重启 AstrBot 服务后，在模型提供商里选择这个 provider。"
            )
        else:
            yield event.plain_result(f"Hermes Provider 配置写入失败：{msg}")

    @filter.command("hermes健康")
    async def hermes_health(self, event: AstrMessageEvent):
        cfg = self._cfg()
        api_base = _normalize_api_base(cfg["api_base"])
        api_key = _resolve_env_ref(str(cfg["api_key"] or ""))
        if not api_base:
            yield event.plain_result("未在插件配置里填写 api_base。")
            return
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        try:
            async with httpx.AsyncClient(timeout=cfg["timeout"]) as client:
                health_url = _health_url_from_api_base(api_base)
                health = await client.get(health_url, headers=headers)
                models = await client.get(f"{api_base}/models", headers=headers)
            health_text = f"health={health.status_code}"
            if models.status_code == 404:
                yield event.plain_result(f"Hermes API 可访问，{health_text}，但 /models 未实现：{api_base}")
                return
            models.raise_for_status()
            data = models.json()
            model_names = [str(i.get("id")) for i in data.get("data", []) if isinstance(i, dict) and i.get("id")]
            yield event.plain_result(
                "Hermes API 正常。\n"
                f"{health_text}\n"
                "模型：" + (", ".join(model_names[:20]) if model_names else "未返回模型列表")
            )
        except Exception as e:
            yield event.plain_result(f"Hermes API 健康检查失败：{type(e).__name__}: {e}")
