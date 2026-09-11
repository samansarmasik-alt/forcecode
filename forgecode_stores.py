#!/usr/bin/env python3
"""ForgeCode stores — cerrahi bölünme adım 1+2 (leaf extraction).

Canonical home for the most isolated persistence leaves:
- Usage / UsageStore  (home/usage.jsonl)
- HistoryStore        (root/.forgecode/history.jsonl)
- SessionStore + safe_session_name (root/.forgecode/sessions/*.jsonl)
- trim_jsonl_file     (shared bounded-append helper)

Neden bunlar ilk?
- Graph: UsageStore -> sadece __init__ caller, 3 metod; HistoryStore -> sadece
  __init__ caller, 3 metod; SessionStore -> __init__/switch_session/
  build_portable_handoff/handle_command caller'ları, hepsi aynı aile.
  Hiçbir provider / WorkspaceTools bunlara doğrudan bağlı değil.
- forgecode.py bu sembolleri `try: from forgecode_stores import ...` ile alır;
  dosya silinirse eski gömülü fallback çalışır.
- SessionStore Config'e sadece `cfg.data.get()` ile dokunur (tip: Any),
  redact/load/atomic helper'lar yerelde tutulur -> forgecode'ya geri
  bağımlılık yok, dairesel import yok.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import re
import threading
import uuid
from dataclasses import dataclass
from typing import Any


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    requests: int = 0

    def add(self, other: "Usage") -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cached_tokens += other.cached_tokens
        self.requests += other.requests

    def cost(self, cfg: Any) -> float:
        return (
            self.input_tokens * float(cfg.data["input_price_per_million"])
            + self.output_tokens * float(cfg.data["output_price_per_million"])
        ) / 1_000_000


def trim_jsonl_file(path: pathlib.Path, max_rows: int, max_bytes: int) -> None:
    """Keep an append-only JSONL log bounded by rewriting only the newest rows."""
    try:
        if path.stat().st_size <= max_bytes:
            return
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            for line in lines[-max(1, int(max_rows)):]:
                f.write(line + "\n")
        tmp.replace(path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass


class UsageStore:
    TRIM_MAX_ROWS = 4000
    TRIM_THRESHOLD_BYTES = 1_000_000

    def __init__(self, home: pathlib.Path):
        self.path = home / "usage.jsonl"
        self.trim_max_rows = self.TRIM_MAX_ROWS
        self.trim_threshold_bytes = self.TRIM_THRESHOLD_BYTES

    def record(self, provider: str, model: str, usage: Usage, cost_usd: float | None = None) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "time": dt.datetime.now(dt.timezone.utc).isoformat(),
            "provider": provider,
            "model": model,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cached_tokens": usage.cached_tokens,
        }
        if cost_usd is not None:
            row["cost_usd"] = round(float(cost_usd), 6)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        trim_jsonl_file(self.path, self.trim_max_rows, self.trim_threshold_bytes)

    def total(self) -> Usage:
        result = Usage()
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                result.add(Usage(int(row.get("input_tokens", 0)), int(row.get("output_tokens", 0)), int(row.get("cached_tokens", 0)), 1))
        except (OSError, json.JSONDecodeError, ValueError):
            pass
        return result


class HistoryStore:
    TRIM_MAX_ROWS = 1000
    TRIM_THRESHOLD_BYTES = 1_000_000

    def __init__(self, root: pathlib.Path):
        self.path = root / ".forgecode" / "history.jsonl"
        self.trim_max_rows = self.TRIM_MAX_ROWS
        self.trim_threshold_bytes = self.TRIM_THRESHOLD_BYTES

    def record(self, user_text: str, assistant_text: str, usage: Usage) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "time": dt.datetime.now().isoformat(timespec="seconds"),
            "user": user_text,
            "assistant": assistant_text,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        trim_jsonl_file(self.path, self.trim_max_rows, self.trim_threshold_bytes)

    def recent(self, limit: int = 10) -> list[dict[str, Any]]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        rows: list[dict[str, Any]] = []
        for line in lines[-limit:]:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
        return rows


def safe_session_name(raw: str) -> str:
    name = str(raw).strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,31}", name):
        raise ValueError("Oturum adı 1-32 karakter olmalı; harf, rakam, _ ve - kullanın")
    return name


def _local_redact(value: str) -> str:
    try:
        from forgecode import redact_sensitive as _rs  # type: ignore

        return str(_rs(value))
    except Exception:
        return str(value)


def _load_json(path: pathlib.Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _atomic_json(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


class SessionStore:
    """Project-local durable chat memory and privacy-safe operational journal."""

    def __init__(self, root: pathlib.Path, session_name: str, cfg: Any):
        self.root = root
        self.cfg = cfg
        self.session_name = safe_session_name(session_name)
        self.base = root / ".forgecode"
        self.session_path = self.base / "sessions" / f"{self.session_name}.jsonl"
        self.memory_path = self.base / "memory.json"
        self.event_path = self.base / "logs" / "events.jsonl"
        self._lock = threading.RLock()

    @staticmethod
    def _append_jsonl(path: pathlib.Path, row: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")

    @staticmethod
    def _read_jsonl(path: pathlib.Path, limit: int = 0) -> list[dict[str, Any]]:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        if limit > 0:
            lines = lines[-limit:]
        rows: list[dict[str, Any]] = []
        for line in lines:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
        return rows

    SESSION_TRIM_THRESHOLD_BYTES = 2_000_000

    def record_turn(self, user: str, assistant: str, usage: Usage, changed_files: list[str] | None = None) -> None:
        if not self.cfg.data.get("persistent_memory_enabled", True):
            return
        row = {
            "time": dt.datetime.now().isoformat(timespec="seconds"),
            "type": "turn",
            "provider": self.cfg.data.get("provider"),
            "model": self.cfg.data.get("model"),
            "user": _local_redact(user),
            "assistant": _local_redact(assistant),
            "changed_files": list(changed_files or [])[:100],
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
        }
        with self._lock:
            self._append_jsonl(self.session_path, row)
            max_rows = max(100, int(self.cfg.data.get("session_log_max_lines", 2000)))
            trim_jsonl_file(self.session_path, max_rows, self.SESSION_TRIM_THRESHOLD_BYTES)

    def recent_turns(self, limit: int = 10) -> list[dict[str, Any]]:
        return self._read_jsonl(self.session_path, max(1, limit))

    def remember(self, text: str) -> dict[str, Any]:
        memories = _load_json(self.memory_path, [])
        if not isinstance(memories, list):
            memories = []
        item = {"id": uuid.uuid4().hex[:6], "time": dt.datetime.now().isoformat(timespec="seconds"), "text": _local_redact(text.strip())}
        memories.append(item)
        limit = max(1, int(self.cfg.data.get("memory_max_items", 40)))
        _atomic_json(self.memory_path, memories[-limit:])
        return item

    def memories(self) -> list[dict[str, Any]]:
        rows = _load_json(self.memory_path, [])
        return rows if isinstance(rows, list) else []

    def forget(self, wanted: str) -> int:
        memories = self.memories()
        if wanted.lower() == "all":
            removed = len(memories)
            _atomic_json(self.memory_path, [])
            return removed
        kept = [item for index, item in enumerate(memories, 1) if str(item.get("id")) != wanted and str(index) != wanted]
        _atomic_json(self.memory_path, kept)
        return len(memories) - len(kept)

    def context(self) -> str:
        if not self.cfg.data.get("persistent_memory_enabled", True):
            return ""
        efficiency = str(self.cfg.data.get("efficiency_mode", "balanced"))
        configured_turns = max(1, int(self.cfg.data.get("history_context_turns", 6)))
        turns = min(configured_turns, 2 if efficiency == "max" else 4 if efficiency == "balanced" else configured_turns)
        char_limit = int(self.cfg.data.get("history_context_chars", 7000))
        char_limit = min(char_limit, 2500 if efficiency == "max" else 6000 if efficiency == "balanced" else char_limit)
        sections: list[str] = []
        force_config = _load_json(self.root / ".force" / "config.json", {})
        force_enabled = isinstance(force_config, dict) and bool(force_config.get("enabled", False))
        memories = [] if force_enabled else self.memories()
        if memories:
            sections.append("KALICI PROJE NOTLARI:\n" + "\n".join(f"- {item.get('text', '')}" for item in memories[-20:]))
        recent = self.recent_turns(turns)
        if recent:
            lines = []
            for row in recent:
                lines.append(f"Kullanıcı: {str(row.get('user', ''))[:1200]}")
                lines.append(f"Sonuç: {str(row.get('assistant', ''))[:1600]}")
                if row.get("changed_files"):
                    lines.append("Dosyalar: " + ", ".join(str(item) for item in row["changed_files"][:20]))
            sections.append(f"KALICI OTURUM GEÇMİŞİ ({self.session_name}):\n" + "\n".join(lines))
        return "\n\n".join(sections)[:char_limit]

    def log_event(self, kind: str, message: str, details: dict[str, Any] | None = None) -> None:
        if not self.cfg.data.get("event_log_enabled", True):
            return
        row = {
            "time": dt.datetime.now().isoformat(timespec="milliseconds"),
            "session": self.session_name,
            "kind": kind,
            "message": _local_redact(message),
            "details": _local_redact(json.dumps(details or {}, ensure_ascii=False)),
        }
        with self._lock:
            self._append_jsonl(self.event_path, row)
            try:
                max_lines = max(100, int(self.cfg.data.get("event_log_max_lines", 2000)))
                trim_jsonl_file(self.event_path, max_lines, 2_000_000)
            except OSError:
                pass

    def recent_events(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._read_jsonl(self.event_path, max(1, min(200, limit)))

    def error_context(self, limit: int = 5) -> str:
        error_kinds = {"api_error", "tool_error", "command_error", "runtime_error", "crash"}
        rows = [row for row in self.recent_events(200) if str(row.get("kind", "")) in error_kinds]
        lines: list[str] = []
        for row in rows[-max(1, limit):]:
            detail = str(row.get("details", ""))
            lines.append(
                f"- {row.get('time', '')} [{row.get('kind', 'error')}] {row.get('message', '')}"
                + (f" · {detail[:1200]}" if detail and detail != "{}" else "")
            )
        return "\n".join(lines)

    def list_sessions(self) -> list[str]:
        folder = self.base / "sessions"
        try:
            return sorted(path.stem for path in folder.glob("*.jsonl") if path.is_file())
        except OSError:
            return []
