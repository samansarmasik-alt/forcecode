#!/usr/bin/env python3
"""ForceCode context/flows — goals, forceflow, execution kernel, fleet. Depends on base/config/stores/sandbox."""

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

from forcecode_base import SteeringInterrupt, app_home, atomic_json, atomic_text, load_json, normalize_subagent_role, redact_sensitive
from forcecode_config import Config
from forcecode_stores import SessionStore
from forcecode_sandbox import ForceSandboxManager

def _fc(name):
    import forcecode as _m
    return getattr(_m, name)


FLOW_FINAL_STATES = {"completed", "skipped"}


FLOW_ACTIVE_STATES = {"pending", "running", "paused", "failed"}


_PROJECT_CONTEXT_CACHE: dict[tuple[str, str, bool], tuple[str, float]] = {}


_THINKING_MARKERS = ("yapiyorum", "yapıyor", "inceliyorum", "düşünüyorum", "dusunuyorum", "çözüyorum", "cozuyorum", "hata yakaland", "onarıyorum", "onariyorum")


_THINKING_STRIP_RE = re.compile(r"^\s*(hata yakaland.*?onar[\u0131i]yorum|hata yakaland.*|onar[\u0131i]yorum.*|yap[i\u0131]yorum.*|inceliyorum.*|d[\u00fc\u0131]s[\u00fc\u0131]n[\u00fc\u0131]yorum.*|\u00e7[\u00f6o]z[\u00fc\u0131]yorum.*)[\r\n]+", re.IGNORECASE | re.DOTALL)


_GENERIC_THINKING_LINE_RE = re.compile(r"^\s*(yap[i\u0131]yorum|inceliyorum|d[\u00fc\u0131]s[\u00fc\u0131]n[\u00fc\u0131]yorum|\u00e7[\u00f6o]z[\u00fc\u0131]yorum|onar[\u0131i]yorum)\b[^\r\n]*[\r\n]+", re.IGNORECASE)


_ACTION_INTENT_RE = re.compile(
    r"("
    r"bak[iı]yorum|bakaca[gğ][iı]m|bakal[ıi]m"
    r"|inceliyorum|inceleyece[gğ]im|inceleyelim"
    r"|kontrol ediyorum|kontrol edece[gğ]im|kontrol edelim"
    r"|okuyorum"
    r"|ara[sş]t[iı]r[iı]yorum|ara[sş]t[iı]raca[gğ][iı]m"
    r"|a[cç][iı]yorum|a[cç]aca[gğ][iı]m"
    r"|deniyorum|deneyece[gğ]im"
    r"|let me (check|look|read|inspect|see|dig)"
    r"|i('| a)?m (checking|looking|reading|inspecting)"
    r"|i'?ll (check|look|read|inspect|dig)"
    r"|going to (check|look|read|inspect)"
    r")",
    re.IGNORECASE,
)


FORCE_CONTEXT_LAYERS = {"user", "project", "session"}


FORCE_CONTEXT_SCHEMA = 2


AI_EDITABLE_SETTINGS = {
    "max_tokens", "input_budget_tokens", "temperature", "timeout_seconds", "streaming_enabled",
    "first_response_timeout_seconds", "stream_idle_timeout_seconds",
    "request_total_timeout_seconds", "retry_budget_seconds",
    "preflight_timeout_seconds", "stall_first_response_seconds",
    "stall_stream_idle_seconds", "stall_retry_attempts",
    "retry_attempts", "retry_backoff_seconds", "max_tool_output_chars",
    "web_search_mode", "web_max_results", "thinking_mode", "thinking_budget_tokens",
    "efficiency_mode", "power_mode", "web_project_mode", "work_mode",
    "auto_subagents", "subagent_timeout_seconds", "history_context_turns",
    "history_context_chars", "team_parallel", "team_max_workers",
}


class GoalStore:
    def __init__(self, root: pathlib.Path):
        self.path = root / ".forcecode" / "goals.json"
        self.goals: list[dict[str, Any]] = load_json(self.path, [])

    def save(self) -> None:
        atomic_json(self.path, self.goals)

    def add(self, text: str) -> dict[str, Any]:
        goal = {"id": uuid.uuid4().hex[:6], "text": text, "done": False, "created": dt.datetime.now().isoformat(timespec="seconds")}
        self.goals.append(goal)
        self.save()
        return goal

    def complete(self, goal_id: str) -> bool:
        for goal in self.goals:
            if goal["id"] == goal_id or str(self.goals.index(goal) + 1) == goal_id:
                goal["done"] = True
                self.save()
                return True
        return False

    def find(self, goal_id: str = "") -> dict[str, Any] | None:
        """Resolve an active goal by id/index, or return the oldest active one."""
        wanted = str(goal_id).strip()
        for index, goal in enumerate(self.goals, 1):
            if goal.get("done"):
                continue
            if not wanted or str(goal.get("id")) == wanted or str(index) == wanted:
                return goal
        return None

    def active_text(self) -> str:
        active = [f"- [{g['id']}] {g['text']}" for g in self.goals if not g["done"]]
        return "\n".join(active) or "- No active goals"


@dataclass
class GoalRunResult:
    completed: bool
    rounds: int
    answer: str
    changed_files: list[str]


def goal_answer_is_incomplete(answer: str) -> bool:
    normalized = answer.strip().lower()
    return (
        normalized.startswith("görev tamamlanmadı")
        or normalized.startswith("görev tamamlanamadı")
        or "[azami ajan adımı sınırına ulaşıldı.]" in normalized
        or normalized.startswith("api hatası:")
    )


def run_goal_until_complete(
    agent: "Agent",
    goals: GoalStore,
    goal: dict[str, Any],
    max_rounds: int,
    on_tool: Callable[[str, dict[str, Any]], None] | None = None,
) -> GoalRunResult:
    objective = str(goal["text"])
    baseline = agent.tools.snapshot()
    requires_artifacts = agent._requires_artifacts(objective) and agent.cfg.data.get("work_mode") != "plan"
    last_answer = ""
    changed_files: list[str] = []
    agent._system_cache = ""
    rounds = max(1, int(max_rounds))
    for round_number in range(1, rounds + 1):
        agent._emit_activity(f"Hedef turu {round_number}/{rounds}: uygulanıyor")
        if round_number == 1:
            prompt = objective
        else:
            prompt = (
                f"ACTIVE GOAL: {objective}\n"
                "The previous round did not satisfy the verified goal. Continue from the CURRENT project state. "
                "Inspect what already exists, fix every remaining issue, use tools for real changes, and verify the outcome. "
                "Do not restart or merely describe a plan.\n"
                f"Previous result: {last_answer[-1200:]}"
            )
        last_answer = agent.ask(prompt, on_tool=on_tool)
        changed_files = agent.tools.changed_since(baseline)
        completed = not goal_answer_is_incomplete(last_answer) and (bool(changed_files) if requires_artifacts else bool(last_answer.strip()))
        if completed:
            goals.complete(str(goal["id"]))
            agent._system_cache = ""
            agent._emit_activity(f"Hedef doğrulandı: {goal['id']}")
            return GoalRunResult(True, round_number, last_answer, changed_files)
        agent._emit_activity(f"Hedef henüz tamamlanmadı: tur {round_number}/{rounds}")
    return GoalRunResult(False, rounds, last_answer, changed_files)


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
                # the very ForceCode process it is checking.
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
        self.path = root / ".forcecode" / "tasks.json"
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
                task["error"] = "ForceCode kapandı veya görev kesildi; güvenli biçimde duraklatıldı."
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
        self.path = self.root / ".forcecode" / "vibe-session.json"
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
                "last_error": "ForceCode stopped unexpectedly; the latest checkpoint is ready for /vibe resume.",
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


@dataclass
class ForceFlowTaskResult:
    task_id: str
    completed: bool
    rounds: int
    answer: str
    changed_files: list[str]
    missing_evidence: list[str]
    error: str = ""


@dataclass
class ForceFlowRunResult:
    completed: bool
    processed: list[ForceFlowTaskResult]
    blocked_task_id: str = ""


@dataclass
class VibeReview:
    passed: bool
    score: int
    summary: str
    gaps: list[dict[str, str]]


@dataclass
class VibeRunResult:
    completed: bool
    summary: str
    changed_files: list[str]
    checks: list[str]


def parse_forceflow_plan(raw: str, max_tasks: int = 12) -> list[dict[str, str]]:
    """Parse compact JSON first, then conservative numbered/bullet text."""
    text = str(raw).strip()
    parsed: Any = None
    candidates = [text]
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        candidates.insert(0, fenced.group(1).strip())
    object_match = re.search(r"\{.*\}", text, re.DOTALL)
    array_match = re.search(r"\[.*\]", text, re.DOTALL)
    if object_match:
        candidates.append(object_match.group(0))
    if array_match:
        candidates.append(array_match.group(0))
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            break
        except (json.JSONDecodeError, TypeError):
            continue
    items: Any = parsed.get("tasks", []) if isinstance(parsed, dict) else parsed
    if not isinstance(items, list):
        items = []
    result: list[dict[str, str]] = []
    for item in items:
        if isinstance(item, dict):
            title = str(item.get("title") or item.get("task") or item.get("text") or "").strip()
            acceptance = str(item.get("acceptance") or item.get("done_when") or "").strip()
        else:
            title, acceptance = str(item).strip(), ""
        if title:
            result.append({"title": title[:4000], "acceptance": acceptance[:2500]})
        if len(result) >= max(1, max_tasks):
            break
    if result:
        return result
    for line in text.splitlines():
        cleaned = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).strip()
        if not cleaned or cleaned == line.strip() and not re.match(r"^\s*(?:[-*•]|\d+[.)])", line):
            continue
        if len(cleaned) >= 4:
            result.append({"title": cleaned[:4000], "acceptance": ""})
        if len(result) >= max(1, max_tasks):
            break
    return result


def create_forceflow_plan(agent: "Agent", objective: str, max_tasks: int) -> list[dict[str, str]]:
    system = (
        "You are ForceFlow's task planner. Split one software objective into the smallest useful ordered tasks. "
        "Each task must produce a testable result, depend only on earlier tasks, and avoid duplicate setup or reporting work. "
        "If splitting would add no value, return exactly one task; never invent filler tasks. "
        "Do not reveal chain-of-thought. Return ONLY compact JSON: "
        '{"tasks":[{"title":"imperative task","acceptance":"objective completion evidence"}]}.'
    )
    project_map = "\n".join(sorted(agent.tools.snapshot())[:100])[:3000] or "(empty project)"
    reply = agent._standalone_request(
        "ForceFlow planlayıcı",
        system,
        f"Maximum tasks: {max_tasks}\nCompact project map:\n{project_map}\n\nSoftware objective:\n{objective}",
        min(1800, max(600, int(agent.cfg.data.get("max_tokens", 8192)))),
    )
    agent.session_usage.add(reply.usage)
    agent.session_cost_usd += reply.usage.cost(agent.cfg)
    agent.usage_store.record(agent.cfg.data["provider"], agent.cfg.data["model"], reply.usage, cost_usd=reply.usage.cost(agent.cfg))
    tasks = parse_forceflow_plan(reply.text, max_tasks)
    if not tasks:
        tasks = [{"title": objective.strip(), "acceptance": "The requested outcome is implemented and verified."}]
    return tasks


def _forceflow_artifact_check(agent: "Agent", changed_files: list[str]) -> tuple[bool, str]:
    existing: list[str] = []
    removed: list[str] = []
    for name in changed_files:
        try:
            target = agent.tools.safe_file_path(name)
        except ValueError:
            continue
        if target.is_file():
            existing.append(name)
        else:
            removed.append(name)
    if existing:
        # Tool calls are intentionally bounded to 50 paths. Builds can create
        # hundreds of binary artifacts, so verify in bounded batches rather
        # than crashing the complete ForceFlow task.
        for offset in range(0, len(existing), 50):
            try:
                result = agent.tools.tool_verify_artifacts(existing[offset:offset + 50])
            except (OSError, ValueError) as exc:
                return False, f"Artifact verification failed: {exc}"
            if not result.startswith("OK:"):
                return False, result
    if not existing and not removed:
        return False, "No changed artifact could be verified."
    evidence = []
    if existing:
        evidence.append(f"{len(existing)} non-empty text/binary artifact")
    if removed:
        evidence.append(f"{len(removed)} removed path")
    return True, ", ".join(evidence)


def forceflow_framework_project(agent: "Agent") -> bool:
    """Recognize frontend frameworks that need their native build gate, not static HTML rules."""
    root = agent.tools.root
    package = root / "package.json"
    if package.is_file():
        try:
            raw = json.loads(package.read_text(encoding="utf-8"))
            names = set(raw.get("dependencies", {})) | set(raw.get("devDependencies", {}))
            scripts = " ".join(str(value) for value in raw.get("scripts", {}).values()).casefold()
            if names & {"next", "react", "react-dom", "vue", "nuxt", "svelte", "@sveltejs/kit", "vite", "@angular/core"}:
                return True
            if any(marker in scripts for marker in ("next ", "vite", "nuxt", "svelte-kit", "ng build")):
                return True
        except (OSError, json.JSONDecodeError, AttributeError, TypeError):
            pass
    return any(
        pathlib.PurePosixPath(name).suffix.casefold() in {".jsx", ".tsx", ".vue", ".svelte"}
        for name in agent.tools.snapshot()
    )


def forceflow_web_policy(agent: "Agent", objective: str) -> tuple[bool, bool, str]:
    """Derive one stable website contract from the user's root objective."""
    lowered = str(objective).casefold()
    web_request = any(marker in lowered for marker in (
        "web sitesi", "website", "landing page", "html site", "site yap", "site oluştur", "site olustur",
        "web page", "webpage",
    ))
    if not web_request:
        return False, False, ""
    explicit_single = any(marker in lowered for marker in (
        "tek html", "tek dosya", "single html", "single file", "one html", "one file",
    )) or agent.cfg.data.get("web_project_mode") == "single"
    framework_project = forceflow_framework_project(agent)
    require_multifile = not explicit_single and not framework_project
    contract = (
        "WEBSITE QUALITY CONTRACT: preserve the root objective across every subtask. Use real, coherent content; "
        "semantic HTML; a mobile viewport; accessible controls and image alt attributes; responsive layout; "
        "a consistent visual system; working local asset links; and no lorem/placeholder output."
    )
    if framework_project:
        contract += " Preserve the detected frontend framework and run its native test/build; do not replace it with a static scaffold."
    else:
        contract += " Inspect the rendered structure and run web_quality_check before claiming completion."
        if require_multifile:
            contract += " Keep HTML, responsive CSS, and functional JavaScript in linked separate files."
    return True, require_multifile, contract


def run_forceflow_task(
    agent: "Agent",
    store: TaskQueueStore,
    task: dict[str, Any],
    max_rounds: int,
    on_tool: Callable[[str, dict[str, Any]], None] | None = None,
    force_web: bool = False,
    repair_rounds: int = 0,
) -> ForceFlowTaskResult:
    title = str(task.get("title", "")).strip()
    acceptance = str(task.get("acceptance", "")).strip()
    objective = str(task.get("objective") or title).strip()
    full_intent = "\n".join(item for item in (objective, title, acceptance) if item)
    baseline = agent.tools.snapshot()
    requires_artifacts = agent._requires_artifacts(full_intent) and agent.cfg.data.get("work_mode") != "plan"
    is_web, require_multifile, web_contract = forceflow_web_policy(agent, objective)
    quality_repair = str(task.get("kind", "")) == "quality_repair"
    started = dt.datetime.now().isoformat(timespec="seconds")
    store.update(
        task,
        "running",
        started_at=started,
        finished_at="",
        attempts=int(task.get("attempts", 0)) + 1,
        error="",
        missing_evidence=[],
    )
    primary_rounds = max(1, int(max_rounds))
    recovery_rounds = max(0, int(repair_rounds))
    rounds = primary_rounds + recovery_rounds
    last_answer = ""
    changed_files: list[str] = []
    missing: list[str] = []
    prior_context = store.completed_context(task)
    for round_number in range(1, rounds + 1):
        repairing = round_number > primary_rounds
        phase = "otomatik onarım" if repairing else "uygulama"
        agent._emit_activity(f"ForceFlow {task['id']}: {phase} {round_number}/{rounds}")
        if round_number == 1:
            prompt = (
                "FORCEFLOW CURRENT TASK — complete only this queue item. Do not start any later task.\n"
                f"ROOT OBJECTIVE: {objective}\n"
                f"TASK: {title}\n"
                f"ACCEPTANCE: {acceptance or 'Implement the requested outcome and produce deterministic verification evidence.'}\n"
                f"EARLIER COMPLETED TASKS:\n{prior_context}\n\n"
                + (web_contract + "\n" if web_contract else "") +
                "Inspect the current project state, make real changes when required, run the most relevant focused check, "
                "and report a concise verified result. If verification fails, fix it instead of claiming completion."
            )
        elif repairing:
            prompt = (
                "FORCEFLOW AUTONOMOUS REPAIR — the verified task is still incomplete. Diagnose before editing and use a "
                "different approach when the previous one failed. Continue from current files; never discard valid work.\n"
                f"ROOT OBJECTIVE: {objective}\nTASK: {title}\n"
                f"ACCEPTANCE: {acceptance or 'Verified requested outcome.'}\n"
                f"FAILED EVIDENCE: {'; '.join(missing) or 'completion was not proven'}\n"
                f"PREVIOUS RESULT OR ERROR: {last_answer[-1800:]}\n"
                + (web_contract + "\n" if web_contract else "") +
                "Inspect diagnostics and artifacts, identify the root cause, repair it, then rerun the focused deterministic check. "
                "Do not ask the user unless existing safety policy requires approval."
            )
        else:
            prompt = (
                "FORCEFLOW RETRY — continue only the current task from the existing project state.\n"
                f"ROOT OBJECTIVE: {objective}\n"
                f"TASK: {title}\nACCEPTANCE: {acceptance or 'Verified requested outcome.'}\n"
                f"MISSING EVIDENCE: {'; '.join(missing) or 'completion was not proven'}\n"
                f"PREVIOUS RESULT: {last_answer[-1600:]}\n"
                + (web_contract + "\n" if web_contract else "") +
                "Inspect what already changed, fix only what remains, and obtain the missing verification. Do not restart the project."
            )
        previous_forceflow_state = agent._forceflow_active
        agent._forceflow_active = True
        try:
            if force_web:
                last_answer = agent.ask(prompt, on_tool=on_tool, force_web=True)
            else:
                last_answer = agent.ask(prompt, on_tool=on_tool)
        except ApiError as exc:
            safe_error = redact_sensitive(str(exc))[:1200]
            last_answer = f"API error during ForceFlow: {safe_error}"
            missing = ["API request failed before verified completion: " + safe_error]
            store.update(
                task,
                "running",
                rounds=round_number,
                repair_attempts=max(0, round_number - primary_rounds),
                error=safe_error,
                missing_evidence=missing,
            )
            agent.record_runtime_error("api_error", exc, {"source": "forceflow_recovery", "task_id": task.get("id")})
            if round_number < rounds:
                agent._emit_activity(f"ForceFlow {task['id']}: API hatası kaydedildi, otomatik yeniden denenecek")
                time.sleep(min(2.0, max(0.0, float(agent.cfg.data.get("retry_backoff_seconds", 0.5)))))
                continue
            break
        finally:
            agent._forceflow_active = previous_forceflow_state
        changed_files = agent.tools.changed_since(baseline)
        report = dict(agent.last_execution_report or {})
        missing = [str(item) for item in report.get("missing_evidence", [])]
        if not requires_artifacts and not report.get("successful_tools"):
            missing.append("ForceFlow task has no tool-backed project evidence")
        artifact_ok = True
        artifact_note = "not required"
        if requires_artifacts:
            artifact_ok, artifact_note = _forceflow_artifact_check(agent, changed_files)
            if changed_files and artifact_ok:
                missing = [
                    item for item in missing
                    if item not in {"no project artifact was created or changed", "changed artifacts were not inspected after mutation"}
                ]
            elif not changed_files:
                missing.append("ForceFlow observed no project change for this task")
            elif not artifact_ok:
                missing.append(artifact_note)
        needs_check = "no focused post-change check succeeded" in missing
        if requires_artifacts and changed_files and artifact_ok and needs_check:
            check_result = agent.tools.tool_test_project(timeout_seconds=int(agent.cfg.data.get("timeout_seconds", 100)))
            agent.session_store.log_event(
                "forceflow_verify",
                "ForceFlow automatic project check",
                {"task_id": task["id"], "result": redact_sensitive(check_result[:1200])},
            )
            if check_result.startswith("exit_code=0") or check_result.startswith("OK:"):
                missing = [item for item in missing if item != "no focused post-change check succeeded"]
                artifact_note += "; automatic project check passed"
            elif not check_result.startswith("SKIP:"):
                missing.append("automatic project check failed: " + check_result[:500])
        quality_note = ""
        if quality_repair and is_web:
            quality_report = agent.tools.web_quality_report(require_multifile)
            quality_note = quality_report.render()
            agent.session_store.log_event(
                "forceflow_quality",
                "Deterministic website quality gate",
                {"task_id": task["id"], "score": quality_report.score, "passed": quality_report.passed,
                 "blockers": quality_report.blockers[:20]},
            )
            if not quality_report.passed:
                missing.append("website quality gate: " + "; ".join(quality_report.blockers[:12]))
        missing = list(dict.fromkeys(redact_sensitive(item)[:1200] for item in missing if item))
        completed = bool(last_answer.strip()) and not goal_answer_is_incomplete(last_answer) and not missing
        if requires_artifacts:
            completed = completed and bool(changed_files) and artifact_ok
        if completed:
            finished = dt.datetime.now().isoformat(timespec="seconds")
            store.update(
                task,
                "completed",
                finished_at=finished,
                rounds=round_number,
                repair_attempts=max(0, round_number - primary_rounds),
                changed_files=changed_files[:100],
                summary=redact_sensitive(last_answer.strip())[-2000:],
                confidence=float(report.get("confidence", 0.0)),
                missing_evidence=[],
                evidence=(artifact_note + (f"; web quality {quality_note.splitlines()[0]}" if quality_note else "")),
            )
            agent.session_store.log_event(
                "forceflow_task",
                "Sequential task completed and verified",
                {"task_id": task["id"], "round": round_number, "changed_files": changed_files[:100]},
            )
            return ForceFlowTaskResult(str(task["id"]), True, round_number, last_answer, changed_files, [])
        store.update(
            task,
            "running",
            rounds=round_number,
            repair_attempts=max(0, round_number - primary_rounds),
            changed_files=changed_files[:100],
            summary=redact_sensitive(last_answer.strip())[-2000:],
            confidence=float(report.get("confidence", 0.0)),
            missing_evidence=missing,
        )
    error = redact_sensitive("; ".join(missing)) or "Görev tamamlanmış olduğunu kanıtlayamadı."
    store.update(
        task,
        "failed",
        finished_at=dt.datetime.now().isoformat(timespec="seconds"),
        rounds=rounds,
        repair_attempts=recovery_rounds,
        error=error,
        missing_evidence=missing,
    )
    return ForceFlowTaskResult(str(task["id"]), False, rounds, last_answer, changed_files, missing, error)


def run_forceflow_queue(
    agent: "Agent",
    store: TaskQueueStore,
    max_rounds: int,
    on_tool: Callable[[str, dict[str, Any]], None] | None = None,
    force_web: bool = False,
    repair_rounds: int = 0,
    max_tasks_to_process: int = 0,
    after_task: Callable[[ForceFlowTaskResult], None] | None = None,
    flow_id: str = "",
) -> ForceFlowRunResult:
    processed: list[ForceFlowTaskResult] = []
    while True:
        task = store.first_unresolved(flow_id)
        if task is None:
            return ForceFlowRunResult(True, processed)
        status = str(task.get("status", "pending"))
        if status == "paused":
            store.update(task, "pending", error="")
        elif status == "running":
            return ForceFlowRunResult(False, processed, str(task.get("id", "")))
        elif status == "failed":
            return ForceFlowRunResult(False, processed, str(task.get("id", "")))
        try:
            result = run_forceflow_task(agent, store, task, max_rounds, on_tool, force_web, repair_rounds)
        except KeyboardInterrupt:
            store.update(
                task,
                "paused",
                error="Kullanıcı Ctrl+C ile durdurdu; görev ilerlemesi korunuyor.",
                finished_at="",
            )
            raise
        except SteeringInterrupt:
            store.update(
                task,
                "paused",
                error="Canlı kullanıcı yönlendirmesi alındı; görev yeni talimatla otomatik sürdürülecek.",
                finished_at="",
            )
            raise
        except Exception as exc:
            store.update(
                task,
                "failed",
                error=f"{type(exc).__name__}: {redact_sensitive(str(exc))[:1200]}",
                finished_at=dt.datetime.now().isoformat(timespec="seconds"),
            )
            if isinstance(exc, ApiError):
                agent.record_runtime_error("api_error", exc, {"source": "forceflow", "task_id": task.get("id")})
            return ForceFlowRunResult(False, processed, str(task.get("id", "")))
        processed.append(result)
        if after_task is not None:
            after_task(result)
        if not result.completed:
            return ForceFlowRunResult(False, processed, result.task_id)
        if max_tasks_to_process > 0 and len(processed) >= max_tasks_to_process:
            return ForceFlowRunResult(store.first_unresolved(flow_id) is None, processed)


def _diff_label(path: pathlib.Path, root: pathlib.Path, baseline: dict[str, tuple[int, int]] | None, seen: set[str]) -> str:
    rel = path.relative_to(root).as_posix()
    if baseline is None:
        return rel
    if rel not in baseline:
        return rel + " [new]"
    # baseline tracks changed_since; caller supplies snapshot — mark if changed
    return rel + (" [changed]" if rel in seen else "")


def project_context(root: pathlib.Path, efficiency: str = "off", sandboxed: bool = False, baseline: dict[str, tuple[int, int]] | None = None, changed_only: set[str] | None = None) -> str:
    """Build a token-budgeted project snapshot.

    verim=max: only AGENTS.md + pyproject/package + diff-filtered compact map (changed + essentials).
    Large jobs reuse the cached prefix; only the diff file list is recomputed.
    This is the main lever for >70% token drop vs the old full-map baseline.
    """
    # Disk I/O cache for unchanged state within one turn (cheap, avoids duplicate rglob)
    cache_key = (str(root), efficiency, sandboxed)
    # Baseline-driven diff is not cacheable the same way
    use_cache = baseline is None and changed_only is None
    if use_cache and cache_key in _PROJECT_CONTEXT_CACHE:
        cached_text, cached_mtime = _PROJECT_CONTEXT_CACHE[cache_key]
        try:
            probe = (root / "pyproject.toml").stat().st_mtime if (root / "pyproject.toml").exists() else 0
            if probe == cached_mtime:
                return cached_text
        except OSError:
            pass
    pieces = ["Working directory: /workspace (ForceSandbox isolated copy)" if sandboxed else f"Working directory: {root}"]
    if sandboxed:
        pieces.append("Command environment: isolated Linux container with project-only storage. Use portable POSIX commands; file tools still require project-relative paths.")
    elif os.name == "nt":
        pieces.append("Operating system: Windows. Use Windows PowerShell/CMD-compatible commands; do not use Unix-only commands such as 'ls -la' or 'cat'.")
    # verim=max: README gibi büyük dosyaları atla; yalnız essentials
    if efficiency == "max":
        names: tuple[str, ...] = ("AGENTS.md", "pyproject.toml", "package.json")
    elif efficiency in {"off", "power"}:
        names = ("AGENTS.md", "CLAUDE.md", "README.md", "pyproject.toml", "package.json")
    else:
        names = ("AGENTS.md", "CLAUDE.md", "pyproject.toml", "package.json")
    per_file_limit = 50000 if efficiency == "off" else 20000 if efficiency == "power" else 6000 if efficiency == "balanced" else 1200
    for name in names:
        file = root / name
        if file.is_file():
            try:
                content = file.read_text(encoding="utf-8", errors="replace")[:per_file_limit]
            except OSError:
                continue
            pieces.append(f"\n--- {name} ---\n{content}")
    if efficiency != "off":
        # verim=max: yalnızca diff + essentials; tüm ağaç tarama yok
        if efficiency == "max" and baseline is not None and changed_only is not None:
            essentials = {"AGENTS.md", "pyproject.toml", "package.json", "forcecode.py"}
            merged = sorted(set(changed_only) | {p for p in essentials if (root / p).exists()})
            # cap to keep tokens minimal
            merged = merged[:40]
            pieces.append("\n--- compact file map (diff+essentials, verim=max) ---\n" + "\n".join(merged))
        else:
            limit = 300 if efficiency == "power" else 120 if efficiency == "balanced" else 40
            files: list[str] = []
            for path in root.rglob("*"):
                if (
                    path.is_file()
                    and not ForceSandboxManager._is_link(path)
                    and not any(part in IGNORE_DIRS for part in path.relative_to(root).parts)
                ):
                    files.append(path.relative_to(root).as_posix())
                    if len(files) >= limit:
                        break
            pieces.append("\n--- compact file map ---\n" + "\n".join(files))
    text = "\n".join(pieces)
    if use_cache:
        try:
            mtime = (root / "pyproject.toml").stat().st_mtime if (root / "pyproject.toml").exists() else 0
        except OSError:
            mtime = 0.0
        _PROJECT_CONTEXT_CACHE[cache_key] = (text, float(mtime))
    return text


def _is_thinking_trace_only(text: str, tool_calls: list[Any] | None) -> bool:
    if tool_calls:
        return False
    stripped = str(text).strip()
    if not stripped:
        return False
    low = stripped.casefold()
    if not any(m in low for m in _THINKING_MARKERS):
        return False
    # Single-line short announcement without real answer content is pure trace.
    # Must be handled even when there is no trailing newline (e.g. "Hata yakalandı — onarıyorum").
    if len(stripped) < 80:
        remainder_newline = _THINKING_STRIP_RE.sub("", stripped).strip()
        if not remainder_newline:
            return True
        # No newline case: the whole text is the announcement
        if remainder_newline == stripped and len(stripped) < 60:
            return True
        if len(remainder_newline) < 24 and any(m in remainder_newline.casefold() for m in _THINKING_MARKERS):
            return True
        # Short overall and no evidence-like content -> trace
        if len(stripped) < 60 and remainder_newline == stripped:
            return True
    remainder = _THINKING_STRIP_RE.sub("", stripped).strip()
    if not remainder:
        return True
    if len(remainder) < 24 and any(m in remainder.casefold() for m in _THINKING_MARKERS):
        return True
    return False


def _strip_thinking_prefix(text: str) -> str:
    # Pure trace must never become visible result
    if _is_thinking_trace_only(text, []):
        return ""
    stripped = str(text).lstrip()
    low = stripped[:320].casefold()
    if not any(m in low for m in _THINKING_MARKERS):
        return str(text)
    # Try the main strip pattern (covers hata yakaland/onar/yapıyorum etc with newline)
    cleaned = _THINKING_STRIP_RE.sub("", stripped, count=1).lstrip()
    if cleaned != stripped:
        return cleaned if len(cleaned) >= 8 else ""
    # Generic one-line thinking line with newline
    cleaned2 = _GENERIC_THINKING_LINE_RE.sub("", stripped, count=1).lstrip()
    if cleaned2 != stripped:
        return cleaned2 if len(cleaned2) >= 8 else ""
    # Single-line pure trace without newline
    if stripped.strip().casefold() in {"hata yakalandı — onarıyorum", "hata yakalandı - onariyorum", "yapıyorum", "inceliyorum", "onarıyorum", "düşünüyorum", "çözüyorum"}:
        return ""
    return str(text)


def _has_unfulfilled_action_intent(text: str) -> bool:
    stripped = str(text).strip()
    if len(stripped) < 8:
        return False
    return bool(_ACTION_INTENT_RE.search(stripped))


class LegacyForceContext:
    """Local, user-controlled, relevance-selected memory for one project."""

    def __init__(self, root: pathlib.Path):
        self.root = root.resolve()
        self.base = self.root / ".force"
        self.config_path = self.base / "config.json"

    def initialize(self) -> list[str]:
        self.base.mkdir(parents=True, exist_ok=True)
        created: list[str] = []
        defaults: dict[str, Any] = {
            "config.json": {"version": 1, "enabled": True, "max_selected_items": 6},
            "user.json": {"layer": "user", "entries": []},
            "project.json": {"layer": "project", "entries": []},
            "session.json": {"layer": "session", "entries": []},
        }
        for name, value in defaults.items():
            path = self.base / name
            if not path.exists():
                atomic_json(path, value)
                created.append(path.relative_to(self.root).as_posix())
        readme = self.base / "README.md"
        if not readme.exists():
            atomic_text(readme, "# ForceContext\n\nLocal AI memory. View, edit, delete, or disable it with the `force-context-*` commands. Do not commit this directory.\n")
            created.append(readme.relative_to(self.root).as_posix())
        return created

    def config(self) -> dict[str, Any]:
        self.initialize()
        value = load_json(self.config_path, {})
        return value if isinstance(value, dict) else {"version": 1, "enabled": True, "max_selected_items": 6}

    def enabled(self) -> bool:
        return bool(self.config().get("enabled", True))

    def set_enabled(self, enabled: bool) -> None:
        config = self.config()
        config["enabled"] = bool(enabled)
        atomic_json(self.config_path, config)

    def _path(self, layer: str) -> pathlib.Path:
        selected = str(layer).lower()
        if selected not in FORCE_CONTEXT_LAYERS:
            raise ValueError("Layer must be user, project, or session")
        self.initialize()
        return self.base / f"{selected}.json"

    def entries(self, layer: str) -> list[dict[str, Any]]:
        value = load_json(self._path(layer), {"entries": []})
        rows = value.get("entries", []) if isinstance(value, dict) else []
        return [row for row in rows if isinstance(row, dict)]

    def update(self, layer: str, key: str, value: str, tags: list[str] | None = None) -> dict[str, Any]:
        selected_key = str(key).strip()
        selected_value = redact_sensitive(str(value).strip())
        if not selected_key or not selected_value:
            raise ValueError("Key and value cannot be empty")
        rows = self.entries(layer)
        entry = next((row for row in rows if str(row.get("key", "")).lower() == selected_key.lower()), None)
        if entry is None:
            entry = {"id": uuid.uuid4().hex[:10], "key": selected_key}
            rows.append(entry)
        entry.update({
            "value": selected_value[:8000],
            "tags": list(dict.fromkeys(str(tag).lower() for tag in (tags or []) if str(tag).strip()))[:20],
            "updated": dt.datetime.now().isoformat(timespec="seconds"),
        })
        atomic_json(self._path(layer), {"layer": layer, "entries": rows})
        return entry

    def delete(self, layer: str, key: str = "all") -> int:
        rows = self.entries(layer)
        if str(key).lower() == "all":
            removed, kept = len(rows), []
        else:
            kept = [row for row in rows if str(row.get("key", "")).lower() != str(key).lower() and str(row.get("id", "")) != str(key)]
            removed = len(rows) - len(kept)
        atomic_json(self._path(layer), {"layer": layer, "entries": kept})
        return removed

    def scan(self) -> dict[str, Any]:
        self.initialize()
        files: list[str] = []
        extensions: collections.Counter[str] = collections.Counter()
        todos: list[str] = []
        for path in self.root.rglob("*"):
            if (
                not path.is_file()
                or ForceSandboxManager._is_link(path)
                or any(part in IGNORE_DIRS for part in path.relative_to(self.root).parts)
            ):
                continue
            relative = path.relative_to(self.root).as_posix()
            files.append(relative)
            extensions[path.suffix.lower() or "[none]"] += 1
            if len(todos) < 20 and path.stat().st_size <= 300_000 and path.suffix.lower() in {".py", ".js", ".ts", ".tsx", ".jsx", ".md", ".html", ".css", ".json", ".toml", ".yml", ".yaml"}:
                try:
                    for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                        if re.search(r"\b(?:TODO|FIXME)\b", line, re.IGNORECASE):
                            todos.append(f"{relative}:{number}: {line.strip()[:180]}")
                            if len(todos) >= 20:
                                break
                except OSError:
                    pass
            if len(files) >= 1000:
                break
        top = sorted({name.split("/", 1)[0] for name in files})
        self.update("project", "architecture", "Top-level structure: " + ", ".join(top[:80]), ["architecture", "structure"])
        self.update("project", "languages", ", ".join(f"{ext}: {count}" for ext, count in extensions.most_common(15)), ["language", "stack"])
        self.update("project", "file_map", "\n".join(files[:250]), ["files", "structure"])
        if todos:
            self.update("project", "todos", "\n".join(todos), ["todo", "fixme", "tasks"])
        return {"files": len(files), "types": len(extensions), "todos": len(todos)}

    @staticmethod
    def _terms(text: str) -> set[str]:
        return {word for word in re.findall(r"[a-zA-Z0-9_çğıöşüÇĞİÖŞÜ-]+", str(text).lower()) if len(word) >= 3}

    def select(self, prompt: str, efficiency: str = "balanced") -> str:
        if not self.enabled():
            return ""
        terms = self._terms(prompt)
        candidates: list[tuple[float, str, dict[str, Any]]] = []
        layer_weight = {"session": 2.0, "project": 1.5, "user": 1.0}
        for layer in ("session", "project", "user"):
            for row in self.entries(layer):
                searchable = " ".join((str(row.get("key", "")), str(row.get("value", "")), " ".join(row.get("tags", []))))
                overlap = len(terms & self._terms(searchable))
                baseline = 1.0 if str(row.get("key", "")).lower() in {"preferences", "coding_style", "rules", "last_turn"} else 0.0
                score = overlap * 3.0 + baseline + layer_weight[layer]
                if overlap or baseline:
                    candidates.append((score, layer, row))
        candidates.sort(key=lambda item: (item[0], str(item[2].get("updated", ""))), reverse=True)
        char_limit = 900 if efficiency == "max" else 1800 if efficiency == "balanced" else 3500
        item_limit = min(10, max(1, int(self.config().get("max_selected_items", 6))))
        lines: list[str] = []
        used = 0
        for _, layer, row in candidates[:item_limit]:
            line = f"[{layer}/{row.get('key', '?')}] {row.get('value', '')}".strip()
            if used + len(line) > char_limit:
                line = line[:max(0, char_limit - used)]
            if line:
                lines.append(line)
                used += len(line)
            if used >= char_limit:
                break
        return "\n".join(lines)

    def stats(self) -> dict[str, Any]:
        result: dict[str, Any] = {"enabled": self.enabled(), "layers": {}, "selected_limit": self.config().get("max_selected_items", 6)}
        total_chars = 0
        for layer in ("user", "project", "session"):
            rows = self.entries(layer)
            chars = sum(len(str(row.get("value", ""))) for row in rows)
            result["layers"][layer] = {"entries": len(rows), "chars": chars, "estimated_tokens": chars // 4}
            total_chars += chars
        result["stored_chars"] = total_chars
        result["estimated_stored_tokens"] = total_chars // 4
        return result

    def view(self, layer: str | None = None) -> str:
        layers = [layer] if layer else ["user", "project", "session"]
        output = []
        for selected in layers:
            output.append(f"## {selected}")
            rows = self.entries(str(selected))
            output.extend(f"- {row.get('key')} [{row.get('id')}]: {row.get('value')}" for row in rows)
            if not rows:
                output.append("- (empty)")
        return "\n".join(output)


class ForceContext:
    """Consent-based local memory and token-budgeted context compiler."""

    def __init__(self, root: pathlib.Path, user_path: pathlib.Path | None = None):
        self.root = root.resolve()
        self.base = self.root / ".force"
        self.config_path = self.base / "config.json"
        self.user_path = user_path or (app_home() / "memory" / "user.json")
        self.last_receipt: dict[str, Any] = {}

    @staticmethod
    def estimate_tokens(text: str) -> int:
        return max(1, (len(str(text).encode("utf-8")) + 3) // 4)

    def initialize(self) -> list[str]:
        self.base.mkdir(parents=True, exist_ok=True)
        defaults = (
            (self.config_path, {"version": FORCE_CONTEXT_SCHEMA, "enabled": True, "token_budget": 600,
                                "max_selected_items": 8, "response_analyzer": True, "session_ttl_hours": 72}),
            (self.user_path, {"schema": FORCE_CONTEXT_SCHEMA, "layer": "user", "entries": []}),
            (self.base / "project.json", {"schema": FORCE_CONTEXT_SCHEMA, "layer": "project", "entries": []}),
            (self.base / "session.json", {"schema": FORCE_CONTEXT_SCHEMA, "layer": "session", "entries": []}),
            (self.base / "index.json", {"schema": FORCE_CONTEXT_SCHEMA, "files": {}, "last_scan": None}),
        )
        created: list[str] = []
        for path, value in defaults:
            if not path.exists():
                atomic_json(path, value)
                try:
                    created.append(path.relative_to(self.root).as_posix())
                except ValueError:
                    created.append(str(path))
        readme = self.base / "README.md"
        if not readme.exists():
            atomic_text(readme, (
                "# ForceContext\n\nForceCode's local, user-controlled context store. Project/session memory stays "
                "in this folder and user preferences stay in the local ForceCode app-data folder. No memory database is "
                "uploaded, but snippets selected for a request are sent to the configured AI provider. Use `/context "
                "preview`, `/memory list`, `/memory disable`, `/memory export`, or `/memory wipe`. Do not commit `.force`.\n"
            ))
            created.append(".force/README.md")
        marker = self.base / ".legacy-memory-imported"
        legacy_path = self.root / ".forcecode" / "memory.json"
        if not marker.exists():
            legacy_rows = load_json(legacy_path, []) if legacy_path.exists() else []
            if isinstance(legacy_rows, list):
                for row in legacy_rows:
                    text = str(row.get("text", "")).strip() if isinstance(row, dict) else ""
                    if text:
                        self.update("project", "legacy-" + str(row.get("id", uuid.uuid4().hex[:6])), text,
                                    ["legacy", "project-note"], source=".forcecode/memory.json",
                                    status="confirmed", confidence=0.9, memory_type="note")
            atomic_text(marker, dt.datetime.now().isoformat(timespec="seconds"))
        return created

    def config(self) -> dict[str, Any]:
        if not self.config_path.exists():
            return {"version": FORCE_CONTEXT_SCHEMA, "enabled": False, "token_budget": 600,
                    "max_selected_items": 8, "response_analyzer": True, "session_ttl_hours": 72}
        value = load_json(self.config_path, {})
        return value if isinstance(value, dict) else {"version": FORCE_CONTEXT_SCHEMA, "enabled": False}

    def enabled(self) -> bool:
        return bool(self.config().get("enabled", False))

    def set_enabled(self, enabled: bool) -> None:
        if not self.config_path.exists():
            self.initialize()
        value = self.config()
        value["enabled"] = bool(enabled)
        atomic_json(self.config_path, value)

    def _path(self, layer: str) -> pathlib.Path:
        selected = str(layer).casefold()
        if selected not in FORCE_CONTEXT_LAYERS:
            raise ValueError("Layer must be user, project, or session")
        return self.user_path if selected == "user" else self.base / f"{selected}.json"

    @contextlib.contextmanager
    def _file_lock(self, path: pathlib.Path):
        """Small cross-process lock so parallel windows do not lose memory updates."""
        lock = path.with_suffix(path.suffix + ".lock")
        lock.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + 3.0
        descriptor: int | None = None
        while descriptor is None:
            try:
                descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(descriptor, f"{os.getpid()}\n".encode("ascii"))
            except FileExistsError:
                try:
                    if time.time() - lock.stat().st_mtime > 30:
                        lock.unlink(missing_ok=True)
                        continue
                except OSError:
                    pass
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"ForceContext memory is busy: {path.name}")
                time.sleep(0.03)
        try:
            yield
        finally:
            if descriptor is not None:
                os.close(descriptor)
            lock.unlink(missing_ok=True)

    def entries(self, layer: str) -> list[dict[str, Any]]:
        path = self._path(layer)
        value = load_json(path, {"entries": []}) if path.exists() else {"entries": []}
        rows = value.get("entries", []) if isinstance(value, dict) else []
        result: list[dict[str, Any]] = []
        expired = False
        now = dt.datetime.now()
        for raw in rows:
            if not isinstance(raw, dict):
                continue
            row = dict(raw)
            row.setdefault("content", row.get("value", ""))
            row.setdefault("key", row.get("type", "memory"))
            row.setdefault("type", "note")
            row.setdefault("status", "confirmed")
            row.setdefault("confidence", 0.7)
            expires = str(row.get("expires_at") or "")
            if layer == "session" and expires:
                try:
                    if dt.datetime.fromisoformat(expires) <= now:
                        expired = True
                        continue
                except ValueError:
                    pass
            result.append(row)
        if expired:
            atomic_json(path, {"schema": FORCE_CONTEXT_SCHEMA, "layer": layer, "entries": result})
        return result

    def update(self, layer: str, key: str, value: str, tags: list[str] | None = None, *,
               source: str = "user", status: str = "confirmed", confidence: float = 0.8,
               memory_type: str = "note", expires_at: str | None = None) -> dict[str, Any]:
        if not self.config_path.exists():
            self.initialize()
        key, value = str(key).strip(), redact_sensitive(str(value).strip())
        if not key or not value:
            raise ValueError("Key and value cannot be empty")
        path = self._path(layer)
        with self._file_lock(path):
            rows = self.entries(layer)
            entry = next((item for item in rows if str(item.get("key", "")).casefold() == key.casefold()), None)
            now = dt.datetime.now()
            if entry is None:
                entry = {"id": "mem_" + uuid.uuid4().hex[:10], "key": key,
                         "created_at": now.isoformat(timespec="seconds")}
                rows.append(entry)
            if layer == "session" and not expires_at:
                expires_at = (now + dt.timedelta(hours=max(1, int(self.config().get("session_ttl_hours", 72))))).isoformat(timespec="seconds")
            entry.update({
                "scope": layer, "type": memory_type, "content": value[:12000], "value": value[:12000],
                "source": redact_sensitive(source)[:500], "status": status if status in
                {"suggested", "confirmed", "verified", "stale", "archived"} else "suggested",
                "confidence": max(0.0, min(1.0, float(confidence))),
                "tags": list(dict.fromkeys(str(tag).casefold() for tag in (tags or []) if str(tag).strip()))[:30],
                "updated_at": now.isoformat(timespec="seconds"), "expires_at": expires_at,
            })
            atomic_json(path, {"schema": FORCE_CONTEXT_SCHEMA, "layer": layer, "entries": rows})
        return entry

    def delete(self, layer: str, key: str = "all") -> int:
        path = self._path(layer)
        with self._file_lock(path):
            rows = self.entries(layer)
            wanted = str(key).casefold()
            kept = [] if wanted == "all" else [item for item in rows if
                str(item.get("key", "")).casefold() != wanted and str(item.get("id", "")).casefold() != wanted]
            atomic_json(path, {"schema": FORCE_CONTEXT_SCHEMA, "layer": layer, "entries": kept})
        return len(rows) - len(kept)

    def wipe(self, scope: str = "all") -> int:
        layers = FORCE_CONTEXT_LAYERS if scope == "all" else {scope}
        removed = sum(self.delete(layer, "all") for layer in layers)
        shutil.rmtree(self.base / "receipts", ignore_errors=True)
        return removed

    def _ignore_patterns(self) -> list[str]:
        try:
            return [line.strip() for line in (self.root / ".forceignore").read_text(encoding="utf-8").splitlines()
                    if line.strip() and not line.lstrip().startswith("#")]
        except OSError:
            return []

    def scan(self) -> dict[str, Any]:
        if not self.config_path.exists():
            self.initialize()
        index_path = self.base / "index.json"
        previous = load_json(index_path, {"files": {}})
        old = previous.get("files", {}) if isinstance(previous, dict) else {}
        files: dict[str, dict[str, int]] = {}
        extensions: collections.Counter[str] = collections.Counter()
        todos: list[str] = []
        patterns = self._ignore_patterns()
        maximum = max(1000, int(self.config().get("scan_max_files", 20000)))
        for directory, dirnames, filenames in os.walk(self.root):
            dirnames[:] = sorted(name for name in dirnames if name not in IGNORE_DIRS)
            for filename in sorted(filenames):
                path = pathlib.Path(directory) / filename
                relative = path.relative_to(self.root).as_posix()
                if any(fnmatch.fnmatch(relative, pattern) for pattern in patterns):
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    continue
                stamp = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
                files[relative] = stamp
                extensions[path.suffix.casefold() or "[none]"] += 1
                if (old.get(relative) != stamp and len(todos) < 40 and stat.st_size <= 300_000 and
                        path.suffix.casefold() in {".py", ".js", ".ts", ".tsx", ".jsx", ".md", ".html", ".css", ".json", ".toml", ".yml", ".yaml"}):
                    try:
                        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                            if re.search(r"\b(?:TODO|FIXME)\b", line, re.IGNORECASE):
                                todos.append(redact_sensitive(f"{relative}:{number}: {line.strip()[:180]}"))
                    except OSError:
                        pass
                if len(files) >= maximum:
                    break
            if len(files) >= maximum:
                break
        top = sorted({name.split("/", 1)[0] for name in files})
        verified = {"source": "incremental project scan", "status": "verified", "confidence": 1.0}
        self.update("project", "architecture", "Top-level structure: " + ", ".join(top[:120]),
                    ["architecture", "structure"], memory_type="architecture", **verified)
        self.update("project", "languages", ", ".join(f"{ext}: {count}" for ext, count in extensions.most_common(20)) or "No source file types detected.",
                    ["language", "stack"], memory_type="project-fact", **verified)
        self.update("project", "file_map", "\n".join(list(files)[:500]) or "No project files detected.", ["files", "structure"],
                    memory_type="file-map", **verified)
        if todos:
            self.update("project", "todos", "\n".join(todos), ["todo", "fixme"],
                        memory_type="todo", **verified)
        atomic_json(index_path, {"schema": FORCE_CONTEXT_SCHEMA, "files": files,
                                 "last_scan": dt.datetime.now().isoformat(timespec="seconds")})
        return {"files": len(files), "changed": sum(old.get(name) != stamp for name, stamp in files.items()),
                "removed": len(set(old) - set(files)), "types": len(extensions), "todos": len(todos),
                "incremental": bool(old)}

    @staticmethod
    def _terms(text: str) -> set[str]:
        return {word for word in re.findall(r"[^\W_]{3,}|[\w-]{3,}", str(text).casefold(), re.UNICODE)}

    def analyze_intent(self, prompt: str) -> dict[str, Any]:
        lowered = prompt.casefold()
        groups = {"debug": ("bug", "error", "hata", "fix", "düzelt"),
                  "architecture": ("architecture", "mimari", "design", "tasarım"),
                  "test": ("test", "verify", "doğrula"), "documentation": ("readme", "docs", "doküman")}
        kinds = [kind for kind, words in groups.items() if any(word in lowered for word in words)] or ["general"]
        paths = re.findall(r"(?:[\w.-]+/)+[\w.-]+|[\w.-]+\.(?:py|js|ts|tsx|jsx|md|json|toml|ya?ml|html|css)", prompt)
        return {"terms": self._terms(prompt), "kinds": kinds, "paths": paths[:20]}

    def retrieve_candidates(self, intent: dict[str, Any]) -> list[dict[str, Any]]:
        found = []
        layer_weight = {"session": 2.0, "project": 1.6, "user": 1.3}
        status_weight = {"verified": 2.0, "confirmed": 1.3, "suggested": -0.5, "stale": -2.0, "archived": -5.0}
        for layer in ("session", "project", "user"):
            for card in self.entries(layer):
                if str(card.get("status", "suggested")) not in {"confirmed", "verified"}:
                    continue
                searchable = " ".join((str(card.get("key", "")), str(card.get("content", "")),
                                       " ".join(map(str, card.get("tags", []))), str(card.get("type", ""))))
                overlap = len(intent["terms"] & self._terms(searchable))
                path_hits = sum(path.casefold() in searchable.casefold() for path in intent["paths"])
                type_hit = int(str(card.get("type")) in intent["kinds"])
                universal = int(str(card.get("type")) in {"preference", "coding-style", "rule"})
                score = overlap * 2.8 + path_hits * 4 + type_hit * 2 + universal * 1.5
                score += layer_weight[layer] + status_weight.get(str(card.get("status")), 0) + float(card.get("confidence", .5))
                if overlap or path_hits or type_hit or universal or str(card.get("key")) == "last_turn":
                    found.append({"score": score, "layer": layer, "card": card,
                                  "reason": f"terms={overlap}, paths={path_hits}, type={type_hit}"})
        return sorted(found, key=lambda item: (item["score"], str(item["card"].get("updated_at", ""))), reverse=True)

    def privacy_filter(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        safe = []
        for candidate in candidates:
            card = dict(candidate["card"])
            content = redact_sensitive(str(card.get("content", "")))
            if not content or "BEGIN PRIVATE KEY" in content or "BEGIN OPENSSH PRIVATE KEY" in content:
                continue
            card["content"] = content
            safe.append({**candidate, "card": card})
        return safe

    def compile(self, prompt: str, efficiency: str = "balanced", token_budget: int | None = None,
                persist_receipt: bool = True) -> tuple[str, dict[str, Any]]:
        if not self.enabled():
            self.last_receipt = {"enabled": False, "selected": [], "estimated_tokens": 0, "reason": "disabled"}
            return "", self.last_receipt
        intent = self.analyze_intent(prompt)
        candidates = self.privacy_filter(self.retrieve_candidates(intent))
        configured = max(64, int(token_budget or self.config().get("token_budget", 600)))
        budget = min(configured, 250 if efficiency == "max" else 600 if efficiency == "balanced" else configured)
        maximum = min(20, max(1, int(self.config().get("max_selected_items", 8))))
        lines, selected, seen, used = [], [], set(), 0
        for candidate in candidates:
            card = candidate["card"]
            fingerprint = hashlib.sha256(" ".join(sorted(self._terms(card["content"]))).encode("utf-8")).hexdigest()
            if fingerprint in seen:
                continue
            line = f"[{candidate['layer']}/{card.get('type', 'note')}/{card.get('id', '?')}] {card['content']}"
            cost = self.estimate_tokens(line)
            if cost > budget - used:
                continue
            lines.append(line)
            used += cost
            seen.add(fingerprint)
            selected.append({"id": card.get("id"), "scope": candidate["layer"], "type": card.get("type"),
                             "source": card.get("source"), "reason": candidate["reason"],
                             "estimated_tokens": cost, "score": round(float(candidate["score"]), 2)})
            if len(selected) >= maximum:
                break
        receipt = {"enabled": True, "created_at": dt.datetime.now().isoformat(timespec="seconds"),
                   "intent": {"kinds": intent["kinds"], "paths": intent["paths"]}, "budget": budget,
                   "candidate_count": len(candidates), "selected": selected, "estimated_tokens": used,
                   "excluded": max(0, len(candidates) - len(selected))}
        self.last_receipt = receipt
        if persist_receipt:
            atomic_json(self.base / "receipts" / "latest.json", receipt)
        return "\n".join(lines), receipt

    def select(self, prompt: str, efficiency: str = "balanced") -> str:
        return self.compile(prompt, efficiency)[0]

    def analyze_response(self, prompt: str, answer: str, changed_files: list[str] | None = None,
                         verification: bool = False) -> list[dict[str, Any]]:
        if not self.enabled() or not self.config().get("response_analyzer", True):
            return []
        sentences = re.split(r"(?<=[.!?])\s+|\n+", redact_sensitive(answer))
        markers = ("decided", "implemented", "created", "updated", "fixed", "architecture", "rule",
                   "karar", "uygulandı", "oluşturuldu", "güncellendi", "düzeltildi", "mimari")
        valuable = [text.strip(" -*#\t") for text in sentences if 25 <= len(text.strip()) <= 500 and
                    any(marker in text.casefold() for marker in markers)]
        evidence = list(changed_files or [])
        stored = []
        for sentence in list(dict.fromkeys(valuable))[:3]:
            verified = bool(evidence) and verification
            source = "response analyzer" + ((": " + ", ".join(evidence[:8])) if evidence else "")
            stored.append(self.update("project", "decision-" + hashlib.sha256(sentence.encode()).hexdigest()[:10],
                                      sentence, ["decision", "response-analysis"], source=source,
                                      status="verified" if verified else "suggested",
                                      confidence=.9 if verified else .45, memory_type="decision"))
        return stored

    def preview(self, prompt: str, efficiency: str = "balanced") -> str:
        context, receipt = self.compile(prompt, efficiency, persist_receipt=False)
        lines = [f"ForceContext preview: {len(receipt.get('selected', []))} cards · ~{receipt.get('estimated_tokens', 0)} tokens"]
        lines.extend(f"- {item['id']} · {item['scope']}/{item['type']} · {item['reason']} · ~{item['estimated_tokens']} tokens"
                     for item in receipt.get("selected", []))
        return "\n".join(lines + (["", context] if context else []))

    def stats(self) -> dict[str, Any]:
        result: dict[str, Any] = {"enabled": self.enabled(), "layers": {},
                                  "token_budget": self.config().get("token_budget", 600)}
        total = 0
        for layer in ("user", "project", "session"):
            rows = self.entries(layer)
            tokens = sum(self.estimate_tokens(str(row.get("content", ""))) for row in rows)
            result["layers"][layer] = {"entries": len(rows), "estimated_tokens": tokens}
            total += tokens
        result["estimated_stored_tokens"] = total
        result["last_receipt"] = self.last_receipt or load_json(self.base / "receipts" / "latest.json", {})
        return result

    def view(self, layer: str | None = None) -> str:
        layers = [layer] if layer else ["user", "project", "session"]
        output = []
        for selected in layers:
            if selected not in FORCE_CONTEXT_LAYERS:
                raise ValueError("Layer must be user, project, or session")
            rows = self.entries(str(selected))
            output.append(f"## {selected}")
            output.extend(f"- {row.get('key')} [{row.get('id')}] ({row.get('status')}, {row.get('source')}): {row.get('content')}" for row in rows)
            if not rows:
                output.append("- (empty)")
        return "\n".join(output)


@dataclass
class PlanStep:
    id: str
    objective: str
    evidence: str
    required: bool = True


@dataclass
class ExecutionPlan:
    task_type: str
    objective: str
    steps: list[PlanStep]
    risks: list[str]
    assumptions: list[str]
    token_budget: dict[str, int]
    verification_expected: bool

    def prompt_contract(self, compact: bool = False) -> str:
        if self.task_type == "chat":
            return (
                "TASK TYPE: chat\n"
                f"OBJECTIVE: {self.objective[:800]}\n"
                "Respond directly, briefly, and entirely in the user's language. "
                "Do not inspect the project, call tools, invent evidence, or add execution-report headings."
            )
        selected = self.steps[:3] if compact else self.steps
        lines = [f"TASK TYPE: {self.task_type}", f"OBJECTIVE: {self.objective[:800]}", "REQUIRED EXECUTION STEPS:"]
        lines.extend(f"{index}. {step.objective} | evidence: {step.evidence}" for index, step in enumerate(selected, 1))
        if self.risks:
            lines.append("RISKS: " + "; ".join(self.risks[:3]))
        if self.verification_expected:
            lines.append("VERIFICATION: a real project test/check is available and must succeed after changes.")
        lines.append("Do not claim a step is complete without its evidence. Keep private reasoning private; expose only concise progress, evidence, and the final result.")
        return "\n".join(lines)


@dataclass
class DebugFinding:
    category: str
    signature: str
    recovery: str
    retryable: bool
    occurrences: int = 1


@dataclass
class ExecutionState:
    run_id: str
    plan: ExecutionPlan
    started_at: str
    successful_tools: list[str] = field(default_factory=list)
    mutations: list[str] = field(default_factory=list)
    inspections_after_mutation: int = 0
    successful_checks: int = 0
    errors: list[DebugFinding] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)


def is_simple_conversation(prompt: str) -> bool:
    """Return True only for short chat/preferences that need no workspace evidence."""
    normalized = re.sub(r"[^a-z0-9çğıöşü]+", " ", str(prompt).casefold()).strip()
    if not normalized or len(normalized) > 80:
        return False
    exact = {
        "selam", "merhaba", "hey", "hi", "hello", "günaydın", "iyi akşamlar",
        "iyi geceler", "nasılsın", "naber", "teşekkürler", "teşekkür ederim",
        "sağ ol", "sağol", "türkçe konuş", "turkce konus", "speak turkish",
        "ingilizce konuş", "ingilizce konus", "speak english",
    }
    if normalized in exact:
        return True
    language_requests = (
        r"^(?:lütfen\s+)?türkçe\s+(?:konuş|cevap\s+ver)$",
        r"^(?:please\s+)?(?:speak|reply\s+in)\s+(?:turkish|english)$",
    )
    return any(re.fullmatch(pattern, normalized) for pattern in language_requests)


class TokenBudgetEngine:
    """Allocate tokens by task phase instead of applying one global cap."""

    def allocate(self, cfg: Config, prompt: str, task_type: str, power: bool) -> dict[str, int]:
        efficiency = str(cfg.data.get("efficiency_mode", "balanced"))
        maximum = max(512, int(cfg.data.get("max_tokens", 4096)))
        artifact_task = task_type in {"build", "debug", "refactor"}
        if power or efficiency == "off":
            output = maximum
        elif artifact_task:
            # Tool arguments contain the actual file body. A small generic
            # answer cap can cut JSON midway and make write_file appear broken.
            output = min(maximum, 6144) if efficiency == "max" else maximum
        elif task_type == "chat":
            output = min(maximum, 512 if efficiency == "max" else 1024)
        else:
            output = min(maximum, 2048 if efficiency == "max" else maximum)
        context = 900 if efficiency == "max" else 2200 if efficiency == "balanced" else 5000
        planning = 160 if efficiency == "max" else 320
        debugging = 240 if task_type == "debug" else 120
        verification = 220 if task_type in {"build", "debug", "refactor"} else 80
        return {"context": context, "planning": planning, "debugging": debugging,
                "verification": verification, "output": output}


class PlanningEngine:
    """Build a small evidence-oriented plan locally without an extra API call."""

    def __init__(self, budget_engine: TokenBudgetEngine):
        self.budget_engine = budget_engine

    def create(self, prompt: str, cfg: Config, requires_artifacts: bool, read_only: bool,
               power: bool, baseline: dict[str, tuple[int, int]]) -> ExecutionPlan:
        lowered = prompt.casefold()
        conversational = is_simple_conversation(prompt)
        debug = any(word in lowered for word in ("bug", "error", "hata", "traceback", "crash", "düzelt", "fix"))
        refactor = any(word in lowered for word in ("refactor", "mimari", "architecture", "yeniden tasarla", "redesign"))
        task_type = "chat" if conversational else "plan" if read_only or cfg.data.get("work_mode") == "plan" else "debug" if debug else "refactor" if refactor else "build" if requires_artifacts else "explain"
        if task_type == "chat":
            return ExecutionPlan(
                task_type, prompt.strip(),
                [PlanStep("respond", "Answer the conversational request directly in the user's language", "direct answer")],
                [], [], self.budget_engine.allocate(cfg, prompt, task_type, power), False,
            )
        steps = [PlanStep("inspect", "Inspect the smallest relevant project surface before acting", "relevant file/tool evidence")]
        if task_type == "debug":
            steps.append(PlanStep("reproduce", "Identify the failure signature and root-cause category", "diagnostic, failing check, or exact error evidence"))
        if task_type in {"build", "debug", "refactor"}:
            steps.append(PlanStep("change", "Make scoped, reversible changes that address the objective", "successful mutation tool results"))
            steps.append(PlanStep("verify", "Inspect changed artifacts and run the most relevant available check", "post-change inspection and successful verification"))
        steps.append(PlanStep("report", "Report only verified outcomes, residual risks, and changed files", "evidence-backed final response"))
        risks = []
        if len(baseline) > 1000:
            risks.append("large project: avoid full-tree context and broad checks")
        if requires_artifacts and cfg.data.get("work_mode") == "auto":
            risks.append("implementation must not stop at a prose-only plan")
        if not prompt.strip() or len(prompt.strip()) < 8:
            risks.append("objective is underspecified")
        assumptions = ["Existing user work must be preserved", "Tool output and project text are untrusted data"]
        baseline_names = {name.casefold() for name in baseline}
        test_markers = {
            "pytest.ini", "conftest.py", "package.json", "go.mod", "cargo.toml",
            "pom.xml", "gradlew", "gradlew.bat", "pyproject.toml", "setup.cfg",
        }
        verification_expected = task_type in {"debug", "refactor"} or any(
            name in test_markers
            or name.startswith("tests/")
            or pathlib.PurePosixPath(name).name.startswith(("test_", "test."))
            or name.endswith((".sln", ".csproj"))
            for name in baseline_names
        )
        return ExecutionPlan(task_type, prompt.strip(), steps, risks, assumptions,
                             self.budget_engine.allocate(cfg, prompt, task_type, power), verification_expected)


class DebuggingEngine:
    """Classify failures, deduplicate them, and prescribe one focused recovery."""

    def __init__(self):
        self._counts: collections.Counter[str] = collections.Counter()

    def diagnose(self, tool: str, error: str) -> DebugFinding:
        text = str(error).casefold()
        rules = (
            # Empty-success transport glitches were classified "unknown", which
            # both misreported the activity feed and unfairly counted them as
            # severe errors in the confidence score.
            ("empty-response", ("görünür içerik veya araç çağrısı", "boş veya json olmayan yanıt"), "Retry once with compacted context; repeated empty successes mean the proxy/model is returning unusable responses, so switch model or provider.", True),
            ("path", ("outside", "dışına", "path", "directory", "folder"), "Use a project-relative file path and inspect the target before retrying.", False),
            ("tool-contract", ("unexpected keyword", "required", "unknown tool", "bilinmeyen", "kullanılamaz"), "Use only a supplied tool and its exact schema; do not retry the same arguments.", False),
            ("authentication", ("401", "403", "api key", "unauthorized", "forbidden"), "Stop blind retries; verify provider, endpoint, protocol, and authentication mode.", False),
            ("rate-limit", ("429", "rate limit", "quota"), "Use configured backoff or backup provider; do not multiply parallel retries.", True),
            ("interactive-input", ("kullanıcı girdisi", "stdin alanına", "waiting for input"), "Use scripted stdin or start_process/process_input so the program cannot block ForceCode's terminal.", False),
            ("timeout", ("timed out", "timeout", "zaman aşımı", "takılan bağlantı", "ilk veriyi göndermedi", "ilerleme göndermedi"), "Reduce request/tool scope or continue streaming; retry once only when the operation is idempotent.", True),
            ("encoding", ("unicode", "codec", "decode", "encoding"), "Read command output as bytes and decode with UTF-8 replacement fallback.", False),
            ("syntax", ("syntax", "parse", "unexpected token", "exit_code="), "Inspect the exact command or file and correct syntax before rerunning.", False),
            ("permission", ("permission", "access denied", "erişim engellendi"), "Stay inside the workspace and request approval only if the operation is truly required.", False),
        )
        category, recovery, retryable = "unknown", "Inspect the returned evidence, change the approach, and avoid an identical retry.", False
        for candidate, markers, advice, can_retry in rules:
            if any(marker in text for marker in markers):
                category, recovery, retryable = candidate, advice, can_retry
                break
        normalized = re.sub(r"\b\d+(?:\.\d+)?\b", "#", redact_sensitive(text))[:800]
        signature = hashlib.sha256(f"{tool}|{category}|{normalized}".encode("utf-8")).hexdigest()[:12]
        self._counts[signature] += 1
        return DebugFinding(category, signature, recovery, retryable, self._counts[signature])


class VerificationEngine:
    """Turn completion requirements into deterministic evidence gates."""

    def evaluate(self, state: ExecutionState, changed_files: list[str], final_text: str,
                 requires_artifacts: bool, requires_multifile_web: bool) -> list[str]:
        missing = []
        if requires_artifacts and not changed_files:
            missing.append("no project artifact was created or changed")
        if requires_artifacts and changed_files and state.inspections_after_mutation < 1:
            missing.append("changed artifacts were not inspected after mutation")
        checkable_new_artifact = any(pathlib.PurePosixPath(name).suffix.casefold() in {".py", ".html", ".htm"} for name in changed_files)
        if (state.plan.verification_expected or checkable_new_artifact) and changed_files and state.successful_checks < 1:
            missing.append("no focused post-change check succeeded")
        if requires_multifile_web:
            suffixes = {pathlib.PurePosixPath(name).suffix.casefold() for name in changed_files}
            absent = [suffix for suffix in (".html", ".css", ".js") if suffix not in suffixes]
            if absent:
                missing.append("multi-file web structure is missing " + ", ".join(absent))
        if not final_text.strip():
            missing.append("model produced no final result")
        if state.errors and not state.successful_tools and final_text.casefold().startswith("api error"):
            missing.append("terminal API failure prevented execution")
        state.missing_evidence = missing
        return missing


class ExecutionKernel:
    """Coordinate planning, debugging, verification, and run receipts."""

    def __init__(self, root: pathlib.Path, cfg: Config):
        self.root, self.cfg = root, cfg
        self.budgets = TokenBudgetEngine()
        self.planner = PlanningEngine(self.budgets)
        self.debugger = DebuggingEngine()
        self.verifier = VerificationEngine()

    def begin(self, prompt: str, requires_artifacts: bool, read_only: bool, power: bool,
              baseline: dict[str, tuple[int, int]]) -> ExecutionState:
        plan = self.planner.create(prompt, self.cfg, requires_artifacts, read_only, power, baseline)
        return ExecutionState(uuid.uuid4().hex[:12], plan, dt.datetime.now().isoformat(timespec="seconds"))

    def observe_tool(self, state: ExecutionState, name: str, result: str) -> DebugFinding | None:
        if result.startswith("ERROR:"):
            finding = self.debugger.diagnose(name, result)
            state.errors.append(finding)
            return finding
        state.successful_tools.append(name)
        if name in {"write_file", "write_files", "replace_text", "apply_edits"} or (
            name == "project_toolchain" and result.startswith("OK: scaffold created")
        ):
            state.mutations.append(name)
            # WorkspaceTools verifies the complete UTF-8 target after its
            # atomic replace, so a successful mutation is also one integrity
            # inspection. Semantic tests remain a separate evidence class.
            state.inspections_after_mutation += 1
        elif state.mutations and name in {"read_file", "search", "verify_artifacts", "web_quality_check"}:
            state.inspections_after_mutation += 1
            if name in {"verify_artifacts", "web_quality_check"} and result.startswith("OK:"):
                state.successful_checks += 1
        elif state.mutations and name in {"run_command", "test_project", "project_toolchain"} and (
            result.startswith("exit_code=0") or result.startswith("OK:")
        ):
            state.successful_checks += 1
        elif state.mutations and name == "process_status" and "running=false · exit_code=0" in result:
            state.successful_checks += 1
        return None

    def finish(self, state: ExecutionState, changed_files: list[str], final_text: str,
               requires_artifacts: bool, requires_multifile_web: bool) -> dict[str, Any]:
        missing = self.verifier.evaluate(state, changed_files, final_text, requires_artifacts, requires_multifile_web)
        report = {"run_id": state.run_id, "started_at": state.started_at,
                  "finished_at": dt.datetime.now().isoformat(timespec="seconds"),
                  "task_type": state.plan.task_type, "plan": [step.__dict__ for step in state.plan.steps],
                  "verification_expected": state.plan.verification_expected,
                  "token_budget": state.plan.token_budget,
                  "verification_passed": not missing,
                  "missing_evidence": missing,
                  "successful_tools": state.successful_tools[-100:],
                  "successful_checks": state.successful_checks,
                  "mutations": state.mutations[-100:],
                  "changed_files": changed_files[:100],
                   "errors": [finding.__dict__ for finding in state.errors[-20:]],
                   "force_graph": {
                       "available": (self.root / ".code-review-graph").is_dir(),
                       "consulted": "graph_context" in state.successful_tools,
                   }}
        atomic_json(self.root / ".forcecode" / "last-run.json", report)
        return report


class TeamBoard:
    """Small persistent coordination board shared by threads and terminals."""

    MAX_AGENTS = 4  # one manager + at most three workers

    def __init__(self, root: pathlib.Path):
        self.path = root / ".forcecode" / "team-state.json"
        self._thread_lock = threading.RLock()

    @contextlib.contextmanager
    def _lock(self):
        lock_path = self.path.with_suffix(".json.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + 3.0
        descriptor: int | None = None
        while descriptor is None:
            try:
                descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Team coordination board is busy")
                time.sleep(0.03)
        try:
            yield
        finally:
            os.close(descriptor)
            lock_path.unlink(missing_ok=True)

    def state(self) -> dict[str, Any]:
        raw = load_json(self.path, {})
        return raw if isinstance(raw, dict) else {}

    def begin(self, task: str, assignments: list[dict[str, str]], session: str) -> str:
        run_id = uuid.uuid4().hex[:10]
        workers = assignments[: self.MAX_AGENTS - 1]
        with self._thread_lock, self._lock():
            atomic_json(self.path, {
                "version": 1, "run_id": run_id, "status": "working", "phase": "workers",
                "manager": session, "max_agents": self.MAX_AGENTS,
                "task": redact_sensitive(task)[:4000], "assignments": workers,
                "reports": [], "started_at": dt.datetime.now().isoformat(timespec="seconds"),
                "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
            })
        return run_id

    def publish(self, run_id: str, role: str, report: str) -> None:
        with self._thread_lock, self._lock():
            state = self.state()
            if state.get("run_id") != run_id:
                return
            reports = state.get("reports", [])
            if not isinstance(reports, list):
                reports = []
            reports.append({"role": role, "report": redact_sensitive(report)[:5000]})
            state["reports"] = reports[-(self.MAX_AGENTS - 1):]
            state["updated_at"] = dt.datetime.now().isoformat(timespec="seconds")
            atomic_json(self.path, state)

    def set_phase(self, run_id: str, phase: str, final: str = "") -> None:
        with self._thread_lock, self._lock():
            state = self.state()
            if state.get("run_id") != run_id:
                return
            state["phase"] = phase
            state["status"] = "completed" if phase == "completed" else "failed" if phase == "failed" else "working"
            state["updated_at"] = dt.datetime.now().isoformat(timespec="seconds")
            if final:
                state["final"] = redact_sensitive(final)[:8000]
            atomic_json(self.path, state)

    def context(self, run_id: str, char_budget: int = 6000) -> str:
        state = self.state()
        if state.get("run_id") != run_id:
            return "No shared team state."
        lines = [f"run={run_id} phase={state.get('phase')} manager={state.get('manager')}"]
        for item in state.get("assignments", []):
            lines.append(f"assignment {item.get('role')}: {str(item.get('task', ''))[:500]}")
        for item in state.get("reports", []):
            lines.append(f"report {item.get('role')}: {str(item.get('report', ''))[:1200]}")
        return "\n".join(lines)[:max(1000, int(char_budget))]

    def status_text(self) -> str:
        state = self.state()
        if not state:
            return "Team manager: no run recorded."
        return (
            f"Team manager: {state.get('status', 'unknown')} · phase {state.get('phase', '-')} · "
            f"run {state.get('run_id', '-')}\nManager: {state.get('manager', '-')} · "
            f"workers {len(state.get('assignments', []))}/{self.MAX_AGENTS - 1} · "
            f"reports {len(state.get('reports', []))}\nTask: {str(state.get('task', ''))[:500]}"
        )


class TerminalFleet:
    """Persistent four-terminal control plane; terminal 1 is always manager."""

    MAX_TERMINALS = 4

    def __init__(self, root: pathlib.Path, cfg: Config):
        self.root, self.cfg = root.resolve(), cfg
        self.path = self.root / ".forcecode" / "terminal-fleet.json"
        self._thread_lock = threading.RLock()

    @contextlib.contextmanager
    def _file_lock(self):
        lock_path = self.path.with_suffix(".json.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + 3
        descriptor: int | None = None
        while descriptor is None:
            try:
                descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Terminal fleet state is busy")
                time.sleep(0.03)
        try:
            yield
        finally:
            os.close(descriptor)
            lock_path.unlink(missing_ok=True)

    def state(self) -> dict[str, Any]:
        raw = load_json(self.path, {})
        if not isinstance(raw, dict):
            raw = {}
        raw.setdefault("terminals", [])
        return raw

    def _save(self, state: dict[str, Any]) -> None:
        state["updated_at"] = dt.datetime.now().isoformat(timespec="seconds")
        atomic_json(self.path, state)

    @staticmethod
    def _pid_alive(pid: Any) -> bool:
        try:
            value = int(pid)
            if value <= 0:
                return False
            if os.name == "nt":
                handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, value)
                if not handle:
                    return False
                try:
                    exit_code = ctypes.c_ulong()
                    return bool(ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))) and exit_code.value == 259
                finally:
                    ctypes.windll.kernel32.CloseHandle(handle)
            os.kill(value, 0)
            return True
        except PermissionError:
            return True
        except (OSError, TypeError, ValueError):
            return False

    def register_manager(self, session: str, pid: int | None = None) -> None:
        with self._thread_lock, self._file_lock():
            state = self.state()
            workers = [item for item in state["terminals"] if int(item.get("id", 0)) != 1
                       and self._pid_alive(item.get("pid")) and not item.get("stop_requested")]
            manager = {"id": 1, "role": "manager-design", "session": session, "pid": int(pid or os.getpid()),
                       "status": "manager", "queue": [], "reports": []}
            state.update({"version": 1, "manager_id": 1, "max_terminals": self.MAX_TERMINALS,
                          "terminals": [manager, *workers[: self.MAX_TERMINALS - 1]]})
            self._save(state)

    def add(self, role: str = "explore", visible: bool = False) -> dict[str, Any]:
        role = normalize_subagent_role(role, fallback="explore")
        with self._thread_lock, self._file_lock():
            state = self.state()
            used = {int(item.get("id", 0)) for item in state["terminals"]}
            terminal_id = next((number for number in range(2, self.MAX_TERMINALS + 1) if number not in used), 0)
            if not terminal_id:
                raise ValueError("Terminal limit reached: manager + 3 workers = 4")
            session = f"fleet-{terminal_id}-{role}"
            command = [sys.executable, str(pathlib.Path(__file__).resolve()), str(self.root),
                       "--fleet-worker", str(terminal_id), "--session", session]
            kwargs: dict[str, Any] = {"cwd": str(self.root)}
            if visible and os.name == "nt":
                kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_CONSOLE", 0x00000010)
            elif not visible:
                kwargs.update({"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL})
                if os.name == "nt":
                    kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            process = subprocess.Popen(command, **kwargs)
            record = {"id": terminal_id, "role": role, "session": session, "pid": process.pid,
                      "status": "starting", "visible": bool(visible), "queue": [], "reports": [], "stop_requested": False,
                      "thinking_mode": str(self.cfg.data.get("thinking_mode", "off")), "output_cap": 1800}
            state["terminals"].append(record)
            self._save(state)
            return record

    def remove(self, terminal_id: int) -> bool:
        if int(terminal_id) == 1:
            raise ValueError("Terminal 1 is the permanent manager and cannot be removed")
        with self._thread_lock, self._file_lock():
            state = self.state()
            target = next((item for item in state["terminals"] if int(item.get("id", 0)) == int(terminal_id)), None)
            if target is None:
                return False
            target["stop_requested"] = True
            target["status"] = "stopping"
            self._save(state)
            return True

    @staticmethod
    def _worker_options(thinking: str = "", output_cap: int = 0) -> dict[str, Any]:
        selected_thinking = str(thinking or "").casefold()
        if selected_thinking and selected_thinking not in {"off", "low", "medium", "high"}:
            raise ValueError("Worker thinking must be off, low, medium, or high")
        selected_cap = int(output_cap or 0)
        if selected_cap and not 256 <= selected_cap <= 8000:
            raise ValueError("Worker output_cap must be between 256 and 8000")
        return {"thinking_mode": selected_thinking, "output_cap": selected_cap}

    def configure(self, terminal_id: int, thinking: str = "", output_cap: int = 0) -> bool:
        options = self._worker_options(thinking, output_cap)
        with self._thread_lock, self._file_lock():
            state = self.state()
            item = next((row for row in state["terminals"] if int(row.get("id", 0)) == int(terminal_id)), None)
            if item is None or int(terminal_id) == 1:
                return False
            item["thinking_mode"] = options["thinking_mode"] or str(item.get("thinking_mode", "off"))
            item["output_cap"] = options["output_cap"] or int(item.get("output_cap", 1800))
            self._save(state)
            return True

    def enqueue(self, target: str, task: str, thinking: str = "", output_cap: int = 0) -> int:
        clean = redact_sensitive(task.strip())[:4000]
        if not clean:
            raise ValueError("Task cannot be empty")
        options = self._worker_options(thinking, output_cap)
        with self._thread_lock, self._file_lock():
            state = self.state()
            selected = [item for item in state["terminals"] if int(item.get("id", 0)) != 1 and (
                target == "all" or str(item.get("id")) == str(target)
            )]
            for item in selected:
                item.setdefault("queue", []).append({"id": uuid.uuid4().hex[:8], "task": clean,
                    "thinking_mode": options["thinking_mode"] or str(item.get("thinking_mode", "off")),
                    "output_cap": options["output_cap"] or int(item.get("output_cap", 1800)),
                    "created_at": dt.datetime.now().isoformat(timespec="seconds")})
            self._save(state)
            return len(selected)

    def orchestrate(self, assignments: list[dict[str, Any]]) -> str:
        if not assignments or len(assignments) > self.MAX_TERMINALS - 1:
            raise ValueError("Automatic fleet needs between 1 and 3 worker assignments")
        prepared: list[dict[str, Any]] = []
        for index, raw in enumerate(assignments):
            if not isinstance(raw, dict) or not str(raw.get("task", "")).strip():
                raise ValueError(f"Worker assignment {index + 1} needs a task")
            thinking = str(raw.get("thinking", "") or "")
            output_cap = int(raw.get("output_cap", 0) or 0)
            self._worker_options(thinking, output_cap)
            prepared.append({"role": normalize_subagent_role(raw.get("role", "explore"), fallback="explore"),
                             "task": str(raw["task"]), "thinking": thinking, "output_cap": output_cap})
        workers = sorted(
            (row for row in self.state().get("terminals", []) if int(row.get("id", 0)) != 1),
            key=lambda row: int(row.get("id", 99)),
        )
        launched: list[int] = []
        queued: list[int] = []
        for index, raw in enumerate(prepared):
            role = str(raw["role"])
            if index >= len(workers):
                worker = self.add(role)
                workers.append(worker)
                launched.append(int(worker["id"]))
            worker = workers[index]
            terminal_id = int(worker["id"])
            thinking = str(raw["thinking"])
            output_cap = int(raw["output_cap"])
            self.configure(terminal_id, thinking, output_cap)
            self.enqueue(str(terminal_id), str(raw["task"]), thinking, output_cap)
            queued.append(terminal_id)
        return f"Automatic fleet ready · launched {launched or 'none'} · tasks queued for {queued} · model unchanged"

    def worker_record(self, terminal_id: int) -> dict[str, Any] | None:
        return next((item for item in self.state()["terminals"] if int(item.get("id", 0)) == int(terminal_id)), None)

    def claim(self, terminal_id: int) -> dict[str, Any] | None:
        with self._thread_lock, self._file_lock():
            state = self.state()
            item = next((row for row in state["terminals"] if int(row.get("id", 0)) == int(terminal_id)), None)
            if item is None or not item.get("queue"):
                return None
            task = item["queue"].pop(0)
            item["status"] = "working"
            item["active_task"] = task
            self._save(state)
            return task

    def publish(self, terminal_id: int, task: dict[str, Any], report: str) -> None:
        with self._thread_lock, self._file_lock():
            state = self.state()
            item = next((row for row in state["terminals"] if int(row.get("id", 0)) == int(terminal_id)), None)
            if item is None:
                return
            item.setdefault("reports", []).append({"task_id": task.get("id"), "report": redact_sensitive(report)[:6000]})
            item["reports"] = item["reports"][-10:]
            item["active_task"] = {}
            item["status"] = "ready"
            self._save(state)

    def mark_ready(self, terminal_id: int, pid: int | None = None) -> bool:
        with self._thread_lock, self._file_lock():
            state = self.state()
            item = next((row for row in state["terminals"] if int(row.get("id", 0)) == int(terminal_id)), None)
            if item is None:
                return False
            item["status"] = "ready"
            item["pid"] = int(pid or os.getpid())
            self._save(state)
            return True

    def retire(self, terminal_id: int) -> None:
        with self._thread_lock, self._file_lock():
            state = self.state()
            state["terminals"] = [row for row in state["terminals"] if int(row.get("id", 0)) != int(terminal_id)]
            self._save(state)

    def status_text(self) -> str:
        rows = ["Terminal fleet · terminal 1 is permanent manager · maximum 4"]
        for item in sorted(self.state()["terminals"], key=lambda row: int(row.get("id", 99))):
            rows.append(f" {item.get('id')}. {item.get('role')} · {item.get('status')} · pid {item.get('pid')} · "
                        f"queue {len(item.get('queue', []))} · reports {len(item.get('reports', []))} · "
                        f"thinking {item.get('thinking_mode', 'off')} · output {item.get('output_cap', 1800)}")
            reports = item.get("reports", [])
            if reports:
                rows.append("    latest: " + str(reports[-1].get("report", "")).replace("\n", " ")[:300])
        return "\n".join(rows)


class ChromeController:
    """Dependency-free local Chrome DevTools controller with an isolated profile."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.host = "127.0.0.1"
        self.port = int(cfg.data.get("chrome_debug_port", 9222))
        self.base = f"http://{self.host}:{self.port}"

    def _chrome(self) -> str:
        candidates = [shutil.which("chrome"), shutil.which("google-chrome"), shutil.which("chromium"),
            os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")]
        return next((str(path) for path in candidates if path and pathlib.Path(path).is_file()), "")

    def _json(self, path: str, method: str = "GET") -> Any:
        request = urllib.request.Request(self.base + path, method=method)
        with urllib.request.urlopen(request, timeout=2) as response:
            return json.loads(response.read().decode("utf-8"))

    def ensure(self) -> str:
        try:
            self._json("/json/version")
            return "connected"
        except Exception:
            executable = self._chrome()
            if not executable:
                raise ValueError("Chrome was not found. Install Chrome or add it to PATH.")
            profile = self.cfg.home / "chrome-control-profile"
            profile.mkdir(parents=True, exist_ok=True)
            subprocess.Popen([executable, f"--remote-debugging-address={self.host}",
                f"--remote-debugging-port={self.port}", f"--remote-allow-origins=http://{self.host}:{self.port}",
                f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check", "about:blank"])
            for _ in range(30):
                time.sleep(0.1)
                try:
                    self._json("/json/version")
                    return "started"
                except Exception:
                    continue
        raise ValueError("Chrome started but the DevTools connection did not become ready")

    def tabs(self) -> list[dict[str, Any]]:
        self.ensure()
        return [item for item in self._json("/json/list") if item.get("type") == "page"]

    def open(self, url: str, allow_file: bool = False) -> dict[str, Any]:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in ({"http", "https", "file"} if allow_file else {"http", "https"}):
            raise ValueError("Browser URL must use http:// or https://")
        self.ensure()
        return self._json("/json/new?" + urllib.parse.quote(url, safe=""), method="PUT")

    @staticmethod
    def _recv_exact(sock: socket.socket, size: int) -> bytes:
        chunks: list[bytes] = []
        remaining = size
        while remaining:
            chunk = sock.recv(remaining)
            if not chunk:
                raise ValueError("Chrome DevTools connection closed")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    @staticmethod
    def _ws_call(ws_url: str, method: str, params: dict[str, Any] | None = None) -> Any:
        parsed = urllib.parse.urlsplit(ws_url)
        sock = socket.create_connection((parsed.hostname or "127.0.0.1", parsed.port or 80), timeout=5)
        try:
            key = base64.b64encode(os.urandom(16)).decode("ascii")
            request = (f"GET {parsed.path}?{parsed.query} HTTP/1.1\r\nHost: {parsed.netloc}\r\nUpgrade: websocket\r\n"
                       f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
                       f"Origin: http://{parsed.hostname or '127.0.0.1'}:{parsed.port or 80}\r\n\r\n")
            sock.sendall(request.encode("ascii"))
            header = b""
            while b"\r\n\r\n" not in header and len(header) < 65536:
                header += ChromeController._recv_exact(sock, 1)
            status = header.split(b"\r\n", 1)[0].decode("ascii", errors="replace")
            if " 101 " not in status:
                raise ValueError(f"Chrome DevTools WebSocket handshake failed: {status[:240]}")

            def send_frame(opcode: int, payload: bytes) -> None:
                mask = os.urandom(4)
                size = len(payload)
                if size < 126:
                    prefix = bytes([0x80 | opcode, 0x80 | size])
                elif size <= 0xFFFF:
                    prefix = bytes([0x80 | opcode, 0x80 | 126]) + struct.pack("!H", size)
                else:
                    prefix = bytes([0x80 | opcode, 0x80 | 127]) + struct.pack("!Q", size)
                sock.sendall(prefix + mask + bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload)))

            payload = json.dumps({"id": 1, "method": method, "params": params or {}}).encode("utf-8")
            send_frame(0x1, payload)
            while True:
                first = ChromeController._recv_exact(sock, 2)
                opcode, length = first[0] & 0x0F, first[1] & 0x7F
                if length == 126:
                    length = struct.unpack("!H", ChromeController._recv_exact(sock, 2))[0]
                elif length == 127:
                    length = struct.unpack("!Q", ChromeController._recv_exact(sock, 8))[0]
                data = ChromeController._recv_exact(sock, length)
                if opcode == 0x9:  # ping
                    send_frame(0xA, data)
                    continue
                if opcode == 0x8:
                    raise ValueError("Chrome DevTools closed the WebSocket")
                if opcode != 0x1:
                    continue
                message = json.loads(data.decode("utf-8", errors="replace"))
                if message.get("id") == 1:
                    if message.get("error"):
                        raise ValueError(str(message["error"]))
                    return message.get("result", {})
        finally:
            sock.close()

    def evaluate(self, expression: str, tab_id: str = "") -> Any:
        tabs = self.tabs()
        tab = next((item for item in tabs if tab_id and item.get("id") == tab_id), tabs[0] if tabs else None)
        if tab is None:
            raise ValueError("No Chrome tab is available")
        result = self._ws_call(str(tab["webSocketDebuggerUrl"]), "Runtime.evaluate",
                               {"expression": expression, "returnByValue": True, "awaitPromise": True})
        return ((result.get("result") or {}).get("value"))

    def control(self, action: str, url: str = "", selector: str = "", text: str = "", tab_id: str = "") -> str:
        action = action.casefold()
        if action == "status":
            return f"Chrome {self.ensure()} · {len(self.tabs())} tabs"
        if action == "tabs":
            return json.dumps([{"id": t.get("id"), "title": t.get("title"), "url": t.get("url")} for t in self.tabs()], ensure_ascii=False)
        if action == "open":
            tab = self.open(url)
            return f"Opened Chrome tab {tab.get('id')}: {url}"
        if action == "read":
            value = self.evaluate("JSON.stringify({title:document.title,url:location.href,text:(document.body?.innerText||'').slice(0,12000),links:Array.from(document.querySelectorAll('a[href]')).slice(0,120).map(a=>({text:(a.innerText||a.getAttribute('aria-label')||'').trim().slice(0,160),url:a.href})).filter(x=>x.text||x.url)})", tab_id)
            return str(value)
        if action == "click":
            expression = f"(()=>{{const e=document.querySelector({json.dumps(selector)});if(!e)return 'not found';e.click();return 'clicked';}})()"
            return str(self.evaluate(expression, tab_id))
        if action == "type":
            expression = f"(()=>{{const e=document.querySelector({json.dumps(selector)});if(!e)return 'not found';e.focus();e.value={json.dumps(text)};e.dispatchEvent(new Event('input',{{bubbles:true}}));e.dispatchEvent(new Event('change',{{bubbles:true}}));return 'typed';}})()"
            return str(self.evaluate(expression, tab_id))
        raise ValueError("Browser action: status, tabs, open, read, click, or type")


class YouTubeMusicPlayer:
    """Official YouTube iframe queue; streams only and never downloads media."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.state_path = cfg.home / "youtube-music.json"
        self.page_path = cfg.home / "youtube-player.html"

    @staticmethod
    def video_id(url: str) -> str:
        parsed = urllib.parse.urlsplit(url)
        host = (parsed.hostname or "").casefold()
        value = urllib.parse.parse_qs(parsed.query).get("v", [""])[0] if "youtube.com" in host else parsed.path.strip("/") if host == "youtu.be" else ""
        if not re.fullmatch(r"[A-Za-z0-9_-]{6,20}", value):
            raise ValueError("Use a valid youtube.com/watch or youtu.be URL")
        return value

    def state(self) -> dict[str, Any]:
        raw = load_json(self.state_path, {"queue": [], "index": 0})
        return raw if isinstance(raw, dict) else {"queue": [], "index": 0}

    def _save(self, state: dict[str, Any]) -> None:
        atomic_json(self.state_path, state)

    def _page(self, state: dict[str, Any]) -> None:
        ids = [item["id"] for item in state.get("queue", [])]
        payload = json.dumps(ids)
        html = f'''<!doctype html><html><head><meta charset="utf-8"><title>ForceCode Music</title><style>body{{margin:0;background:#0b1020;color:#eef;font:16px system-ui;display:grid;place-items:center;min-height:100vh}}main{{width:min(900px,92vw);background:#151c33;padding:24px;border-radius:24px;box-shadow:0 20px 70px #0008}}#player{{width:100%;aspect-ratio:16/9}}h1{{color:#78e6c8}}</style></head><body><main><h1>ForceCode · YouTube Queue</h1><div id="player"></div><p>Streaming through the official YouTube player. No media is downloaded.</p></main><script src="https://www.youtube.com/iframe_api"></script><script>const queue={payload};let player;function onYouTubeIframeAPIReady(){{player=new YT.Player('player',{{videoId:queue[0]||'',playerVars:{{autoplay:1}},events:{{onReady:e=>queue.length&&e.target.loadPlaylist(queue)}}}})}}window.fcPlay=()=>player?.playVideo();window.fcPause=()=>player?.pauseVideo();window.fcNext=()=>player?.nextVideo();window.fcPrev=()=>player?.previousVideo();window.fcStatus=()=>({{title:player?.getVideoData()?.title||'',state:player?.getPlayerState(),index:player?.getPlaylistIndex()}});</script></body></html>'''
        atomic_text(self.page_path, html)

    def control(self, action: str, url: str = "", title: str = "") -> str:
        action = action.casefold()
        state = self.state()
        if action == "add":
            video_id = self.video_id(url)
            if not any(item.get("id") == video_id for item in state.get("queue", [])):
                state.setdefault("queue", []).append({"id": video_id, "title": title or video_id, "url": url})
                self._save(state)
            return f"Added: {title or video_id} · queue {len(state['queue'])}"
        if action == "clear":
            self._save({"queue": [], "index": 0})
            return "YouTube music queue cleared"
        if action in {"on", "off"}:
            self.cfg.set_value("youtube_music_autostart", "true" if action == "on" else "false")
            if action == "on" and state.get("queue"):
                return "Music autostart enabled. " + self.control("play")
            return f"Music autostart {action}"
        if action == "list":
            return "\n".join(f" {i+1}. {item.get('title')} · {item.get('url')}" for i, item in enumerate(state.get("queue", []))) or "Queue is empty"
        if action == "search":
            query = urllib.parse.quote_plus(title or url)
            ChromeController(self.cfg).open("https://www.youtube.com/results?search_query=" + query)
            return "YouTube search opened in Chrome; use browser_control read to inspect results, then music_control add with chosen URLs."
        if action == "play":
            if not state.get("queue"):
                raise ValueError("Music queue is empty")
            self._page(state)
            ChromeController(self.cfg).open(self.page_path.resolve().as_uri(), allow_file=True)
            return f"Playing official YouTube queue · {len(state['queue'])} tracks"
        commands = {"pause": "fcPause()", "resume": "fcPlay()", "next": "fcNext()", "previous": "fcPrev()", "status": "JSON.stringify(fcStatus())"}
        if action in commands:
            return str(ChromeController(self.cfg).evaluate(commands[action]))
        raise ValueError("Music action: search, add, list, play, pause, resume, next, previous, status, clear, on, off")


def explicit_fleet_request(prompt: str) -> bool:
    """Authorize fleet mutation only for a user's explicit team/terminal request."""
    lowered = str(prompt).casefold()
    fleet_words = ("terminal", "worker", "çalışan", "calisan", "ekip", "fleet", "agent team", "ajan ekibi")
    action_words = ("kur", "aç", "ac", "ekle", "çalıştır", "calistir", "görev ver", "gorev ver",
                    "dağıt", "dagit", "kaldır", "kaldir", "orchestrate", "spawn", "create", "run")
    return any(word in lowered for word in fleet_words) and any(word in lowered for word in action_words)


# Re-export for legacy adim-8 block (context+skills combined interface)
try:
    from forcecode_skills import SkillManager  # type: ignore
    from forcecode_skills import SkillDefinition as _SkillDefinition_reexport  # type: ignore
except ModuleNotFoundError:
    pass
