# kernel/lesson_engine/schemas.py
"""
v1.0.0 — Lesson Engine Data Schemas

Defines the core data structures for the retrieval-backed lesson engine.
"""

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone


@dataclass
class EvidenceResource:
    """A verified learning resource from web retrieval."""
    title: str
    provider: str  # e.g., "AWS Skill Builder", "Microsoft Learn", "Coursera"
    type: str  # course, lab, guide, documentation, video, tutorial
    estimated_hours: float
    difficulty: str  # foundational, intermediate, advanced
    url: str
    tags: List[str] = field(default_factory=list)
    description: str = ""
    retrieved_at: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> "EvidenceResource":
        return cls(
            title=data.get("title", ""),
            provider=data.get("provider", ""),
            type=data.get("type", "guide"),
            estimated_hours=float(data.get("estimated_hours", 1.0)),
            difficulty=data.get("difficulty", "foundational"),
            url=data.get("url", ""),
            tags=data.get("tags", []),
            description=data.get("description", ""),
            retrieved_at=data.get("retrieved_at", ""),
        )


@dataclass
class EvidencePack:
    """Evidence pack for a subdomain - verified resources from web retrieval."""
    subdomain: str
    domain: str
    resources: List[EvidenceResource] = field(default_factory=list)
    retrieved_at: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "subdomain": self.subdomain,
            "domain": self.domain,
            "resources": [r.to_dict() for r in self.resources],
            "retrieved_at": self.retrieved_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "EvidencePack":
        resources = [
            EvidenceResource.from_dict(r) if isinstance(r, dict) else r
            for r in data.get("resources", [])
        ]
        return cls(
            subdomain=data.get("subdomain", ""),
            domain=data.get("domain", ""),
            resources=resources,
            retrieved_at=data.get("retrieved_at", ""),
        )


@dataclass
class LessonStep:
    """A single lesson step - 60-120 minutes of focused learning."""
    step_id: str
    step_type: str  # INFO, APPLY, RECALL, BOSS
    title: str
    estimated_time_minutes: int  # Must be 60-120
    goal: str  # What you will understand/accomplish
    actions: List[str]  # Concrete tasks (3-5 items)
    completion_check: str  # "You're done when..."
    
    # Resource references
    resource_refs: List[str] = field(default_factory=list)  # URLs from evidence pack
    
    # Metadata
    domain: str = ""
    subdomain: str = ""
    subtopics: List[str] = field(default_factory=list)
    day_number: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> "LessonStep":
        return cls(
            step_id=data.get("step_id", data.get("id", "")),
            step_type=data.get("step_type", data.get("type", "INFO")),
            title=data.get("title", ""),
            estimated_time_minutes=int(data.get("estimated_time_minutes", 90)),
            goal=data.get("goal", data.get("prompt", "")),
            actions=data.get("actions", []),
            completion_check=data.get("completion_check", ""),
            resource_refs=data.get("resource_refs", []),
            domain=data.get("domain", data.get("_domain", "")),
            subdomain=data.get("subdomain", ""),
            subtopics=data.get("subtopics", []),
            day_number=data.get("day_number"),
        )
    
    def to_quest_step(self) -> Dict[str, Any]:
        """Convert to Quest Engine step format for backwards compatibility."""
        return {
            "id": self.step_id,
            "type": self.step_type.lower(),
            "title": self.title,
            "prompt": self.goal,
            "actions": self.actions,
            "subtopics": self.subtopics,
            "_domain": self.domain,
            "_generation_mode": "lesson_engine",
            "_completion_check": self.completion_check,
            "_resource_refs": self.resource_refs,
            "_estimated_minutes": self.estimated_time_minutes,
        }


@dataclass
class LessonPlan:
    """Complete lesson plan with all steps organized."""
    quest_id: str
    quest_title: str
    total_steps: int
    total_hours: float
    steps: List[LessonStep] = field(default_factory=list)
    evidence_packs: List[EvidencePack] = field(default_factory=list)
    
    # Pacing metadata
    recommended_days: int = 0
    steps_per_day: int = 1
    
    # Generation metadata
    generated_at: str = ""
    engine_version: str = "1.0.0"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "quest_id": self.quest_id,
            "quest_title": self.quest_title,
            "total_steps": self.total_steps,
            "total_hours": self.total_hours,
            "steps": [s.to_dict() for s in self.steps],
            "evidence_packs": [e.to_dict() for e in self.evidence_packs],
            "recommended_days": self.recommended_days,
            "steps_per_day": self.steps_per_day,
            "generated_at": self.generated_at,
            "engine_version": self.engine_version,
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "LessonPlan":
        steps = [
            LessonStep.from_dict(s) if isinstance(s, dict) else s
            for s in data.get("steps", [])
        ]
        evidence_packs = [
            EvidencePack.from_dict(e) if isinstance(e, dict) else e
            for e in data.get("evidence_packs", [])
        ]
        return cls(
            quest_id=data.get("quest_id", ""),
            quest_title=data.get("quest_title", ""),
            total_steps=data.get("total_steps", len(steps)),
            total_hours=data.get("total_hours", 0),
            steps=steps,
            evidence_packs=evidence_packs,
            recommended_days=data.get("recommended_days", 0),
            steps_per_day=data.get("steps_per_day", 1),
            generated_at=data.get("generated_at", ""),
            engine_version=data.get("engine_version", "1.0.0"),
        )
    
    def to_quest_steps(self) -> List[Dict[str, Any]]:
        """Convert all steps to Quest Engine format."""
        return [step.to_quest_step() for step in self.steps]


# =============================================================================
# VALIDATION
# =============================================================================

def validate_lesson_step(step: LessonStep) -> List[str]:
    """Validate a lesson step meets all constraints. Returns list of issues."""
    issues = []
    
    # Time constraint: 60-120 minutes
    if step.estimated_time_minutes < 60:
        issues.append(f"Step '{step.title}' is too short ({step.estimated_time_minutes} min, need 60+)")
    if step.estimated_time_minutes > 120:
        issues.append(f"Step '{step.title}' is too long ({step.estimated_time_minutes} min, max 120)")
    
    # Actions constraint: must have concrete actions
    if not step.actions:
        issues.append(f"Step '{step.title}' has no actions")
    elif len(step.actions) < 2:
        issues.append(f"Step '{step.title}' needs at least 2 actions")
    
    # Vague action check
    vague_patterns = ["learn about", "understand", "study", "explore", "review"]
    for action in step.actions:
        action_lower = action.lower()
        if any(action_lower.startswith(p) for p in vague_patterns):
            if len(action) < 50:  # Short vague actions are bad
                issues.append(f"Step '{step.title}' has vague action: '{action[:50]}'")
    
    # Completion check
    if not step.completion_check:
        issues.append(f"Step '{step.title}' has no completion check")
    
    # Goal
    if not step.goal:
        issues.append(f"Step '{step.title}' has no goal")
    
    return issues


def validate_lesson_plan(plan: LessonPlan) -> List[str]:
    """Validate entire lesson plan. Returns list of issues."""
    all_issues = []
    
    for step in plan.steps:
        step_issues = validate_lesson_step(step)
        all_issues.extend(step_issues)
    
    # Check evidence references (optional but recommended)
    if not plan.evidence_packs:
        all_issues.append("Warning: No evidence packs attached to plan")
    
    return all_issues
