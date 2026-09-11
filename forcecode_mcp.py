#!/usr/bin/env python3
"""ForceCode mcp + graph bridge. Depends on base/config."""

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

from forcecode_base import decode_subprocess_output, load_json, redact_sensitive
from forcecode_config import Config

VERSION = "8.0.0a2"

def _fc(name):
    import forcecode as _m
    return getattr(_m, name)


FORCEGRAPH_REPOSITORY = "https://github.com/samansarmasik-alt/code-review-graph.git"


FORCEGRAPH_MIN_VERSION = (2, 7, 0)


FORCEGRAPH_MIN_VERSION_TEXT = ".".join(str(part) for part in FORCEGRAPH_MIN_VERSION)


FORCEGRAPH_AUTO_LOCK = threading.RLock()


class ForceGraphBridge:
    """Optional, self-maintaining local-first bridge to the ForceGraph CLI.

    ForceCode remains dependency-free when ForceGraph is absent. All invocations
    use argument arrays with shell=False and are scoped to the selected project.
    """

    SOURCE_SUFFIXES = {
        ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".kt",
        ".kts", ".cs", ".vb", ".c", ".h", ".cc", ".cpp", ".hpp", ".rb",
        ".php", ".swift", ".scala", ".sol", ".dart", ".lua", ".luau", ".pl",
        ".pm", ".sh", ".bash", ".ps1", ".ex", ".exs", ".zig", ".sql",
        ".vue", ".svelte", ".astro", ".ipynb",
    }

    def __init__(self, root: pathlib.Path, cfg: Config | None = None):
        self.root = root.resolve()
        self.cfg = cfg
        self.runtime_auto = False

    def command(self) -> list[str] | None:
        # Prefer the package in ForceCode's own interpreter. /graph install and
        # automatic upgrades target this exact environment, avoiding a stale
        # executable from another Python installation on Windows.
        try:
            importlib.metadata.version("code-review-graph")
            if importlib.util.find_spec("code_review_graph") is not None:
                return [sys.executable, "-m", "code_review_graph"]
        except (ImportError, ValueError, importlib.metadata.PackageNotFoundError):
            pass
        for executable in ("forcegraph", "code-review-graph"):
            found = shutil.which(executable)
            if found:
                return [found]
        return None

    def installed(self) -> bool:
        return self.command() is not None

    def data_dir(self) -> pathlib.Path:
        return self.root / ".code-review-graph"

    def state_path(self) -> pathlib.Path:
        return self.root / ".forcecode" / "forcegraph-state.json"

    def state(self) -> dict[str, Any]:
        value = load_json(self.state_path(), {})
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _version_tuple(value: str) -> tuple[int, int, int] | None:
        match = re.search(r"(?<!\d)(\d+)\.(\d+)\.(\d+)(?!\d)", str(value))
        return tuple(int(part) for part in match.groups()) if match else None

    def version(self) -> str:
        try:
            value = importlib.metadata.version("code-review-graph")
            if self._version_tuple(value):
                return value
        except (ImportError, OSError, RuntimeError, importlib.metadata.PackageNotFoundError):
            pass
        if self.command() is None:
            return ""
        output = self.run(["--version"], 30)
        match = re.search(r"(?<!\d)\d+\.\d+\.\d+(?!\d)", output)
        return match.group(0) if match else ""

    @classmethod
    def _source_snapshot(cls, snapshot: dict[str, tuple[int, int]]) -> dict[str, tuple[int, int]]:
        return {
            name: signature for name, signature in snapshot.items()
            if pathlib.PurePosixPath(name).suffix.casefold() in cls.SOURCE_SUFFIXES
        }

    @classmethod
    def _snapshot_signature(cls, snapshot: dict[str, tuple[int, int]]) -> str:
        selected = cls._source_snapshot(snapshot)
        digest = hashlib.sha256()
        for name, signature in sorted(selected.items()):
            digest.update(f"{name}\0{signature[0]}\0{signature[1]}\n".encode("utf-8", errors="replace"))
        return digest.hexdigest()[:20] if selected else ""

    def _save_auto_state(self, **values: Any) -> dict[str, Any]:
        state = self.state()
        state.update(values)
        state["updated_at"] = dt.datetime.now().isoformat(timespec="seconds")
        try:
            atomic_json(self.state_path(), state)
        except OSError as exc:
            state["persistence_error"] = redact_sensitive(str(exc))[:500]
        if self.data_dir().is_dir():
            try:
                atomic_json(self.data_dir() / "forcecode-auto-receipt.json", {
                    "schema_version": 1,
                    "status": state.get("status", "unknown"),
                    "mode": "native-auto-sync",
                    "version": state.get("version", ""),
                    "source_signature": state.get("source_signature", ""),
                    "last_action": state.get("last_action", ""),
                    "updated_at": state["updated_at"],
                })
            except OSError as exc:
                state["persistence_error"] = redact_sensitive(str(exc))[:500]
        return state

    def ensure_automatic(
        self,
        snapshot: dict[str, tuple[int, int]],
        progress: Callable[[str], None] | None = None,
        force_sync: bool = False,
    ) -> dict[str, Any]:
        """Install once, build once, then incrementally sync before AI work."""
        if (
            not self.runtime_auto
            or (self.cfg and not self.cfg.data.get("forcegraph_auto_enabled", True))
            or (self.cfg and self.cfg.data.get("mcp_enabled", False))
        ):
            return {"status": "disabled"}
        source_snapshot = self._source_snapshot(snapshot)
        signature = self._snapshot_signature(source_snapshot)
        if not source_snapshot:
            return {
                "status": "not-applicable", "source_files": 0,
                "reason": "Bu klasörde desteklenen kaynak kod dosyası yok.",
            }
        notify = progress or (lambda _message: None)
        with FORCEGRAPH_AUTO_LOCK:
            previous = self.state()
            installed_version = self.version()
            version_tuple = self._version_tuple(installed_version)
            needs_upgrade = (
                self.command() is None
                or version_tuple is None
                or version_tuple < FORCEGRAPH_MIN_VERSION
            )
            error_time = float(previous.get("error_time", 0) or 0)
            same_failed_requirement = (
                previous.get("required_version") == FORCEGRAPH_MIN_VERSION_TEXT
                and str(previous.get("last_action", "")).startswith("install")
            )
            if (
                not force_sync
                and error_time
                and time.time() - error_time < 3600
                and (not needs_upgrade or same_failed_requirement)
            ):
                return previous

            upgraded = False
            if needs_upgrade:
                notify(f"ForceGraph {FORCEGRAPH_MIN_VERSION_TEXT}+ hazırlanıyor · tek seferlik otomatik kurulum")
                install_result = self.install()
                if install_result.startswith("ERROR:"):
                    return self._save_auto_state(
                        status="degraded", last_action="install", error=install_result[:2000],
                        error_time=time.time(), source_signature="",
                        required_version=FORCEGRAPH_MIN_VERSION_TEXT,
                    )
                importlib.invalidate_caches()
                installed_version = self.version() or f"{FORCEGRAPH_MIN_VERSION_TEXT}+"
                refreshed_tuple = self._version_tuple(installed_version)
                if refreshed_tuple is not None and refreshed_tuple < FORCEGRAPH_MIN_VERSION:
                    return self._save_auto_state(
                        status="degraded", last_action="install-verify",
                        error=f"ForceGraph {FORCEGRAPH_MIN_VERSION_TEXT}+ gerekli, bulunan sürüm: {installed_version}",
                        error_time=time.time(), source_signature="",
                        required_version=FORCEGRAPH_MIN_VERSION_TEXT,
                    )
                upgraded = True

            if not self.ready():
                fast = len(source_snapshot) > 2500
                notify(f"ForceGraph proje haritası oluşturuluyor · {len(source_snapshot)} kaynak dosya")
                result = self.build(fast=fast)
                action = "build-fast" if fast else "build"
            elif force_sync or previous.get("source_signature") != signature:
                notify("ForceGraph değişiklikleri otomatik indeksliyor")
                result = self.run(["update", "--brief"], 600)
                action = "update"
            else:
                if (
                    upgraded
                    or previous.get("version") != installed_version
                    or previous.get("required_version") != FORCEGRAPH_MIN_VERSION_TEXT
                ):
                    notify(f"ForceGraph {installed_version} hazır · entegrasyon kaydı güncellendi")
                    return self._save_auto_state(
                        status="ready", last_action="upgrade" if upgraded else "version-refresh",
                        error="", error_time=0, version=installed_version,
                        required_version=FORCEGRAPH_MIN_VERSION_TEXT,
                        source_signature=signature, source_files=len(source_snapshot),
                    )
                return previous or {"status": "ready", "version": installed_version, "source_signature": signature}

            if result.startswith("ERROR:"):
                notify("ForceGraph kullanılamadı · normal ForceCode akışı devam ediyor")
                return self._save_auto_state(
                    status="degraded", last_action=action, error=result[:2000],
                    error_time=time.time(), version=installed_version,
                    source_signature=previous.get("source_signature", ""),
                )
            if action.startswith("build") and not self.ready(verify_graph=True):
                notify("ForceGraph grafiği doğrulanamadı · normal ForceCode akışı devam ediyor")
                return self._save_auto_state(
                    status="degraded", last_action="build-verify",
                    error="Build başarı bildirdi ancak yerel grafik veritabanı bulunamadı.",
                    error_time=time.time(), version=installed_version, source_signature="",
                )
            notify("ForceGraph hazır · mimari ve etki bağlamı güncel")
            return self._save_auto_state(
                status="ready", last_action=action, error="", error_time=0,
                version=installed_version, required_version=FORCEGRAPH_MIN_VERSION_TEXT,
                source_signature=signature,
                source_files=len(source_snapshot),
            )

    def ready(self, verify_graph: bool = False) -> bool:
        receipt = load_json(self.data_dir() / "quickstart-receipt.json", {})
        graph_receipt = receipt.get("graph") if isinstance(receipt, dict) else None
        if (
            isinstance(receipt, dict)
            and receipt.get("status") == "ready"
            and isinstance(graph_receipt, dict)
            and graph_receipt.get("built") is True
        ):
            return True
        if not self.data_dir().is_dir():
            return False
        try:
            database_exists = any(
                path.is_file() and path.suffix.casefold() in {".db", ".sqlite", ".sqlite3"}
                for path in self.data_dir().iterdir()
            )
        except OSError:
            return False
        # `forcegraph status` can create an empty database as a migration side
        # effect. A database file alone therefore is not evidence of a built
        # graph. Trust our successful build receipt, or explicitly verify live
        # graph counts immediately after a build.
        state = self.state()
        if database_exists and state.get("status") == "ready" and state.get("source_signature"):
            return True
        if verify_graph and database_exists:
            payload = self.status_payload()
            return bool(payload and int(payload.get("files", 0) or 0) > 0 and int(payload.get("nodes", 0) or 0) > 0)
        return False

    @staticmethod
    def _safe_base(base: str) -> str:
        value = str(base or "HEAD~1").strip()
        if not re.fullmatch(r"[A-Za-z0-9_./~^@{}+-]{1,160}", value):
            raise ValueError("Geçersiz Git base değeri")
        return value

    def run(self, arguments: list[str], timeout_seconds: int = 180) -> str:
        command = self.command()
        if command is None:
            return (
                "ERROR: ForceGraph kurulu değil. Kurulum: "
                f'python -m pip install "git+{FORCEGRAPH_REPOSITORY}"'
            )
        env = os.environ.copy()
        env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONSAFEPATH": "1"})
        try:
            completed = subprocess.run(
                [*command, *arguments], cwd=str(self.root), env=env,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=max(5, min(int(timeout_seconds), 600)), shell=False,
            )
        except subprocess.TimeoutExpired:
            return f"ERROR: ForceGraph {timeout_seconds} saniyede tamamlanamadı."
        except OSError as exc:
            return f"ERROR: ForceGraph başlatılamadı: {exc}"
        stdout = decode_subprocess_output(completed.stdout).strip()
        stderr = decode_subprocess_output(completed.stderr).strip()
        combined = "\n".join(part for part in (stdout, stderr) if part).strip()
        if completed.returncode != 0:
            return f"ERROR: ForceGraph exit_code={completed.returncode}\n{combined or 'Ayrıntı yok.'}"
        return combined or "ForceGraph işlemi tamamlandı."

    def status(self) -> str:
        return self.run(["status", "--json"], 45)

    @staticmethod
    def _json_payload(raw: str) -> dict[str, Any] | None:
        """Extract ForceGraph JSON while ignoring migration/info lines."""
        for line in reversed(str(raw).splitlines()):
            candidate = line.strip()
            if not candidate.startswith("{"):
                continue
            try:
                value = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
        return None

    def status_payload(self) -> dict[str, Any] | None:
        raw = self.status()
        if raw.startswith("ERROR:"):
            return None
        return self._json_payload(raw)

    def status_summary(self) -> str:
        raw = self.status()
        if raw.startswith("ERROR:"):
            return raw
        payload = self._json_payload(raw)
        if not payload:
            return "ForceGraph durum yanıtı okunamadı. /graph repair ile yeniden oluşturmayı deneyin."
        files = int(payload.get("files", 0) or 0)
        nodes = int(payload.get("nodes", 0) or 0)
        edges = int(payload.get("edges", 0) or 0)
        languages = payload.get("languages") or []
        language_text = ", ".join(str(item) for item in languages[:8]) if isinstance(languages, list) else str(languages)
        state = "hazır" if files > 0 and nodes > 0 else "boş"
        summary = f"Grafik: {state} · {files} dosya · {nodes} düğüm · {edges} bağlantı"
        if language_text:
            summary += f" · diller: {language_text}"
        return summary

    def install(self) -> str:
        env = os.environ.copy()
        env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONSAFEPATH": "1"})
        try:
            completed = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--upgrade", f"git+{FORCEGRAPH_REPOSITORY}"],
                cwd=str(self.root), env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=600, shell=False,
            )
        except subprocess.TimeoutExpired:
            return "ERROR: ForceGraph kurulumu 600 saniyede tamamlanamadı."
        except OSError as exc:
            return f"ERROR: ForceGraph kurulumu başlatılamadı: {exc}"
        output = "\n".join(filter(None, (
            decode_subprocess_output(completed.stdout).strip(),
            decode_subprocess_output(completed.stderr).strip(),
        )))
        if completed.returncode != 0:
            return f"ERROR: ForceGraph kurulamadı (exit_code={completed.returncode})\n{output}"
        importlib.invalidate_caches()
        return output or "ForceGraph kuruldu."

    def build(self, fast: bool = False) -> str:
        args = ["build"]
        if fast:
            args.append("--skip-flows")
        return self.run(args, 600)

    def update(self, base: str = "HEAD~1") -> str:
        return self.run(["update", "--base", self._safe_base(base), "--brief"], 600)

    def impact(self, base: str = "HEAD~1") -> str:
        return self.run(["detect-changes", "--base", self._safe_base(base), "--brief"], 180)

    def review(self, base: str = "HEAD~1") -> str:
        return self.run(["detect-changes", "--base", self._safe_base(base)], 240)

    def visualize(self) -> str:
        return self.run(["visualize"], 180)


def mcp_safe_environment() -> dict[str, str]:
    """Build a minimal process environment without provider/API credentials."""
    allowed = {
        "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP",
        "LOCALAPPDATA", "APPDATA", "PROGRAMDATA", "PROGRAMFILES",
        "PROGRAMFILES(X86)", "PYTHONUTF8", "PYTHONIOENCODING",
    }
    environment = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    environment.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONSAFEPATH": "1"})
    return environment


class MCPStdioClient:
    """Small dependency-free MCP JSON-RPC stdio client with bounded waits."""

    def __init__(self, command: list[str], root: pathlib.Path, timeout_seconds: int = 45):
        self.command = list(command)
        self.root = root.resolve()
        self.timeout_seconds = max(5, min(int(timeout_seconds), 300))
        self.process: subprocess.Popen[str] | None = None
        self._condition = threading.Condition()
        self._responses: dict[int, dict[str, Any]] = {}
        self._next_id = 1
        self._stderr: collections.deque[str] = collections.deque(maxlen=20)
        self._closed = False

    def start(self) -> None:
        if self.process is not None and self.process.poll() is None:
            return
        try:
            self.process = subprocess.Popen(
                self.command, cwd=str(self.root), env=mcp_safe_environment(), shell=False,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
            )
        except OSError as exc:
            raise RuntimeError(f"MCP sunucusu başlatılamadı: {exc}") from exc
        threading.Thread(target=self._read_stdout, daemon=True, name="forcecode-mcp-out").start()
        threading.Thread(target=self._read_stderr, daemon=True, name="forcecode-mcp-err").start()
        initialized = self.request("initialize", {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": APP_NAME, "version": VERSION},
        })
        if not isinstance(initialized, dict):
            raise RuntimeError("MCP initialize geçerli bir sonuç döndürmedi")
        self.notify("notifications/initialized", {})

    def _read_stdout(self) -> None:
        process = self.process
        if process is None or process.stdout is None:
            return
        try:
            for raw_line in process.stdout:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(message, dict):
                    continue
                request_id = message.get("id")
                if isinstance(request_id, int) and "method" not in message:
                    with self._condition:
                        self._responses[request_id] = message
                        self._condition.notify_all()
        finally:
            with self._condition:
                self._closed = True
                self._condition.notify_all()

    def _read_stderr(self) -> None:
        process = self.process
        if process is None or process.stderr is None:
            return
        for raw_line in process.stderr:
            line = redact_sensitive(raw_line.strip())[:500]
            if line:
                self._stderr.append(line)

    def _send(self, payload: dict[str, Any]) -> None:
        process = self.process
        if process is None or process.poll() is not None or process.stdin is None:
            detail = self._stderr[-1] if self._stderr else "işlem kapandı"
            raise RuntimeError(f"MCP bağlantısı kapalı: {detail}")
        try:
            process.stdin.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
            process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as exc:
            raise RuntimeError(f"MCP isteği gönderilemedi: {exc}") from exc

    def request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        with self._condition:
            request_id = self._next_id
            self._next_id += 1
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
        deadline = time.monotonic() + self.timeout_seconds
        with self._condition:
            while request_id not in self._responses:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"MCP {method} isteği {self.timeout_seconds} saniyede yanıt vermedi")
                if self._closed:
                    detail = self._stderr[-1] if self._stderr else "sunucu çıktı vermeden kapandı"
                    raise RuntimeError(f"MCP sunucusu kapandı: {detail}")
                self._condition.wait(min(remaining, 0.25))
            response = self._responses.pop(request_id)
        if "error" in response:
            error = response.get("error")
            if isinstance(error, dict):
                raise RuntimeError(f"MCP {method}: {error.get('message', error)}")
            raise RuntimeError(f"MCP {method}: {error}")
        return response.get("result")

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def close(self) -> None:
        process = self.process
        self._closed = True
        if process is None:
            return
        if process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    process.kill()
                except OSError:
                    pass
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except (OSError, ValueError):
                    pass


class MCPHttpClient:
    """Minimal MCP Streamable HTTP client for public or local endpoints."""

    def __init__(self, url: str, timeout_seconds: int = 45):
        self.url = url
        self.timeout_seconds = max(5, min(int(timeout_seconds), 300))
        self.session_id = ""
        self._next_id = 1

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        request = urllib.request.Request(
            self.url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers, method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                self.session_id = response.headers.get("Mcp-Session-Id", self.session_id)
                payload = response.read(5_000_001)
                if len(payload) > 5_000_000:
                    raise RuntimeError("MCP HTTP yanıtı 5 MB güvenlik sınırını aştı")
                raw = payload.decode("utf-8", errors="replace").strip()
                content_type = response.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:800]
            raise RuntimeError(f"MCP HTTP {exc.code}: {redact_sensitive(detail)}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(f"MCP HTTP bağlantısı başarısız: {exc}") from exc
        if not raw:
            return {}
        if "text/event-stream" in content_type:
            data_lines = [line[5:].strip() for line in raw.splitlines() if line.startswith("data:")]
            raw = data_lines[-1] if data_lines else raw
        try:
            result = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("MCP HTTP sunucusu JSON/SSE yerine geçersiz yanıt döndürdü") from exc
        return result if isinstance(result, dict) else {}

    def request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        request_id = self._next_id
        self._next_id += 1
        response = self._post({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
        if "error" in response:
            error = response.get("error")
            message = error.get("message", error) if isinstance(error, dict) else error
            raise RuntimeError(f"MCP {method}: {message}")
        return response.get("result")

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self._post({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def start(self) -> None:
        result = self.request("initialize", {
            "protocolVersion": "2025-03-26", "capabilities": {},
            "clientInfo": {"name": APP_NAME, "version": VERSION},
        })
        if not isinstance(result, dict):
            raise RuntimeError("MCP initialize geçerli bir sonuç döndürmedi")
        self.notify("notifications/initialized", {})

    def close(self) -> None:
        if self.session_id:
            try:
                request = urllib.request.Request(
                    self.url, headers={"Mcp-Session-Id": self.session_id}, method="DELETE",
                )
                urllib.request.urlopen(request, timeout=5).close()
            except (urllib.error.URLError, OSError):
                pass


class MCPManager:
    """Own MCP profiles, one active connection, and provider-neutral tool schemas."""

    def __init__(self, root: pathlib.Path, cfg: Config):
        self.root = root.resolve()
        self.cfg = cfg
        self.client: MCPStdioClient | MCPHttpClient | None = None
        self._schemas: list[dict[str, Any]] = []
        self._tool_names: dict[str, str] = {}
        self.management_requested = False
        self.last_error = ""
        atexit.register(self.close)

    def set_request(self, prompt: str) -> None:
        lowered = str(prompt).casefold()
        self.management_requested = "mcp" in lowered and any(word in lowered for word in (
            "bağla", "bagla", "connect", "ekle", "kur", "kullan", "geç", "gec",
            "aç", "ac", "kapat", "sil", "remove", "test", "tara", "bul", "yönet",
        ))

    def profiles(self) -> dict[str, dict[str, Any]]:
        value = self.cfg.data.get("mcp_servers", {})
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _validate_http_url(url: str) -> str:
        parsed = urllib.parse.urlsplit(str(url).strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("MCP URL geçerli bir http(s) adresi olmalı")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("MCP URL içine kullanıcı adı, parola, token, query veya fragment koymayın")
        host = (parsed.hostname or "").casefold()
        if parsed.scheme == "http" and host not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("Uzak MCP bağlantısı HTTPS kullanmalı; HTTP yalnızca localhost için kabul edilir")
        return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", "", ""))

    @staticmethod
    def _validate_command(command: str, args: list[str]) -> tuple[str, list[str]]:
        executable = str(command).strip()
        if not executable or "\n" in executable or "\r" in executable:
            raise ValueError("MCP komutu boş veya geçersiz")
        if pathlib.Path(executable).name.casefold() in {
            "cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh", "pwsh.exe",
            "bash", "bash.exe", "sh", "zsh",
        }:
            raise ValueError("MCP için shell sarmalayıcısı kullanılamaz; çalıştırılabilir dosyayı doğrudan verin")
        cleaned = []
        for value in args:
            item = str(value)
            if "\n" in item or "\r" in item or len(item) > 4000:
                raise ValueError("MCP argümanı geçersiz")
            cleaned.append(item)
        joined = " ".join([executable, *cleaned])
        if "[REDACTED]" in redact_sensitive(joined):
            raise ValueError("MCP komutuna API anahtarı/token koymayın; gizli değerler profile kaydedilmez")
        return executable, cleaned

    def add_stdio(self, name: str, command: str, args: list[str]) -> str:
        slug = mcp_slug(name)
        executable, cleaned = self._validate_command(command, args)
        profiles = copy.deepcopy(self.profiles())
        profiles[slug] = {"transport": "stdio", "command": executable, "args": cleaned}
        self.cfg.data["mcp_servers"] = profiles
        self.cfg.save()
        return slug

    def add_http(self, name: str, url: str) -> str:
        slug = mcp_slug(name)
        profiles = copy.deepcopy(self.profiles())
        profiles[slug] = {"transport": "http", "url": self._validate_http_url(url)}
        self.cfg.data["mcp_servers"] = profiles
        self.cfg.save()
        return slug

    def discover(self) -> list[str]:
        """Import secret-free project MCP entries and expose ForceGraph's server."""
        found: list[str] = []
        for path in (self.root / ".mcp.json", self.root / ".vscode" / "mcp.json", self.root / ".cursor" / "mcp.json"):
            value = load_json(path, {})
            servers = value.get("mcpServers", value.get("servers", {})) if isinstance(value, dict) else {}
            if not isinstance(servers, dict):
                continue
            for name, profile in servers.items():
                if not isinstance(profile, dict):
                    continue
                try:
                    if profile.get("url"):
                        found.append(self.add_http(str(name), str(profile["url"])))
                    elif profile.get("command"):
                        found.append(self.add_stdio(str(name), str(profile["command"]), list(profile.get("args", []))))
                except (TypeError, ValueError):
                    continue
        bridge = ForceGraphBridge(self.root, self.cfg)
        command = bridge.command()
        if command:
            found.append(self.add_stdio("forcegraph", command[0], [
                *command[1:], "serve", "--repo", str(self.root), "--tool-profile", "compact",
            ]))
        return sorted(set(found))

    def _profile(self, name: str = "") -> tuple[str, dict[str, Any]]:
        selected = mcp_slug(name or str(self.cfg.data.get("mcp_active_server", "")))
        if selected == "forcegraph":
            command = ForceGraphBridge(self.root, self.cfg).command()
            if command:
                return selected, {
                    "transport": "stdio", "command": command[0],
                    "args": [
                        *command[1:], "serve", "--repo", str(self.root),
                        "--tool-profile", "compact",
                    ],
                }
        profile = self.profiles().get(selected)
        if not isinstance(profile, dict):
            raise ValueError(f"MCP sunucusu bulunamadı: {selected or '(seçilmedi)'}")
        return selected, profile

    def connect(self, name: str = "") -> list[dict[str, Any]]:
        selected, profile = self._profile(name)
        timeout = int(self.cfg.data.get("mcp_timeout_seconds", 45))
        candidate: MCPStdioClient | MCPHttpClient
        if profile.get("transport") == "http":
            candidate = MCPHttpClient(self._validate_http_url(str(profile.get("url", ""))), timeout)
        else:
            executable, arguments = self._validate_command(
                str(profile.get("command", "")), list(profile.get("args", [])),
            )
            candidate = MCPStdioClient([executable, *arguments], self.root, timeout)
        previous_client = self.client
        try:
            candidate.start()
            result = candidate.request("tools/list", {})
            tools = result.get("tools", []) if isinstance(result, dict) else []
            if not isinstance(tools, list):
                raise RuntimeError("MCP tools/list geçerli araç listesi döndürmedi")
            schemas: list[dict[str, Any]] = []
            names: dict[str, str] = {}
            schema_budget = 80_000
            for item in tools[:60]:
                if not isinstance(item, dict) or not str(item.get("name", "")).strip():
                    continue
                remote_name = str(item["name"])
                local_name = f"mcp__{mcp_slug(selected)[:16]}__{mcp_slug(remote_name)[:38]}"
                if local_name in names:
                    suffix = hashlib.sha256(remote_name.encode("utf-8", errors="replace")).hexdigest()[:8]
                    local_name = f"{local_name[:55]}_{suffix}"
                schema = item.get("inputSchema", {"type": "object", "properties": {}})
                if not isinstance(schema, dict):
                    schema = {"type": "object", "properties": {}}
                try:
                    encoded_schema = json.dumps(schema, ensure_ascii=False)
                except (TypeError, ValueError):
                    encoded_schema = ""
                if not encoded_schema or len(encoded_schema) > 12_000:
                    schema = {"type": "object", "properties": {}}
                    encoded_schema = json.dumps(schema)
                description = f"MCP [{selected}] · {str(item.get('description') or remote_name)[:800]}"
                cost = len(encoded_schema) + len(description)
                if cost > schema_budget:
                    break
                schemas.append({
                    "name": local_name,
                    "description": description,
                    "input_schema": schema,
                })
                names[local_name] = remote_name
                schema_budget -= cost
        except Exception:
            candidate.close()
            raise
        if previous_client is not None:
            previous_client.close()
        self.client = candidate
        self._schemas = schemas
        self._tool_names = names
        self.last_error = ""
        self.cfg.data.update({
            "mcp_enabled": True, "mcp_active_server": selected,
            "forcegraph_auto_enabled": False,
        })
        self.cfg.save()
        return schemas

    def close(self) -> None:
        if self.client is not None:
            self.client.close()
        self.client = None
        self._schemas = []
        self._tool_names = {}

    def switch_to_forcegraph(self) -> None:
        self.close()
        self.cfg.data["mcp_enabled"] = False
        self.cfg.data["forcegraph_auto_enabled"] = True
        self.cfg.save()

    def ensure_connected(self) -> bool:
        if not self.cfg.data.get("mcp_enabled", False):
            return False
        if self.client is not None:
            return True
        try:
            self.connect()
            return True
        except Exception as exc:
            self.last_error = redact_sensitive(str(exc))[:800]
            # A persisted MCP selection may become unavailable after restart.
            # Never strand the agent with both intelligence backends disabled.
            self.cfg.data["mcp_enabled"] = False
            self.cfg.data["forcegraph_auto_enabled"] = True
            self.cfg.save()
            return False

    def schemas(self) -> list[dict[str, Any]]:
        return list(self._schemas) if self.ensure_connected() else []

    def call_tool(self, local_name: str, arguments: dict[str, Any]) -> str:
        if not self.ensure_connected() or self.client is None:
            raise RuntimeError(self.last_error or "MCP bağlı değil")
        remote_name = self._tool_names.get(local_name)
        if not remote_name:
            raise ValueError(f"MCP aracı bulunamadı: {local_name}")
        result = self.client.request("tools/call", {"name": remote_name, "arguments": arguments})
        if isinstance(result, dict) and result.get("isError"):
            raise RuntimeError(self._result_text(result))
        return self._result_text(result)

    @staticmethod
    def _result_text(result: Any) -> str:
        if isinstance(result, dict) and isinstance(result.get("content"), list):
            parts = []
            for item in result["content"]:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
                else:
                    parts.append(json.dumps(item, ensure_ascii=False))
            return "\n".join(parts).strip() or json.dumps(result, ensure_ascii=False)
        return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)

    def status_text(self) -> str:
        active = str(self.cfg.data.get("mcp_active_server", "")) or "seçilmedi"
        enabled = bool(self.cfg.data.get("mcp_enabled", False))
        connected = enabled and self.ensure_connected()
        profiles = ", ".join(sorted(self.profiles())) or "yok"
        detail = f"MCP: {'bağlı' if connected else 'kapalı'} · aktif: {active} · profiller: {profiles}"
        if self.last_error:
            detail += f"\nSon hata: {self.last_error}"
        return detail

    def remove(self, name: str) -> None:
        selected = mcp_slug(name)
        profiles = copy.deepcopy(self.profiles())
        if selected not in profiles:
            raise ValueError(f"MCP sunucusu bulunamadı: {selected}")
        if selected == self.cfg.data.get("mcp_active_server"):
            self.switch_to_forcegraph()
            self.cfg.data["mcp_active_server"] = ""
        profiles.pop(selected)
        self.cfg.data["mcp_servers"] = profiles
        self.cfg.save()
