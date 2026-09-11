"""Read-only Mission Control projections for ForgeCode's persistent task queue."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping


_TERMINAL_STATES = {"completed", "skipped"}


def _bounded(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _unique_strings(values: Iterable[Any], limit: int, item_limit: int) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = _bounded(value, item_limit)
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
        if len(result) >= limit:
            break
    return tuple(result)


@dataclass(frozen=True)
class MissionTaskView:
    """One immutable task row in an ordered mission graph."""

    task_id: str
    title: str
    status: str
    acceptance: str
    depends_on: tuple[str, ...]
    changed_files: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    summary: str


@dataclass(frozen=True)
class MissionView:
    """A bounded, immutable projection derived from one ForceFlow task group."""

    flow_id: str
    objective: str
    status: str
    total_tasks: int
    completed_tasks: int
    current_task_id: str
    current_task_title: str
    changed_files: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    tasks: tuple[MissionTaskView, ...]

    @property
    def progress_percent(self) -> int:
        if self.total_tasks <= 0:
            return 0
        return round(self.completed_tasks * 100 / self.total_tasks)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation for future UI clients."""
        return asdict(self)


def _mission_status(statuses: list[str]) -> str:
    if "failed" in statuses:
        return "blocked"
    if "running" in statuses:
        return "running"
    if "paused" in statuses:
        return "paused"
    if "pending" in statuses:
        return "queued"
    if statuses and all(status == "completed" for status in statuses):
        return "completed"
    if statuses and all(status in _TERMINAL_STATES for status in statuses):
        return "stopped"
    return "queued"


def build_mission_views(tasks: Iterable[Mapping[str, Any]]) -> list[MissionView]:
    """Group persisted queue tasks by ``flow_id`` and derive mission state."""
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for raw in tasks:
        if not isinstance(raw, Mapping):
            continue
        flow_id = _bounded(raw.get("flow_id") or "manual", 64)
        grouped.setdefault(flow_id, []).append(raw)

    views: list[MissionView] = []
    for flow_id, rows in grouped.items():
        task_views: list[MissionTaskView] = []
        previous_id = ""
        all_files: list[Any] = []
        all_missing: list[Any] = []
        statuses: list[str] = []
        objective = ""
        current_id = ""
        current_title = ""
        completed = 0

        for index, row in enumerate(rows, 1):
            task_id = _bounded(row.get("id") or f"task-{index}", 64)
            title = _bounded(row.get("title") or row.get("text") or "Untitled task", 500)
            status = _bounded(row.get("status") or "pending", 20).lower()
            if status not in {"pending", "running", "paused", "failed", "completed", "skipped"}:
                status = "pending"
            if not objective:
                objective = _bounded(row.get("objective") or title, 4000)
            if status == "completed":
                completed += 1
            if not current_id and status not in _TERMINAL_STATES:
                current_id, current_title = task_id, title

            changed_files = _unique_strings(row.get("changed_files") or (), 100, 500)
            missing = _unique_strings(row.get("missing_evidence") or (), 50, 500)
            all_files.extend(changed_files)
            all_missing.extend(missing)
            statuses.append(status)
            task_views.append(MissionTaskView(
                task_id=task_id,
                title=title,
                status=status,
                acceptance=_bounded(row.get("acceptance"), 1200),
                depends_on=(previous_id,) if previous_id else (),
                changed_files=changed_files,
                missing_evidence=missing,
                summary=_bounded(row.get("summary"), 1200),
            ))
            previous_id = task_id

        views.append(MissionView(
            flow_id=flow_id,
            objective=objective,
            status=_mission_status(statuses),
            total_tasks=len(task_views),
            completed_tasks=completed,
            current_task_id=current_id,
            current_task_title=current_title,
            changed_files=_unique_strings(all_files, 200, 500),
            missing_evidence=_unique_strings(all_missing, 100, 500),
            tasks=tuple(task_views),
        ))
    return views


def select_mission(tasks: Iterable[Mapping[str, Any]], wanted: str = "") -> MissionView | None:
    """Select by flow id/prefix/one-based index, or choose the active mission."""
    views = build_mission_views(tasks)
    selected = _bounded(wanted, 64)
    if selected:
        if selected.isdigit() and 1 <= int(selected) <= len(views):
            return views[int(selected) - 1]
        exact = next((view for view in views if view.flow_id.casefold() == selected.casefold()), None)
        if exact is not None:
            return exact
        matches = [view for view in views if view.flow_id.casefold().startswith(selected.casefold())]
        return matches[0] if len(matches) == 1 else None
    active = next((view for view in views if view.status not in {"completed", "stopped"}), None)
    return active or (views[-1] if views else None)


def _graph_line(view: MissionView) -> str:
    marks = {
        "completed": "✓", "running": "▶", "failed": "!",
        "paused": "Ⅱ", "skipped": "×", "pending": "○",
    }
    return " → ".join(f"{marks.get(task.status, '○')} {task.task_id}" for task in view.tasks)


def render_mission(view: MissionView, language: str = "tr") -> str:
    """Render a compact terminal-safe mission status and evidence receipt."""
    english = str(language).lower() == "en"
    labels = ({
        "mission": "MISSION", "goal": "Goal", "progress": "Progress", "active": "Active",
        "graph": "Graph", "evidence": "Evidence", "files": "files", "missing": "missing gates",
        "none": "none", "complete": "complete",
    } if english else {
        "mission": "MISSION", "goal": "Hedef", "progress": "İlerleme", "active": "Aktif",
        "graph": "Grafik", "evidence": "Kanıt", "files": "dosya", "missing": "eksik kapı",
        "none": "yok", "complete": "tamamlandı",
    })
    current = view.current_task_title or labels["complete"]
    return "\n".join((
        f"{labels['mission']} {view.flow_id} · {view.status}",
        f"{labels['goal']}: {view.objective}",
        f"{labels['progress']}: {view.completed_tasks}/{view.total_tasks} · %{view.progress_percent}",
        f"{labels['active']}: {current}",
        f"{labels['graph']}: {_graph_line(view) or labels['none']}",
        f"{labels['evidence']}: {len(view.changed_files)} {labels['files']} · "
        f"{len(view.missing_evidence)} {labels['missing']}",
    ))


def render_mission_list(views: Iterable[MissionView], language: str = "tr") -> str:
    """Render one bounded summary row per mission."""
    rows = list(views)
    if not rows:
        return "No missions." if str(language).lower() == "en" else "Henüz mission yok."
    header = "Missions:" if str(language).lower() == "en" else "Mission'lar:"
    lines = [header]
    for index, view in enumerate(rows, 1):
        lines.append(
            f" {index}. [{view.flow_id}] {view.status} · "
            f"{view.completed_tasks}/{view.total_tasks} · {view.objective[:120]}"
        )
    return "\n".join(lines)
