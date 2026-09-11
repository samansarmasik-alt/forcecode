#!/usr/bin/env python3
"""ForgeCode providers — cerrahi bölünme adım 3 (provider extraction).

Canonical home for API provider leaves:
- ApiError / RequestStallError
- ModelReply
- portable_message_text / convert_messages_for_mode
- Provider / compatible_tool_* / tool_call_validation_error
- AnthropicProvider / OpenAIProvider / OpenAIChatProvider
- subscription_cli_path / SubscriptionCLIProvider
- make_provider

Tasarım notu (dairesel import yok):
- forgecode.py transport katmanında kalır: request_endpoint,
  api_transport_timeout, post_json_with_retry, stream_or_json,
  consume_*_stream, custom_auth_headers, PROVIDERS, APP_NAME,
  redact_sensitive. Bu semboller SADECE request anında
  `import forgecode` ile tembel alınır (_fc).
- Config'e tip olarak dokunulmaz (Any) — 88 edge'lik göbekten
  import zinciri kurulmaz.
- Usage forgecode_stores'tan gelir (izole, güvenli).
- forgecode.py bu sembolleri `try: from forgecode_providers import ...`
  ile alır; dosya silinirse eski gömülü fallback çalışır.
"""

from __future__ import annotations

import copy
import json
import os
import pathlib
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from forgecode_stores import Usage


def _fc(name: str) -> Any:
    import forgecode as _mod  # type: ignore

    return getattr(_mod, name)


def _redact(value: Any) -> str:
    try:
        fn = _fc("redact_sensitive")
        return str(fn(str(value)))
    except Exception:
        return str(value)


class ApiError(RuntimeError):
    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = max(0.0, float(retry_after)) if retry_after is not None else None


class RequestStallError(ApiError):
    """A detached API request made no useful progress and may be retried safely once."""

    def __init__(self, message: str, reason: str, elapsed_seconds: float, safe_to_retry: bool):
        super().__init__(message)
        self.reason = str(reason)
        self.elapsed_seconds = max(0.0, float(elapsed_seconds))
        self.safe_to_retry = bool(safe_to_retry)


@dataclass
class ModelReply:
    text: str
    tool_calls: list[dict[str, Any]]
    usage: Usage
    native_output: Any
    finish_reason: str = ""


def portable_message_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(part for item in value if (part := portable_message_text(item)).strip())
    if not isinstance(value, dict):
        return str(value)
    block_type = str(value.get("type", ""))
    if value.get("text") is not None:
        return str(value.get("text"))
    if block_type in {"tool_use", "function_call"}:
        name = value.get("name") or (value.get("function") or {}).get("name") or "tool"
        arguments = value.get("input") or value.get("arguments") or value.get("parameters") or ""
        return f"[Tool call: {name} {_redact(str(arguments))[:1200]}]"
    if block_type in {"tool_result", "function_call_output"}:
        result = value.get("content", value.get("output", ""))
        return "[Tool result]\n" + portable_message_text(result)
    pieces: list[str] = []
    if value.get("content") is not None:
        pieces.append(portable_message_text(value.get("content")))
    if value.get("output") is not None:
        pieces.append(portable_message_text(value.get("output")))
    if value.get("tool_calls"):
        pieces.append(portable_message_text(value.get("tool_calls")))
    return "\n".join(piece for piece in pieces if piece.strip())


def convert_messages_for_mode(messages: list[Any], target_mode: str) -> list[Any]:
    neutral: list[dict[str, str]] = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        source_role = str(item.get("role", "user"))
        role = "assistant" if source_role == "assistant" else "user"
        text = portable_message_text(item).strip()
        if not text:
            continue
        if source_role not in {"user", "assistant"}:
            text = f"[{source_role}]\n{text}"
        text = _redact(text)[:30000]
        if neutral and neutral[-1]["role"] == role:
            neutral[-1]["content"] += "\n\n" + text
        else:
            neutral.append({"role": role, "content": text})
    if neutral and neutral[0]["role"] == "assistant":
        neutral.insert(0, {"role": "user", "content": "Previous conversation context follows."})
    if target_mode == "responses":
        transcript = "\n\n".join(f"{item['role'].upper()}:\n{item['content']}" for item in neutral)
        return [{"role": "user", "content": [{"type": "input_text", "text": transcript or "Continue the current task."}]}]
    return neutral


class Provider:
    def __init__(self, cfg: Any):
        self.cfg = cfg

    def request(self, system: str, messages: list[Any], tools: list[dict[str, Any]], max_tokens: int | None = None, web_search: bool = False, on_text: Callable[[str], None] | None = None) -> ModelReply:
        raise NotImplementedError


def compatible_tool_arguments_with_error(block: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Read proxy tool arguments and preserve evidence of truncated JSON."""
    candidates: list[Any] = [block.get("input"), block.get("arguments"), block.get("parameters")]
    function = block.get("function")
    if isinstance(function, dict):
        candidates.extend([function.get("arguments"), function.get("parameters")])
    invalid_json = False
    for candidate in candidates:
        if isinstance(candidate, dict):
            return candidate, ""
        if isinstance(candidate, str) and candidate.strip():
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                invalid_json = True
                continue
            if isinstance(parsed, dict):
                return parsed, ""
    embedded = str(block.get("_forgecode_parse_error") or "").strip()
    if embedded:
        return {}, embedded
    if invalid_json:
        return {}, "tool arguments were cut off or are not valid JSON"
    return {}, ""


def compatible_tool_arguments(block: dict[str, Any]) -> dict[str, Any]:
    """Backward-compatible argument-only view used by existing callers."""
    return compatible_tool_arguments_with_error(block)[0]


def tool_call_validation_error(name: str, raw_arguments: Any, parse_error: str = "") -> str:
    """Reject incomplete calls before a workspace tool can report false success."""
    if parse_error:
        return f"Tool arguments are incomplete: {parse_error}."
    args = raw_arguments if isinstance(raw_arguments, dict) else {}
    if name == "write_file":
        has_path = any(key in args for key in ("path", "file_path"))
        has_content = any(key in args for key in ("content", "text"))
        if not has_path or not str(args.get("path") or args.get("file_path") or "").strip():
            return "write_file requires a non-empty project-relative path."
        if not has_content:
            return "write_file requires the complete content field; the model response may have been truncated."
    elif name == "write_files":
        files = args.get("files")
        if not isinstance(files, list) or not files:
            return "write_files requires a non-empty files array; the model response may have been truncated."
        for index, item in enumerate(files, 1):
            if not isinstance(item, dict) or not str(item.get("path", "")).strip() or "content" not in item:
                return f"write_files item {index} is incomplete; resend complete path/content fields."
    elif name == "apply_edits":
        edits = args.get("edits", args.get("changes"))
        if not isinstance(edits, list) or not edits:
            return "apply_edits requires a non-empty edits array."
        for index, item in enumerate(edits, 1):
            if not isinstance(item, dict):
                return f"apply_edits item {index} must be an object."
            if not str(item.get("path", "")).strip() or not str(item.get("old_text", "")):
                return f"apply_edits item {index} requires path and non-empty old_text."
            if "new_text" not in item:
                return f"apply_edits item {index} requires the complete new_text field."
    elif name == "verify_artifacts":
        paths = args.get("paths", args.get("files"))
        if isinstance(paths, str):
            paths = [paths]
        if not isinstance(paths, list) or not paths or any(not str(path).strip() for path in paths):
            return "verify_artifacts requires a non-empty paths array."
    return ""


class AnthropicProvider(Provider):
    def request(self, system: str, messages: list[Any], tools: list[dict[str, Any]], max_tokens: int | None = None, web_search: bool = False, on_text: Callable[[str], None] | None = None) -> ModelReply:
        cfg = self.cfg.data
        payload: dict[str, Any] = {
            "model": cfg["model"],
            "max_tokens": max_tokens or cfg["max_tokens"],
            "temperature": cfg["temperature"],
            "system": system,
            "messages": messages,
        }
        request_tools = list(tools)
        if web_search and cfg["provider"] == "anthropic":
            request_tools.append({"type": "web_search_20250305", "name": "web_search", "max_uses": int(cfg["web_max_results"])})
        if request_tools:
            payload["tools"] = request_tools
        thinking = cfg.get("thinking_mode", "off")
        if thinking != "off" and int(payload["max_tokens"]) >= 1280:
            requested = int(cfg["thinking_budget_tokens"])
            requested = min(requested, 2048) if thinking == "low" else min(requested, 8192) if thinking == "medium" else requested
            budget = max(1024, min(requested, max(1024, int(payload["max_tokens"]) - 256)))
            payload["thinking"] = {"type": "enabled", "budget_tokens": budget}
            payload["temperature"] = 1
        endpoint = _fc("request_endpoint")(self.cfg, "/v1/messages")
        request_timeout = _fc("api_transport_timeout")(self.cfg)
        streaming = bool(cfg.get("streaming_enabled", True) and on_text)
        if streaming:
            payload["stream"] = True

        def send(headers: dict[str, str]) -> dict[str, Any]:
            try:
                if streaming and on_text:
                    return _fc("stream_or_json")(self.cfg, endpoint, headers, payload, request_timeout, _fc("consume_anthropic_stream"), on_text)
                return _fc("post_json_with_retry")(self.cfg, endpoint, headers, payload, request_timeout)
            except ApiError as exc:
                message = str(exc).lower()
                unsupported_thinking = "thinking" in payload and any(marker in message for marker in (
                    "thinking", "budget_tokens", "unsupported parameter", "unknown parameter", "extra inputs",
                ))
                if cfg["provider"] != "custom" or not unsupported_thinking:
                    raise
                fallback_payload = dict(payload)
                fallback_payload.pop("thinking", None)
                fallback_payload["temperature"] = cfg["temperature"]
                if streaming and on_text:
                    return _fc("stream_or_json")(self.cfg, endpoint, headers, fallback_payload, request_timeout, _fc("consume_anthropic_stream"), on_text)
                return _fc("post_json_with_retry")(self.cfg, endpoint, headers, fallback_payload, request_timeout)

        if cfg["provider"] == "custom":
            selected_auth = str(cfg.get("custom_auth_mode", "auto"))
            modes = [selected_auth] if selected_auth != "auto" else ["x-api-key", "bearer", "api-key", "both", "none"]
            data = None
            auth_errors: list[str] = []
            for auth_mode in modes:
                headers = {"anthropic-version": "2023-06-01"}
                if self.cfg.key() and auth_mode in {"x-api-key", "both"}:
                    headers["x-api-key"] = self.cfg.key()
                if self.cfg.key() and auth_mode in {"bearer", "both"}:
                    headers["Authorization"] = f"Bearer {self.cfg.key()}"
                if self.cfg.key() and auth_mode == "api-key":
                    headers["api-key"] = self.cfg.key()
                try:
                    data = send(headers)
                    if selected_auth == "auto":
                        cfg["custom_auth_mode"] = auth_mode
                    if str(cfg.get("custom_protocol", "auto")).lower() != "off":
                        cfg["custom_protocol"] = "anthropic"
                        cfg["api_mode"] = "anthropic"
                    self.cfg.save()
                    break
                except ApiError as exc:
                    lowered = str(exc).lower()
                    auth_failure = any(mark in lowered for mark in ("api 401", "api 403", "unauthorized", "forbidden", "api key", "apikey", "authentication"))
                    if not auth_failure or selected_auth != "auto":
                        raise
                    auth_errors.append(f"{auth_mode}: {exc}")
            if data is None:
                raise ApiError("Claude Code/Anthropic protokolünde tüm kimlik doğrulama biçimleri reddedildi. Son hata: " + auth_errors[-1])
        else:
            data = send({"x-api-key": self.cfg.key(), "anthropic-version": "2023-06-01"})
        content = data.get("content", [])
        text = "\n".join(block.get("text", "") for block in content if block.get("type") == "text")
        calls = []
        native_content = copy.deepcopy(content)
        for index, block in enumerate(content):
            if block.get("type") != "tool_use":
                continue
            function = block.get("function") if isinstance(block.get("function"), dict) else {}
            name = block.get("name") or function.get("name") or ""
            arguments, parse_error = compatible_tool_arguments_with_error(block)
            calls.append({
                "id": block.get("id") or block.get("call_id") or uuid.uuid4().hex,
                "name": name,
                "arguments": arguments,
                "parse_error": parse_error,
            })
            native_block = native_content[index]
            native_block["id"] = calls[-1]["id"]
            native_block["name"] = name
            native_block["input"] = arguments
            native_block.pop("arguments", None)
            native_block.pop("parameters", None)
            native_block.pop("function", None)
            native_block.pop("_forgecode_parse_error", None)
        u = data.get("usage", {})
        if not text.strip() and not calls:
            raise ApiError("API başarılı durum döndürdü ancak görünür içerik veya araç çağrısı üretmedi")
        usage = Usage(int(u.get("input_tokens", 0)), int(u.get("output_tokens", 0)), int(u.get("cache_read_input_tokens", 0)), 1)
        return ModelReply(text, calls, usage, native_content, str(data.get("stop_reason") or ""))


class OpenAIProvider(Provider):
    def request(self, system: str, messages: list[Any], tools: list[dict[str, Any]], max_tokens: int | None = None, web_search: bool = False, on_text: Callable[[str], None] | None = None) -> ModelReply:
        cfg = self.cfg.data
        oa_tools = [
            {"type": "function", "name": t["name"], "description": t["description"], "parameters": t["input_schema"], "strict": False}
            for t in tools
        ]
        payload: dict[str, Any] = {
            "model": cfg["model"],
            "instructions": system,
            "input": messages,
            "max_output_tokens": max_tokens or cfg["max_tokens"],
            "store": False,
        }
        if web_search:
            oa_tools.append({"type": "web_search", "search_context_size": "low" if cfg.get("efficiency_mode") != "off" else "medium"})
        if oa_tools:
            payload["tools"] = oa_tools
        if cfg.get("thinking_mode", "off") != "off":
            payload["reasoning"] = {"effort": cfg["thinking_mode"]}
        endpoint = _fc("request_endpoint")(self.cfg, "/responses")
        headers = {"Authorization": f"Bearer {self.cfg.key()}"}
        if cfg.get("streaming_enabled", True) and on_text:
            payload["stream"] = True
            data = _fc("stream_or_json")(self.cfg, endpoint, headers, payload, _fc("api_transport_timeout")(self.cfg), _fc("consume_responses_stream"), on_text)
        else:
            data = _fc("post_json_with_retry")(self.cfg, endpoint, headers, payload, _fc("api_transport_timeout")(self.cfg))
        output = data.get("output", [])
        texts: list[str] = []
        calls: list[dict[str, Any]] = []
        for item in output:
            if item.get("type") == "message":
                texts.extend(part.get("text", "") for part in item.get("content", []) if part.get("type") == "output_text")
            elif item.get("type") == "function_call":
                raw_arguments = item.get("arguments", "{}")
                parse_error = ""
                try:
                    args = raw_arguments if isinstance(raw_arguments, dict) else json.loads(raw_arguments)
                except (json.JSONDecodeError, TypeError):
                    args = {}
                    parse_error = "tool arguments were cut off or are not valid JSON"
                calls.append({"id": item["call_id"], "name": item["name"], "arguments": args, "parse_error": parse_error})
        u = data.get("usage", {})
        if not any(text.strip() for text in texts) and not calls:
            raise ApiError("API başarılı durum döndürdü ancak görünür içerik veya araç çağrısı üretmedi")
        usage = Usage(int(u.get("input_tokens", 0)), int(u.get("output_tokens", 0)), int(u.get("input_tokens_details", {}).get("cached_tokens", 0)), 1)
        incomplete = data.get("incomplete_details") or {}
        finish_reason = str(incomplete.get("reason") or data.get("status") or "")
        return ModelReply("\n".join(texts), calls, usage, output, finish_reason)


class OpenAIChatProvider(Provider):
    """Provider for OpenAI-compatible /chat/completions services."""

    def request(self, system: str, messages: list[Any], tools: list[dict[str, Any]], max_tokens: int | None = None, web_search: bool = False, on_text: Callable[[str], None] | None = None) -> ModelReply:
        cfg = self.cfg.data
        chat_tools = [
            {
                "type": "function",
                "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]},
            }
            for t in tools
        ]
        payload: dict[str, Any] = {
            "model": cfg["model"],
            "messages": [{"role": "system", "content": system}, *messages],
            "max_tokens": max_tokens or cfg["max_tokens"],
            "temperature": cfg["temperature"],
        }
        if chat_tools:
            payload["tools"] = chat_tools
            payload["tool_choice"] = "auto"
        if web_search and cfg["provider"] == "openrouter":
            payload.setdefault("tools", []).append({"type": "openrouter:web_search"})
        thinking = cfg.get("thinking_mode", "off")
        if thinking != "off" and cfg["provider"] == "openrouter":
            payload["reasoning"] = {"effort": thinking, "exclude": True}
        headers: dict[str, str] = {}
        if self.cfg.key():
            headers["Authorization"] = f"Bearer {self.cfg.key()}"
        extras = _fc("PROVIDERS").get(str(cfg.get("provider")), {}).get("headers", {})
        if isinstance(extras, dict):
            headers.update({str(key): str(value) for key, value in extras.items()})
        if cfg["provider"] == "openrouter":
            headers.update({"HTTP-Referer": "https://forgecode.local", "X-OpenRouter-Title": _fc("APP_NAME")})
        endpoint = _fc("request_endpoint")(self.cfg, "/chat/completions")
        streaming = bool(cfg.get("streaming_enabled", True) and on_text)
        if streaming:
            payload["stream"] = True

        def send(request_headers: dict[str, str]) -> dict[str, Any]:
            if streaming and on_text:
                return _fc("stream_or_json")(self.cfg, endpoint, request_headers, payload, _fc("api_transport_timeout")(self.cfg), _fc("consume_chat_stream"), on_text)
            return _fc("post_json_with_retry")(self.cfg, endpoint, request_headers, payload, _fc("api_transport_timeout")(self.cfg))

        if cfg["provider"] == "custom":
            selected_auth = str(cfg.get("custom_auth_mode", "auto"))
            modes = [selected_auth] if selected_auth != "auto" else ["bearer", "x-api-key", "api-key", "both", "none"]
            auth_errors: list[str] = []
            data = None
            for auth_mode in modes:
                try:
                    data = send(_fc("custom_auth_headers")(self.cfg, auth_mode))
                    if selected_auth == "auto":
                        cfg["custom_auth_mode"] = auth_mode
                        self.cfg.save()
                    break
                except ApiError as exc:
                    message = str(exc)
                    lowered = message.lower()
                    auth_failure = any(mark in lowered for mark in ("api 401", "api 403", "unauthorized", "forbidden", "api key", "apikey", "authentication"))
                    if not auth_failure or selected_auth != "auto":
                        raise
                    auth_errors.append(f"{auth_mode}: {message}")
            if data is None:
                raise ApiError("Özel API anahtarı tüm desteklenen kimlik doğrulama biçimlerinde reddedildi (Bearer, x-api-key, api-key, anahtarsız). Anahtarın bu sunucuya ait, etkin ve sohbet yetkili olduğunu kontrol edin. Son hata: " + auth_errors[-1])
        else:
            data = send(headers)
        choices = data.get("choices", [])
        if not choices:
            raise ApiError("API yanıtında choices alanı boş")
        message = choices[0].get("message", {})
        content = message.get("content") or ""
        if isinstance(content, list):
            content = "\n".join(part.get("text", "") for part in content if isinstance(part, dict))
        calls: list[dict[str, Any]] = []
        for item in message.get("tool_calls", []) or []:
            function = item.get("function", {})
            raw_arguments = function.get("arguments", "{}")
            parse_error = ""
            try:
                args = raw_arguments if isinstance(raw_arguments, dict) else json.loads(raw_arguments)
            except (json.JSONDecodeError, TypeError):
                args = {}
                parse_error = "tool arguments were cut off or are not valid JSON"
            calls.append({"id": item.get("id", uuid.uuid4().hex), "name": function.get("name", ""), "arguments": args, "parse_error": parse_error})
        if not str(content).strip() and not calls:
            raise ApiError("API başarılı durum döndürdü ancak görünür içerik veya araç çağrısı üretmedi")
        u = data.get("usage", {}) or {}
        usage = Usage(
            int(u.get("prompt_tokens", 0)),
            int(u.get("completion_tokens", 0)),
            int((u.get("prompt_tokens_details") or {}).get("cached_tokens", 0)),
            1,
        )
        native = {"role": "assistant", "content": message.get("content")}
        if message.get("tool_calls"):
            native_calls = copy.deepcopy(message["tool_calls"])
            for index, call in enumerate(calls):
                if call.get("parse_error") and index < len(native_calls):
                    native_calls[index].setdefault("function", {})["arguments"] = "{}"
            native["tool_calls"] = native_calls
        finish_reason = str(choices[0].get("finish_reason") or "")
        return ModelReply(str(content), calls, usage, native, finish_reason)


def subscription_cli_path(command: str) -> str | None:
    """Locate an official subscription CLI without relying only on a stale Windows PATH."""
    found = shutil.which(command)
    if found:
        return found
    if os.name != "nt":
        return None
    suffixes = [suffix for suffix in os.environ.get("PATHEXT", ".EXE;.CMD;.BAT").split(";") if suffix]
    names = [command] if pathlib.Path(command).suffix else [command + suffix.lower() for suffix in suffixes]
    home = pathlib.Path.home()
    roots = (
        home / ".local" / "bin",
        pathlib.Path(os.environ.get("APPDATA", home / "AppData" / "Roaming")) / "npm",
        pathlib.Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local")) / "Microsoft" / "WinGet" / "Links",
        home / "scoop" / "shims",
    )
    for root in roots:
        for name in names:
            candidate = root / name
            if candidate.is_file():
                return str(candidate)
    return None


class SubscriptionCLIProvider(Provider):
    """Use an official, already signed-in vendor CLI without reading tokens."""

    def request(self, system: str, messages: list[Any], tools: list[dict[str, Any]], max_tokens: int | None = None,
                web_search: bool = False, on_text: Callable[[str], None] | None = None) -> ModelReply:
        preset = _fc("PROVIDERS").get(str(self.cfg.data.get("provider")), {})
        command = [str(part) for part in preset.get("command", [])]
        if not command:
            raise ApiError("Subscription provider has no official CLI command configured")
        executable = subscription_cli_path(command[0])
        if not executable:
            raise ApiError(
                f"Official {command[0]} CLI is not installed or is not on PATH. Install it from the vendor, "
                "sign in with the subscription, then run /subscriptions test."
            )
        transcript = json.dumps(messages, ensure_ascii=False, default=str)
        prompt = (
            system[:12000]
            + "\n\nFORGECODE SUBSCRIPTION BRIDGE: This is an advisory, read-only CLI call. "
              "Do not claim that files were changed. Return concise actionable text; ForgeCode remains responsible for tools and approvals."
            + ("\nCurrent information may be researched using the CLI's supported web features." if web_search else "")
            + "\n\nMESSAGES:\n" + transcript[-16000:]
        )
        timeout = _fc("api_transport_timeout")(self.cfg)
        if timeout is None:
            configured_total = float(self.cfg.data.get("request_total_timeout_seconds", 180))
            timeout = max(30.0, min(900.0, configured_total))
        try:
            project_root = pathlib.Path(str(self.cfg.data.get("_runtime_project_root") or ".")).resolve()
            if not project_root.is_dir():
                raise ApiError(f"Subscription workspace is unavailable: {project_root}")
            environment = os.environ.copy()
            if self.cfg.data.get("provider") == "claude-subscription":
                environment.pop("ANTHROPIC_API_KEY", None)
                environment.pop("ANTHROPIC_AUTH_TOKEN", None)
            elif self.cfg.data.get("provider") == "codex-subscription":
                environment.pop("OPENAI_API_KEY", None)
                environment.pop("CODEX_API_KEY", None)
            invocation = [executable, *command[1:]]
            selected_model = str(self.cfg.data.get("model") or "").strip()
            model_arg = [str(part) for part in preset.get("model_arg", [])]
            if model_arg and selected_model and selected_model not in {"configured", "subscription"}:
                invocation.extend([*model_arg, selected_model])
            completed = subprocess.run(
                [*invocation, "-"], cwd=str(project_root), input=prompt,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                timeout=timeout, check=False, env=environment,
            )
        except subprocess.TimeoutExpired as exc:
            raise ApiError(f"Subscription CLI timed out: {command[0]}") from exc
        if completed.returncode != 0:
            detail = _redact((completed.stderr or completed.stdout).strip())[:1200]
            raise ApiError(f"Subscription CLI failed ({command[0]}, exit {completed.returncode}): {detail}")
        text = self._visible_output(preset, completed.stdout)
        if not text:
            raise ApiError(f"Subscription CLI returned no visible response: {command[0]}")
        if on_text:
            on_text(text)
        return ModelReply(text, [], Usage(0, 0, 0, 1), {"role": "assistant", "content": text})

    @staticmethod
    def _visible_output(preset: dict[str, Any], raw: str) -> str:
        """Extract final visible text from vendor CLIs without exposing JSON traces."""
        if preset.get("output") != "jsonl":
            return raw.strip()
        messages: list[str] = []
        for line in raw.splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(item, dict):
                continue
            if item.get("type") == "say":
                if item.get("partial"):
                    continue
                value = str(item.get("text") or "").strip()
            elif item.get("type") == "item.completed":
                payload = item.get("item")
                if not isinstance(payload, dict) or payload.get("type") not in {"agent_message", "message"}:
                    continue
                content = payload.get("content")
                if isinstance(content, list):
                    value = "\n".join(
                        str(part.get("text") or "").strip()
                        for part in content
                        if isinstance(part, dict) and part.get("text")
                    ).strip()
                else:
                    value = str(payload.get("text") or content or "").strip()
            else:
                continue
            if value and (not messages or messages[-1] != value):
                messages.append(value)
        return "\n".join(messages).strip()


def make_provider(cfg: Any) -> Provider:
    if cfg.mode() == "subscription":
        return SubscriptionCLIProvider(cfg)
    if cfg.mode() == "anthropic":
        return AnthropicProvider(cfg)
    if cfg.mode() == "responses":
        return OpenAIProvider(cfg)
    return OpenAIChatProvider(cfg)
