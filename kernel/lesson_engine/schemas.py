# kernel/lesson_engine/schemas.py
"""
v2.0.0 — Lesson Engine Data Schemas

Defines the core data structures for the retrieval-backed lesson engine.

v2.0 Changes:
- Added resource_type field for gap detection
- Added estimated_minutes alongside estimated_hours
- Added source_subdomain for explicit mapping
- Added LessonManifest for coverage tracking
- Added GapReport for gap detection results
"""

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone


# =============================================================================
# RESOURCE TYPES
# =============================================================================

RESOURCE_TYPES = [
    "official_docs",  # Vendor documentation
    "hands_on",       # Labs, tutorials, exercises
    "video",          # Video courses/tutorials
    "lab",            # Dedicated lab environments
    "reference",      # Reference guides, cheat sheets
    "course",         # Full courses
    "tutorial",       # Step-by-step tutorials
    "guide",          # General guides
]


# =============================================================================
# EVIDENCE (Phase A)
# =============================================================================

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
    
    # v2.0 fields
    resource_type: str = "reference"  # official_docs, hands_on, video, lab, reference
    estimated_minutes: int = 60  # Direct minutes (easier for step sizing)
    source_subdomain: str = ""  # Which subdomain this was retrieved for
    prereqs: List[str] = field(default_factory=list)  # Optional prerequisites
    
    def __post_init__(self):
        """Ensure estimated_minutes is set from hours if not provided."""
        if self.estimated_minutes == 60 and self.estimated_hours:
            self.estimated_minutes = int(self.estimated_hours * 60)
        
        # Auto-classify resource_type from type if not set
        if self.resource_type == "reference":
            type_lower = self.type.lower()
            if type_lower in ("documentation", "docs", "official_docs"):
                self.resource_type = "official_docs"
            elif type_lower in ("lab", "hands_on", "exercise", "hands-on"):
                self.resource_type = "hands_on"
            elif type_lower in ("video", "youtube"):
                self.resource_type = "video"
            elif type_lower in ("tutorial", "guide"):
                self.resource_type = "tutorial"
            elif type_lower == "course":
                self.resource_type = "course"
    
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
            resource_type=data.get("resource_type", "reference"),
            estimated_minutes=int(data.get("estimated_minutes", 60)),
            source_subdomain=data.get("source_subdomain", ""),
            prereqs=data.get("prereqs", []),
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
    
    def has_resource_type(self, resource_type: str) -> bool:
        """Check if this pack has a resource of the given type."""
        return any(r.resource_type == resource_type for r in self.resources)
    
    def get_total_minutes(self) -> int:
        """Get total estimated minutes across all resources."""
        return sum(r.estimated_minutes for r in self.resources)


# =============================================================================
# MANIFEST (Coverage Tracking)
# =============================================================================

@dataclass
class LessonManifest:
    """
    Manifest of expected coverage for lesson generation.
    Created when domains+subdomains are confirmed.
    """
    domains: List[Dict[str, Any]] = field(default_factory=list)
    constraints: Dict[str, Any] = field(default_factory=lambda: {
        "daily_minutes": 90,
        "step_minutes_range": [60, 120],
        "max_resources_per_subdomain": 5,
        "max_patch_attempts_per_subdomain": 2,
    })
    created_at: str = ""
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "domains": self.domains,
            "constraints": self.constraints,
            "created_at": self.created_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "LessonManifest":
        return cls(
            domains=data.get("domains", []),
            constraints=data.get("constraints", {}),
            created_at=data.get("created_at", ""),
        )
    
    @classmethod
    def from_domains(cls, domains: List[Dict[str, Any]]) -> "LessonManifest":
        """Create manifest from confirmed domains with subdomains."""
        manifest_domains = []
        
        for d in domains:
            domain_entry = {
                "name": d.get("name", ""),
                "subdomains": d.get("subdomains", d.get("subtopics", [])),
                "required_resource_types": ["official_docs", "hands_on", "reference"],
            }
            manifest_domains.append(domain_entry)
        
        return cls(domains=manifest_domains)
    
    def get_all_subdomains(self) -> List[Dict[str, str]]:
        """Get flat list of all subdomains with their parent domains."""
        result = []
        for d in self.domains:
            domain_name = d.get("name", "")
            for subdomain in d.get("subdomains", []):
                result.append({"domain": domain_name, "subdomain": subdomain})
        return result
    
    def count_subdomains(self) -> int:
        """Count total subdomains."""
        return sum(len(d.get("subdomains", [])) for d in self.domains)


# =============================================================================
# GAP DETECTION
# =============================================================================

@dataclass
class Gap:
    """A detected gap in coverage."""
    domain: str
    subdomain: str
    reason: str
    attempts: int = 0
    resolved: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> "Gap":
        return cls(
            domain=data.get("domain", ""),
            subdomain=data.get("subdomain", ""),
            reason=data.get("reason", ""),
            attempts=data.get("attempts", 0),
            resolved=data.get("resolved", False),
        )


@dataclass
class GapReport:
    """Report of gap detection and patching results."""
    resolved_gaps: List[Gap] = field(default_factory=list)
    unresolved_gaps: List[Gap] = field(default_factory=list)
    generated_at: str = ""
    
    def __post_init__(self):
        if not self.generated_at:
            self.generated_at = datetime.now(timezone.utc).isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "resolved_gaps": [g.to_dict() for g in self.resolved_gaps],
            "unresolved_gaps": [g.to_dict() for g in self.unresolved_gaps],
            "generated_at": self.generated_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "GapReport":
        resolved = [Gap.from_dict(g) for g in data.get("resolved_gaps", [])]
        unresolved = [Gap.from_dict(g) for g in data.get("unresolved_gaps", [])]
        return cls(
            resolved_gaps=resolved,
            unresolved_gaps=unresolved,
            generated_at=data.get("generated_at", ""),
        )
    
    def has_unresolved(self) -> bool:
        """Check if there are any unresolved gaps."""
        return len(self.unresolved_gaps) > 0


# =============================================================================
# LESSON STEPS (Phase B)
# =============================================================================

# Action types for validation
ACTION_TYPES = {
    "read": ["read", "watch", "study", "review", "explore"],
    "do": ["build", "create", "configure", "deploy", "implement", "write", "complete"],
    "verify": ["test", "verify", "check", "validate", "quiz", "summarize", "explain"],
}


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
    subdomains_covered: List[str] = field(default_factory=list)  # v2.0: explicit subdomain mapping
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
            subdomains_covered=data.get("subdomains_covered", []),
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
            "subtopics": self.subtopics or self.subdomains_covered,
            "_domain": self.domain,
            "_generation_mode": "lesson_engine",
            "_completion_check": self.completion_check,
            "_resource_refs": self.resource_refs,
            "_estimated_minutes": self.estimated_time_minutes,
            "_subdomains_covered": self.subdomains_covered,
        }
    
    def get_action_types(self) -> Dict[str, List[str]]:
        """Categorize actions by type (read/do/verify)."""
        result = {"read": [], "do": [], "verify": [], "other": []}
        
        for action in self.actions:
            action_lower = action.lower()
            categorized = False
            
            for action_type, keywords in ACTION_TYPES.items():
                if any(action_lower.startswith(kw) or f" {kw} " in action_lower for kw in keywords):
                    result[action_type].append(action)
                    categorized = True
                    break
            
            if not categorized:
                result["other"].append(action)
        
        return result
    
    def has_required_action_types(self) -> bool:
        """Check if step has at least one read, one do, and one verify action."""
        types = self.get_action_types()
        return bool(types["read"]) and bool(types["do"]) and bool(types["verify"])


# =============================================================================
# LESSON PLAN (Final Output)
# =============================================================================

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
    engine_version: str = "2.0.0"
    
    # v2.0: Gap report reference
    gap_report: Optional[GapReport] = None
    coverage_summary: str = ""
    
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
            "gap_report": self.gap_report.to_dict() if self.gap_report else None,
            "coverage_summary": self.coverage_summary,
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
        gap_report = None
        if data.get("gap_report"):
            gap_report = GapReport.from_dict(data["gap_report"])
        
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
            engine_version=data.get("engine_version", "2.0.0"),
            gap_report=gap_report,
            coverage_summary=data.get("coverage_summary", ""),
        )
    
    def to_quest_steps(self) -> List[Dict[str, Any]]:
        """Convert all steps to Quest Engine format."""
        return [step.to_quest_step() for step in self.steps]
    
    def get_covered_subdomains(self) -> List[str]:
        """Get list of all subdomains covered by steps."""
        covered = set()
        for step in self.steps:
            if step.subdomain:
                covered.add(step.subdomain)
            for sd in step.subdomains_covered:
                covered.add(sd)
        return list(covered)


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


def validate_step_action_types(step: LessonStep) -> List[str]:
    """Validate that step has required action types (read/do/verify)."""
    issues = []
    types = step.get_action_types()
    
    if not types["read"]:
        issues.append(f"Step '{step.title}' missing read/reference action")
    if not types["do"]:
        issues.append(f"Step '{step.title}' missing do/build action")
    if not types["verify"]:
        issues.append(f"Step '{step.title}' missing verify/check action")
    
    return issues


def validate_subdomain_coverage(
    steps: List[LessonStep],
    manifest: LessonManifest,
) -> Dict[str, Any]:
    """
    Validate that all subdomains are covered by at least one step.
    
    Returns:
        Dict with 'covered', 'missing', and 'coverage_percent' keys
    """
    # Get all expected subdomains
    expected = set()
    for entry in manifest.get_all_subdomains():
        expected.add(entry["subdomain"])
    
    # Get covered subdomains
    covered = set()
    for step in steps:
        if step.subdomain:
            covered.add(step.subdomain)
        for sd in step.subdomains_covered:
            covered.add(sd)
        for st in step.subtopics:
            covered.add(st)
    
    # Calculate
    missing = expected - covered
    coverage_percent = (len(covered & expected) / len(expected) * 100) if expected else 100
    
    return {
        "covered": list(covered & expected),
        "missing": list(missing),
        "coverage_percent": round(coverage_percent, 1),
        "total_expected": len(expected),
        "total_covered": len(covered & expected),
    }


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
