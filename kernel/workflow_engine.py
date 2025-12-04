# FILE: kernel/workflow_engine.py

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


WorkflowStatus = str  # "pending" | "active" | "completed" | "paused" | "halted"

# Default path for workflow persistence
DEFAULT_WORKFLOWS_PATH = "data/workflows.json"


@dataclass
class WorkflowStep:
    """
    A single step in a workflow.
    """
    id: str
    title: str
    description: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Workflow:
    """
    A workflow tracked by the WorkflowEngine.
    """
    id: str
    name: str
    steps: List[WorkflowStep] = field(default_factory=list)
    current_step: int = 0  # 0-based index into steps
    status: WorkflowStatus = "pending"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    meta: Dict[str, Any] = field(default_factory=dict)

    # ---------- Helpers ----------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "steps": [asdict(step) for step in self.steps],
            "current_step": self.current_step,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "last_updated": self.last_updated.isoformat(),
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Workflow":
        steps = [
            WorkflowStep(
                id=s.get("id", f"step-{idx}"),
                title=s.get("title", ""),
                description=s.get("description", ""),
                meta=s.get("meta") or {},
            )
            for idx, s in enumerate(data.get("steps", []))
        ]
        created_at_raw = data.get("created_at")
        last_updated_raw = data.get("last_updated")

        def _parse_dt(value: Optional[str]) -> datetime:
            if not value:
                return datetime.now(timezone.utc)
            try:
                return datetime.fromisoformat(value)
            except Exception:
                return datetime.now(timezone.utc)

        return cls(
            id=data["id"],
            name=data.get("name", data["id"]),
            steps=steps,
            current_step=int(data.get("current_step", 0)),
            status=data.get("status", "pending"),
            created_at=_parse_dt(created_at_raw),
            last_updated=_parse_dt(last_updated_raw),
            meta=data.get("meta") or {},
        )

    def active_step(self) -> Optional[WorkflowStep]:
        if not self.steps:
            return None
        if self.current_step < 0 or self.current_step >= len(self.steps):
            return None
        return self.steps[self.current_step]

    def mark_updated(self) -> None:
        self.last_updated = datetime.now(timezone.utc)


class WorkflowEngine:
    """
    Workflow registry and lifecycle manager with JSON persistence.
    
    v0.7.11: Added automatic JSON persistence for workflows.
    """

    def __init__(
        self, 
        workflows: Optional[Dict[str, Workflow]] = None,
        storage_path: Optional[str] = None,
    ) -> None:
        self._storage_path = storage_path or DEFAULT_WORKFLOWS_PATH
        
        if workflows is not None:
            # Explicit workflows provided (e.g., from tests)
            self._workflows: Dict[str, Workflow] = workflows
        else:
            # Load from disk if available
            self._workflows = {}
            self._load_from_disk()

    # ---------- Persistence ----------

    def _load_from_disk(self) -> None:
        """Load workflows from JSON file if it exists."""
        if not os.path.exists(self._storage_path):
            return
        
        try:
            with open(self._storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            raw = data.get("workflows") or {}
            for wid, wf_data in raw.items():
                try:
                    self._workflows[wid] = Workflow.from_dict(wf_data)
                except Exception:
                    # Skip invalid entries safely
                    continue
        except Exception:
            # If file is corrupted or unreadable, start fresh
            pass

    def _save_to_disk(self) -> None:
        """Save all workflows to JSON file."""
        try:
            # Ensure data directory exists
            dir_path = os.path.dirname(self._storage_path)
            if dir_path:
                os.makedirs(dir_path, exist_ok=True)
            
            data = {
                "workflows": {wid: wf.to_dict() for wid, wf in self._workflows.items()},
                "last_saved": datetime.now(timezone.utc).isoformat(),
            }
            
            with open(self._storage_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception:
            # Silently fail persistence (better than crashing)
            pass

    # ---------- Serialization ----------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "workflows": {wid: wf.to_dict() for wid, wf in self._workflows.items()},
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowEngine":
        raw = data.get("workflows") or {}
        workflows: Dict[str, Workflow] = {}
        for wid, wf_data in raw.items():
            try:
                workflows[wid] = Workflow.from_dict(wf_data)
            except Exception:
                # Skip invalid entries safely
                continue
        return cls(workflows=workflows)

    # ---------- Core API ----------

    def list_workflows(self) -> List[Workflow]:
        return list(self._workflows.values())

    def get(self, workflow_id: str) -> Optional[Workflow]:
        return self._workflows.get(workflow_id)

    def upsert(self, workflow: Workflow) -> Workflow:
        self._workflows[workflow.id] = workflow
        self._save_to_disk()  # v0.7.11: Persist on change
        return workflow

    def delete(self, workflow_id: str) -> bool:
        if workflow_id in self._workflows:
            del self._workflows[workflow_id]
            self._save_to_disk()  # v0.7.11: Persist on change
            return True
        return False

    # ---------- Lifecycle helpers ----------

    def start(
        self,
        workflow_id: str,
        name: Optional[str] = None,
        steps: Optional[List[Dict[str, Any]]] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> Workflow:
        """
        Start (or restart) a workflow.
        If it already exists, reset it to the beginning.
        """
        step_objs: List[WorkflowStep] = []
        for idx, s in enumerate(steps or []):
            step_objs.append(
                WorkflowStep(
                    id=s.get("id", f"{workflow_id}-step-{idx+1}"),
                    title=s.get("title", f"Step {idx+1}"),
                    description=s.get("description", ""),
                    meta=s.get("meta") or {},
                )
            )

        wf = Workflow(
            id=workflow_id,
            name=name or workflow_id,
            steps=step_objs,
            current_step=0,
            status="active" if step_objs else "pending",
            meta=meta or {},
        )
        self._workflows[workflow_id] = wf
        self._save_to_disk()  # v0.7.11: Persist on change
        return wf

    def advance(self, workflow_id: str) -> Optional[Workflow]:
        """
        Move the workflow to the next step.
        If already at the final step, mark as completed.
        """
        wf = self._workflows.get(workflow_id)
        if not wf:
            return None

        if not wf.steps:
            wf.status = "completed"
            wf.mark_updated()
            self._save_to_disk()  # v0.7.11: Persist on change
            return wf

        if wf.status not in ("active", "pending"):
            # Do not advance halted/completed workflows
            return wf

        if wf.current_step + 1 >= len(wf.steps):
            # Last step -> complete workflow
            wf.current_step = len(wf.steps) - 1
            wf.status = "completed"
        else:
            if wf.status == "pending":
                wf.status = "active"
            wf.current_step += 1

        wf.mark_updated()
        self._save_to_disk()  # v0.7.11: Persist on change
        return wf

    def halt(self, workflow_id: str, status: WorkflowStatus = "paused") -> Optional[Workflow]:
        """
        Pause or halt a workflow.
        """
        wf = self._workflows.get(workflow_id)
        if not wf:
            return None

        wf.status = status
        wf.mark_updated()
        self._save_to_disk()  # v0.7.11: Persist on change
        return wf
    
    def resume(self, workflow_id: str) -> Optional[Workflow]:
        """
        Resume a paused/halted workflow (set status back to active).
        """
        wf = self._workflows.get(workflow_id)
        if not wf:
            return None
        
        if wf.status in ("paused", "halted", "pending"):
            wf.status = "active"
            wf.mark_updated()
            self._save_to_disk()
        
        return wf

    # ---------- Introspection / summaries ----------

    def summarize(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        wf = self._workflows.get(workflow_id)
        if not wf:
            return None
        return self._summary_dict(wf)

    def summarize_all(self) -> List[Dict[str, Any]]:
        return [self._summary_dict(wf) for wf in self._workflows.values()]

    @staticmethod
    def _summary_dict(wf: Workflow) -> Dict[str, Any]:
        active = wf.active_step()
        return {
            "id": wf.id,
            "name": wf.name,
            "status": wf.status,
            "current_step_index": wf.current_step,
            "total_steps": len(wf.steps),
            "active_step_title": active.title if active else None,
            "last_updated": wf.last_updated.isoformat(),
            "meta": wf.meta,
        }
