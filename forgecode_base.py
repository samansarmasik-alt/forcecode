#!/usr/bin/env python3
"""ForgeCode base — leaf utils, no internal deps. Canonical home for tiny helpers + constants."""

from __future__ import annotations

import argparse
import atexit
import base64
import builtins
import codecs
import collections
import concurrent.futures
import contextlib
import copy
import ctypes
import datetime as dt
import difflib
import email.utils
import fnmatch
import getpass
import hashlib
import html.parser
import importlib.metadata
import importlib.util
import json
import locale
import os
import pathlib
import platform
import random
import re
import shlex
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable




HOST_PATH_TYPE = type(pathlib.Path())


_UI_LANGUAGE = "tr"


_EN_UI_REPLACEMENTS = (
    ("ForgeCode ilk kurulum", "ForgeCode first-time setup"),
    ("Önce kullanacağınız yapay zekâ sağlayıcısını seçin.", "First choose the AI provider you want to use."),
    ("Desteklenen sağlayıcılar", "Supported providers"),
    ("SAĞLAYICI    HIZ (ilk yanıt · toplam)", "PROVIDER    SPEED (first response · total)"),
    ("Hızlar başarılı gerçek isteklerden otomatik güncellenir; ilk yanıt streaming başlangıcıdır.", "Speeds update automatically from successful real requests; first response is the streaming start."),
    ("Sağlayıcı adı veya sıra numarası", "Provider name or number"),
    ("Sıradaki adım: /key ile API anahtarını girin, sonra /test kullanın.", "Next: enter your API key with /key, then use /test."),
    ("Yerel sunucuyu başlatıp /test kullanabilirsiniz.", "Start the local server, then use /test."),
    ("Sağlayıcı değiştirildi", "Provider changed"),
    ("Mevcut sağlayıcı", "Current provider"),
    ("Bağlantı hazır", "Connection ready"),
    ("Bağlantı iptal edildi.", "Connection cancelled."),
    ("API anahtarı ayarlanmadı.", "API key is not configured."),
    ("API anahtarı yok.", "API key is missing."),
    ("Anahtar kaydedildi.", "Key saved."),
    ("Modeller taranıyor", "Scanning models"),
    ("Model doğrulanamadı", "Model could not be verified"),
    ("Model sıra numarası bulunamadı.", "Model number was not found."),
    ("Seçmek için", "To select"),
    ("sonuç", "results"),
    ("Kullanım:", "Usage:"),
    ("Kaydedildi:", "Saved:"),
    ("Tahmini maliyet:", "Estimated cost:"),
    ("ortam değişkeni önceliklidir", "environment variable takes priority"),
    ("fiyat ayarlanmadı", "pricing is not configured"),
    ("istek", "requests"),
    ("giriş", "input"),
    ("çıkış", "output"),
    ("önbellek", "cached"),
    ("Proje:", "Project:"),
    ("Oturum:", "Session:"),
    ("Sağlayıcı:", "Provider:"),
    ("Aktif hedef:", "Active goals:"),
    ("Henüz geçmiş yok.", "No history yet."),
    ("Henüz hedef yok.", "No goals yet."),
    ("Henüz işlem kaydı yok.", "No operation log yet."),
    ("Beklenmeyen hata yakalandı", "Unexpected error caught"),
    ("Pencere açık tutuldu. Teknik kayıt", "The window remains open. Technical log"),
    ("Görüşürüz.", "Goodbye."),
    ("Ana model", "Main model"),
    ("alt ajan", "subagent"),
    ("yanıt bekleniyor", "waiting for response"),
    ("istek gönderildi", "request sent"),
    ("yanıt alındı", "response received"),
    ("Araç çalışıyor", "Running tool"),
    ("Araç tamamlandı", "Tool completed"),
    ("Araç başarısız", "Tool failed"),
    ("Komutu çalıştır?", "Run command?"),
    ("dosyasını oluştur?", "Create file?"),
    ("dosyasını değiştir?", "Modify file?"),
    ("içinde metin değiştirilsin mi?", "Replace text in file?"),
    ("dosya birlikte yazılsın mı?", "Write files together?"),
    ("ForceFlow görev zinciri", "ForceFlow task chain"),
    ("Henüz görev yok.", "No tasks yet."),
    ("Görev sıraya eklendi", "Task queued"),
    ("ForceFlow başladı; her görev doğrulandıktan sonra sıradakine geçilecek.", "ForceFlow started; each task must pass verification before the next begins."),
    ("tamamlandı ve doğrulandı", "completed and verified"),
    ("doğrulanamadı", "could not be verified"),
    ("Zincir", "The chain"),
    ("görevinde güvenli biçimde durdu.", "stopped safely at task."),
    ("Bitiş ölçütü:", "Acceptance:"),
    ("Dosyalar:", "Files:"),
    ("Smart Autopilot onayı", "Smart Autopilot approval"),
    ("komutlar", "commands"),
    ("genel görünüm", "overview"),
    ("oturum", "session"),
    ("öneriler", "suggestions"),
    ("tamamla", "complete"),
    ("geçmiş", "history"),
    ("kapalı", "off"),
    ("açık", "on"),
)


ANSI = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


UI_THEMES: dict[str, dict[str, str]] = {
    "dark": {
        "user": "\033[35m",
        "forge": "\033[36m",
        "accent": "\033[35m",
        "ok": "\033[32m",
        "warn": "\033[33m",
        "err": "\033[31m",
        "dim": "\033[2m",
        "bold": "\033[1m",
        "reset": "\033[0m",
    },
    # Light terminals need darker hues; yellow is unreadable on white.
    "light": {
        "user": "\033[32m",
        "forge": "\033[34m",
        "accent": "\033[34m",
        "ok": "\033[32m",
        "warn": "\033[31m",
        "err": "\033[31m",
        "dim": "\033[2m",
        "bold": "\033[1m",
        "reset": "\033[0m",
    },
}


DEFAULT_CONFIG: dict[str, Any] = {
    "config_version": 31,
    "ui_language": "tr",
    "ui_theme": "dark",
    "ui_markdown": True,
    "ui_language_selected": False,
    "provider": "anthropic",
    "model": "claude-sonnet-4-5",
    "api_mode": "anthropic",
    "base_url": "https://api.anthropic.com",
    "base_url_origin": "preset",
    "setup_complete": False,
    "anthropic_base_url": "https://api.anthropic.com",
    "openai_base_url": "https://api.openai.com/v1",
    "max_tokens": 8192,
    "temperature": 1.0,
    "timeout_seconds": 100,
    "streaming_enabled": True,
    "watchdog_enabled": True,
    "stall_guard_enabled": True,
    "stall_first_response_seconds": 120,
    "stall_stream_idle_seconds": 180,
    "stall_retry_attempts": 1,
    "first_response_timeout_seconds": 60,
    "stream_idle_timeout_seconds": 75,
    "request_total_timeout_seconds": 180,
    "retry_budget_seconds": 120,
    "preflight_timeout_seconds": 12,
    "max_agent_steps": 0,
    "goal_max_rounds": 3,
    "flow_max_tasks": 12,
    "flow_max_rounds": 3,
    "flow_repair_rounds": 3,
    "flow_quality_gate": True,
    "vibe_mode": False,
    "vibe_max_hours": 10,
    "vibe_review_cycles": 4,
    "vibe_failure_retries": 6,
    "vibe_retry_delay_seconds": 15,
    "vibe_command_timeout_seconds": 1200,
    "retry_attempts": 2,
    "retry_backoff_seconds": 0.5,
    "retry_jitter_ratio": 0.25,
    "max_tool_output_chars": 30000,
    # Rolling provider transcript ceiling. Quality parity with peer coding
    # agents needs the model to keep its own earlier tool results; 48k tokens
    # still bounds cost per tool round while avoiding mid-task context loss.
    "input_budget_tokens": 48000,
    "auto_approve_writes": False,
    "auto_approve_commands": False,
    "input_price_per_million": 0.0,
    "output_price_per_million": 0.0,
    "system_prompt_extra": "",
    "model_cache": {},
    "latency_stats": {},
    "request_watchdog_stats": {},
    "web_search_mode": "auto",
    "web_max_results": 3,
    "thinking_mode": "off",
    "thinking_budget_tokens": 2048,
    "efficiency_mode": "balanced",
    "power_mode": "auto",
    "subagent_max_per_turn": 3,
    "auto_subagents": True,
    "subagent_timeout_seconds": 60,
    "custom_auth_mode": "auto",
    "web_project_mode": "auto",
    "work_mode": "auto",
    "autopilot_mode": False,
    "smart_autopilot_mode": False,
    "custom_model_hints": [],
    "custom_rejected_models": [],
    "custom_no_tool_models": [],
    "auto_model_switch": False,
    # Automatic recovery may repair an endpoint, but the selected model stays
    # fixed until a user explicitly uses /model, /provider, or /agentconfig.
    "model_lock": True,
    "skills_enabled": True,
    "skill_auto_select": True,
    "skill_scout_enabled": True,
    "skill_scout_min_security": 80,
    "skill_scout_min_relevance": 60,
    "skill_scout_max_auto_install": 2,
    "skill_scout_max_project_skills": 8,
    "skill_scout_cooldown_hours": 24,
    "custom_protocol": "auto",
    "custom_endpoint_path": "auto",
    "last_model_endpoint": "",
    "connection_profiles": {},
    "startup_prompt": "",
    "persistent_memory_enabled": True,
    "memory_max_items": 40,
    "history_context_turns": 6,
    "history_context_chars": 7000,
    "event_log_enabled": True,
    "event_log_max_lines": 2000,
    # Durable per-session turn log cap (rows kept after each write).
    "session_log_max_lines": 2000,
    "session_name": "main",
    "team_parallel": True,
    "team_max_workers": 3,
    "team_roles": ["design", "backend", "review"],
    "agent_profiles": {},
    "backup_enabled": False,
    "backup_connection": {},
    "backup_active": False,
    "backup_primary_state": {},
    "backup_last_reason": "",
    "backup_last_switch": "",
    "forcegraph_auto_enabled": True,
    "mcp_enabled": False,
    "mcp_active_server": "",
    "mcp_servers": {},
    "mcp_timeout_seconds": 45,
    "sandbox_enabled": True,
    "sandbox_engine": "auto",
    "sandbox_network_enabled": True,
    "sandbox_auto_transfer": True,
    "sandbox_snapshot_enabled": True,
    "sandbox_max_file_mb": 20,
    # Zero disables the aggregate project/transfer size cap. The per-file
    # limit remains independently configurable to avoid copying huge binary
    # artifacts accidentally.
    "sandbox_max_transfer_mb": 0,
    "chrome_debug_port": 9222,
    "youtube_music_autostart": False,
    "manager_design_mode": True,
}


def set_ui_language(language: str) -> None:
    global _UI_LANGUAGE
    _UI_LANGUAGE = "en" if str(language).lower() == "en" else "tr"


def localize_ui_text(value: object) -> object:
    if _UI_LANGUAGE != "en" or not isinstance(value, str):
        return value
    translated = value
    for source, target in _EN_UI_REPLACEMENTS:
        translated = translated.replace(source, target)
    return translated


def _raw_ansi(code: str) -> str:
    return code if ANSI else ""


def ui_palette(cfg: "Config | None" = None) -> dict[str, str]:
    """Semantic ANSI palette for the active ui_theme (all empty strings when ANSI is off)."""
    if not ANSI:
        return {key: "" for key in next(iter(UI_THEMES.values()))}
    name = str(cfg.data.get("ui_theme", "dark")).lower() if cfg is not None and isinstance(getattr(cfg, "data", None), dict) else "dark"
    return dict(UI_THEMES.get(name, UI_THEMES["dark"]))


def atomic_json(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def atomic_text(path: pathlib.Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{uuid.uuid4().hex}.tmp")
    tmp.write_text(value, encoding="utf-8")
    tmp.replace(path)


def load_json(path: pathlib.Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def app_home() -> pathlib.Path:
    custom = os.environ.get("FORGECODE_HOME")
    if custom:
        return HOST_PATH_TYPE(custom).expanduser()
    local_app_data = os.environ.get("LOCALAPPDATA")
    if os.name == "nt" and local_app_data:
        return HOST_PATH_TYPE(local_app_data) / "ForgeCode"
    return HOST_PATH_TYPE.home() / ".forgecode"


def migrate_legacy_app_home(destination: pathlib.Path) -> None:
    """Copy legacy Windows user state into AppData without deleting the source."""
    if os.name != "nt" or os.environ.get("FORGECODE_HOME"):
        return
    legacy = pathlib.Path.home() / ".forgecode"
    if destination.resolve() == legacy.resolve() or (destination / "config.json").exists():
        return
    for name in ("config.json", "usage.jsonl", "crash.log"):
        source = legacy / name
        target = destination / name
        if source.is_file() and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)


def normalize_api_base_url(raw: str) -> str:
    value = str(raw).strip().rstrip("/")
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Base URL http:// veya https:// ile başlayan geçerli bir adres olmalı")
    path = parsed.path.rstrip("/")
    lowered = path.lower()
    suffixes = ("/chat/completions", "/v1/messages", "/responses", "/models")
    for suffix in suffixes:
        if lowered.endswith(suffix):
            path = path[:-len(suffix)]
            if suffix == "/v1/messages":
                path += "/v1"
            break
    normalized = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path.rstrip("/"), parsed.query, ""))
    return normalized.rstrip("/")


def normalize_custom_route(raw: str) -> str:
    route = str(raw).strip()
    if route.lower() in {"auto", "exact", "off"}:
        return route.lower()
    if route.startswith(("http://", "https://")):
        parsed = urllib.parse.urlsplit(route)
        if parsed.netloc:
            return route.rstrip("/")
    if route.startswith("/") and not route.startswith("//"):
        return route
    raise ValueError("Custom route: auto, off, exact, /ozel/yol veya tam http(s) adresi olmali")


def inferred_custom_route(raw_url: str) -> str:
    """Use a supplied endpoint verbatim; otherwise send directly to the base."""
    value = str(raw_url).strip().rstrip("/")
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Adres http:// veya https:// ile başlayan geçerli bir URL olmalı")
    return value if parsed.path.rstrip("/") else "off"


def custom_protocol_for_route(route: str) -> str:
    """Infer protocol only when the user supplied an unambiguous API path."""
    value = str(route).strip()
    if value.startswith(("http://", "https://")):
        path = urllib.parse.urlsplit(value).path
    else:
        path = value
    lowered = path.rstrip("/").casefold()
    if lowered.endswith("/chat/completions"):
        return "openai"
    if lowered.endswith("/messages"):
        return "anthropic"
    return ""


def endpoint_hint_from_error(error: BaseException | str) -> tuple[str, str] | None:
    """Extract a supported API route advertised by a proxy error."""
    message = str(error).lower()
    if "/v1/messages" in message:
        return "anthropic", "/v1/messages"
    if "/v1/chat/completions" in message:
        return "openai", "/v1/chat/completions"
    if "/chat/completions" in message:
        return "openai", "/chat/completions"
    if "/v1/responses" in message:
        return "responses", "/v1/responses"
    if "/responses" in message:
        return "responses", "/responses"
    return None


def is_endpoint_route_error(error: BaseException | str) -> bool:
    message = str(error).lower()
    if endpoint_hint_from_error(message):
        return True
    if any(marker in message for marker in ("model not found", "unknown model", "invalid model", "model unavailable")):
        return False
    return any(marker in message for marker in (
        "api 404", "api 405", "not found", "cannot post", "unsupported endpoint",
        "json olmayan yanıt", "boş veya json olmayan", "expecting value",
    ))


def redact_sensitive(value: str) -> str:
    text = str(value)
    patterns = (
        r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+",
        r"(?i)((?:api[_ -]?key|token|secret)\s*[:=]\s*)[^\s,;]+",
        r"(?i)\b(?:sk|gsk|hf|github_pat|glpat)[-_][a-z0-9_-]{12,}\b",
        r"(?i)\b(?:fe_oa|or-v1|nvapi|pplx|csk|xai)[-_]?[a-z0-9_-]{12,}\b",
        r"\bAIza[A-Za-z0-9_-]{20,}\b",
        r"(?i)\bhttps?://(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?(?:/[^\s,;]*)?",
    )
    for pattern in patterns:
        text = re.sub(pattern, lambda match: (match.group(1) if match.lastindex else "") + "[REDACTED]", text)
    return text


class SteeringInterrupt(RuntimeError):
    """User supplied a replacement instruction while an API call was active."""

    def __init__(self, prompt: str):
        super().__init__(prompt)
        self.prompt = prompt


def normalize_subagent_role(raw: Any, fallback: str = "explore") -> str:
    requested = str(raw or "").strip().lower()
    normalized = SUBAGENT_ROLE_ALIASES.get(requested, requested)
    return normalized if normalized in SUBAGENT_ROLES else fallback


def normalize_tool_name(name: str) -> str:
    """Map proxy-generated CompatToolName<hash> wrappers to known tools only."""
    raw = str(name).strip()
    if raw in TOOL_NAME_MAP.values():
        return raw
    compact = re.sub(r"[^a-z0-9]", "", raw.lower())
    if compact in TOOL_NAME_MAP:
        return TOOL_NAME_MAP[compact]
    if not compact.startswith("compat"):
        return raw
    compact = compact[len("compat"):]
    for alias in sorted(TOOL_NAME_MAP, key=len, reverse=True):
        if compact == alias:
            return TOOL_NAME_MAP[alias]
        if compact.startswith(alias) and re.fullmatch(r"[0-9a-f]{6,}", compact[len(alias):]):
            return TOOL_NAME_MAP[alias]
    return raw


def normalize_tool_arguments(name: str, args: Any) -> dict[str, Any]:
    """Translate Claude Code/native proxy argument names and discard extras."""
    source = args if isinstance(args, dict) else {}
    if name == "list_files":
        pattern = str(source.get("pattern") or source.get("glob") or "*")
        folder = str(source.get("path") or "").strip().replace("\\", "/").strip("/")
        if folder and folder not in {".", "*"} and not pathlib.PurePath(folder).is_absolute():
            pattern = f"{folder}/{pattern}"
        return {"pattern": pattern}
    if name == "read_file":
        path = source.get("path") or source.get("file_path")
        result: dict[str, Any] = {"path": str(path or "")}
        start = source.get("start_line", source.get("offset", 1))
        try:
            start_number = max(1, int(start or 1))
        except (TypeError, ValueError):
            start_number = 1
        result["start_line"] = start_number
        if source.get("end_line") is not None:
            try:
                result["end_line"] = int(source["end_line"])
            except (TypeError, ValueError):
                pass
        elif source.get("limit") is not None:
            try:
                result["end_line"] = start_number + max(1, int(source["limit"])) - 1
            except (TypeError, ValueError):
                pass
        return result
    if name == "search":
        return {
            "query": str(source.get("query") or source.get("pattern") or ""),
            "pattern": str(source.get("glob") or source.get("file_pattern") or "*"),
            "case_sensitive": bool(source.get("case_sensitive", False)),
        }
    if name == "write_file":
        return {
            "path": str(source.get("path") or source.get("file_path") or ""),
            "content": str(source.get("content") or source.get("text") or ""),
        }
    if name == "write_files":
        return {"files": source.get("files", [])}
    if name == "replace_text":
        return {
            "path": str(source.get("path") or source.get("file_path") or ""),
            "old_text": str(source.get("old_text") or source.get("old_string") or ""),
            "new_text": str(source.get("new_text") or source.get("new_string") or ""),
            "replace_all": bool(source.get("replace_all", False)),
        }
    if name == "apply_edits":
        return {"edits": source.get("edits", source.get("changes", []))}
    if name == "verify_artifacts":
        paths = source.get("paths", source.get("files", []))
        if isinstance(paths, str):
            paths = [paths]
        required_text = source.get("required_text", source.get("contains", {}))
        return {
            "paths": paths if isinstance(paths, list) else [],
            "required_text": required_text if isinstance(required_text, dict) else {},
        }
    if name == "web_quality_check":
        return {"require_multifile": bool(source.get("require_multifile", False))}
    if name == "run_command":
        result = {"command": str(source.get("command") or source.get("cmd") or "")}
        timeout = source.get("timeout_seconds", source.get("timeout"))
        if timeout is not None:
            try:
                timeout_number = int(timeout)
                if timeout_number > 1000:
                    timeout_number = max(1, timeout_number // 1000)
                result["timeout_seconds"] = timeout_number
            except (TypeError, ValueError):
                pass
        if "stdin" in source or "input" in source:
            result["stdin"] = str(source.get("stdin", source.get("input", "")))
        return result
    if name == "test_project":
        result = {"command": str(source.get("command") or source.get("cmd") or "")}
        timeout = source.get("timeout_seconds", source.get("timeout"))
        if timeout is not None:
            try:
                timeout_number = int(timeout)
                if timeout_number > 1000:
                    timeout_number = max(1, timeout_number // 1000)
                result["timeout_seconds"] = timeout_number
            except (TypeError, ValueError):
                pass
        if "stdin" in source or "input" in source:
            result["stdin"] = str(source.get("stdin", source.get("input", "")))
        result["interactive"] = bool(source.get("interactive", False))
        return result
    if name == "project_toolchain":
        action = str(source.get("action") or source.get("operation") or "inspect").strip().lower()
        target = str(source.get("target") or source.get("project_type") or source.get("type") or "auto").strip().lower()
        aliases = {
            "cpp": "cpp-cmake", "c++": "cpp-cmake", "cmake": "cpp-cmake",
            "dotnet": "dotnet-exe", "csharp": "dotnet-exe", "c#": "dotnet-exe", "exe": "dotnet-exe",
            "java": "java-jar", "jar": "java-jar", "maven": "java-jar",
            "minecraft": "paper-plugin", "paper": "paper-plugin", "mc-plugin": "paper-plugin",
        }
        target = aliases.get(target, target)
        if action not in {"inspect", "scaffold", "build", "test", "package"}:
            action = "inspect"
        if target not in {"auto", "cpp-cmake", "dotnet-exe", "java-jar", "paper-plugin"}:
            target = "auto"
        result = {
            "action": action,
            "target": target,
            "name": str(source.get("name") or source.get("project_name") or ""),
            "package_name": str(source.get("package_name") or source.get("package") or source.get("namespace") or ""),
            "language_version": str(source.get("language_version") or source.get("java_version") or source.get("framework") or ""),
            "platform_version": str(source.get("platform_version") or source.get("minecraft_version") or source.get("paper_version") or ""),
            "configuration": str(source.get("configuration") or source.get("config") or "Release"),
            "runtime": str(source.get("runtime") or source.get("rid") or ""),
            "self_contained": bool(source.get("self_contained", False)),
            "overwrite": bool(source.get("overwrite", False)),
        }
        timeout = source.get("timeout_seconds", source.get("timeout"))
        if timeout is not None:
            try:
                result["timeout_seconds"] = int(timeout)
            except (TypeError, ValueError):
                pass
        return result
    if name == "start_process":
        return {"command": str(source.get("command") or source.get("cmd") or "")}
    if name == "process_input":
        return {
            "process_id": str(source.get("process_id") or source.get("id") or ""),
            "input": str(source.get("input", source.get("text", ""))),
            "append_newline": bool(source.get("append_newline", True)),
        }
    if name == "process_status":
        result = {"process_id": str(source.get("process_id") or source.get("id") or "")}
        try:
            result["wait_ms"] = max(0, min(3000, int(source.get("wait_ms", 300))))
        except (TypeError, ValueError):
            result["wait_ms"] = 300
        return result
    if name == "stop_process":
        return {"process_id": str(source.get("process_id") or source.get("id") or "")}
    if name == "get_diagnostics":
        return {}
    if name == "set_forgecode_setting":
        return {
            "name": str(source.get("name") or source.get("setting") or ""),
            "value": str(source.get("value", "")),
            "reason": str(source.get("reason") or source.get("rationale") or ""),
        }
    if name == "list_skills":
        return {"query": str(source.get("query") or source.get("filter") or "")}
    if name == "manage_skill":
        return {
            "action": str(source.get("action") or "show").strip().lower(),
            "name": str(source.get("name") or source.get("skill") or ""),
            "source": str(source.get("source") or source.get("url") or ""),
            "scope": str(source.get("scope") or "user").strip().lower(),
            "description": str(source.get("description") or ""),
            "instructions": str(source.get("instructions") or source.get("content") or ""),
        }
    if name == "manage_mcp_server":
        return {
            "action": str(source.get("action") or "status").strip().lower(),
            "name": str(source.get("name") or source.get("server") or ""),
            "transport": str(source.get("transport") or "stdio").strip().lower(),
            "command": str(source.get("command") or ""),
            "args": [str(item) for item in source.get("args", [])] if isinstance(source.get("args", []), list) else [],
            "url": str(source.get("url") or source.get("endpoint") or ""),
        }
    if name == "graph_context":
        action = str(source.get("action") or "status").strip().lower()
        if action not in {"status", "impact", "review"}:
            action = "status"
        return {"action": action, "base": str(source.get("base") or "HEAD~1")}
    if name == "manage_terminal":
        assignments = source.get("assignments", [])
        return {
            "action": str(source.get("action") or "status").strip().lower(),
            "terminal": str(source.get("terminal") or ""),
            "role": str(source.get("role") or "explore"),
            "visible": bool(source.get("visible", False)),
            "task": str(source.get("task") or ""),
            "thinking": str(source.get("thinking") or ""),
            "output_cap": int(source.get("output_cap") or 0),
            "assignments": assignments if isinstance(assignments, list) else [],
        }
    if name == "browser_control":
        return {key: str(source.get(key) or "") for key in ("action", "url", "selector", "text", "tab_id")}
    if name == "music_control":
        return {"action": str(source.get("action") or "status"), "url": str(source.get("url") or ""),
                "title": str(source.get("title") or "")}
    if name == "delegate_task":
        requested_role = str(source.get("role") or source.get("subagent_type") or "explore").lower()
        role = normalize_subagent_role(requested_role)
        task = source.get("task") or source.get("prompt") or source.get("description") or ""
        return {"role": role, "task": str(task)}
    return {}


def powershell_literal_path(raw: str) -> str:
    """Return a PowerShell-safe literal path, including paths with spaces."""
    value = str(raw).strip().strip('"\'').replace("'", "''")
    return f"'{value}'"


def windows_shell_command(command: str) -> str:
    """Translate the small Unix inspection idioms Claude Code commonly emits."""
    translated = adapt_powershell_chain(command)
    translated = re.sub(r"(?<![\w-])ls\s+-(?:la|al|a|l)\b(?!-)", "Get-ChildItem -Force", translated)
    translated = re.sub(r"(?<![\w-])ls\b(?!-)", "Get-ChildItem", translated)
    translated = translated.replace("2>/dev/null", "2>$null").replace(">/dev/null", ">$null")
    translated = re.sub(
        r"\bmkdir\s+-p\s+([^;|&]+)",
        lambda match: f"New-Item -ItemType Directory -Force -LiteralPath {powershell_literal_path(match.group(1))}",
        translated,
    )
    translated = re.sub(
        r"(?i)(?<![\w-])cd\s+([^;|&]+)",
        lambda match: f"Set-Location -LiteralPath {powershell_literal_path(match.group(1))}",
        translated,
    )

    def cat_slice(match: re.Match[str]) -> str:
        direction = "Last" if match.group("direction").lower() == "tail" else "First"
        return f"Get-Content -LiteralPath {powershell_literal_path(match.group('path'))} -Encoding UTF8 | Select-Object -{direction} {int(match.group('count'))}"

    path_pattern = r'(?P<path>"[^"\r\n]+"|\'[^\'\r\n]+\'|[^\s|;&]+)'
    translated = re.sub(
        rf"\bcat\s+{path_pattern}\s*\|\s*(?P<direction>tail|head)\s+(?:-n\s+)?-?(?P<count>\d+)\b",
        cat_slice, translated, flags=re.IGNORECASE,
    )
    translated = re.sub(
        rf"\bcat\s+{path_pattern}",
        lambda match: f"Get-Content -LiteralPath {powershell_literal_path(match.group('path'))} -Encoding UTF8",
        translated, flags=re.IGNORECASE,
    )
    return translated


def decode_subprocess_output(value: bytes | str | None) -> str:
    """Decode Windows command output without locale reader-thread crashes."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if value.startswith((b"\xff\xfe", b"\xfe\xff")) or (value and value.count(b"\x00") > len(value) // 5):
        try:
            return value.decode("utf-16")
        except UnicodeError:
            pass
    encodings = ["utf-8", locale.getpreferredencoding(False), "cp1254", "cp857", "cp850"]
    attempted: set[str] = set()
    for encoding in encodings:
        normalized = encoding.lower()
        if normalized in attempted:
            continue
        attempted.add(normalized)
        try:
            return value.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return value.decode("utf-8", errors="replace")


def clean_native_runtime_noise(value: str) -> str:
    """Hide CPython's harmless AppContainer real-path diagnostic."""
    return "\n".join(
        line for line in str(value).replace("\r\n", "\n").split("\n")
        if not (line.startswith("Failed to find real location of ") and line.rstrip().lower().endswith("python.exe"))
    )


def mcp_slug(value: str) -> str:
    """Return a stable MCP/tool identifier accepted by all provider codecs."""
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(value).strip()).strip("_-").lower()
    return slug[:64] or "server"
