#!/usr/bin/env python3
"""ForgeCode workspace — 1642-line toolbelt. Depends on base/config/sandbox/mcp/skills/context."""

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

from forgecode_base import clean_native_runtime_noise, decode_subprocess_output, mcp_slug, normalize_tool_arguments, normalize_tool_name
from forgecode_config import Config
from forgecode_stores import SessionStore
from forgecode_sandbox import ForceSandboxManager, hard_operation_risk, parse_file_view_command, is_known_safe_read_command
from forgecode_mcp import ForceGraphBridge, MCPManager
from forgecode_skills import SkillManager, StaticWebAudit, WebQualityReport
from forgecode_context import ChromeController, TeamBoard, TerminalFleet, YouTubeMusicPlayer

def _fc(name):
    import forgecode as _m
    return getattr(_m, name)

def confirm(*a, **k):
    import forgecode as _m
    return _m.confirm(*a, **k)

def interactive(*a, **k):
    import forgecode as _m
    return _m.interactive(*a, **k)


TOOL_NAME_MAP = {
    "listfiles": "list_files",
    "readfile": "read_file",
    "search": "search",
    "writefile": "write_file",
    "writefiles": "write_files",
    "replacetext": "replace_text",
    "applyedits": "apply_edits",
    "verifyartifacts": "verify_artifacts",
    "webqualitycheck": "web_quality_check",
    "runcommand": "run_command",
    "testproject": "test_project",
    "projecttoolchain": "project_toolchain",
    "toolchain": "project_toolchain",
    "buildproject": "project_toolchain",
    "startprocess": "start_process",
    "processinput": "process_input",
    "processstatus": "process_status",
    "stopprocess": "stop_process",
    "getdiagnostics": "get_diagnostics",
    "setforgecodesetting": "set_forgecode_setting",
    "listskills": "list_skills",
    "manageskill": "manage_skill",
    "skill": "manage_skill",
    "managemcpserver": "manage_mcp_server",
    "mcpserver": "manage_mcp_server",
    "graphcontext": "graph_context",
    "manageterminal": "manage_terminal",
    "browsercontrol": "browser_control",
    "musiccontrol": "music_control",
    "delegatetask": "delegate_task",
    # Claude Code native tool names used by some Messages API proxies.
    "bash": "run_command",
    "read": "read_file",
    "write": "write_file",
    "edit": "replace_text",
    "glob": "list_files",
    "grep": "search",
    "task": "delegate_task",
    "test": "test_project",
    "ls": "list_files",
}


@dataclass
class InteractiveProcess:
    process_id: str
    command: str
    process: Any
    output: str = ""
    cursor: int = 0
    pending_line: str = ""
    lock: threading.RLock = field(default_factory=threading.RLock)
    started_at: float = field(default_factory=time.monotonic)
    last_activity_at: float = 0.0
    activity_cursor: int = 0


class WorkspaceTools:
    def __init__(self, root: pathlib.Path, cfg: Config, confirm: Callable[[str], bool], risk_assessor: Callable[[str, str], tuple[str, str]] | None = None, diagnostic_provider: Callable[[], str] | None = None, progress: Callable[[str], None] | None = None, sandbox: ForceSandboxManager | None = None, skill_manager: SkillManager | None = None):
        self.root = root.resolve()
        self.cfg = cfg
        self.confirm = confirm
        self.risk_assessor = risk_assessor
        self.diagnostic_provider = diagnostic_provider
        self.progress = progress
        self.sandbox = sandbox
        self.skill_manager = skill_manager
        self._risk_cache: dict[str, tuple[str, str]] = {}
        self._processes: dict[str, InteractiveProcess] = {}
        self._process_lock = threading.RLock()
        self.unattended_mode = False
        self.force_graph = ForceGraphBridge(self.root, cfg)
        self.mcp = MCPManager(self.root, cfg)
        atexit.register(self.close_processes)

    def _notify_progress(self, message: str) -> None:
        """Publish bounded, redacted activity without letting UI errors break tools."""
        if self.progress is None:
            return
        try:
            self.progress(redact_sensitive(str(message))[:240])
        except Exception:
            pass

    def _authorize(self, operation: str, summary: str, details: str, legacy_auto: bool) -> tuple[bool, str]:
        if self.unattended_mode:
            floor = hard_operation_risk(operation, details)
            if floor:
                return False, "ERROR: VibeCode safety boundary: " + floor[1]
            if self.sandbox is None or not self.sandbox.active():
                return False, "ERROR: VibeCode unattended changes require ForceSandbox."
            # The isolated workspace contains no user secrets and cannot reach
            # host files. Safe project writes/commands therefore need no
            # overnight prompt, while deterministic destructive patterns above
            # remain blocked and transfer still requires verification.
            return True, ""
        if self.cfg.data.get("autopilot_mode") or legacy_auto:
            return True, ""
        if not self.cfg.data.get("smart_autopilot_mode"):
            rejected_action = "komut çalıştırılmadı" if operation == "command" else "dosya yazılmadı"
            return (True, "") if self.confirm(summary) else (False, f"ERROR: Kullanıcı işlemi reddetti; {rejected_action}.")
        floor = hard_operation_risk(operation, details)
        if floor:
            return False, "ERROR: Smart Autopilot güvenlik engeli: " + floor[1]
        # File mutations already target ForceSandbox's private project copy.
        # They cannot reach host files, credentials, or another project, and
        # transfer still happens only after verification/conflict checks. An
        # extra remote safety-model call here adds latency without increasing
        # the effective boundary.
        if operation == "write" and self.sandbox is not None and self.sandbox.active():
            return True, ""
        if operation == "command":
            # Authorization metadata may follow the command on later lines (for
            # example stdin=closed).  Only the command itself belongs in the
            # safe read-only parser.
            command_text = details.partition("command=")[2].splitlines()[0]
            if is_known_safe_read_command(command_text):
                return True, ""
        cache_key = hashlib.sha256((operation + "\0" + details).encode("utf-8", errors="replace")).hexdigest()
        verdict = self._risk_cache.get(cache_key)
        if verdict is None:
            if self.risk_assessor is None:
                verdict = ("ask", "AI güvenlik değerlendirmesi kullanılamıyor.")
            else:
                try:
                    verdict = self.risk_assessor(operation, details)
                except Exception as exc:
                    verdict = ("ask", f"AI güvenlik değerlendirmesi başarısız: {type(exc).__name__}")
            decision = str(verdict[0]).strip().lower()
            if decision not in {"safe", "ask", "block"}:
                verdict = ("ask", "AI kesin bir güvenlik kararı veremedi.")
            self._risk_cache[cache_key] = verdict
        decision, reason = str(verdict[0]).lower(), str(verdict[1]).strip()
        if decision == "safe":
            return True, ""
        if decision == "block":
            return False, "ERROR: Smart Autopilot güvenlik engeli: " + (reason or "İşlem tehlikeli sınıflandırıldı.")
        question = f"Smart Autopilot onayı: {reason or 'İşlemin etkisi belirsiz.'}\n{summary}"
        rejected_action = "komut çalıştırılmadı" if operation == "command" else "dosya yazılmadı"
        return (True, "") if self.confirm(question) else (False, f"ERROR: Kullanıcı riskli işlemi reddetti; {rejected_action}.")

    def safe_path(self, raw: str) -> pathlib.Path:
        raw_text = str(raw).strip()
        candidate = (self.root / raw_text).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            is_custom_claude = self.cfg.data.get("provider") == "custom" and self.cfg.mode() == "anthropic"
            remapped: pathlib.Path | None = None
            if is_custom_claude:
                normalized = raw_text.replace("\\", "/")
                parts = [part for part in normalized.split("/") if part not in {"", "."}]
                lowered = [part.lower() for part in parts]
                relative_parts: list[str] = []
                if normalized.startswith("/") and len(parts) >= 3 and lowered[0] == "tmp":
                    # Claude Code proxy workspace: /tmp/<remote-project>/<local path>
                    relative_parts = parts[2:]
                elif normalized.startswith("/") and len(parts) >= 2 and lowered[0] in {"workspace", "project", "repo"}:
                    relative_parts = parts[1:]
                elif self.root.name.lower() in lowered:
                    index = len(lowered) - 1 - lowered[::-1].index(self.root.name.lower())
                    relative_parts = parts[index + 1:]
                if relative_parts and ".." not in relative_parts:
                    remapped = (self.root / pathlib.Path(*relative_parts)).resolve()
            if remapped is None:
                raise ValueError(f"Proje klasörünün dışına erişim engellendi: {raw_text}") from exc
            try:
                remapped.relative_to(self.root)
            except ValueError as remap_exc:
                raise ValueError(f"Proje klasörünün dışına erişim engellendi: {raw_text}") from remap_exc
            candidate = remapped
        return candidate

    def safe_file_path(self, raw: str) -> pathlib.Path:
        """Resolve a project file and reject empty/root/directory targets."""
        raw_text = str(raw).strip()
        if not raw_text or raw_text.replace("\\", "/").rstrip("/") in {"", "."}:
            raise ValueError("Dosya yolu boş veya proje kökü olamaz; göreli bir dosya yolu verin (ör. index.html).")
        candidate = self.safe_path(raw_text)
        if candidate == self.root:
            raise ValueError("Proje kökü bir dosya değildir; göreli bir dosya yolu verin (ör. index.html).")
        if candidate.exists() and candidate.is_dir():
            raise ValueError(f"Dosya yolu bekleniyordu fakat klasör verildi: {raw_text}")
        return candidate

    @staticmethod
    def _write_utf8_verified(file: pathlib.Path, content: str) -> int:
        """Atomically write verified UTF-8 chunks without a BOM."""
        clean_content = str(content).lstrip("\ufeff")
        payload = clean_content.encode("utf-8")
        temporary = file.with_name(f".{file.name}.forgecode-{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("wb") as stream:
                for offset in range(0, len(payload), 64 * 1024):
                    stream.write(payload[offset:offset + 64 * 1024])
                stream.flush()
                os.fsync(stream.fileno())
            verified = temporary.read_bytes()
            if verified != payload:
                raise OSError(
                    f"Yazma doğrulaması başarısız: beklenen {len(payload)} bayt, okunan {len(verified)} bayt"
                )
            os.replace(temporary, file)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        return len(clean_content)

    def visible_files(self) -> list[pathlib.Path]:
        result = []
        for path in self.root.rglob("*"):
            if (
                path.is_file()
                and not ForceSandboxManager._is_link(path)
                and not any(part in IGNORE_DIRS for part in path.relative_to(self.root).parts)
            ):
                result.append(path)
        return result

    def snapshot(self) -> dict[str, tuple[int, int]]:
        result: dict[str, tuple[int, int]] = {}
        config_home = self.cfg.home.resolve()
        for path in self.visible_files():
            if self.sandbox is None or not self.sandbox.active():
                try:
                    path.resolve().relative_to(config_home)
                    continue
                except ValueError:
                    pass
            try:
                stat = path.stat()
                result[path.relative_to(self.root).as_posix()] = (stat.st_size, stat.st_mtime_ns)
            except OSError:
                continue
        return result

    def changed_since(self, before: dict[str, tuple[int, int]]) -> list[str]:
        after = self.snapshot()
        return sorted(name for name in set(before) | set(after) if before.get(name) != after.get(name))

    def execute(self, name: str, args: dict[str, Any]) -> str:
        try:
            if str(name).startswith("mcp__"):
                output = self.mcp.call_tool(str(name), args if isinstance(args, dict) else {})
            else:
                resolved_name = normalize_tool_name(name)
                if resolved_name not in TOOL_NAME_MAP.values():
                    raise ValueError(f"Bilinmeyen veya güvenilmeyen araç adı: {name}")
                method = getattr(self, f"tool_{resolved_name}")
                output = method(**normalize_tool_arguments(resolved_name, args))
        except Exception as exc:
            output = f"ERROR: {type(exc).__name__}: {exc}"
        limit = int(self.cfg.data["max_tool_output_chars"])
        efficiency = self.cfg.data.get("efficiency_mode", "balanced")
        if efficiency == "balanced":
            limit = min(limit, 28000)
        elif efficiency == "max":
            limit = min(limit, 6000)
        if len(output) > limit:
            output = output[:limit] + f"\n… [çıktı {len(output) - limit} karakter kısaltıldı]"
        return output

    def dispatch(self, name: str, args: dict[str, Any]) -> str:
        """Backward-compatible alias — hiçbir yolda AttributeError üretmez."""
        return self.execute(name, args)

    def tool_manage_terminal(self, action: str, terminal: str = "", role: str = "explore", visible: bool = False, task: str = "",
                             thinking: str = "", output_cap: int = 0,
                             assignments: list[dict[str, Any]] | None = None) -> str:
        fleet = TerminalFleet(self.root, self.cfg)
        action = action.casefold()
        if action == "status":
            return fleet.status_text()
        if not self.cfg.data.get("_runtime_fleet_authorized", False):
            approved, rejection = self._authorize(
                "command", f"Terminal fleet action: {action}",
                f"command=forgecode terminal {action} {terminal or role}", False,
            )
            if not approved:
                return rejection
        if action == "add":
            item = fleet.add(role, visible=visible)
            return f"Terminal {item['id']} opened · role {item['role']} · pid {item['pid']}"
        if action == "remove":
            return "Stop requested" if fleet.remove(int(terminal)) else "Terminal not found"
        if action == "task":
            count = fleet.enqueue(terminal or "all", task, thinking, output_cap)
            return f"Task queued for {count} worker terminal(s)"
        if action == "configure":
            return "Worker configured" if fleet.configure(int(terminal), thinking, output_cap) else "Terminal not found"
        if action == "orchestrate":
            return fleet.orchestrate(assignments or [])
        raise ValueError("Terminal action: status, add, remove, task, configure, or orchestrate")

    def tool_browser_control(self, action: str, url: str = "", selector: str = "", text: str = "", tab_id: str = "") -> str:
        if action.casefold() in {"click", "type"}:
            approved, rejection = self._authorize(
                "command", f"Chrome {action}: {selector}",
                f"command=chrome {action} selector={selector} url={url}", False,
            )
            if not approved:
                return rejection
        return ChromeController(self.cfg).control(action, url, selector, text, tab_id)

    def tool_music_control(self, action: str, url: str = "", title: str = "") -> str:
        return YouTubeMusicPlayer(self.cfg).control(action, url, title)

    def tool_list_files(self, pattern: str = "*") -> str:
        names = [p.relative_to(self.root).as_posix() for p in self.visible_files()]
        matched = [n for n in names if fnmatch.fnmatch(n, pattern) or fnmatch.fnmatch(pathlib.PurePosixPath(n).name, pattern)]
        result_limit = 150 if self.cfg.data.get("efficiency_mode") == "max" else 1000 if self.cfg.data.get("efficiency_mode") == "balanced" else 4000
        return "\n".join(sorted(matched)[:result_limit]) or "Dosya bulunamadı."

    def tool_read_file(self, path: str, start_line: int = 1, end_line: int = 400) -> str:
        file = self.safe_file_path(path)
        if file.stat().st_size > 2_000_000:
            raise ValueError("Dosya 2 MB sınırından büyük")
        lines = file.read_text(encoding="utf-8", errors="replace").splitlines()
        line_limit = 150 if self.cfg.data.get("efficiency_mode") == "max" else 800 if self.cfg.data.get("efficiency_mode") == "balanced" else 2000
        start = max(1, start_line)
        end = min(len(lines), max(start_line, end_line), start + line_limit - 1)
        return "\n".join(f"{i:>5} | {lines[i-1]}" for i in range(start, end + 1))

    def tool_search(self, query: str, pattern: str = "*", case_sensitive: bool = False) -> str:
        needle = query if case_sensitive else query.lower()
        hits = []
        for file in self.visible_files():
            rel = file.relative_to(self.root).as_posix()
            if not (fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(file.name, pattern)):
                continue
            if file.stat().st_size > 2_000_000:
                continue
            try:
                for i, line in enumerate(file.read_text(encoding="utf-8").splitlines(), 1):
                    hay = line if case_sensitive else line.lower()
                    if needle in hay:
                        hits.append(f"{rel}:{i}: {line[:400]}")
                        hit_limit = 80 if self.cfg.data.get("efficiency_mode") == "max" else 300 if self.cfg.data.get("efficiency_mode") == "balanced" else 500
                        if len(hits) >= hit_limit:
                            return "\n".join(hits) + "\n… sonuç sınırı"
            except (OSError, UnicodeDecodeError):
                continue
        return "\n".join(hits) or "Eşleşme bulunamadı."

    def tool_write_file(self, path: str, content: str) -> str:
        file = self.safe_file_path(path)
        local_path = file.relative_to(self.root).as_posix()
        action = "değiştir" if file.exists() else "oluştur"
        approved, rejection = self._authorize(
            "write", f"{local_path} dosyasını {action}?",
            f"path={local_path}\naction={action}\ncontent={redact_sensitive(content[:6000])}",
            bool(self.cfg.data["auto_approve_writes"]),
        )
        if not approved:
            return rejection
        file.parent.mkdir(parents=True, exist_ok=True)
        written = self._write_utf8_verified(file, content)
        return f"OK: {local_path} yazıldı ({written} karakter, UTF-8 doğrulandı)."

    def tool_write_files(self, files: list[dict[str, str]]) -> str:
        if not files or len(files) > 30:
            raise ValueError("Bir toplu yazma işleminde 1-30 dosya olmalı")
        prepared: list[tuple[str, pathlib.Path, str]] = []
        seen: set[pathlib.Path] = set()
        for item in files:
            path = str(item.get("path", "")).strip()
            content = str(item.get("content", ""))
            if not path:
                raise ValueError("Her dosyada path alanı bulunmalı")
            target = self.safe_file_path(path)
            if target in seen:
                raise ValueError(f"Aynı dosya iki kez verildi: {path}")
            seen.add(target)
            prepared.append((path, target, content))
        names = ", ".join(path for path, _, _ in prepared[:8])
        if len(prepared) > 8:
            names += f" ve {len(prepared) - 8} dosya daha"
        risk_details = "\n\n".join(
            f"path={path}\ncontent={redact_sensitive(content[:1500])}" for path, _, content in prepared[:10]
        )
        approved, rejection = self._authorize(
            "write", f"{len(prepared)} dosya birlikte yazılsın mı? {names}", risk_details,
            bool(self.cfg.data["auto_approve_writes"]),
        )
        if not approved:
            return rejection
        for _, target, content in prepared:
            target.parent.mkdir(parents=True, exist_ok=True)
            self._write_utf8_verified(target, content)
        return "OK: Toplu yazma tamamlandı: " + ", ".join(path for path, _, _ in prepared)

    def tool_replace_text(self, path: str, old_text: str, new_text: str, replace_all: bool = False) -> str:
        file = self.safe_file_path(path)
        local_path = file.relative_to(self.root).as_posix()
        content = file.read_text(encoding="utf-8")
        count = content.count(old_text)
        if count < 1 or (count != 1 and not replace_all):
            raise ValueError(f"old_text tam olarak bir kez bulunmalı; bulunan: {count}")
        approved, rejection = self._authorize(
            "write", f"{local_path} içinde metin değiştirilsin mi?",
            f"path={local_path}\nold={redact_sensitive(old_text[:3000])}\nnew={redact_sensitive(new_text[:3000])}",
            bool(self.cfg.data["auto_approve_writes"]),
        )
        if not approved:
            return rejection
        self._write_utf8_verified(file, content.replace(old_text, new_text, -1 if replace_all else 1))
        return f"OK: {local_path} güncellendi."

    def tool_apply_edits(self, edits: list[dict[str, Any]]) -> str:
        """Apply exact multi-file edits only after the complete transaction validates."""
        if not isinstance(edits, list) or not 1 <= len(edits) <= 30:
            raise ValueError("Bir işlemde 1-30 düzenleme olmalı")
        originals: dict[pathlib.Path, str] = {}
        prepared: dict[pathlib.Path, str] = {}
        labels: list[str] = []
        for index, item in enumerate(edits, 1):
            if not isinstance(item, dict):
                raise ValueError(f"Düzenleme {index} nesne olmalı")
            raw_path = str(item.get("path", "")).strip()
            old_text = str(item.get("old_text", ""))
            new_text = str(item.get("new_text", ""))
            replace_all = bool(item.get("replace_all", False))
            if not raw_path or not old_text:
                raise ValueError(f"Düzenleme {index} için path ve boş olmayan old_text gerekli")
            target = self.safe_file_path(raw_path)
            if not target.is_file():
                raise ValueError(f"Düzenlenecek dosya bulunamadı: {raw_path}")
            if target not in originals:
                originals[target] = target.read_text(encoding="utf-8")
                prepared[target] = originals[target]
            current = prepared[target]
            count = current.count(old_text)
            if count < 1 or (count != 1 and not replace_all):
                raise ValueError(
                    f"Düzenleme {index} ({raw_path}) old_text eşleşmesi geçersiz; bulunan: {count}"
                )
            prepared[target] = current.replace(old_text, new_text, -1 if replace_all else 1)
            labels.append(target.relative_to(self.root).as_posix())
        unique_labels = list(dict.fromkeys(labels))
        details = "\n\n".join(
            f"path={str(item.get('path', ''))}\nold={redact_sensitive(str(item.get('old_text', ''))[:1200])}"
            f"\nnew={redact_sensitive(str(item.get('new_text', ''))[:1200])}"
            for item in edits[:12]
        )
        approved, rejection = self._authorize(
            "write",
            f"{len(edits)} düzenleme {len(unique_labels)} dosyaya işlemsel olarak uygulansın mı?",
            details,
            bool(self.cfg.data["auto_approve_writes"]),
        )
        if not approved:
            return rejection
        written: list[pathlib.Path] = []
        try:
            for target, content in prepared.items():
                self._write_utf8_verified(target, content)
                written.append(target)
        except Exception:
            for target in written:
                try:
                    self._write_utf8_verified(target, originals[target])
                except OSError:
                    pass
            raise
        return (
            f"OK: {len(edits)} düzenleme doğrulandı ve {len(prepared)} dosyaya uygulandı: "
            + ", ".join(unique_labels)
        )

    def tool_verify_artifacts(self, paths: list[str], required_text: dict[str, str] | None = None) -> str:
        if not isinstance(paths, list) or not 1 <= len(paths) <= 50:
            raise ValueError("Doğrulama için 1-50 dosya yolu gerekli")
        requirements = required_text if isinstance(required_text, dict) else {}
        rows: list[str] = []
        seen: set[pathlib.Path] = set()
        for raw_path in paths:
            target = self.safe_file_path(str(raw_path))
            if target in seen:
                continue
            seen.add(target)
            if not target.is_file():
                raise ValueError(f"Doğrulama başarısız; dosya yok: {raw_path}")
            payload = target.read_bytes()
            if not payload:
                raise ValueError(
                    f"Doğrulama başarısız; dosya boş: {raw_path} "
                    "(boş dosyalar doğrulanamaz; önce içeriğini yazın veya bu yolu listeden çıkarın)"
                )
            relative = target.relative_to(self.root).as_posix()
            expected = str(requirements.get(str(raw_path), requirements.get(relative, "")))
            digest = hashlib.sha256(payload).hexdigest()[:16]
            known_binary = target.suffix.casefold() in BINARY_ARTIFACT_SUFFIXES
            text = ""
            if not known_binary:
                try:
                    text = payload.decode("utf-8")
                except UnicodeDecodeError:
                    known_binary = True
                else:
                    # Some binary formats happen to decode but contain NUL or
                    # dense control bytes. Treat them as binary evidence too.
                    sample = text[:4096]
                    controls = sum(ord(char) < 32 and char not in "\t\r\n" for char in sample)
                    known_binary = "\x00" in sample or controls > max(8, len(sample) // 20)
            if known_binary:
                if expected:
                    raise ValueError(
                        f"Doğrulama başarısız; binary dosyada required_text aranamaz: {relative}"
                    )
                rows.append(f"{relative} · {len(payload)} bayt · binary · sha256:{digest}")
                continue
            if expected and expected not in text:
                raise ValueError(f"Doğrulama başarısız; beklenen metin bulunamadı: {relative}")
            line_count = len(text.splitlines())
            rows.append(f"{relative} · {len(payload)} bayt · {line_count} satır · sha256:{digest}")
        return "OK: Artifact doğrulaması geçti\n" + "\n".join(rows)

    def _interactive_command(self, command: str) -> tuple[list[str] | str, bool]:
        if os.name == "nt":
            # Avoid PowerShell's native-output buffering for the Python runtime
            # that launched ForgeCode.  In particular CPython 3.10 can already
            # be waiting at input() while its prompt is still hidden upstream.
            escaped_executable = str(sys.executable).replace("'", "''")
            python_prefix = f"& '{escaped_executable}'"
            if command[:len(python_prefix)].casefold() == python_prefix.casefold():
                tail = command[len(python_prefix):].strip()
                arguments = shlex.split(tail, posix=False) if tail else []
                arguments = [
                    value[1:-1] if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'} else value
                    for value in arguments
                ]
                return [sys.executable, "-u", *arguments], False
            return ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", windows_shell_command(command)], False
        return command, True

    def _process_activity(self, session: InteractiveProcess, force: bool = False) -> None:
        if self.progress is None:
            return
        now = time.monotonic()
        with session.lock:
            fresh = session.output[session.activity_cursor:]
            if not fresh:
                return
            visible = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", fresh)
            prompt_like = visible.rstrip().endswith((":", "?", ">", "›"))
            line_ready = "\n" in visible or "\r" in visible
            # Do not publish a prompt one character at a time.  The byte reader
            # still captures it immediately, but the activity bar is updated
            # only when a complete line or an input prompt is recognizable.
            if not force and not line_ready and not prompt_like:
                return
            summary = visible.replace("\r", "\n").splitlines()[-1] if visible.splitlines() else visible
            summary = redact_sensitive(summary.strip())[:180]
            if summary.startswith("Failed to find real location of ") and summary.lower().endswith("python.exe"):
                session.activity_cursor = len(session.output)
                return
            if not summary and not force:
                return
            session.activity_cursor = len(session.output)
            session.last_activity_at = now
        if summary:
            self._notify_progress(f"Program {session.process_id}: {summary}")

    def _read_interactive_process(self, session: InteractiveProcess) -> None:
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        stream = session.process.stdout
        try:
            while True:
                chunk = stream.read(1)
                if not chunk:
                    break
                text = decoder.decode(chunk)
                if not text:
                    continue
                with session.lock:
                    session.output += text
                    if len(session.output) > 200_000:
                        removed = len(session.output) - 160_000
                        session.output = session.output[removed:]
                        session.cursor = max(0, session.cursor - removed)
                        session.activity_cursor = max(0, session.activity_cursor - removed)
                self._process_activity(session)
            tail = decoder.decode(b"", final=True)
            if tail:
                with session.lock:
                    session.output += tail
        finally:
            self._process_activity(session, force=True)
            if self.progress is not None:
                code = session.process.poll()
                self.progress(f"Program {session.process_id}: tamamlandı · çıkış {code}")

    def _get_process(self, process_id: str) -> InteractiveProcess:
        selected = str(process_id).strip()
        with self._process_lock:
            session = self._processes.get(selected)
        if session is None:
            raise ValueError(f"Etkileşimli süreç bulunamadı: {selected}")
        return session

    def _process_snapshot(self, session: InteractiveProcess, consume: bool = True) -> str:
        with session.lock:
            fresh = session.output[session.cursor:]
            if consume:
                session.cursor = len(session.output)
        fresh = clean_native_runtime_noise(fresh)
        code = session.process.poll()
        state = f"running=true · process_id={session.process_id}" if code is None else f"running=false · exit_code={code} · process_id={session.process_id}"
        return state + ("\nYeni çıktı:\n" + fresh if fresh else "\nYeni çıktı yok.")

    def tool_start_process(self, command: str) -> str:
        selected = str(command).strip()
        if not selected:
            raise ValueError("Başlatılacak komut boş olamaz")
        approved, rejection = self._authorize(
            "command", f"Etkileşimli programı çalıştır?  {selected}",
            f"cwd={self.root}\ncommand={redact_sensitive(selected[:8000])}\nstdin=interactive-pipe",
            bool(self.cfg.data["auto_approve_commands"]),
        )
        if not approved:
            return rejection
        if self.sandbox is not None and self.sandbox.active():
            process = self.sandbox.start_command(selected)
        else:
            command_value, shell = self._interactive_command(selected)
            process_env = os.environ.copy()
            # CPython 3.10 on Windows may retain prompts behind the PowerShell
            # wrapper when stdout is a pipe.  Unbuffered UTF-8 output lets the
            # tester observe the prompt before it sends staged stdin.
            process_env.setdefault("PYTHONUNBUFFERED", "1")
            process_env.setdefault("PYTHONIOENCODING", "utf-8")
            options: dict[str, Any] = {
                "cwd": self.root, "shell": shell, "stdin": subprocess.PIPE,
                "stdout": subprocess.PIPE, "stderr": subprocess.STDOUT,
                "text": False, "bufsize": 0, "env": process_env,
            }
            if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
                options["creationflags"] = subprocess.CREATE_NO_WINDOW
            process = subprocess.Popen(command_value, **options)
        process_id = uuid.uuid4().hex[:8]
        session = InteractiveProcess(process_id, selected, process)
        with self._process_lock:
            self._processes[process_id] = session
        threading.Thread(target=self._read_interactive_process, args=(session,), daemon=True,
                         name=f"forgecode-process-{process_id}").start()
        # Windows CI and cold Python/PowerShell starts can take longer than a
        # fraction of a second before the child publishes its first prompt.
        # Waiting briefly here makes staged-input programs deterministic while
        # still returning immediately as soon as output or process exit exists.
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            with session.lock:
                if session.output:
                    break
            if process.poll() is not None:
                break
            time.sleep(0.03)
        return "PROCESS_STARTED\n" + self._process_snapshot(session)

    def tool_process_input(self, process_id: str, input: str, append_newline: bool = True) -> str:
        session = self._get_process(process_id)
        if session.process.poll() is not None:
            return "ERROR: Süreç zaten tamamlandı.\n" + self._process_snapshot(session)
        payload = str(input) + ("\n" if append_newline else "")
        try:
            session.process.stdin.write(payload.encode("utf-8"))
            session.process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as exc:
            return f"ERROR: Sürece input gönderilemedi: {exc}\n" + self._process_snapshot(session)
        if self.progress is not None:
            self.progress(f"Program {session.process_id}: input gönderildi · {len(payload)} karakter")
        before = len(session.output)
        deadline = time.monotonic() + 0.8
        while time.monotonic() < deadline and session.process.poll() is None:
            with session.lock:
                if len(session.output) > before:
                    break
            time.sleep(0.04)
        return "INPUT_SENT\n" + self._process_snapshot(session)

    def tool_process_status(self, process_id: str, wait_ms: int = 300) -> str:
        session = self._get_process(process_id)
        before = len(session.output)
        deadline = time.monotonic() + max(0, min(3000, int(wait_ms))) / 1000
        while time.monotonic() < deadline and session.process.poll() is None:
            with session.lock:
                if len(session.output) > before:
                    break
            time.sleep(0.04)
        return self._process_snapshot(session)

    def tool_stop_process(self, process_id: str) -> str:
        session = self._get_process(process_id)
        if session.process.poll() is None:
            session.process.terminate()
            try:
                session.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                session.process.kill()
                session.process.wait(timeout=2)
        try:
            session.process.stdin.close()
        except (OSError, ValueError):
            pass
        return "PROCESS_STOPPED\n" + self._process_snapshot(session)

    def close_processes(self) -> None:
        self.mcp.close()
        with self._process_lock:
            sessions = list(self._processes.values())
        for session in sessions:
            if session.process.poll() is None:
                try:
                    session.process.terminate()
                    session.process.wait(timeout=1)
                except (OSError, subprocess.TimeoutExpired):
                    try:
                        session.process.kill()
                    except OSError:
                        pass

    def active_process_ids(self) -> list[str]:
        with self._process_lock:
            return [process_id for process_id, session in self._processes.items() if session.process.poll() is None]

    def tool_run_command(self, command: str, timeout_seconds: int = 100, stdin: str | None = None) -> str:
        stdin_note = "provided" if stdin is not None else "closed"
        approved, rejection = self._authorize(
            "command", f"Komutu çalıştır?  {command}",
            f"cwd={self.root}\ncommand={redact_sensitive(command[:8000])}\nstdin={stdin_note}"
            + (f" ({len(str(stdin))} karakter)" if stdin is not None else ""),
            bool(self.cfg.data["auto_approve_commands"]),
        )
        if not approved:
            return rejection
        requested_timeout = int(timeout_seconds)
        if self.unattended_mode:
            requested_timeout = max(
                requested_timeout,
                int(self.cfg.data.get("vibe_command_timeout_seconds", 1200)),
            )
        timeout = (
            max(1, requested_timeout)
            if self.unattended_mode
            else min(max(1, requested_timeout), int(self.cfg.data["timeout_seconds"]))
        )
        view = parse_file_view_command(command)
        if view:
            path, direction, count = view
            file = self.safe_file_path(path)
            if file.stat().st_size > 2_000_000:
                raise ValueError("Dosya 2 MB sınırından büyük")
            lines = file.read_text(encoding="utf-8", errors="replace").splitlines()
            if direction == "tail" and count:
                lines = lines[-count:]
            elif direction == "head" and count:
                lines = lines[:count]
            return "exit_code=0\n" + "\n".join(lines)
        run_options: dict[str, Any] = {
            "cwd": self.root, "text": False, "capture_output": True, "timeout": timeout,
        }
        if stdin is None:
            # Never inherit ForgeCode's own terminal input. Interactive child
            # programs must receive explicit scripted input or immediate EOF.
            run_options["stdin"] = subprocess.DEVNULL
        else:
            run_options["input"] = str(stdin).encode("utf-8")
        started_at = time.monotonic()
        activity_stop = threading.Event()
        activity_label = redact_sensitive(command.replace("\r", " ").replace("\n", " ").strip())[:150]

        def command_heartbeat() -> None:
            while not activity_stop.wait(5.0):
                elapsed = int(time.monotonic() - started_at)
                self._notify_progress(f"Komut sürüyor · {elapsed} sn: {activity_label}")

        self._notify_progress(f"Komut başladı: {activity_label}")
        heartbeat = threading.Thread(target=command_heartbeat, name="forgecode-command-progress", daemon=True)
        heartbeat.start()
        try:
            if self.sandbox is not None and self.sandbox.active():
                self._notify_progress("ForceSandbox: komut izole yerel motorda çalışıyor")
                completed = self.sandbox.run_command(
                    command,
                    input=str(stdin).encode("utf-8") if stdin is not None else None,
                    timeout=timeout,
                )
            elif os.name == "nt":
                # Reuse the direct Python command adapter used by interactive
                # processes. Passing scripted stdin through PowerShell can
                # intermittently leave the child waiting forever on Windows
                # CI, while a direct argv preserves bytes and EOF reliably.
                command_value, command_shell = self._interactive_command(command)
                completed = subprocess.run(
                    command_value, shell=command_shell, **run_options,
                )
            else:
                completed = subprocess.run(command, shell=True, **run_options)
        except subprocess.TimeoutExpired as exc:
            partial = clean_native_runtime_noise(
                decode_subprocess_output(exc.stdout) + decode_subprocess_output(exc.stderr)
            ).strip()
            self._notify_progress(f"Komut zaman aşımı · {timeout} sn: {activity_label}")
            detail = f"\nKısmi çıktı:\n{partial[:4000]}" if partial else ""
            return (
                f"ERROR: Komut {timeout} saniyede tamamlanmadı. Program kullanıcı girdisi bekliyorsa "
                "run_command veya test_project çağrısında stdin alanına satır sonlarıyla cevapları verin."
                + detail
            )
        finally:
            activity_stop.set()
            heartbeat.join(timeout=0.2)
        output = clean_native_runtime_noise(
            decode_subprocess_output(completed.stdout) + decode_subprocess_output(completed.stderr)
        ).strip()
        output_lines = [line.strip() for line in output.replace("\r", "\n").splitlines() if line.strip()]
        for line in output_lines[-2:]:
            self._notify_progress(f"Komut çıktısı: {line[:180]}")
        if completed.returncode != 0:
            self._notify_progress(f"Komut başarısız · kod {completed.returncode}: {activity_label}")
            detail = f"\n{output}" if output else ""
            return f"ERROR: Komut {completed.returncode} çıkış koduyla başarısız oldu (stdin={stdin_note}).{detail}"
        elapsed = time.monotonic() - started_at
        self._notify_progress(f"Komut tamamlandı · {elapsed:.2f} sn: {activity_label}")
        return f"exit_code=0\nstdin={stdin_note}\n{output}"

    @staticmethod
    def _is_remote_web_reference(reference: str) -> bool:
        value = str(reference).strip().casefold()
        return not value or value.startswith(("#", "data:", "mailto:", "tel:", "javascript:", "http://", "https://", "//"))

    def web_quality_report(self, require_multifile: bool = False) -> WebQualityReport:
        """Return stable, model-independent quality evidence for a static site."""
        visible = self.visible_files()
        html_files = [path for path in visible if path.suffix.lower() in {".html", ".htm"}][:100]
        css_files = [path for path in visible if path.suffix.lower() == ".css"][:100]
        js_files = [path for path in visible if path.suffix.lower() == ".js"][:100]
        blockers: list[str] = []
        warnings: list[str] = []
        referenced_css: set[pathlib.Path] = set()
        referenced_js: set[pathlib.Path] = set()
        if not html_files:
            blockers.append("HTML giriş dosyası bulunamadı")
        if html_files and not any(path.name.casefold() == "index.html" for path in html_files):
            blockers.append("Statik yayın için index.html bulunamadı")
        placeholder_pattern = re.compile(
            r"\b(?:lorem\s+ipsum|replace\s+me|your\s+(?:logo|company|brand)|todo:\s*(?:content|copy)|placeholder\.com)\b",
            re.IGNORECASE,
        )
        for file in html_files:
            rel = file.relative_to(self.root).as_posix()
            try:
                raw = file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                blockers.append(f"{rel}: UTF-8 HTML okunamadı ({type(exc).__name__})")
                continue
            audit = StaticWebAudit()
            try:
                audit.feed(raw)
                audit.close()
            except Exception as exc:
                blockers.append(f"{rel}: HTML ayrıştırılamadı ({type(exc).__name__})")
                continue
            if len(raw.strip()) < 500:
                blockers.append(f"{rel}: sayfa iskeleti çok küçük/eksik ({len(raw.strip())} karakter)")
            if not re.search(r"<!doctype\s+html", raw, re.IGNORECASE):
                blockers.append(f"{rel}: HTML5 doctype eksik")
            for required_tag in ("html", "head", "body", "main", "h1"):
                if audit.tags.get(required_tag, 0) < 1:
                    blockers.append(f"{rel}: semantik <{required_tag}> öğesi eksik")
            if not audit.has_viewport:
                blockers.append(f"{rel}: mobil viewport meta etiketi eksik")
            if not audit.html_language:
                warnings.append(f"{rel}: html lang değeri eksik")
            if audit.duplicate_ids:
                blockers.append(f"{rel}: yinelenen id: {', '.join(sorted(audit.duplicate_ids)[:10])}")
            if audit.images_without_alt:
                blockers.append(f"{rel}: alt niteliği olmayan {audit.images_without_alt} görsel")
            if audit.inputs_without_hint:
                blockers.append(f"{rel}: erişilebilir adı/ipucu olmayan {audit.inputs_without_hint} form alanı")
            if placeholder_pattern.search(raw):
                blockers.append(f"{rel}: kullanıcıya gösterilen placeholder içerik bulundu")
            for reference in audit.references:
                if self._is_remote_web_reference(reference) or any(marker in reference for marker in ("{{", "}}", "<%", "%>")):
                    continue
                clean = urllib.parse.unquote(urllib.parse.urlsplit(reference).path)
                if not clean:
                    continue
                target = (self.root / clean.lstrip("/")) if clean.startswith("/") else (file.parent / clean)
                try:
                    resolved = target.resolve()
                    resolved.relative_to(self.root)
                except (OSError, ValueError):
                    blockers.append(f"{rel}: proje dışına çıkan yerel varlık {reference}")
                    continue
                if not resolved.is_file():
                    blockers.append(f"{rel}: eksik yerel varlık {reference}")
                    continue
                if resolved.suffix.casefold() == ".css":
                    referenced_css.add(resolved)
                elif resolved.suffix.casefold() == ".js":
                    referenced_js.add(resolved)
        if require_multifile and html_files:
            if not css_files or not referenced_css:
                blockers.append("Profesyonel site yapısı için bağlı ayrı bir CSS dosyası gerekli")
            if not js_files or not referenced_js:
                blockers.append("Profesyonel site yapısı için bağlı ayrı bir JavaScript dosyası gerekli")
        css_text = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in css_files)
        js_text = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in js_files)
        if css_files:
            if len(css_text.strip()) < 400:
                blockers.append("CSS görsel sistem oluşturmak için çok küçük")
            if require_multifile and not re.search(r"@media|@container|clamp\s*\(", css_text, re.IGNORECASE):
                blockers.append("CSS içinde doğrulanabilir responsive davranış bulunamadı")
            if not re.search(r":root\s*\{|--[a-z0-9_-]+\s*:", css_text, re.IGNORECASE):
                warnings.append("CSS tasarım tokenları/değişkenleri kullanmıyor")
        if require_multifile and js_files and len(js_text.strip()) < 80:
            blockers.append("JavaScript dosyası gerçek bir etkileşimi doğrulayacak kadar içerik taşımıyor")
        blockers = list(dict.fromkeys(blockers))
        warnings = list(dict.fromkeys(warnings))
        score = max(0, 100 - len(blockers) * 16 - len(warnings) * 4)
        passed = not blockers and score >= 75
        return WebQualityReport(passed, score, blockers, warnings, len(html_files), len(css_files), len(js_files))

    def tool_web_quality_check(self, require_multifile: bool = False) -> str:
        return self.web_quality_report(bool(require_multifile)).render()

    @staticmethod
    def _toolchain_identifiers(name: str, package_name: str = "") -> tuple[str, str, str]:
        raw_name = str(name).strip()
        if not raw_name:
            raise ValueError("scaffold requires a project name")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_. -]{0,63}", raw_name):
            raise ValueError("Project name must start with a letter and contain only letters, numbers, spaces, '.', '_' or '-'")
        words = re.findall(r"[A-Za-z0-9]+", raw_name)
        slug = "-".join(word.lower() for word in words)
        class_name = "".join(word[:1].upper() + word[1:] for word in words)
        if not class_name or class_name[0].isdigit():
            raise ValueError("Project name could not be converted to a safe identifier")
        selected_package = str(package_name).strip() or f"dev.forcecode.{slug.replace('-', '')}"
        if not re.fullmatch(r"[a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)*", selected_package):
            raise ValueError("package_name must be a valid Java package or .NET namespace")
        return slug, class_name, selected_package

    def _detect_project_toolchain(self) -> dict[str, Any]:
        files = self.visible_files()
        names = {path.relative_to(self.root).as_posix() for path in files}
        lower_names = {name.casefold() for name in names}
        manifests: list[str] = []
        detected = "unknown"
        build_system = "none"

        def matching(suffix: str) -> list[str]:
            return sorted(name for name in names if name.casefold().endswith(suffix))

        cmake_files = [name for name in names if name.casefold() == "cmakelists.txt"]
        dotnet_files = matching(".sln") + matching(".csproj") + matching(".fsproj")
        paper_manifest = any(
            name.endswith(("/plugin.yml", "/paper-plugin.yml")) or name in {"plugin.yml", "paper-plugin.yml"}
            for name in lower_names
        )
        pom = "pom.xml" in lower_names
        gradle = any(name in lower_names for name in {"build.gradle", "build.gradle.kts"})
        if cmake_files:
            detected, build_system, manifests = "cpp-cmake", "CMake", sorted(cmake_files)
        elif dotnet_files:
            detected, build_system, manifests = "dotnet-exe", ".NET SDK", dotnet_files
        elif pom or gradle:
            detected = "paper-plugin" if paper_manifest else "java-jar"
            build_system = "Gradle" if gradle else "Maven"
            manifests = sorted(
                name for name in names
                if pathlib.PurePosixPath(name).name.casefold() in {
                    "pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts",
                    "gradlew", "gradlew.bat", "mvnw", "mvnw.cmd", "plugin.yml", "paper-plugin.yml",
                }
            )
        elif "cargo.toml" in lower_names:
            detected, build_system, manifests = "rust-cargo", "Cargo", ["Cargo.toml"]
        elif "go.mod" in lower_names:
            detected, build_system, manifests = "go", "Go", ["go.mod"]
        elif "package.json" in lower_names:
            detected, build_system, manifests = "node", "npm", ["package.json"]
        elif "pyproject.toml" in lower_names or "setup.py" in lower_names:
            detected, build_system = "python-package", "Python"
            manifests = [name for name in ("pyproject.toml", "setup.py") if name in lower_names]
        elif any(name.endswith((".html", ".htm")) for name in lower_names):
            detected, build_system = "static-web", "static"

        executable_names = {
            "cpp-cmake": ["cmake"], "dotnet-exe": ["dotnet"], "java-jar": ["java"],
            "paper-plugin": ["java"], "rust-cargo": ["cargo"], "go": ["go"],
            "node": ["node", "npm"], "python-package": ["python"],
        }.get(detected, [])
        availability: dict[str, bool] = {}
        if build_system == "Maven":
            if {"mvnw", "mvnw.cmd"} & lower_names:
                availability["maven-wrapper"] = True
            else:
                executable_names.append("mvn")
        elif build_system == "Gradle" and not ({"gradlew", "gradlew.bat"} & lower_names):
            executable_names.append("gradle")
        elif build_system == "Gradle":
            availability["gradle-wrapper"] = True
        availability.update({item: bool(shutil.which(item)) for item in executable_names})
        return {
            "type": detected,
            "build_system": build_system,
            "manifests": manifests[:20],
            "available": availability,
            "file_count": len(files),
        }

    def _project_command(self, action: str, detected: dict[str, Any], configuration: str,
                         runtime: str, self_contained: bool) -> tuple[str, str]:
        project_type = str(detected["type"])
        build_system = str(detected["build_system"])
        config = configuration if configuration in {"Debug", "Release", "RelWithDebInfo", "MinSizeRel"} else "Release"
        if project_type == "cpp-cmake":
            command = (
                f"cmake -S . -B build -DCMAKE_BUILD_TYPE={config} && "
                f"cmake --build build --config {config} --parallel"
            )
            if action == "test":
                command += f" && ctest --test-dir build -C {config} --output-on-failure"
            return command, f"build/ (configuration {config}; .exe on Windows)"
        if project_type == "dotnet-exe":
            if action == "test":
                return f"dotnet test -c {config} --nologo", "test report"
            if action == "package":
                rid = str(runtime).strip()
                if not rid:
                    machine = platform.machine().casefold()
                    arch = "arm64" if "arm" in machine or "aarch64" in machine else "x64"
                    rid = ("win" if os.name == "nt" else "osx" if sys.platform == "darwin" else "linux") + "-" + arch
                contained = "true" if self_contained else "false"
                return (
                    f"dotnet publish -c {config} -r {rid} --self-contained {contained} "
                    "-p:PublishSingleFile=true --nologo",
                    f"bin/{config}/<framework>/{rid}/publish/",
                )
            return f"dotnet build -c {config} --nologo", f"bin/{config}/"
        if project_type in {"java-jar", "paper-plugin"}:
            if build_system == "Maven":
                wrapper = ".\\mvnw.cmd" if os.name == "nt" and (self.root / "mvnw.cmd").is_file() else "./mvnw" if (self.root / "mvnw").is_file() else "mvn"
                goal = "test" if action == "test" else "package"
                return f"{wrapper} -B -ntp {goal}", "target/*.jar" if goal == "package" else "Maven test report"
            wrapper = ".\\gradlew.bat" if os.name == "nt" and (self.root / "gradlew.bat").is_file() else "./gradlew" if (self.root / "gradlew").is_file() else "gradle"
            task = "test" if action == "test" else "build"
            return f"{wrapper} {task} --console=plain", "build/libs/*.jar" if task == "build" else "Gradle test report"
        if project_type == "rust-cargo":
            if action == "test":
                return "cargo test", "Cargo test report"
            return "cargo build --release", "target/release/"
        if project_type == "go":
            if action == "test":
                return "go test ./...", "Go test report"
            if action == "package":
                output_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", self.root.name).strip("-") or "application"
                suffix = ".exe" if os.name == "nt" else ""
                return f"go build -o dist/{output_name}{suffix} .", f"dist/{output_name}{suffix}"
            return "go build ./...", "Go executable/package output"
        if project_type == "node":
            scripts: dict[str, Any] = {}
            try:
                scripts = json.loads((self.root / "package.json").read_text(encoding="utf-8")).get("scripts", {})
            except (OSError, json.JSONDecodeError, AttributeError):
                pass
            if action == "test" and scripts.get("test"):
                return "npm test", "npm test report"
            if action in {"build", "package"} and scripts.get("build"):
                return "npm run build", "project build output"
            if action == "package":
                return "npm pack", "*.tgz"
            raise ValueError(f"package.json has no usable script for action={action}")
        if project_type == "python-package":
            if action == "test":
                return f"{shlex.quote(sys.executable)} -m unittest discover -s tests", "unittest report"
            return f"{shlex.quote(sys.executable)} -m build", "dist/*"
        raise ValueError("No supported project toolchain was detected. Use action=scaffold with an explicit target.")

    def _toolchain_artifacts(self, detected: dict[str, Any], action: str,
                             configuration: str) -> list[str]:
        """Return deterministic artifact evidence after a successful native build."""
        project_type = str(detected["type"])
        config = configuration if configuration in {"Debug", "Release", "RelWithDebInfo", "MinSizeRel"} else "Release"
        candidates: list[pathlib.Path] = []
        if project_type == "cpp-cmake":
            if os.name == "nt":
                candidates = list((self.root / "build").rglob("*.exe"))
            else:
                candidates = [
                    path for path in (self.root / "build").rglob("*")
                    if path.is_file() and os.access(path, os.X_OK)
                    and path.suffix not in {".a", ".so", ".dylib", ".cmake"}
                ]
        elif project_type == "dotnet-exe":
            base = self.root / "bin" / config
            if action == "package":
                candidates = [path for path in base.rglob("*") if path.is_file() and "publish" in path.parts]
                candidates = [
                    path for path in candidates
                    if path.suffix.casefold() not in {".json", ".pdb", ".xml", ".config"}
                ]
            else:
                candidates = list(base.rglob("*.exe")) + list(base.rglob("*.dll"))
        elif project_type in {"java-jar", "paper-plugin"}:
            folder = self.root / ("target" if detected["build_system"] == "Maven" else "build/libs")
            candidates = [
                path for path in folder.glob("*.jar")
                if not path.name.startswith(("original-", "plain-"))
            ]
        elif project_type == "rust-cargo":
            base = self.root / "target" / "release"
            candidates = [
                path for path in base.glob("*")
                if path.is_file() and (
                    path.suffix.casefold() == ".exe"
                    or (not path.suffix and os.access(path, os.X_OK))
                )
            ]
        elif project_type == "go" and action == "package":
            candidates = [path for path in (self.root / "dist").glob("*") if path.is_file()]
        result: list[str] = []
        for path in sorted(set(candidates)):
            try:
                if path.stat().st_size > 0:
                    result.append(path.relative_to(self.root).as_posix())
            except OSError:
                continue
        return result[:50]

    def _scaffold_files(self, target: str, name: str, package_name: str,
                        language_version: str, platform_version: str) -> dict[str, str]:
        slug, class_name, namespace = self._toolchain_identifiers(name, package_name)
        if target == "cpp-cmake":
            standard = str(language_version).strip().removeprefix("c++") or "20"
            if standard not in {"17", "20", "23", "26"}:
                raise ValueError("C++ language_version must be 17, 20, 23, or 26")
            symbol = slug.replace("-", "_")
            return {
                ".gitignore": "build/\nout/\n*.user\n*.suo\n",
                "CMakeLists.txt": f"""cmake_minimum_required(VERSION 3.20)
project({symbol} VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD {standard})
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_library({symbol}_core src/greeting.cpp)
target_include_directories({symbol}_core PUBLIC include)

add_executable({symbol} src/main.cpp)
target_link_libraries({symbol} PRIVATE {symbol}_core)

include(CTest)
if(BUILD_TESTING)
    add_executable({symbol}_tests tests/greeting_test.cpp)
    target_link_libraries({symbol}_tests PRIVATE {symbol}_core)
    add_test(NAME greeting_test COMMAND {symbol}_tests)
endif()
""",
                f"include/{symbol}/greeting.hpp": """#pragma once

#include <string>

namespace app {
std::string greeting(const std::string& name);
}
""",
                "src/greeting.cpp": f"""#include \"{symbol}/greeting.hpp\"

namespace app {{
std::string greeting(const std::string& name) {{
    return \"Hello, \" + (name.empty() ? std::string{{\"world\"}} : name) + \"!\";
}}
}}
""",
                "src/main.cpp": f"""#include \"{symbol}/greeting.hpp\"

#include <iostream>

int main(int argc, char** argv) {{
    const std::string name = argc > 1 ? argv[1] : \"world\";
    std::cout << app::greeting(name) << '\\n';
    return 0;
}}
""",
                "tests/greeting_test.cpp": f"""#include \"{symbol}/greeting.hpp\"

#include <iostream>

int main() {{
    if (app::greeting(\"ForgeCode\") != \"Hello, ForgeCode!\") {{
        std::cerr << \"greeting test failed\\n\";
        return 1;
    }}
    return 0;
}}
""",
            }
        if target == "dotnet-exe":
            framework = str(language_version).strip() or "net8.0"
            if re.fullmatch(r"\d+(?:\.\d+)?", framework):
                framework = "net" + framework
            if not re.fullmatch(r"net\d+(?:\.\d+)?", framework):
                raise ValueError(".NET language_version must look like net8.0 or net10.0")
            return {
                ".gitignore": "bin/\nobj/\n*.user\n*.suo\n",
                f"{class_name}.csproj": f"""<Project Sdk=\"Microsoft.NET.Sdk\">
  <PropertyGroup>
    <OutputType>Exe</OutputType>
    <TargetFramework>{framework}</TargetFramework>
    <ImplicitUsings>enable</ImplicitUsings>
    <Nullable>enable</Nullable>
    <TreatWarningsAsErrors>true</TreatWarningsAsErrors>
  </PropertyGroup>
</Project>
""",
                "Program.cs": f"""using {namespace};

var who = args.Length > 0 ? args[0] : \"world\";
Console.WriteLine(GreetingService.Create(who));
""",
                "Services/GreetingService.cs": f"""namespace {namespace};

public static class GreetingService
{{
    public static string Create(string name) => $\"Hello, {{(string.IsNullOrWhiteSpace(name) ? \"world\" : name)}}!\";
}}
""",
            }
        if target == "java-jar":
            java_version = str(language_version).strip() or "21"
            if not re.fullmatch(r"(?:17|21|25)", java_version):
                raise ValueError("Java language_version must be 17, 21, or 25")
            package_path = namespace.replace(".", "/")
            main_class = class_name + "Application"
            return {
                ".gitignore": "target/\n*.class\n.idea/\n",
                "pom.xml": f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<project xmlns=\"http://maven.apache.org/POM/4.0.0\" xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\"
         xsi:schemaLocation=\"http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd\">
  <modelVersion>4.0.0</modelVersion>
  <groupId>{namespace}</groupId>
  <artifactId>{slug}</artifactId>
  <version>1.0.0-SNAPSHOT</version>
  <properties>
    <maven.compiler.release>{java_version}</maven.compiler.release>
    <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
  </properties>
  <build>
    <plugins>
      <plugin>
        <groupId>org.apache.maven.plugins</groupId>
        <artifactId>maven-jar-plugin</artifactId>
        <version>3.4.2</version>
        <configuration><archive><manifest><mainClass>{namespace}.{main_class}</mainClass></manifest></archive></configuration>
      </plugin>
    </plugins>
  </build>
</project>
""",
                f"src/main/java/{package_path}/{main_class}.java": f"""package {namespace};

public final class {main_class} {{
    private {main_class}() {{}}

    public static void main(String[] args) {{
        String name = args.length > 0 ? args[0] : \"world\";
        System.out.println(GreetingService.greeting(name));
    }}
}}
""",
                f"src/main/java/{package_path}/GreetingService.java": f"""package {namespace};

public final class GreetingService {{
    private GreetingService() {{}}

    public static String greeting(String name) {{
        return \"Hello, \" + (name == null || name.isBlank() ? \"world\" : name) + \"!\";
    }}
}}
""",
            }
        if target == "paper-plugin":
            paper_version = str(platform_version).strip() or "26.2"
            if not re.fullmatch(r"(?:\d{2,}\.\d+|1\.\d+(?:\.\d+)?)", paper_version):
                raise ValueError("platform_version must look like 26.2 or 1.21.11")
            dependency = f"{paper_version}.build.+" if re.fullmatch(r"\d{2,}\.\d+", paper_version) else f"{paper_version}-R0.1-SNAPSHOT"
            java_version = str(language_version).strip() or ("25" if re.fullmatch(r"\d{2,}\.\d+", paper_version) else "21")
            if not re.fullmatch(r"(?:21|25)", java_version):
                raise ValueError("Paper language_version must be 21 or 25")
            package_path = namespace.replace(".", "/")
            plugin_class = class_name if class_name.casefold().endswith("plugin") else class_name + "Plugin"
            command = slug.split("-")[0]
            return {
                ".gitignore": ".gradle/\nbuild/\n.idea/\n*.iml\n",
                "settings.gradle.kts": f'rootProject.name = "{slug}"\n',
                "build.gradle.kts": f"""plugins {{
    java
}}

group = \"{namespace}\"
version = \"1.0.0\"

repositories {{
    mavenCentral()
    maven {{
        name = \"papermc\"
        url = uri(\"https://repo.papermc.io/repository/maven-public/\")
    }}
}}

dependencies {{
    compileOnly(\"io.papermc.paper:paper-api:{dependency}\")
}}

java {{
    toolchain.languageVersion.set(JavaLanguageVersion.of({java_version}))
}}

tasks.withType<JavaCompile>().configureEach {{
    options.encoding = \"UTF-8\"
}}

tasks.processResources {{
    filesMatching(\"plugin.yml\") {{ expand(\"version\" to project.version) }}
}}
""",
                f"src/main/java/{package_path}/{plugin_class}.java": f"""package {namespace};

import org.bukkit.plugin.java.JavaPlugin;

public final class {plugin_class} extends JavaPlugin {{
    @Override
    public void onEnable() {{
        getLogger().info(\"{class_name} enabled\");
        var command = getCommand(\"{command}\");
        if (command != null) {{
            command.setExecutor(new StatusCommand());
        }}
    }}
}}
""",
                f"src/main/java/{package_path}/StatusCommand.java": f"""package {namespace};

import org.bukkit.command.Command;
import org.bukkit.command.CommandExecutor;
import org.bukkit.command.CommandSender;
import org.jetbrains.annotations.NotNull;

public final class StatusCommand implements CommandExecutor {{
    @Override
    public boolean onCommand(@NotNull CommandSender sender, @NotNull Command command,
                             @NotNull String label, @NotNull String[] args) {{
        sender.sendMessage(\"{class_name} is running.\");
        return true;
    }}
}}
""",
                "src/main/resources/plugin.yml": f"""name: {class_name}
version: '${{version}}'
main: {namespace}.{plugin_class}
description: {class_name} Paper plugin
api-version: '{paper_version}'
commands:
  {command}:
    description: Show plugin status
    usage: /{command}
""",
            }
        raise ValueError("scaffold target must be cpp-cmake, dotnet-exe, java-jar, or paper-plugin")

    def tool_project_toolchain(self, action: str, target: str = "auto", name: str = "",
                               package_name: str = "", language_version: str = "",
                               platform_version: str = "", configuration: str = "Release",
                               runtime: str = "", self_contained: bool = False,
                               overwrite: bool = False, timeout_seconds: int = 100) -> str:
        selected_action = str(action).strip().casefold()
        selected_target = str(target).strip().casefold() or "auto"
        if selected_action == "inspect":
            detected = self._detect_project_toolchain()
            return "OK: project toolchain inspection\n" + json.dumps(detected, ensure_ascii=False, indent=2)
        if selected_action == "scaffold":
            if selected_target == "auto":
                raise ValueError("scaffold requires an explicit target")
            files = self._scaffold_files(selected_target, name, package_name, language_version, platform_version)
            prepared: list[tuple[str, pathlib.Path, str]] = []
            existing: list[str] = []
            for relative, content in files.items():
                destination = self.safe_file_path(relative)
                prepared.append((relative, destination, content))
                if destination.exists():
                    existing.append(relative)
            if existing and not overwrite:
                raise ValueError("Refusing to overwrite existing scaffold files: " + ", ".join(existing))
            summary = ", ".join(files)
            approved, rejection = self._authorize(
                "write",
                f"Create {selected_target} project scaffold with {len(files)} verified files?",
                f"target={selected_target}\nfiles={summary}\noverwrite={bool(overwrite)}",
                bool(self.cfg.data["auto_approve_writes"]),
            )
            if not approved:
                return rejection
            originals: dict[pathlib.Path, bytes | None] = {
                destination: destination.read_bytes() if destination.is_file() else None
                for _, destination, _ in prepared
            }
            written: list[pathlib.Path] = []
            try:
                for _, destination, content in prepared:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    self._write_utf8_verified(destination, content)
                    written.append(destination)
            except Exception:
                for destination in reversed(written):
                    original = originals[destination]
                    try:
                        if original is None:
                            destination.unlink(missing_ok=True)
                        else:
                            temporary = destination.with_name(f".{destination.name}.rollback-{uuid.uuid4().hex}.tmp")
                            temporary.write_bytes(original)
                            os.replace(temporary, destination)
                    except OSError:
                        pass
                raise
            evidence = []
            for relative, destination, _ in prepared:
                payload = destination.read_bytes()
                evidence.append(f"{relative}:{len(payload)}:{hashlib.sha256(payload).hexdigest()[:12]}")
            return (
                f"OK: scaffold created · target={selected_target} · files={len(files)}\n"
                + "\n".join(evidence)
                + "\nNext: project_toolchain action=build, then action=test."
            )
        if selected_action not in {"build", "test", "package"}:
            raise ValueError("action must be inspect, scaffold, build, test, or package")
        detected = self._detect_project_toolchain()
        if selected_target != "auto" and detected["type"] != selected_target:
            raise ValueError(f"Requested target={selected_target}, but detected type={detected['type']}")
        command, expected = self._project_command(
            selected_action, detected, configuration, runtime, bool(self_contained)
        )
        result = self.tool_run_command(command, timeout_seconds)
        if result.startswith("ERROR:"):
            return result
        artifact_types = {"cpp-cmake", "dotnet-exe", "java-jar", "paper-plugin", "rust-cargo"}
        require_artifact = selected_action in {"build", "package"} and detected["type"] in artifact_types
        if detected["type"] == "go" and selected_action == "package":
            require_artifact = True
        artifacts = self._toolchain_artifacts(detected, selected_action, configuration)
        if require_artifact and not artifacts:
            return (
                "ERROR: Native toolchain command succeeded but no non-empty build artifact was found "
                f"for type={detected['type']} action={selected_action}. Expected: {expected}"
            )
        artifact_note = ", ".join(artifacts[:12]) if artifacts else "command-only verification"
        return (
            f"OK: toolchain {selected_action} passed · type={detected['type']} · "
            f"build_system={detected['build_system']} · artifacts={artifact_note}\n{result}"
        )

    def _validate_static_web_project(self) -> str:
        html_files = [path for path in self.visible_files() if path.suffix.lower() in {".html", ".htm"}]
        if not html_files:
            return "SKIP: Statik web doğrulaması için HTML dosyası bulunamadı."
        errors: list[str] = []
        warnings: list[str] = []
        checked_refs = 0
        for file in html_files[:100]:
            audit = StaticWebAudit()
            try:
                audit.feed(file.read_text(encoding="utf-8", errors="replace"))
                audit.close()
            except Exception as exc:
                errors.append(f"{file.relative_to(self.root).as_posix()}: HTML ayrıştırılamadı ({exc})")
                continue
            rel = file.relative_to(self.root).as_posix()
            if audit.duplicate_ids:
                errors.append(f"{rel}: yinelenen id: {', '.join(sorted(audit.duplicate_ids)[:10])}")
            if audit.images_without_alt:
                warnings.append(f"{rel}: alt metni olmayan {audit.images_without_alt} görsel")
            if audit.inputs_without_hint:
                warnings.append(f"{rel}: erişilebilir adı/ipucu olmayan {audit.inputs_without_hint} form alanı")
            for reference in audit.references:
                clean = urllib.parse.urlsplit(reference).path
                if not clean or reference.startswith(("#", "data:", "mailto:", "tel:", "javascript:", "http://", "https://", "//")):
                    continue
                if any(marker in clean for marker in ("{{", "}}", "<%", "%>")):
                    continue
                target = (self.root / clean.lstrip("/")) if clean.startswith("/") else (file.parent / clean)
                checked_refs += 1
                if not target.resolve().is_file():
                    errors.append(f"{rel}: eksik yerel varlık {reference}")
        if errors:
            return "ERROR: Statik web doğrulaması başarısız:\n- " + "\n- ".join(errors[:30])
        result = f"OK: Statik web doğrulaması geçti ({len(html_files[:100])} HTML, {checked_refs} yerel bağlantı)."
        if warnings:
            result += "\nUyarılar:\n- " + "\n- ".join(warnings[:20])
        return result

    def tool_test_project(self, command: str = "", timeout_seconds: int = 100, stdin: str | None = None, interactive: bool = False) -> str:
        def run_test(test_command: str) -> str:
            if interactive:
                if stdin is not None:
                    return "ERROR: interactive=true ile toplu stdin birlikte kullanılamaz. Süreci başlatın, sonra process_input ile aşama aşama cevap verin."
                return self.tool_start_process(test_command)
            return self.tool_run_command(test_command, timeout_seconds, stdin)

        selected = str(command).strip()
        if selected:
            return run_test(selected)
        names = {path.relative_to(self.root).as_posix() for path in self.visible_files()}
        lower_names = {name.lower() for name in names}
        sandboxed = self.sandbox is not None and self.sandbox.active()
        python_executable = "python" if sandboxed else str(sys.executable)
        if os.name == "nt" and not sandboxed:
            python_command = "& '" + python_executable.replace("'", "''") + "'"
        else:
            python_command = shlex.quote(python_executable)
        if any(name.startswith("tests/") and pathlib.PurePosixPath(name).name.startswith("test") and name.endswith(".py") for name in lower_names):
            return run_test(f"{python_command} -m unittest discover -s tests")
        if "pytest.ini" in lower_names or "conftest.py" in lower_names:
            return run_test(f"{python_command} -m pytest")
        package = self.root / "package.json"
        if package.is_file():
            try:
                scripts = json.loads(package.read_text(encoding="utf-8")).get("scripts", {})
                test_script = str(scripts.get("test", "")).strip()
                build_script = str(scripts.get("build", "")).strip()
            except (OSError, json.JSONDecodeError, AttributeError):
                test_script = ""
                build_script = ""
            if test_script and "no test specified" not in test_script.lower():
                return run_test("npm test")
            if build_script:
                return run_test("npm run build")
        if "go.mod" in lower_names:
            return run_test("go test ./...")
        if "cargo.toml" in lower_names:
            return run_test("cargo test")
        if any(name.endswith((".sln", ".csproj", ".fsproj")) for name in lower_names):
            return run_test("dotnet test")
        if "cmakelists.txt" in lower_names:
            return run_test(
                "cmake -S . -B build -DCMAKE_BUILD_TYPE=Release && "
                "cmake --build build --config Release --parallel && "
                "ctest --test-dir build -C Release --output-on-failure"
            )
        if "pom.xml" in lower_names:
            wrapper = ".\\mvnw.cmd" if os.name == "nt" and "mvnw.cmd" in lower_names else "./mvnw" if "mvnw" in lower_names else "mvn"
            return run_test(f"{wrapper} test")
        if "gradlew.bat" in lower_names and not sandboxed:
            return run_test(".\\gradlew.bat test")
        if "gradlew" in lower_names:
            return run_test("./gradlew test")
        if "build.gradle" in lower_names or "build.gradle.kts" in lower_names:
            return run_test("gradle test --console=plain")
        if any(name.endswith(".py") for name in lower_names):
            return run_test(f"{python_command} -m compileall -q .")
        if any(name.endswith((".html", ".htm")) for name in lower_names):
            return self._validate_static_web_project()
        return "SKIP: Güvenilir otomatik test komutu bulunamadı; test uydurulmadı."

    def tool_get_diagnostics(self) -> str:
        if self.diagnostic_provider:
            return self.diagnostic_provider()
        safe = {name: self.cfg.data.get(name) for name in sorted(AI_EDITABLE_SETTINGS)}
        return "ForgeCode ayarları:\n" + json.dumps(safe, ensure_ascii=False, indent=2)

    def tool_list_skills(self, query: str = "") -> str:
        if self.skill_manager is None:
            return "ForceCode Skill Engine bu oturumda kullanılamıyor."
        return self.skill_manager.list_text(query)

    def tool_manage_skill(self, action: str, name: str = "", source: str = "", scope: str = "user",
                          description: str = "", instructions: str = "") -> str:
        if self.skill_manager is None:
            raise ValueError("ForceCode Skill Engine bu oturumda kullanılamıyor")
        selected = str(action).strip().casefold()
        if selected == "show":
            return self.skill_manager.show(name)
        if selected == "discover":
            return self.skill_manager.discover_text(source)
        if selected == "install":
            record = self.skill_manager.install(source, scope)
            return f"OK: Skill kuruldu: {record.name} · kapsam {record.scope} · sonraki uygun istekte otomatik seçilebilir"
        if selected == "update":
            record = self.skill_manager.update(name)
            return f"OK: Skill güncellendi: {record.name}"
        if selected == "create":
            record = self.skill_manager.create(name, description, instructions, scope)
            return f"OK: Yerel skill oluşturuldu: {record.name} · kapsam {record.scope}"
        if selected == "enable":
            return "OK: " + self.skill_manager.set_enabled(name, True)
        if selected == "disable":
            return "OK: " + self.skill_manager.set_enabled(name, False)
        if selected == "remove":
            return "OK: " + self.skill_manager.remove(name)
        raise ValueError("Skill action show, discover, install, update, create, enable, disable veya remove olmalı")

    def tool_manage_mcp_server(self, action: str, name: str = "", transport: str = "stdio",
                               command: str = "", args: list[str] | None = None, url: str = "") -> str:
        selected = str(action).strip().casefold()
        if selected == "status":
            return self.mcp.status_text()
        if not self.mcp.management_requested:
            raise ValueError("MCP yönetimi için kullanıcı açıkça MCP bağlama veya geçiş isteği vermeli")
        if selected == "discover":
            found = self.mcp.discover()
            return "MCP profilleri tarandı: " + (", ".join(found) if found else "uygun sunucu bulunamadı")
        if selected == "add":
            if str(transport).casefold() == "http":
                saved = self.mcp.add_http(name, url)
            else:
                saved = self.mcp.add_stdio(name, command, list(args or []))
            approved, rejection = self._authorize(
                "command", f"MCP sunucusuna bağlanılsın mı? {saved}",
                f"mcp_server={saved}\ntransport={transport}\ncommand={redact_sensitive(command)}\nurl={redact_sensitive(url)}",
                False,
            )
            if not approved:
                return rejection
            schemas = self.mcp.connect(saved)
            return f"OK: MCP bağlandı: {saved} · {len(schemas)} araç · ForceGraph kapatıldı"
        if selected in {"test", "use"}:
            approved, rejection = self._authorize(
                "command", f"Kayıtlı MCP sunucusuna bağlanılsın mı? {mcp_slug(name)}",
                f"mcp_server={mcp_slug(name)}",
                False,
            )
            if not approved:
                return rejection
            schemas = self.mcp.connect(name)
            return f"OK: MCP bağlandı: {self.cfg.data.get('mcp_active_server')} · {len(schemas)} araç · ForceGraph kapatıldı"
        if selected == "remove":
            self.mcp.remove(name)
            return f"OK: MCP profili kaldırıldı: {mcp_slug(name)}"
        if selected in {"disable", "graph"}:
            self.mcp.switch_to_forcegraph()
            return "OK: MCP kapatıldı; ForceGraph yeniden etkin"
        raise ValueError(f"Bilinmeyen MCP işlemi: {action}")

    def tool_graph_context(self, action: str = "status", base: str = "HEAD~1") -> str:
        """Read structural graph evidence without mutating project source files."""
        if self.cfg.data.get("mcp_enabled", False):
            return "MCP etkin olduğu için ForceGraph kapalı. Geri dönmek için /mcp veya 'ForceGraph'a geri geç' yazın."
        selected = str(action).strip().lower()
        self._notify_progress(f"ForceGraph: {selected} analizi")
        self.force_graph.ensure_automatic(self.snapshot(), self._notify_progress)
        if selected == "status":
            source_count = len(self.force_graph._source_snapshot(self.snapshot()))
            if source_count == 0:
                return "ForceGraph otomasyonu açık, ancak bu klasörde desteklenen kaynak kod dosyası olmadığı için grafik uygulanamaz."
            return self.force_graph.status_summary()
        if selected == "impact":
            return self.force_graph.impact(base)
        if selected == "review":
            return self.force_graph.review(base)
        raise ValueError("ForceGraph action status, impact veya review olmalı")

    def tool_set_forgecode_setting(self, name: str, value: str, reason: str) -> str:
        selected = str(name).strip()
        if selected not in AI_EDITABLE_SETTINGS:
            raise ValueError(
                f"AI bu ayarı değiştiremez: {selected}. API anahtarı, sağlayıcı/model, URL/route ve güvenlik onayları yalnızca kullanıcı komutlarıyla değişir."
            )
        numeric_limits: dict[str, tuple[float, float]] = {
            "max_tokens": (256, 65536), "temperature": (0, 1), "timeout_seconds": (5, 600),
            "first_response_timeout_seconds": (5, 180), "stream_idle_timeout_seconds": (5, 300),
            "request_total_timeout_seconds": (15, 600), "retry_budget_seconds": (5, 300),
            "preflight_timeout_seconds": (1, 60),
            "stall_first_response_seconds": (15, 900), "stall_stream_idle_seconds": (30, 1800),
            "stall_retry_attempts": (0, 3),
            "retry_attempts": (1, 5), "retry_backoff_seconds": (0, 10),
            "max_tool_output_chars": (1000, 100000), "web_max_results": (1, 20),
            "thinking_budget_tokens": (1024, 32000), "subagent_timeout_seconds": (5, 300),
            "history_context_turns": (1, 50), "history_context_chars": (1000, 100000),
            "session_log_max_lines": (100, 100000),
            "team_max_workers": (1, 3),
        }
        if selected in numeric_limits:
            try:
                number = float(value)
            except ValueError as exc:
                raise ValueError(f"{selected} sayısal olmalı") from exc
            low, high = numeric_limits[selected]
            if not low <= number <= high:
                raise ValueError(f"{selected} {low:g} ile {high:g} arasında olmalı")
        before = self.cfg.data.get(selected)
        self.cfg.set_value(selected, str(value))
        after = self.cfg.data.get(selected)
        safe_reason = redact_sensitive(reason).strip()[:500]
        return f"OK: ForgeCode ayarı güncellendi: {selected} = {after!r} (önce: {before!r}). Gerekçe: {safe_reason or 'belirtilmedi'}"
