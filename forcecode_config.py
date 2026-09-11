#!/usr/bin/env python3
"""ForceCode config — Config + connection profiles. Depends only on base."""

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

from forcecode_base import (
    DEFAULT_CONFIG, HOST_PATH_TYPE, app_home, atomic_json, load_json,
    migrate_legacy_app_home, normalize_api_base_url, normalize_custom_route,
    inferred_custom_route, custom_protocol_for_route, redact_sensitive, set_ui_language,
)

def _fc(name):
    import forcecode as _m
    return getattr(_m, name)


APP_NAME = "ForceCode"


PROVIDERS: dict[str, dict[str, Any]] = {
    "anthropic": {"label": "Anthropic / Claude", "mode": "anthropic", "url": "https://api.anthropic.com", "model": "claude-sonnet-4-5", "env": "ANTHROPIC_API_KEY", "key": True},
    "openai": {"label": "OpenAI", "mode": "responses", "url": "https://api.openai.com/v1", "model": "gpt-5-mini", "env": "OPENAI_API_KEY", "key": True},
    "openrouter": {"label": "OpenRouter (çoklu model)", "mode": "chat", "url": "https://openrouter.ai/api/v1", "model": "openrouter/free", "env": "OPENROUTER_API_KEY", "key": True},
    "gemini": {"label": "Google Gemini", "mode": "chat", "url": "https://generativelanguage.googleapis.com/v1beta/openai", "model": "gemini-3.5-flash", "env": "GEMINI_API_KEY", "key": True},
    "groq": {"label": "GroqCloud", "mode": "chat", "url": "https://api.groq.com/openai/v1", "model": "llama-3.3-70b-versatile", "env": "GROQ_API_KEY", "key": True},
    "mistral": {"label": "Mistral AI", "mode": "chat", "url": "https://api.mistral.ai/v1", "model": "mistral-large-latest", "env": "MISTRAL_API_KEY", "key": True},
    "deepseek": {"label": "DeepSeek", "mode": "chat", "url": "https://api.deepseek.com", "model": "deepseek-chat", "env": "DEEPSEEK_API_KEY", "key": True},
    "xai": {"label": "xAI / Grok", "mode": "chat", "url": "https://api.x.ai/v1", "model": "grok-4-1-fast-reasoning", "env": "XAI_API_KEY", "key": True},
    "together": {"label": "Together AI", "mode": "chat", "url": "https://api.together.xyz/v1", "model": "meta-llama/Llama-3.3-70B-Instruct-Turbo", "env": "TOGETHER_API_KEY", "key": True},
    "fireworks": {"label": "Fireworks AI", "mode": "chat", "url": "https://api.fireworks.ai/inference/v1", "model": "accounts/fireworks/models/llama-v3p3-70b-instruct", "env": "FIREWORKS_API_KEY", "key": True},
    "perplexity": {"label": "Perplexity", "mode": "chat", "url": "https://api.perplexity.ai", "model": "sonar-pro", "env": "PERPLEXITY_API_KEY", "key": True},
    "cerebras": {"label": "Cerebras", "mode": "chat", "url": "https://api.cerebras.ai/v1", "model": "gpt-oss-120b", "env": "CEREBRAS_API_KEY", "key": True},
    "sambanova": {"label": "SambaNova", "mode": "chat", "url": "https://api.sambanova.ai/v1", "model": "Meta-Llama-3.3-70B-Instruct", "env": "SAMBANOVA_API_KEY", "key": True},
    "nvidia": {"label": "NVIDIA NIM", "mode": "chat", "url": "https://integrate.api.nvidia.com/v1", "model": "meta/llama-3.3-70b-instruct", "env": "NVIDIA_API_KEY", "key": True},
    "cohere": {"label": "Cohere", "mode": "chat", "url": "https://api.cohere.ai/compatibility/v1", "model": "command-a-03-2025", "env": "COHERE_API_KEY", "key": True},
    "kimchi": {"label": "Kimchi Inference", "mode": "chat", "url": "https://llm.kimchi.dev/openai/v1", "model": "minimax-m3", "env": "KIMCHI_API_KEY", "key": True, "input_price": 0.30, "output_price": 1.20},
    "ollama": {"label": "Ollama (yerel, ücretsiz)", "mode": "chat", "url": "http://localhost:11434/v1", "model": "qwen3-coder", "env": "", "key": False},
    "lmstudio": {"label": "LM Studio (yerel)", "mode": "chat", "url": "http://localhost:1234/v1", "model": "local-model", "env": "", "key": False},
    "custom": {"label": "Özel OpenAI / Claude Code servisi", "mode": "chat", "url": "http://localhost:8000/v1", "model": "model-name", "env": "CUSTOM_API_KEY", "key": False},
    "github": {"label": "GitHub Models", "mode": "chat", "url": "https://models.github.ai/inference", "models_url": "https://models.github.ai/catalog/models", "model": "openai/gpt-4.1", "env": "GITHUB_TOKEN", "key": True, "headers": {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2026-03-10"}},
    "huggingface": {"label": "Hugging Face Inference Providers", "mode": "chat", "url": "https://router.huggingface.co/v1", "model": "openai/gpt-oss-120b:fastest", "env": "HF_TOKEN", "key": True},
    "siliconflow": {"label": "SiliconFlow", "mode": "chat", "url": "https://api.siliconflow.com/v1", "model": "deepseek-ai/DeepSeek-V3.2", "env": "SILICONFLOW_API_KEY", "key": True},
    "dashscope": {"label": "Alibaba DashScope / Qwen", "mode": "chat", "url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus", "env": "DASHSCOPE_API_KEY", "key": True},
    "freemodel": {"label": "FreeModel (resmî API)", "mode": "chat", "url": "https://api.freemodel.dev/v1", "model": "auto", "env": "FREEMODEL_API_KEY", "key": True},
    # Subscription adapters never copy browser cookies or OAuth tokens. They
    # call the vendor's already-authenticated official CLI as a child process.
    "claude-subscription": {"label": "Claude Code subscription (official CLI)", "mode": "subscription", "url": "", "model": "default", "env": "", "key": False, "command": ["claude", "-p", "--output-format", "text", "--permission-mode", "plan"], "setup": ["claude", "auth", "login"], "models": ["default", "sonnet", "opus", "haiku"], "model_arg": ["--model"]},
    "codex-subscription": {"label": "ChatGPT/Codex subscription (official CLI)", "mode": "subscription", "url": "", "model": "configured", "env": "", "key": False, "command": ["codex", "exec", "--skip-git-repo-check", "--sandbox", "read-only", "--ephemeral", "--color", "never", "--json"], "output": "jsonl", "setup": ["codex", "login"], "model_arg": ["--model"]},
    "cline-subscription": {"label": "Cline subscription (official CLI)", "mode": "subscription", "url": "", "model": "configured", "env": "", "key": False, "command": ["cline", "--json", "--auto-approve", "false", "--plan"], "output": "jsonl", "setup": ["cline", "auth"], "model_arg": ["--model"]},
    "gemini-subscription": {"label": "Gemini subscription (official CLI)", "mode": "subscription", "url": "", "model": "gemini-subscription", "env": "", "key": False, "command": ["gemini", "-p"], "setup": ["gemini"]},
}


PROFILE_FIELDS = (
    "provider", "model", "api_mode", "base_url", "custom_protocol", "custom_auth_mode",
    "custom_endpoint_path",
    "input_price_per_million", "output_price_per_million",
)


CONNECTION_STATE_FIELDS = (*PROFILE_FIELDS, "base_url_origin", "setup_complete")


class Config:
    def __init__(self, home: pathlib.Path | None = None):
        self.home = home or app_home()
        if home is None:
            migrate_legacy_app_home(self.home)
        self.path = self.home / "config.json"
        saved = load_json(self.path, {})
        # v2.3 and older used a silent 120-second default. Preserve custom
        # values, but migrate that legacy default to the safer v2.4 limit.
        if saved.get("config_version", 1) < 2 and saved.get("timeout_seconds", 120) == 120:
            saved["timeout_seconds"] = 60
        if saved.get("config_version", 1) < 13 and saved.get("timeout_seconds", 60) == 60:
            saved["timeout_seconds"] = 100
        if saved.get("config_version", 1) < 8 and saved.get("temperature", 0.2) == 0.2:
            saved["temperature"] = 1.0
        # v5.7 removes the fixed main-agent turn cap. Keep the setting for
        # backwards-compatible config files; zero means unlimited.
        if saved.get("config_version", 1) < 16 and saved.get("max_agent_steps", 12) == 12:
            saved["max_agent_steps"] = 0
        if saved.get("config_version", 1) < 23 and saved.get("provider") == "custom":
            pinned_protocol = custom_protocol_for_route(str(saved.get("custom_endpoint_path", "auto")))
            if pinned_protocol:
                saved["custom_protocol"] = pinned_protocol
                saved["api_mode"] = "anthropic" if pinned_protocol == "anthropic" else "chat"
                # Older /connect versions could learn x-api-key from a wrong
                # protocol probe. Re-detect authentication once with the
                # corrected wire format.
                saved["custom_auth_mode"] = "auto"
        # v7.7.2 removes the old aggregate 200 MB ForceSandbox default. Only
        # migrate the legacy default; deliberately customized limits remain.
        if saved.get("config_version", 1) < 24 and saved.get("sandbox_max_transfer_mb", 200) == 200:
            saved["sandbox_max_transfer_mb"] = 0
        saved["config_version"] = 31
        self.data = copy.deepcopy(DEFAULT_CONFIG)
        self.data.update(saved)
        self.data["_runtime_enable_sandbox"] = home is None
        set_ui_language(str(self.data.get("ui_language", "tr")))
        if self.data.get("backup_active") and self.data.get("backup_api_key"):
            self.data["_runtime_api_key_override"] = str(self.data["backup_api_key"])

    def save(self) -> None:
        if self.data.get("_runtime_no_save"):
            return
        persisted = {key: value for key, value in self.data.items() if not str(key).startswith("_runtime_")}
        atomic_json(self.path, persisted)

    def key(self) -> str:
        if self.data.get("_runtime_api_key_override") is not None:
            return str(self.data.get("_runtime_api_key_override") or "")
        provider = self.data["provider"]
        env_name = PROVIDERS.get(provider, PROVIDERS["custom"]).get("env", "")
        return os.environ.get(env_name, "") or self.data.get(f"{provider}_api_key", "")

    def mode(self) -> str:
        if self.data.get("provider") == "custom":
            protocol = str(self.data.get("custom_protocol", "auto")).lower()
            # `off` disables protocol inference/enforcement, not JSON itself:
            # the last explicitly selected wire codec remains in api_mode.
            # This lets custom gateways receive requests at an exact URL even
            # when that URL happens to resemble a well-known API route.
            if protocol == "off":
                payload_mode = str(self.data.get("api_mode", "chat")).lower()
                return payload_mode if payload_mode in {"anthropic", "chat", "responses"} else "chat"
            routed_protocol = custom_protocol_for_route(str(self.data.get("custom_endpoint_path", "auto")))
            if routed_protocol:
                return "anthropic" if routed_protocol == "anthropic" else "chat"
            if protocol == "anthropic":
                return "anthropic"
            if protocol == "openai":
                return "chat"
            model = str(self.data.get("model", "")).lower()
            if model.startswith("claude-") or "anthropic" in model:
                return "anthropic"
        return str(self.data.get("api_mode") or PROVIDERS.get(self.data["provider"], PROVIDERS["custom"])["mode"])

    def base_url(self) -> str:
        if self.data.get("provider") == "anthropic":
            configured = str(self.data.get("base_url") or "").strip()
            preset = str(PROVIDERS["anthropic"]["url"])
            origin = str(self.data.get("base_url_origin", ""))
            if configured and (origin in {"explicit", "discovered", "profile"} or configured.rstrip("/") != preset.rstrip("/")):
                return configured
            env_base = os.environ.get("ANTHROPIC_BASE_URL", "").strip()
            if env_base:
                return normalize_api_base_url(env_base)
        return str(self.data.get("base_url") or PROVIDERS.get(self.data["provider"], PROVIDERS["custom"])["url"])

    def base_url_source(self) -> str:
        if self.data.get("provider") == "anthropic":
            configured = str(self.data.get("base_url") or "").strip()
            preset = str(PROVIDERS["anthropic"]["url"])
            origin = str(self.data.get("base_url_origin", ""))
            if configured and (origin in {"explicit", "discovered", "profile"} or configured.rstrip("/") != preset.rstrip("/")):
                return "ayar"
            if os.environ.get("ANTHROPIC_BASE_URL", "").strip():
                return "ANTHROPIC_BASE_URL"
        return str(self.data.get("base_url_origin") or "ayar")

    def requires_key(self) -> bool:
        return bool(PROVIDERS.get(self.data["provider"], PROVIDERS["custom"])["key"])

    def select_provider(self, provider: str) -> None:
        provider = provider.lower()
        if provider not in PROVIDERS:
            raise ValueError(f"Bilinmeyen sağlayıcı: {provider}")
        preset = PROVIDERS[provider]
        previous_provider = str(self.data.get("provider", ""))
        previous_base = str(self.data.get("base_url", ""))
        reusable_freemodel_key = ""
        if provider == "freemodel" and previous_provider == "custom":
            try:
                previous_host = (urllib.parse.urlsplit(previous_base).hostname or "").casefold()
            except ValueError:
                previous_host = ""
            if previous_host in {"api.freemodel.dev", "work.freemodel.dev"}:
                reusable_freemodel_key = str(self.data.get("custom_api_key", ""))
        self.data.pop("_runtime_api_key_override", None)
        self.data.update({
            "provider": provider, "model": preset["model"], "api_mode": preset["mode"], "base_url": preset["url"], "setup_complete": True,
            "base_url_origin": "preset",
            "input_price_per_million": float(preset.get("input_price", 0.0)),
            "output_price_per_million": float(preset.get("output_price", 0.0)),
            "backup_active": False,
            "backup_primary_state": {},
        })
        if reusable_freemodel_key and not self.data.get("freemodel_api_key"):
            # Reuse only a key the user already saved for a FreeModel host.
            # The secret remains local and is never printed or copied to docs.
            self.data["freemodel_api_key"] = reusable_freemodel_key
        self.save()

    def masked_key(self) -> str:
        key = self.key()
        return "ayarlanmadı" if not key else f"{key[:5]}…{key[-4:]}"

    def set_value(self, name: str, raw: str) -> None:
        if name not in DEFAULT_CONFIG and not name.endswith("_api_key"):
            raise ValueError(f"Bilinmeyen ayar: {name}")
        if name == "provider":
            self.select_provider(raw)
            return
        if name == "ui_language":
            value = raw.lower()
            if value not in {"tr", "en"}:
                raise ValueError("ui_language must be tr or en")
        elif name == "ui_theme":
            value = raw.lower()
            if value not in {"dark", "light"}:
                raise ValueError("ui_theme must be dark or light")
        elif name == "max_agent_steps":
            if int(raw) != 0:
                raise ValueError("Sabit ajan adım sınırı kaldırıldı; max_agent_steps yalnızca 0 (sınırsız) olabilir")
            value = 0
        elif name in {"max_tokens", "input_budget_tokens", "timeout_seconds", "first_response_timeout_seconds", "stream_idle_timeout_seconds", "request_total_timeout_seconds", "retry_budget_seconds", "preflight_timeout_seconds", "stall_first_response_seconds", "stall_stream_idle_seconds", "stall_retry_attempts", "goal_max_rounds", "flow_max_tasks", "flow_max_rounds", "flow_repair_rounds", "retry_attempts", "max_tool_output_chars", "web_max_results", "thinking_budget_tokens", "subagent_max_per_turn", "subagent_timeout_seconds", "memory_max_items", "history_context_turns", "history_context_chars", "event_log_max_lines", "session_log_max_lines", "team_max_workers", "sandbox_max_file_mb", "sandbox_max_transfer_mb", "vibe_max_hours", "vibe_review_cycles", "vibe_failure_retries", "vibe_retry_delay_seconds", "vibe_command_timeout_seconds", "skill_scout_min_security", "skill_scout_min_relevance", "skill_scout_max_auto_install", "skill_scout_max_project_skills", "skill_scout_cooldown_hours", "mcp_timeout_seconds", "chrome_debug_port"}:
            value: Any = int(raw)
            zero_allowed = {"flow_repair_rounds", "sandbox_max_transfer_mb", "stall_retry_attempts"}
            if value < 0 or (value == 0 and name not in zero_allowed):
                raise ValueError("Değer sıfırdan büyük olmalı")
            if name == "retry_attempts" and value > 5:
                raise ValueError("retry_attempts 1 ile 5 arasında olmalı")
            if name == "stall_retry_attempts" and value > 3:
                raise ValueError("stall_retry_attempts 0 ile 3 arasında olmalı")
            if name == "flow_max_tasks" and value > 50:
                raise ValueError("flow_max_tasks 1 ile 50 arasında olmalı")
            if name in {"team_max_workers", "subagent_max_per_turn"} and value > 3:
                raise ValueError(f"{name} en fazla 3 olabilir (ana yöneticiyle toplam 4 AI)")
            if name in {"skill_scout_min_security", "skill_scout_min_relevance"} and value > 100:
                raise ValueError(f"{name} 1 ile 100 arasında olmalı")
            if name == "skill_scout_max_auto_install" and value > 5:
                raise ValueError("skill_scout_max_auto_install en fazla 5 olabilir")
            if name == "skill_scout_max_project_skills" and value > 50:
                raise ValueError("skill_scout_max_project_skills en fazla 50 olabilir")
            if name == "skill_scout_cooldown_hours" and value > 720:
                raise ValueError("skill_scout_cooldown_hours en fazla 720 olabilir")
            stall_maximums = {"stall_first_response_seconds": 900, "stall_stream_idle_seconds": 1800}
            if name in stall_maximums and value > stall_maximums[name]:
                raise ValueError(f"{name} en fazla {stall_maximums[name]} olabilir")
            if name in {"flow_max_rounds", "flow_repair_rounds"} and value > 10:
                raise ValueError(f"{name} en fazla 10 olabilir")
            vibe_maximums = {
                "vibe_max_hours": 24,
                "vibe_review_cycles": 10,
                "vibe_failure_retries": 20,
                "vibe_retry_delay_seconds": 300,
                "vibe_command_timeout_seconds": 3600,
            }
            if name in vibe_maximums and value > vibe_maximums[name]:
                raise ValueError(f"{name} en fazla {vibe_maximums[name]} olabilir")
            watchdog_maximums = {
                "first_response_timeout_seconds": 180,
                "stream_idle_timeout_seconds": 300,
                "request_total_timeout_seconds": 600,
                "retry_budget_seconds": 300,
                "preflight_timeout_seconds": 60,
            }
            if name in watchdog_maximums and value > watchdog_maximums[name]:
                raise ValueError(f"{name} en fazla {watchdog_maximums[name]} olabilir")
            sandbox_maximums = {"sandbox_max_file_mb": 1024, "sandbox_max_transfer_mb": 4096}
            if name in sandbox_maximums and value > sandbox_maximums[name]:
                raise ValueError(f"{name} en fazla {sandbox_maximums[name]} olabilir")
        elif name in {"temperature", "retry_backoff_seconds", "retry_jitter_ratio", "input_price_per_million", "output_price_per_million"}:
            value = float(raw)
            if value < 0:
                raise ValueError("Değer negatif olamaz")
            if name == "temperature" and value > 1:
                raise ValueError("temperature 0 ile 1 arasında olmalı")
            if name == "retry_backoff_seconds" and value > 10:
                raise ValueError("retry_backoff_seconds 0 ile 10 arasında olmalı")
            if name == "retry_jitter_ratio" and value > 1:
                raise ValueError("retry_jitter_ratio 0 ile 1 arasında olmalı")
        elif name in {"auto_approve_writes", "auto_approve_commands", "setup_complete", "ui_language_selected", "ui_markdown", "auto_subagents", "autopilot_mode", "smart_autopilot_mode", "persistent_memory_enabled", "event_log_enabled", "team_parallel", "backup_enabled", "backup_active", "streaming_enabled", "watchdog_enabled", "stall_guard_enabled", "forcegraph_auto_enabled", "mcp_enabled", "sandbox_enabled", "sandbox_network_enabled", "sandbox_auto_transfer", "sandbox_snapshot_enabled", "flow_quality_gate", "auto_model_switch", "model_lock", "skills_enabled", "skill_auto_select", "skill_scout_enabled", "vibe_mode", "youtube_music_autostart", "manager_design_mode"}:
            if raw.lower() not in {"true", "false", "on", "off", "1", "0", "yes", "no"}:
                raise ValueError("true veya false kullanın")
            value = raw.lower() in {"true", "on", "1", "yes"}
        elif name == "web_search_mode":
            value = raw.lower()
            if value not in {"off", "auto", "on"}:
                raise ValueError("web_search_mode: off, auto veya on olmalı")
        elif name == "thinking_mode":
            value = raw.lower()
            if value not in {"off", "low", "medium", "high"}:
                raise ValueError("thinking_mode: off, low, medium veya high olmalı")
        elif name == "efficiency_mode":
            value = raw.lower()
            if value not in {"off", "balanced", "max"}:
                raise ValueError("efficiency_mode: off, balanced veya max olmalı")
        elif name == "power_mode":
            value = raw.lower()
            if value not in {"off", "auto", "on"}:
                raise ValueError("power_mode: off, auto veya on olmalı")
        elif name == "sandbox_engine":
            value = raw.lower()
            if value not in {"auto", "native", "docker", "podman"}:
                raise ValueError("sandbox_engine: auto, native, docker veya podman olmalı")
        elif name == "custom_auth_mode":
            value = raw.lower()
            if value not in {"auto", "bearer", "x-api-key", "api-key", "both", "none"}:
                raise ValueError("custom_auth_mode: auto, bearer, x-api-key, api-key, both veya none olmalı")
        elif name == "custom_protocol":
            value = raw.lower()
            if value not in {"auto", "off", "openai", "anthropic"}:
                raise ValueError("custom_protocol: auto, off, openai veya anthropic olmalı")
        elif name == "custom_endpoint_path":
            value = normalize_custom_route(raw)
        elif name == "web_project_mode":
            value = raw.lower()
            if value not in {"auto", "single", "multi"}:
                raise ValueError("web_project_mode: auto, single veya multi olmalı")
        elif name == "work_mode":
            value = raw.lower()
            if value not in {"auto", "plan", "build"}:
                raise ValueError("work_mode: auto, plan veya build olmalı")
        elif name == "team_roles":
            allowed_roles = {"explore", "review", "plan", "design", "backend", "frontend", "research", "test", "security"}
            value = [item.strip().lower() for item in re.split(r"[,\s]+", raw) if item.strip()]
            if not value or any(item not in allowed_roles for item in value):
                raise ValueError("team_roles geçerli rollerin virgülle ayrılmış listesi olmalı")
            value = list(dict.fromkeys(value))
        elif name in {"startup_prompt", "system_prompt_extra"}:
            value = redact_sensitive(raw)
        else:
            value = raw
        self.data[name] = value
        if name == "ui_language":
            self.data["ui_language_selected"] = True
            set_ui_language(str(value))
        if name == "base_url":
            raw_url = str(value)
            self.data[name] = normalize_api_base_url(raw_url)
            self.data["base_url_origin"] = "explicit"
            if self.data.get("provider") == "custom":
                self.data["custom_endpoint_path"] = inferred_custom_route(raw_url)
        self.save()


def connection_state(cfg: Config) -> dict[str, Any]:
    state = {field: copy.deepcopy(cfg.data.get(field)) for field in CONNECTION_STATE_FIELDS}
    state["base_url"] = normalize_api_base_url(cfg.base_url())
    return state


def apply_connection_state(cfg: Config, state: dict[str, Any]) -> None:
    provider = str(state.get("provider", ""))
    if provider not in PROVIDERS:
        raise ValueError(f"Bağlantıda bilinmeyen sağlayıcı: {provider}")
    for field in CONNECTION_STATE_FIELDS:
        if field in state:
            cfg.data[field] = copy.deepcopy(state[field])
    cfg.data["base_url"] = normalize_api_base_url(str(state.get("base_url") or PROVIDERS[provider]["url"]))
    cfg.data["base_url_origin"] = str(state.get("base_url_origin") or "backup")
    cfg.data["setup_complete"] = True


def backup_connection_for(cfg: Config, target: str, model: str = "") -> dict[str, Any]:
    wanted = str(target).strip().lower()
    profiles = cfg.data.get("connection_profiles", {})
    if isinstance(profiles, dict) and isinstance(profiles.get(wanted), dict):
        state = dict(profiles[wanted])
        state["base_url_origin"] = "profile"
        state["setup_complete"] = True
    elif wanted in PROVIDERS and wanted != "custom":
        preset = PROVIDERS[wanted]
        state = {
            "provider": wanted,
            "model": preset["model"],
            "api_mode": preset["mode"],
            "base_url": preset["url"],
            "base_url_origin": "preset",
            "setup_complete": True,
            "custom_protocol": "auto",
            "custom_auth_mode": "auto",
            "custom_endpoint_path": "auto",
            "input_price_per_million": float(preset.get("input_price", 0.0)),
            "output_price_per_million": float(preset.get("output_price", 0.0)),
        }
    elif wanted == "custom":
        raise ValueError("Custom yedek için önce bağlantıyı kurup /profile save <ad> kullanın")
    else:
        raise ValueError(f"Sağlayıcı veya bağlantı profili bulunamadı: {wanted}")
    if model.strip():
        state["model"] = model.strip()
    state["base_url"] = normalize_api_base_url(str(state["base_url"]))
    return state


def make_backup_config(cfg: Config) -> Config:
    state = cfg.data.get("backup_connection", {})
    if not isinstance(state, dict) or not state.get("provider"):
        raise ValueError("Yedek API seçilmedi. /backup set <sağlayıcı|profil> kullanın")
    backup_cfg = Config(cfg.home)
    backup_cfg.data = copy.deepcopy(cfg.data)
    backup_cfg.data["_runtime_no_save"] = True
    apply_connection_state(backup_cfg, state)
    if cfg.data.get("backup_api_key"):
        backup_cfg.data["_runtime_api_key_override"] = str(cfg.data["backup_api_key"])
    else:
        backup_cfg.data.pop("_runtime_api_key_override", None)
    return backup_cfg


def is_limit_or_quota_error(error: BaseException | str) -> bool:
    message = str(error).lower()
    markers = (
        "api 429", "api 402", "too many requests", "rate limit", "rate_limit",
        "quota", "insufficient_quota", "resource_exhausted", "resource exhausted",
        "usage limit", "limit exceeded", "credit balance", "insufficient credit",
        "insufficient balance", "out of credits", "tokens exhausted", "billing limit",
        "capacity exceeded", "overloaded capacity",
    )
    return any(marker in message for marker in markers)


def masked_secret(value: Any) -> str:
    secret = str(value or "")
    if not secret:
        return "ayarlanmadı"
    if len(secret) <= 9:
        return "•" * len(secret)
    return f"{secret[:5]}…{secret[-4:]}"


def backup_status(cfg: Config) -> tuple[str, str]:
    state = cfg.data.get("backup_connection", {})
    if not isinstance(state, dict) or not state.get("provider"):
        return "kapalı", "seçilmedi"
    target = f"{state.get('provider')}/{state.get('model') or 'varsayılan'}"
    if cfg.data.get("backup_active"):
        return "AKTİF", target
    return ("hazır" if cfg.data.get("backup_enabled") else "kapalı"), target


def profile_name(raw: str) -> str:
    name = str(raw).strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,31}", name):
        raise ValueError("Profil adı 1-32 karakter olmalı; harf, rakam, _ ve - kullanın")
    return name


def save_connection_profile(cfg: Config, raw_name: str) -> dict[str, Any]:
    name = profile_name(raw_name)
    profile = {field: cfg.data.get(field) for field in PROFILE_FIELDS}
    profile["base_url"] = normalize_api_base_url(cfg.base_url())
    profiles = dict(cfg.data.get("connection_profiles", {}))
    profiles[name] = profile
    cfg.data["connection_profiles"] = profiles
    cfg.save()
    return profile


def use_connection_profile(cfg: Config, raw_name: str) -> dict[str, Any]:
    name = profile_name(raw_name)
    profiles = cfg.data.get("connection_profiles", {})
    if not isinstance(profiles, dict) or name not in profiles:
        raise ValueError(f"Bağlantı profili bulunamadı: {name}")
    profile = dict(profiles[name])
    provider = str(profile.get("provider", "custom"))
    if provider not in PROVIDERS:
        raise ValueError(f"Profilde bilinmeyen sağlayıcı: {provider}")
    for field in PROFILE_FIELDS:
        if field in profile:
            cfg.data[field] = profile[field]
    cfg.data["base_url"] = normalize_api_base_url(str(profile["base_url"]))
    cfg.data["base_url_origin"] = "profile"
    cfg.data["setup_complete"] = True
    cfg.data["backup_active"] = False
    cfg.data["backup_primary_state"] = {}
    cfg.data.pop("_runtime_api_key_override", None)
    cfg.save()
    return profile


def delete_connection_profile(cfg: Config, raw_name: str) -> bool:
    name = profile_name(raw_name)
    profiles = dict(cfg.data.get("connection_profiles", {}))
    if name not in profiles:
        return False
    del profiles[name]
    cfg.data["connection_profiles"] = profiles
    cfg.save()
    return True
