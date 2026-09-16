"""Desk registry: start / stop / dismiss / status / schedule.

States: working | quiet | dismissed.
- stop  → quiet; keep last live DAG visible; CoS remains ready
- dismiss → disband standing org; archive/clear DAG
Persists under OKSTRATR_STATE_DIR / desks.json (+ per-desk DAG files).
"""

from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from time import time
from typing import Any

from . import dag as dag_mod
from . import kernel, okbay, roles, status
from .paths import state_dir
from .schedule_parse import ScheduleParseError, describe, parse_schedule_args

VALID_DESK_STATES = frozenset({"working", "quiet", "dismissed"})
# Placeholder / idle is UI-facing for default kinds with no live desk yet.
VALID_STANDING_STATES = frozenset({"working", "quiet", "idle"})
# Node states that mean work is still in flight / queued (not finished).
ACTIVE_NODE_STATES = frozenset({"pending", "ready", "running", "blocked"})
TERMINAL_NODE_STATES = frozenset({"done", "failed"})
REGISTRY_NAME = "desks.json"
PLACEHOLDER_ID_PREFIX = "kind:"


def default_standing_rows(registry: "DeskRegistry | None" = None) -> list[dict[str, Any]]:
    """Always expose default desk kinds (work/curate/code/deck/auto).

    Prefer a live non-dismissed desk of that kind; otherwise a standing/idle
    placeholder so CLI/HTTP/UI agree without QML-only fake rows.
    """
    reg = registry if registry is not None else default_registry()
    by_kind: dict[str, list[Desk]] = {}
    for d in reg.standing():
        by_kind.setdefault(d.kind, []).append(d)

    def _pick(kind: str) -> Desk | None:
        cands = by_kind.get(kind) or []
        if not cands:
            return None
        # Prefer working, then quiet; newest updated_at
        cands = sorted(
            cands,
            key=lambda x: (0 if x.state == "working" else 1, -float(x.updated_at or 0)),
        )
        return cands[0]

    rows: list[dict[str, Any]] = []
    for kind in roles.DEFAULT_DESK_KINDS:
        live = _pick(kind)
        if live is not None:
            row = live.to_dict()
            row["placeholder"] = False
            row["standing"] = True
            rows.append(row)
        else:
            rows.append({
                "id": f"{PLACEHOLDER_ID_PREFIX}{kind}",
                "kind": kind,
                "objective": "",
                "state": "idle",
                "roles": [],
                "schedule": None,
                "created_at": 0.0,
                "updated_at": 0.0,
                "thread_id": "",
                "dag_relpath": "",
                "hire": {},
                "effort": None,
                "org": {},
                "okbay_workspace_id": "",
                "commit_path": None,
                "placeholder": True,
                "standing": True,
            })
    return rows



def _new_id() -> str:
    return f"desk-{uuid.uuid4().hex[:10]}"


@dataclass
class Desk:
    id: str
    kind: str
    objective: str
    state: str = "working"  # working|quiet|dismissed
    roles: list[str] = field(default_factory=list)
    schedule: dict[str, Any] | None = None
    created_at: float = 0.0
    updated_at: float = 0.0
    thread_id: str = ""
    """Herdr thread label companion (okstratr); stub id for now."""
    dag_relpath: str = ""
    """Relative to state_dir; live DAG for this desk."""
    hire: dict[str, Any] = field(default_factory=dict)
    effort: float | None = None
    org: dict[str, Any] = field(default_factory=dict)
    okbay_workspace_id: str = ""
    commit_path: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Desk:
        now = time()
        st = str(data.get("state") or "working")
        if st not in VALID_DESK_STATES:
            st = "working"
        return cls(
            id=str(data["id"]),
            kind=str(data.get("kind") or "auto"),
            objective=str(data.get("objective") or ""),
            state=st,
            roles=[str(r) for r in (data.get("roles") or [])],
            schedule=data.get("schedule") if isinstance(data.get("schedule"), dict) else None,
            created_at=float(data.get("created_at") or now),
            updated_at=float(data.get("updated_at") or now),
            thread_id=str(data.get("thread_id") or ""),
            dag_relpath=str(data.get("dag_relpath") or ""),
            hire=dict(data.get("hire") or {}),
            effort=(
                float(data["effort"])
                if data.get("effort") is not None and data.get("effort") != ""
                else None
            ),
            org=dict(data.get("org") or {}),
            okbay_workspace_id=str(data.get("okbay_workspace_id") or ""),
            commit_path=(
                dict(data["commit_path"])
                if isinstance(data.get("commit_path"), dict)
                else None
            ),
        )



def dag_is_fully_terminal(g: Any) -> bool:
    """True when every node is done|failed (no pending/ready/running/blocked left).

    Empty DAGs count as terminal. Root is not special: if children are still
    pending/ready after CoS marks root done, the desk is *not* finished.
    """
    nodes = getattr(g, "nodes", None) or {}
    if not nodes:
        return True
    for n in nodes.values():
        st = getattr(n, "state", None) or ""
        if st not in TERMINAL_NODE_STATES:
            return False
    return True



class DeskRegistry:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else state_dir() / REGISTRY_NAME
        self.active_id: str | None = None
        self.focus_id: str | None = None
        self.desks: dict[str, Desk] = {}

    def load(self) -> DeskRegistry:
        self.desks = {}
        self.active_id = None
        self.focus_id = None
        if not self.path.is_file():
            return self
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self
        if not isinstance(raw, dict):
            return self
        self.active_id = raw.get("active_id")
        if self.active_id is not None:
            self.active_id = str(self.active_id) or None
        self.focus_id = raw.get("focus_id")
        if self.focus_id is not None:
            self.focus_id = str(self.focus_id) or None
        for item in raw.get("desks") or []:
            if not isinstance(item, dict) or "id" not in item:
                continue
            d = Desk.from_dict(item)
            # Skip dismissed from standing set? Keep for status history but
            # standing org is only non-dismissed.
            self.desks[d.id] = d
        if self.active_id and self.active_id not in self.desks:
            self.active_id = None
        if self.focus_id and self.focus_id not in self.desks:
            self.focus_id = self.active_id
        if not self.focus_id:
            self.focus_id = self.active_id
        return self

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "updated_at": time(),
            "active_id": self.active_id,
            "focus_id": self.focus_id,
            "desks": [d.to_dict() for d in self.desks.values()],
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.path)

    @classmethod
    def open(cls, path: Path | None = None) -> DeskRegistry:
        return cls(path=path).load()

    def desks_root(self) -> Path:
        return state_dir() / "desks"

    def dag_path_for(self, desk: Desk) -> Path:
        rel = desk.dag_relpath or f"desks/{desk.id}/dag.json"
        return state_dir() / rel

    def standing(self) -> list[Desk]:
        return [d for d in self.desks.values() if d.state != "dismissed"]

    def active(self) -> Desk | None:
        if not self.active_id:
            return None
        d = self.desks.get(self.active_id)
        if d is None or d.state == "dismissed":
            return None
        return d

    def _sync_global_dag_from_desk(self, desk: Desk) -> None:
        """Copy desk DAG into the process-global default dag.json for CLI/panel."""
        src = self.dag_path_for(desk)
        dst = state_dir() / "dag.json"
        if src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        dag_mod._DEFAULT = None
        dag_mod._DEFAULT_PATH = None

    def _persist_desk_dag(self, desk: Desk) -> None:
        """Write current default DAG into the desk's dag file."""
        g = dag_mod.default_dag(force_reload=True)
        dest = self.dag_path_for(desk)
        dest.parent.mkdir(parents=True, exist_ok=True)
        # Save via temporary Dag pointing at desk path
        desk_dag = dag_mod.Dag(path=dest)
        desk_dag.nodes = dict(g.nodes)
        desk_dag.save()
        desk.dag_relpath = str(dest.relative_to(state_dir()))

    # --- lifecycle ---

    def start(
        self,
        objective: str = "",
        *,
        kind: str | None = None,
        reset: bool = False,
        effort: float | None = None,
        run_cos: bool = True,
        okbay_workspace_id: str | None = None,
        workspace_id: str | None = None,
        drive_herdr: bool = False,
    ) -> dict[str, Any]:
        """
        Start (or resume) a desk. Kernel picks kind/roles; always hires CoS.
        Seeds a per-desk DAG and syncs to global dag.json.

        Bind selected okbay workspace when okbay_workspace_id / workspace_id given
        (also persists panel selection).

        ``working`` means an active Herdr run. After CoS breakdown, if we are not
        immediately driving Herdr seats (``drive_herdr=False``, the default), the
        desk lands ``quiet`` (planned / waiting). Pass ``drive_herdr=True`` when
        the caller will run ``herdr.run_ready`` / ``run_one`` next — then the desk
        stays ``working`` until that loop ends and ``maybe_quiet_if_finished``.
        """
        raw = (objective or "").strip()
        # Slash override: "/curate …" wins over an explicit kind and is stripped
        # from the stored objective. Query box defaults to auto when no slash.
        slash_kind, obj = kernel.parse_objective_slash(raw)
        effective_kind = slash_kind or kind
        wid = (okbay_workspace_id or workspace_id or "").strip()
        if wid and wid not in ("local",):
            okbay.set_selected_workspace(wid)
        plan = kernel.spin_up_desk_spec(obj, kind=effective_kind, effort=effort)
        chosen_kind = plan["kind"]
        org = plan.get("org") or kernel.org_from_plan(plan)
        ws = okbay.active_workspace()
        now = time()

        # Resume quiet desk: same objective+kind, or same kind when focusing a quiet rail row
        resumed = None
        if not reset:
            for d in self.standing():
                if d.kind != chosen_kind or d.state != "quiet":
                    continue
                if obj and d.objective == obj:
                    resumed = d
                    break
                if not obj and kind:
                    # Start-from-rail without new query → resume quiet of that kind
                    resumed = d
                    break
            if resumed is None and obj and kind and not reset:
                # New query on existing quiet kind → continue that desk with new objective
                for d in self.standing():
                    if d.kind == chosen_kind and d.state == "quiet":
                        resumed = d
                        break

        if resumed is not None:
            desk = resumed
            desk.state = "working"
            desk.updated_at = now
            if obj:
                desk.objective = obj
            desk.roles = list(plan["roles"])
            desk.hire = plan
            desk.effort = plan.get("effort")
            desk.org = org
            desk.okbay_workspace_id = str(ws.get("id") or "")
            self.active_id = desk.id
            self.focus_id = desk.id
            self._sync_global_dag_from_desk(desk)
        else:
            desk_id = _new_id()
            desk = Desk(
                id=desk_id,
                kind=chosen_kind,
                objective=obj,
                state="working",
                roles=list(plan["roles"]),
                created_at=now,
                updated_at=now,
                thread_id=f"thread-{desk_id}",
                dag_relpath=f"desks/{desk_id}/dag.json",
                hire=plan,
                effort=plan.get("effort"),
                org=org,
                okbay_workspace_id=str(ws.get("id") or ""),
                commit_path=plan.get("commit_path") if plan.get("commit_path", {}).get("configured") else None,
            )
            self.desks[desk.id] = desk
            self.active_id = desk.id
            self.focus_id = desk.id

            # Fresh desk DAG
            dest = self.dag_path_for(desk)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                dest.unlink()
            # Reset global then seat
            g = dag_mod.default_dag(force_reload=True)
            # New desk always gets a clean DAG mirror for its own file.
            g.reset()
            g.seat_root(obj or f"{chosen_kind} desk", reset=False, save=True)
            if run_cos and obj:
                from . import cos

                cos.break_down(obj, kind=chosen_kind)
            self._persist_desk_dag(desk)

        status.set_objective(obj)
        # working == active Herdr run. CoS-only / planned desks land quiet.
        landed_quiet = False
        if not drive_herdr and desk.state == "working":
            desk.state = "quiet"
            desk.updated_at = time()
            landed_quiet = True
        self.save()
        status.write_status()

        return {
            "ok": True,
            "action": "resume" if resumed else "start",
            "desk": desk.to_dict(),
            "hire": plan,
            "active_id": self.active_id,
            "herdr_labels": {
                "desk_id": desk.id,
                "thread_id": desk.thread_id,
                "focus_desk_id": self.focus_id or desk.id,
                "format": "okstratr-{desk}-{role}-{node}",
            },
            "focus_desk_id": self.focus_id or desk.id,
            "effort": desk.effort,
            "org": desk.org,
            "okbay_workspace": ws,
            "drive_herdr": bool(drive_herdr),
            "landed_quiet": landed_quiet,
        }

    def stop(self, desk_id: str | None = None) -> dict[str, Any]:
        """Desk goes quiet; keep last live DAG; CoS remains ready."""
        desk = self._resolve(desk_id)
        if desk is None:
            return {"ok": False, "error": "no active desk to stop"}
        if desk.state == "dismissed":
            return {"ok": False, "error": f"desk {desk.id} already dismissed"}
        # Persist current global DAG onto the desk before quieting
        self._persist_desk_dag(desk)
        desk.state = "quiet"
        desk.updated_at = time()
        self.save()
        web_revoked = None
        try:
            from . import web_egress

            web_revoked = web_egress.on_desk_stop_or_dismiss()
        except Exception:  # noqa: BLE001
            web_revoked = None
        status.write_status()
        return {
            "ok": True,
            "action": "stop",
            "desk": desk.to_dict(),
            "dag_kept": True,
            "cos_ready": roles.ROLE_COS in desk.roles,
            "web_egress": web_revoked,
            "message": "Desk quiet; last live DAG kept; CoS ready for input",
        }

    def dismiss(self, desk_id: str | None = None) -> dict[str, Any]:
        """Disband standing org; archive DAG; clear from active standing set."""
        desk = self._resolve(desk_id)
        if desk is None:
            return {"ok": False, "error": "no desk to dismiss"}
        # Archive DAG
        live = self.dag_path_for(desk)
        archive_dir = state_dir() / "desks" / desk.id / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        archived = None
        if live.is_file():
            archived = archive_dir / f"dag-{int(time())}.json"
            shutil.copy2(live, archived)
            live.unlink()
        # Also archive a copy of current global if this was active
        was_active = self.active_id == desk.id
        if was_active:
            gpath = state_dir() / "dag.json"
            if gpath.is_file() and archived is None:
                archived = archive_dir / f"dag-global-{int(time())}.json"
                shutil.copy2(gpath, archived)
            # Clear standing global DAG
            g = dag_mod.default_dag(force_reload=True)
            g.reset()
            self.active_id = None
            if self.focus_id == desk.id:
                self.focus_id = None
            status.set_objective("")

        desk.state = "dismissed"
        desk.updated_at = time()
        desk.roles = []  # standing org torn down
        if self.focus_id == desk.id:
            self.focus_id = self.active_id
        self.save()
        web_revoked = None
        try:
            from . import web_egress

            web_revoked = web_egress.on_desk_stop_or_dismiss()
        except Exception:  # noqa: BLE001
            web_revoked = None
        status.write_status()
        return {
            "ok": True,
            "action": "dismiss",
            "desk": desk.to_dict(),
            "archived_dag": str(archived) if archived else None,
            "standing_cleared": was_active,
            "web_egress": web_revoked,
            "message": "Desk disbanded; standing org torn down; DAG archived",
        }

    def schedule(
        self,
        args: list[str] | str,
        *,
        desk_id: str | None = None,
    ) -> dict[str, Any]:
        """Parse schedule args and attach to the desk (dialog UI is future)."""
        desk = self._resolve(desk_id)
        if desk is None:
            return {"ok": False, "error": "no desk for schedule (start a desk first)"}
        try:
            parsed = parse_schedule_args(args)
        except ScheduleParseError as e:
            return {"ok": False, "error": str(e)}
        payload = parsed.to_dict()
        payload["describe"] = describe(parsed)
        desk.schedule = payload
        desk.updated_at = time()
        self.save()
        status.write_status()
        return {
            "ok": True,
            "action": "schedule",
            "desk_id": desk.id,
            "schedule": payload,
            "message": "Schedule attached (dialog UI later)",
        }

    def status_snapshot(self) -> dict[str, Any]:
        active = self.active()
        try:
            from . import web_egress

            web = web_egress.status()
        except Exception:  # noqa: BLE001
            web = {"mode": "off", "label": "Off", "chip": "Web: Off"}
        defaults = default_standing_rows(self)
        return {
            "ok": True,
            "active_id": self.active_id,
            "focus_desk_id": self.focus_id or self.active_id,
            "active": active.to_dict() if active else None,
            "standing": defaults,
            "standing_live": [d.to_dict() for d in self.standing()],
            "default_kinds": list(roles.DEFAULT_DESK_KINDS),
            "all": [d.to_dict() for d in self.desks.values()],
            "counts": {
                "working": sum(1 for d in self.desks.values() if d.state == "working"),
                "quiet": sum(1 for d in self.desks.values() if d.state == "quiet"),
                "dismissed": sum(1 for d in self.desks.values() if d.state == "dismissed"),
                "idle": sum(1 for r in defaults if r.get("state") == "idle"),
            },
            "roles_catalog": roles.catalog_summary(),
            "roles_config": roles.load_role_config(),
            "effort": active.effort if active else None,
            "effort_slider": kernel.effort_slider(
                active.effort if active else None,
                desk_id=active.id if active else None,
            ),
            "web_egress": web,
            "okbay_workspace": okbay.active_workspace(),
            "okbay_workspaces": okbay.list_workspaces(),
        }

    def hire(self, request: Any, *, desk_id: str | None = None) -> dict[str, Any]:
        desk = self._resolve(desk_id)
        return kernel.hire(desk, request)

    def retire_worker(
        self,
        node_id: str,
        *,
        desk_id: str | None = None,
        summary: str | None = None,
    ) -> dict[str, Any]:
        desk = self._resolve(desk_id)
        return kernel.retire_worker(node_id, desk=desk, summary=summary)

    def set_effort(self, value: float, *, desk_id: str | None = None) -> dict[str, Any]:
        desk = self._resolve(desk_id)
        return kernel.set_effort(desk, value)

    def focus(self, desk_id: str | None = None) -> dict[str, Any]:
        """Stub: record focus for future bidirectional Herdr sync."""
        from . import herdr as herdr_mod

        return herdr_mod.focus_desk(desk_id)


    def maybe_quiet_if_finished(self, desk_id: str | None = None) -> dict[str, Any]:
        """If a working desk's DAG is fully terminal, stop → quiet (keep DAG).

        Terminal = every node ``done`` or ``failed`` (no pending/ready/running/blocked).
        No-ops when the desk is not working or work remains. Safe to call from
        herdr.run_one / run_ready and status reconcile.
        """
        desk = self._resolve(desk_id)
        if desk is None:
            return {"ok": True, "action": "noop", "reason": "no_desk"}
        if desk.state != "working":
            return {
                "ok": True,
                "action": "noop",
                "reason": f"desk_{desk.state}",
                "desk_id": desk.id,
            }
        g = self._dag_for_desk(desk)
        g.refresh_ready(save=False)
        if not dag_is_fully_terminal(g):
            active = sorted(
                {
                    f"{n.id}:{n.state}"
                    for n in g.nodes.values()
                    if n.state in ACTIVE_NODE_STATES
                }
            )
            return {
                "ok": True,
                "action": "noop",
                "reason": "dag_not_terminal",
                "desk_id": desk.id,
                "active_nodes": active,
            }
        stopped = self.stop(desk.id)
        stopped["action"] = "auto_quiet"
        stopped["reason"] = "dag_fully_terminal"
        return stopped

    def _dag_for_desk(self, desk: Desk) -> Any:
        """Prefer the live global DAG when this desk is active; else desk file."""
        if self.active_id == desk.id:
            return dag_mod.default_dag(force_reload=True)
        path = self.dag_path_for(desk)
        return dag_mod.Dag(path=path).load()

    def _resolve(self, desk_id: str | None) -> Desk | None:
        if desk_id:
            did = str(desk_id)
            if did.startswith(PLACEHOLDER_ID_PREFIX):
                return None  # idle placeholder — no live desk
            return self.desks.get(did)
        return self.active()


_DEFAULT: DeskRegistry | None = None
_DEFAULT_PATH: Path | None = None


def default_registry(*, force_reload: bool = False) -> DeskRegistry:
    global _DEFAULT, _DEFAULT_PATH
    path = state_dir() / REGISTRY_NAME
    if _DEFAULT is None or force_reload or _DEFAULT_PATH != path:
        _DEFAULT = DeskRegistry.open(path)
        _DEFAULT_PATH = path
    return _DEFAULT


def start(objective: str = "", **kwargs: Any) -> dict[str, Any]:
    return default_registry().start(objective, **kwargs)


def stop(desk_id: str | None = None) -> dict[str, Any]:
    return default_registry().stop(desk_id)


def dismiss(desk_id: str | None = None) -> dict[str, Any]:
    return default_registry().dismiss(desk_id)


def schedule(args: list[str] | str, **kwargs: Any) -> dict[str, Any]:
    return default_registry().schedule(args, **kwargs)


def status_snapshot() -> dict[str, Any]:
    return default_registry().status_snapshot()


def hire(request: Any, *, desk_id: str | None = None) -> dict[str, Any]:
    return default_registry().hire(request, desk_id=desk_id)


def retire_worker(
    node_id: str,
    *,
    desk_id: str | None = None,
    summary: str | None = None,
) -> dict[str, Any]:
    return default_registry().retire_worker(node_id, desk_id=desk_id, summary=summary)


def set_effort(value: float, *, desk_id: str | None = None) -> dict[str, Any]:
    return default_registry().set_effort(value, desk_id=desk_id)


def focus(desk_id: str | None = None) -> dict[str, Any]:
    return default_registry().focus(desk_id)


_QUIETING = False


def maybe_quiet_if_finished(desk_id: str | None = None) -> dict[str, Any]:
    """Module entry with reentrancy guard (stop → write_status → reconcile)."""
    global _QUIETING
    if _QUIETING:
        return {"ok": True, "action": "noop", "reason": "reentrant"}
    _QUIETING = True
    try:
        return default_registry().maybe_quiet_if_finished(desk_id)
    finally:
        _QUIETING = False
