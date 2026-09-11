#!/usr/bin/env python3
"""cerrahi bölünme adım 5: queues canonical override

Canonical home: TaskQueueStore + VibeSessionStore. Stores ailesinin kuyruk uzantısı; eksik globaller host enjeksiyonuyla tamamlanır.
"""

from __future__ import annotations

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
import ctypes.wintypes
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

class TaskQueueStore:
    """Persistent ordered work queue with crash-safe task state."""

    @staticmethod
    def _pid_alive(value: Any) -> bool:
        try:
            pid = int(value)
            if pid <= 0:
                return False
            if os.name == "nt":
                # Never use os.kill(pid, 0) on Windows: CPython maps most
                # signals to TerminateProcess, so a liveness probe can kill
                # the very ForgeCode process it is checking.
                process_query_limited_information = 0x1000
                still_active = 259
                handle = ctypes.windll.kernel32.OpenProcess(
                    process_query_limited_information, False, pid
                )
                if not handle:
                    return False
                try:
                    exit_code = ctypes.wintypes.DWORD()
                    if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                        return False
                    return int(exit_code.value) == still_active
                finally:
                    ctypes.windll.kernel32.CloseHandle(handle)
            os.kill(pid, 0)
            return True
        except (OSError, TypeError, ValueError, OverflowError):
            return False

    MAX_FINISHED_TASKS = 150

    def __init__(self, root: pathlib.Path):
        self.path = root / ".forgecode" / "tasks.json"
        self.max_finished_tasks = self.MAX_FINISHED_TASKS
        raw = load_json(self.path, {"version": 2, "tasks": []})
        source = raw if isinstance(raw, list) else raw.get("tasks", []) if isinstance(raw, dict) else []
        self.tasks: list[dict[str, Any]] = []
        recovered = False
        for item in source:
            if not isinstance(item, dict) or not str(item.get("title") or item.get("text") or "").strip():
                continue
            task = dict(item)
            task["id"] = str(task.get("id") or uuid.uuid4().hex[:8])[:12]
            task["title"] = redact_sensitive(str(task.get("title") or task.get("text")).strip())[:4000]
            task["acceptance"] = redact_sensitive(str(task.get("acceptance") or "").strip())[:2500]
            task["objective"] = redact_sensitive(str(task.get("objective") or task["title"]).strip())[:4000]
            task["kind"] = str(task.get("kind") or "task")[:40]
            task["status"] = str(task.get("status") or "pending").lower()
            if task["status"] not in FLOW_FINAL_STATES | FLOW_ACTIVE_STATES:
                task["status"] = "pending"
            if task["status"] == "running" and not self._pid_alive(task.get("owner_pid")):
                task["status"] = "paused"
                task["error"] = "ForgeCode kapandı veya görev kesildi; güvenli biçimde duraklatıldı."
                task["owner_pid"] = 0
                recovered = True
            task.setdefault("flow_id", "manual")
            task.setdefault("created_at", dt.datetime.now().isoformat(timespec="seconds"))
            task.setdefault("attempts", 0)
            task.setdefault("rounds", 0)
            task.setdefault("repair_attempts", 0)
            task.setdefault("changed_files", [])
            task.setdefault("summary", "")
            task.setdefault("missing_evidence", [])
            task.setdefault("owner_pid", 0)
            self.tasks.append(task)
        if recovered:
            self.save()

    def save(self) -> None:
        finished_indexes = [i for i, task in enumerate(self.tasks) if task.get("status") in FLOW_FINAL_STATES]
        overflow = len(finished_indexes) - max(1, int(self.max_finished_tasks))
        if overflow > 0:
            oldest = set(sorted(finished_indexes, key=lambda i: str(self.tasks[i].get("created_at") or ""))[:overflow])
            self.tasks = [task for index, task in enumerate(self.tasks) if index not in oldest]
        atomic_json(self.path, {"version": 2, "updated_at": dt.datetime.now().isoformat(timespec="seconds"), "tasks": self.tasks})

    def add(self, title: str, acceptance: str = "", flow_id: str = "manual", objective: str = "", kind: str = "task") -> dict[str, Any]:
        clean_title = str(title).strip()
        if not clean_title:
            raise ValueError("Görev metni boş olamaz")
        task = {
            "id": uuid.uuid4().hex[:8],
            "flow_id": str(flow_id or "manual")[:20],
            "title": redact_sensitive(clean_title)[:4000],
            "acceptance": redact_sensitive(str(acceptance).strip())[:2500],
            "objective": redact_sensitive(str(objective).strip() or clean_title)[:4000],
            "kind": str(kind or "task")[:40],
            "status": "pending",
            "created_at": dt.datetime.now().isoformat(timespec="seconds"),
            "started_at": "",
            "finished_at": "",
            "attempts": 0,
            "rounds": 0,
            "repair_attempts": 0,
            "changed_files": [],
            "summary": "",
            "confidence": 0.0,
            "missing_evidence": [],
            "error": "",
            "owner_pid": 0,
        }
        self.tasks.append(task)
        self.save()
        return task

    def add_many(self, items: list[Any], flow_id: str | None = None, objective: str = "") -> list[dict[str, Any]]:
        if not isinstance(items, list) or not items:
            raise ValueError("En az bir görev gerekli")
        selected_flow = flow_id or uuid.uuid4().hex[:8]
        added = []
        for item in items:
            if isinstance(item, dict):
                title = item.get("title") or item.get("task") or item.get("text") or ""
                acceptance = item.get("acceptance") or item.get("done_when") or ""
            else:
                title, acceptance = str(item), ""
            added.append(self.add(str(title), str(acceptance), selected_flow, objective))
        return added

    def find(self, wanted: str = "") -> dict[str, Any] | None:
        value = str(wanted).strip()
        for index, task in enumerate(self.tasks, 1):
            if not value or value == str(index) or value == str(task.get("id")):
                return task
        return None

    def first_unresolved(self, flow_id: str = "") -> dict[str, Any] | None:
        selected_flow = str(flow_id).strip()
        return next((
            task for task in self.tasks
            if task.get("status") not in FLOW_FINAL_STATES
            and (not selected_flow or str(task.get("flow_id", "")) == selected_flow)
        ), None)

    def update(self, task: dict[str, Any], status: str, **fields: Any) -> None:
        if status not in FLOW_FINAL_STATES | FLOW_ACTIVE_STATES:
            raise ValueError(f"Geçersiz görev durumu: {status}")
        task["status"] = status
        task["owner_pid"] = os.getpid() if status == "running" else 0
        task.update(fields)
        self.save()

    def retry(self, wanted: str = "") -> dict[str, Any] | None:
        task = self.find(wanted) if wanted else self.first_unresolved()
        if task is None or task.get("status") in FLOW_FINAL_STATES:
            return None
        self.update(task, "pending", error="", missing_evidence=[], finished_at="")
        return task

    def skip(self, wanted: str = "") -> dict[str, Any] | None:
        task = self.find(wanted) if wanted else self.first_unresolved()
        if task is None or task.get("status") in FLOW_FINAL_STATES:
            return None
        self.update(task, "skipped", finished_at=dt.datetime.now().isoformat(timespec="seconds"))
        return task

    def clear_finished(self) -> int:
        before = len(self.tasks)
        self.tasks = [task for task in self.tasks if task.get("status") not in FLOW_FINAL_STATES]
        removed = before - len(self.tasks)
        if removed:
            self.save()
        return removed

    def collapse_unresolved_flow(self, current: dict[str, Any], objective: str) -> int:
        """Collapse an over-planned cohesive objective without losing completed work."""
        flow_id = str(current.get("flow_id", ""))
        removable = [
            task for task in self.tasks
            if task is not current
            and str(task.get("flow_id", "")) == flow_id
            and task.get("status") not in FLOW_FINAL_STATES
        ]
        if not removable:
            return 0
        self.tasks = [task for task in self.tasks if task not in removable]
        current["title"] = redact_sensitive(str(objective).strip())[:4000]
        current["acceptance"] = (
            "The complete root objective is implemented as one cohesive change and deterministic verification passes."
        )
        current["objective"] = redact_sensitive(str(objective).strip())[:4000]
        current["status"] = "pending"
        current["owner_pid"] = 0
        current["error"] = ""
        current["missing_evidence"] = []
        self.save()
        return len(removable)

    def counts(self) -> dict[str, int]:
        counts = collections.Counter(str(task.get("status", "pending")) for task in self.tasks)
        return {name: int(counts.get(name, 0)) for name in ("pending", "running", "paused", "failed", "completed", "skipped")}

    def skip_unresolved(self, reason: str, except_flow_id: str = "") -> int:
        """Archive stale work before an explicitly requested autonomous objective."""
        changed = 0
        finished = dt.datetime.now().isoformat(timespec="seconds")
        for task in self.tasks:
            if task.get("status") in FLOW_FINAL_STATES:
                continue
            if except_flow_id and str(task.get("flow_id", "")) == except_flow_id:
                continue
            task.update({
                "status": "skipped",
                "owner_pid": 0,
                "finished_at": finished,
                "error": redact_sensitive(str(reason))[:1200],
            })
            changed += 1
        if changed:
            self.save()
        return changed

    def flow_tasks(self, flow_id: str) -> list[dict[str, Any]]:
        selected = str(flow_id)
        return [task for task in self.tasks if str(task.get("flow_id", "")) == selected]

    def completed_context(self, before_task: dict[str, Any], limit: int = 3, char_budget: int = 1800) -> str:
        try:
            stop = self.tasks.index(before_task)
        except ValueError:
            stop = len(self.tasks)
        rows = []
        for task in self.tasks[:stop]:
            if task.get("status") != "completed":
                continue
            summary = redact_sensitive(str(task.get("summary") or "").strip().replace("\n", " "))[:260]
            files = ", ".join(str(name) for name in task.get("changed_files", [])[:6]) or "none"
            rows.append(f"- {task.get('title', '')[:100]} | files: {files[:360]} | result: {summary}")
        result = "\n".join(rows[-max(1, limit):]) or "- No earlier completed queue task."
        budget = max(400, int(char_budget))
        if len(result) > budget:
            result = result[:budget].rsplit("\n", 1)[0] + "\n- … earlier details omitted (token budget)"
        return result


class VibeSessionStore:
    """Crash-safe control plane for one long-running autonomous build."""

    def __init__(self, root: pathlib.Path):
        self.root = root.resolve()
        self.path = self.root / ".forgecode" / "vibe-session.json"
        raw = load_json(self.path, {})
        self.state: dict[str, Any] = raw if isinstance(raw, dict) else {}
        if (
            self.state.get("status") in {"planning", "running", "reviewing"}
            and not TaskQueueStore._pid_alive(self.state.get("owner_pid"))
        ):
            self.state.update({
                "status": "paused",
                "owner_pid": 0,
                "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
                "last_error": "ForgeCode stopped unexpectedly; the latest checkpoint is ready for /vibe resume.",
            })
            self.save()

    def save(self) -> None:
        if self.state:
            atomic_json(self.path, self.state)

    def start(self, objective: str, max_hours: int) -> dict[str, Any]:
        clean = redact_sensitive(str(objective).strip())[:12000]
        if not clean:
            raise ValueError("VibeCode objective cannot be empty")
        now = dt.datetime.now().isoformat(timespec="seconds")
        self.state = {
            "version": 1,
            "id": uuid.uuid4().hex[:10],
            "flow_id": "",
            "objective": clean,
            "status": "planning",
            "created_at": now,
            "updated_at": now,
            "started_at": now,
            "finished_at": "",
            "deadline_epoch": time.time() + max(1, int(max_hours)) * 3600,
            "owner_pid": os.getpid(),
            "review_cycle": 0,
            "failure_streak": 0,
            "retries": 0,
            "completed_tasks": 0,
            "deferred_tasks": [],
            "changed_files": [],
            "checks": [],
            "last_error": "",
            "last_summary": "",
        }
        self.save()
        return self.state

    def update(self, **fields: Any) -> None:
        if not self.state:
            raise ValueError("No VibeCode session exists")
        self.state.update(fields)
        self.state["updated_at"] = dt.datetime.now().isoformat(timespec="seconds")
        self.save()

    def mark_running(self) -> None:
        self.update(status="running", owner_pid=os.getpid(), last_error="")

    def pause(self, reason: str) -> None:
        if self.state:
            self.update(status="paused", owner_pid=0, last_error=redact_sensitive(str(reason))[:2000])

    def complete(self, summary: str, changed_files: list[str], checks: list[str]) -> None:
        self.update(
            status="completed",
            owner_pid=0,
            finished_at=dt.datetime.now().isoformat(timespec="seconds"),
            last_summary=redact_sensitive(str(summary))[:8000],
            changed_files=list(dict.fromkeys(str(item) for item in changed_files))[:500],
            checks=[redact_sensitive(str(item))[:2000] for item in checks[-50:]],
            last_error="",
        )

    def stop(self, reason: str = "Stopped by user") -> None:
        if self.state:
            self.update(
                status="stopped",
                owner_pid=0,
                finished_at=dt.datetime.now().isoformat(timespec="seconds"),
                last_error=redact_sensitive(reason)[:2000],
            )

    def resumable(self) -> bool:
        return bool(
            self.state
            and self.state.get("status") in {"planning", "running", "reviewing", "paused", "blocked"}
        )

    def remaining_seconds(self) -> float:
        return max(0.0, float(self.state.get("deadline_epoch", 0.0)) - time.time())

    def status_text(self, queue: TaskQueueStore | None = None) -> str:
        if not self.state:
            return "VibeCode: no session"
        if queue is not None and self.state.get("flow_id"):
            flow_tasks = queue.flow_tasks(str(self.state["flow_id"]))
            raw_counts = collections.Counter(str(task.get("status", "pending")) for task in flow_tasks)
            counts = {
                name: int(raw_counts.get(name, 0))
                for name in ("pending", "running", "paused", "failed", "completed", "skipped")
            }
        else:
            counts = queue.counts() if queue is not None else {}
        remaining = int(self.remaining_seconds())
        hours, remainder = divmod(remaining, 3600)
        minutes = remainder // 60
        return (
            f"VibeCode: {self.state.get('status', 'unknown')} · id {self.state.get('id', '-')}\n"
            f"Objective: {str(self.state.get('objective', ''))[:500]}\n"
            f"Progress: {self.state.get('completed_tasks', 0)} completed · "
            f"{counts.get('pending', 0)} pending · {counts.get('failed', 0)} failed · "
            f"review {self.state.get('review_cycle', 0)}\n"
            f"Time remaining: {hours}h {minutes}m · retries {self.state.get('retries', 0)}\n"
            f"Last checkpoint: {self.state.get('updated_at', '-')}"
            + (f"\nLast issue: {self.state.get('last_error')}" if self.state.get("last_error") else "")
        )
