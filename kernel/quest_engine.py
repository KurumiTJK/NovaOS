# kernel/quest_engine.py
"""
v0.8.0 — NovaOS Quest Engine

A complete replacement for the legacy workflow system.
Implements gamified learning quests with XP, skills, streaks, and boss battles.

Key concepts:
- Quest: A structured learning path with multiple steps
- Step: An individual learning activity (info, recall, apply, reflect, boss, etc.)
- RunState: Tracks progress through an active quest
- Progress: Persistent storage of XP, skills, streaks, and completion history

Commands:
- #quest         - Open Quest Board, start/resume quests
- #next          - Advance to next step
- #pause         - Pause active quest
- #quest-log     - View progress, XP, skills, streaks
- #quest-reset   - Reset quest progress
- #quest-compose - Create new quest with LLM
- #quest-delete  - Delete a quest
- #quest-list    - List all quest definitions
- #quest-inspect - Inspect quest details
- #quest-debug   - Debug output
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Literal
from enum import Enum


# =============================================================================
# TYPE DEFINITIONS
# =============================================================================

StepType = Literal["info", "action", "recall", "reflect", "apply", "transfer", "mini_boss", "boss"]
ValidationMode = Literal["none", "keyword", "llm_rubric", "self_check"]
QuestStatus = Literal["not_started", "in_progress", "paused", "completed", "abandoned"]
StepStatus = Literal["pending", "completed", "skipped", "failed"]


# =============================================================================
# VALIDATION CONFIG
# =============================================================================

@dataclass
class ValidationConfig:
    """Configuration for step validation."""
    mode: ValidationMode = "none"
    keywords: Optional[List[str]] = None  # For "keyword" mode
    rubric: Optional[str] = None  # For "llm_rubric" mode
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "keywords": self.keywords,
            "rubric": self.rubric,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ValidationConfig":
        return cls(
            mode=data.get("mode", "none"),
            keywords=data.get("keywords"),
            rubric=data.get("rubric"),
        )


# =============================================================================
# STEP MODEL
# =============================================================================

@dataclass
class Step:
    """A single step in a quest."""
    id: str
    type: StepType
    prompt: str
    title: Optional[str] = None
    help_text: Optional[str] = None
    skill_focus: Optional[List[str]] = None
    difficulty: int = 1  # 1-5
    min_reflection_chars: Optional[int] = None
    validation: Optional[ValidationConfig] = None
    passing_threshold: float = 0.7  # For boss steps
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "prompt": self.prompt,
            "title": self.title,
            "help_text": self.help_text,
            "skill_focus": self.skill_focus,
            "difficulty": self.difficulty,
            "min_reflection_chars": self.min_reflection_chars,
            "validation": self.validation.to_dict() if self.validation else None,
            "passing_threshold": self.passing_threshold,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Step":
        validation = None
        if data.get("validation"):
            validation = ValidationConfig.from_dict(data["validation"])
        
        return cls(
            id=data["id"],
            type=data.get("type", "info"),
            prompt=data.get("prompt", ""),
            title=data.get("title"),
            help_text=data.get("help_text"),
            skill_focus=data.get("skill_focus"),
            difficulty=data.get("difficulty", 1),
            min_reflection_chars=data.get("min_reflection_chars"),
            validation=validation,
            passing_threshold=data.get("passing_threshold", 0.7),
        )
    
    @property
    def is_boss(self) -> bool:
        return self.type in ("boss", "mini_boss")
    
    @property
    def xp_value(self) -> int:
        """Calculate XP value for this step."""
        if self.type == "info":
            return 0
        elif self.type == "boss":
            return 5 * self.difficulty
        elif self.type == "mini_boss":
            return 2 * self.difficulty
        else:
            return self.difficulty


# =============================================================================
# REWARD BUNDLE
# =============================================================================

@dataclass
class RewardBundle:
    """Rewards granted upon quest completion."""
    xp: int = 0
    titles: List[str] = field(default_factory=list)  # v0.8.0: Titles to award
    shortcuts: List[str] = field(default_factory=list)
    visual_unlock: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "xp": self.xp,
            "titles": self.titles,
            "shortcuts": self.shortcuts,
            "visual_unlock": self.visual_unlock,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RewardBundle":
        return cls(
            xp=data.get("xp", 0),
            titles=data.get("titles", []),
            shortcuts=data.get("shortcuts", []),
            visual_unlock=data.get("visual_unlock"),
        )


# =============================================================================
# QUEST MODEL
# =============================================================================

@dataclass
class Quest:
    """A complete quest definition."""
    id: str
    title: str
    subtitle: Optional[str] = None
    description: Optional[str] = None
    category: str = "general"  # cyber, finance, real_estate, meta, etc.
    module_id: Optional[str] = None  # v0.8.0: Links quest to a module/region
    skill_tree_path: str = "general"  # e.g., "cyber.jwt.tier1"
    difficulty: int = 1  # 1-5
    estimated_minutes: int = 15
    tags: List[str] = field(default_factory=list)
    steps: List[Step] = field(default_factory=list)
    rewards: Optional[RewardBundle] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
    def __post_init__(self):
        # If module_id not set, derive from category
        if self.module_id is None:
            self.module_id = self.category
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "subtitle": self.subtitle,
            "description": self.description,
            "category": self.category,
            "module_id": self.module_id,
            "skill_tree_path": self.skill_tree_path,
            "difficulty": self.difficulty,
            "estimated_minutes": self.estimated_minutes,
            "tags": self.tags,
            "steps": [s.to_dict() for s in self.steps],
            "rewards": self.rewards.to_dict() if self.rewards else None,
            "created_at": self.created_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Quest":
        steps = [Step.from_dict(s) for s in data.get("steps", [])]
        rewards = None
        if data.get("rewards"):
            rewards = RewardBundle.from_dict(data["rewards"])
        
        return cls(
            id=data["id"],
            title=data.get("title", data["id"]),
            subtitle=data.get("subtitle"),
            description=data.get("description"),
            category=data.get("category", "general"),
            module_id=data.get("module_id"),
            skill_tree_path=data.get("skill_tree_path", "general"),
            difficulty=data.get("difficulty", 1),
            estimated_minutes=data.get("estimated_minutes", 15),
            tags=data.get("tags", []),
            steps=steps,
            rewards=rewards,
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
        )
    
    @property
    def boss_step(self) -> Optional[Step]:
        """Get the boss step if one exists."""
        for step in self.steps:
            if step.type == "boss":
                return step
        return None
    
    @property
    def has_boss(self) -> bool:
        return self.boss_step is not None
    
    @property
    def total_xp(self) -> int:
        """Calculate total possible XP for this quest."""
        step_xp = sum(s.xp_value for s in self.steps)
        reward_xp = self.rewards.xp if self.rewards else 0
        return step_xp + reward_xp


# =============================================================================
# STEP RUN STATE
# =============================================================================

@dataclass
class StepRunState:
    """Runtime state for a single step."""
    status: StepStatus = "pending"
    user_input: Optional[str] = None
    validated: bool = False
    score: Optional[float] = None
    completed_at: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "user_input": self.user_input,
            "validated": self.validated,
            "score": self.score,
            "completed_at": self.completed_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StepRunState":
        return cls(
            status=data.get("status", "pending"),
            user_input=data.get("user_input"),
            validated=data.get("validated", False),
            score=data.get("score"),
            completed_at=data.get("completed_at"),
        )


# =============================================================================
# RUN STATE
# =============================================================================

@dataclass
class RunState:
    """Runtime state for an active quest."""
    run_id: str
    quest_id: str
    status: QuestStatus = "in_progress"
    current_step_index: int = 0
    steps_state: Dict[str, StepRunState] = field(default_factory=dict)
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    mode: str = "normal"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "quest_id": self.quest_id,
            "status": self.status,
            "current_step_index": self.current_step_index,
            "steps_state": {k: v.to_dict() for k, v in self.steps_state.items()},
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "mode": self.mode,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RunState":
        steps_state = {
            k: StepRunState.from_dict(v)
            for k, v in data.get("steps_state", {}).items()
        }
        return cls(
            run_id=data["run_id"],
            quest_id=data["quest_id"],
            status=data.get("status", "in_progress"),
            current_step_index=data.get("current_step_index", 0),
            steps_state=steps_state,
            started_at=data.get("started_at", datetime.now(timezone.utc).isoformat()),
            updated_at=data.get("updated_at", datetime.now(timezone.utc).isoformat()),
            mode=data.get("mode", "normal"),
        )
    
    def mark_updated(self) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat()


# =============================================================================
# STEP RESULT
# =============================================================================

@dataclass
class StepResult:
    """Result of advancing through a step."""
    step_id: str
    status: Literal["passed", "failed", "skipped"]
    score: float  # 0-1
    feedback_text: str
    xp_gained: int
    is_boss: bool
    quest_completed: bool
    next_step: Optional[Step] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "status": self.status,
            "score": self.score,
            "feedback_text": self.feedback_text,
            "xp_gained": self.xp_gained,
            "is_boss": self.is_boss,
            "quest_completed": self.quest_completed,
            "next_step": self.next_step.to_dict() if self.next_step else None,
        }


# =============================================================================
# QUEST SUMMARY (for listings)
# =============================================================================

@dataclass
class QuestSummary:
    """Summary of a quest for listings."""
    id: str
    title: str
    category: str
    difficulty: int
    has_boss: bool
    step_count: int
    status: QuestStatus = "not_started"
    module_id: Optional[str] = None  # v0.8.0: Links quest to a region
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "category": self.category,
            "module_id": self.module_id,
            "difficulty": self.difficulty,
            "has_boss": self.has_boss,
            "step_count": self.step_count,
            "status": self.status,
        }


# =============================================================================
# PROGRESS STATE
# =============================================================================

@dataclass
class SkillProgress:
    """Progress in a skill tree path."""
    xp: int = 0
    current_tier: int = 1
    
    def to_dict(self) -> Dict[str, Any]:
        return {"xp": self.xp, "current_tier": self.current_tier}
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SkillProgress":
        return cls(xp=data.get("xp", 0), current_tier=data.get("current_tier", 1))


@dataclass
class StreakInfo:
    """Learning streak tracking."""
    current: int = 0
    longest: int = 0
    last_date: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "current": self.current,
            "longest": self.longest,
            "last_date": self.last_date,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StreakInfo":
        return cls(
            current=data.get("current", 0),
            longest=data.get("longest", 0),
            last_date=data.get("last_date"),
        )


@dataclass
class QuestRunProgress:
    """Progress for a single quest."""
    status: QuestStatus = "not_started"
    last_step_id: Optional[str] = None
    attempts: int = 0
    completed_at: Optional[str] = None
    xp_earned: int = 0
    boss_cleared: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "last_step_id": self.last_step_id,
            "attempts": self.attempts,
            "completed_at": self.completed_at,
            "xp_earned": self.xp_earned,
            "boss_cleared": self.boss_cleared,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "QuestRunProgress":
        return cls(
            status=data.get("status", "not_started"),
            last_step_id=data.get("last_step_id"),
            attempts=data.get("attempts", 0),
            completed_at=data.get("completed_at"),
            xp_earned=data.get("xp_earned", 0),
            boss_cleared=data.get("boss_cleared", False),
        )


@dataclass
class ProgressState:
    """Complete progress state."""
    quest_runs: Dict[str, QuestRunProgress] = field(default_factory=dict)
    skills: Dict[str, SkillProgress] = field(default_factory=dict)
    streaks: Dict[str, StreakInfo] = field(default_factory=dict)
    meta: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "quest_runs": {k: v.to_dict() for k, v in self.quest_runs.items()},
            "skills": {k: v.to_dict() for k, v in self.skills.items()},
            "streaks": {k: v.to_dict() for k, v in self.streaks.items()},
            "meta": self.meta,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProgressState":
        return cls(
            quest_runs={k: QuestRunProgress.from_dict(v) for k, v in data.get("quest_runs", {}).items()},
            skills={k: SkillProgress.from_dict(v) for k, v in data.get("skills", {}).items()},
            streaks={k: StreakInfo.from_dict(v) for k, v in data.get("streaks", {}).items()},
            meta=data.get("meta", {}),
        )


# =============================================================================
# QUEST ENGINE
# =============================================================================

class QuestEngine:
    """
    The Quest Engine - manages quests, runs, and progress.
    
    Replaces the legacy WorkflowEngine with a gamified learning system.
    """
    
    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = data_dir or Path("data")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # File paths
        self.quests_file = self.data_dir / "quests.json"
        self.progress_file = self.data_dir / "quest_progress.json"
        self.active_run_file = self.data_dir / "quest_active_run.json"
        
        # Load data
        self._quests: Dict[str, Quest] = self._load_quests()
        self._progress: ProgressState = self._load_progress()
        self._active_run: Optional[RunState] = self._load_active_run()
    
    # ─────────────────────────────────────────────────────────────────────
    # PERSISTENCE
    # ─────────────────────────────────────────────────────────────────────
    
    def _load_quests(self) -> Dict[str, Quest]:
        """Load quest definitions from disk."""
        if not self.quests_file.exists():
            # Create default quests
            default = self._create_example_quests()
            self._save_quests(default)
            return default
        
        try:
            with open(self.quests_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {k: Quest.from_dict(v) for k, v in data.items()}
        except Exception as e:
            print(f"[QuestEngine] Error loading quests: {e}", flush=True)
            return {}
    
    def _save_quests(self, quests: Optional[Dict[str, Quest]] = None) -> None:
        """Save quest definitions to disk."""
        quests = quests or self._quests
        data = {k: v.to_dict() for k, v in quests.items()}
        with open(self.quests_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def _load_progress(self) -> ProgressState:
        """Load progress from disk."""
        if not self.progress_file.exists():
            return ProgressState()
        
        try:
            with open(self.progress_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return ProgressState.from_dict(data)
        except Exception as e:
            print(f"[QuestEngine] Error loading progress: {e}", flush=True)
            return ProgressState()
    
    def _save_progress(self) -> None:
        """Save progress to disk."""
        with open(self.progress_file, "w", encoding="utf-8") as f:
            json.dump(self._progress.to_dict(), f, indent=2, ensure_ascii=False)
    
    def _load_active_run(self) -> Optional[RunState]:
        """Load active run from disk."""
        if not self.active_run_file.exists():
            return None
        
        try:
            with open(self.active_run_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not data:
                return None
            return RunState.from_dict(data)
        except Exception as e:
            print(f"[QuestEngine] Error loading active run: {e}", flush=True)
            return None
    
    def _save_active_run(self) -> None:
        """Save active run to disk."""
        data = self._active_run.to_dict() if self._active_run else {}
        with open(self.active_run_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def _clear_active_run(self) -> None:
        """Clear the active run."""
        self._active_run = None
        if self.active_run_file.exists():
            self.active_run_file.unlink()
    
    # ─────────────────────────────────────────────────────────────────────
    # EXAMPLE QUESTS
    # ─────────────────────────────────────────────────────────────────────
    
    def _create_example_quests(self) -> Dict[str, Quest]:
        """Create example quests for testing."""
        return {
            "jwt_intro": Quest(
                id="jwt_intro",
                title="JWT Fundamentals",
                subtitle="Understanding JSON Web Tokens",
                description="Learn the basics of JWT structure, encoding, and common vulnerabilities.",
                category="cyber",
                skill_tree_path="cyber.jwt.tier1",
                difficulty=2,
                estimated_minutes=20,
                tags=["learning", "security", "authentication"],
                steps=[
                    Step(
                        id="step_1",
                        type="info",
                        title="What is a JWT?",
                        prompt="A JSON Web Token (JWT) is a compact, URL-safe means of representing claims between two parties.\n\nJWTs have three parts separated by dots:\n• Header (algorithm + type)\n• Payload (claims/data)\n• Signature (verification)\n\nExample: `eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.signature`\n\nType **next** when ready to continue.",
                        help_text="JWTs are commonly used for authentication and information exchange.",
                    ),
                    Step(
                        id="step_2",
                        type="recall",
                        title="JWT Structure",
                        prompt="What are the three parts of a JWT? List them in order.",
                        help_text="Think about what we just covered: header, payload, and...",
                        difficulty=1,
                        validation=ValidationConfig(
                            mode="keyword",
                            keywords=["header", "payload", "signature"],
                        ),
                    ),
                    Step(
                        id="step_3",
                        type="reflect",
                        title="Security Implications",
                        prompt="Why might it be dangerous to trust a JWT's payload without verifying the signature?",
                        help_text="Consider what an attacker could do if they modified the payload.",
                        difficulty=2,
                        min_reflection_chars=50,
                    ),
                    Step(
                        id="step_4",
                        type="apply",
                        title="Decode a JWT",
                        prompt="Given this JWT header (base64): `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9`\n\nDecode it and tell me what algorithm is being used.",
                        help_text="Base64 decode the header to see the JSON inside.",
                        difficulty=2,
                        validation=ValidationConfig(
                            mode="keyword",
                            keywords=["HS256", "HMAC", "SHA256"],
                        ),
                    ),
                    Step(
                        id="boss",
                        type="boss",
                        title="JWT Security Challenge",
                        prompt="Explain a real-world attack scenario where JWT misconfiguration could lead to unauthorized access. Include:\n1. The vulnerability\n2. How an attacker would exploit it\n3. How to prevent it",
                        help_text="Think about algorithm confusion, weak secrets, or missing validation.",
                        difficulty=3,
                        min_reflection_chars=100,
                        passing_threshold=0.7,
                    ),
                ],
                rewards=RewardBundle(
                    xp=25,
                    shortcuts=["jwt-decode"],
                    visual_unlock="🔐",
                ),
            ),
            "nova_basics": Quest(
                id="nova_basics",
                title="NovaOS Basics",
                subtitle="Getting Started with Nova",
                description="Learn the core commands and concepts of NovaOS.",
                category="meta",
                skill_tree_path="meta.nova.basics",
                difficulty=1,
                estimated_minutes=10,
                tags=["learning", "meta", "tutorial"],
                steps=[
                    Step(
                        id="step_1",
                        type="info",
                        title="Welcome to NovaOS",
                        prompt="NovaOS is your personal AI operating system. It helps you:\n\n• Store and recall memories\n• Track learning progress\n• Manage workflows and quests\n• Build custom commands\n\nAll commands start with `#`. For example: `#help`, `#status`, `#quest`\n\nType **next** to continue.",
                    ),
                    Step(
                        id="step_2",
                        type="action",
                        title="Try a Command",
                        prompt="Try running `#status` to see your current NovaOS state.\n\nThen type **next** to continue.",
                        help_text="Commands always start with # symbol.",
                        difficulty=1,
                    ),
                    Step(
                        id="step_3",
                        type="recall",
                        title="Command Basics",
                        prompt="What symbol do all NovaOS commands start with?",
                        difficulty=1,
                        validation=ValidationConfig(
                            mode="keyword",
                            keywords=["#", "hash", "hashtag"],
                        ),
                    ),
                ],
                rewards=RewardBundle(xp=10),
            ),
        }
    
    # ─────────────────────────────────────────────────────────────────────
    # PUBLIC API - QUEST MANAGEMENT
    # ─────────────────────────────────────────────────────────────────────
    
    def list_quests(self, category: Optional[str] = None) -> List[QuestSummary]:
        """List all quests with optional category filter."""
        summaries = []
        for quest_id, quest in self._quests.items():
            if category and quest.category != category:
                continue
            
            # Get status from progress
            progress = self._progress.quest_runs.get(quest_id)
            status: QuestStatus = progress.status if progress else "not_started"
            
            summaries.append(QuestSummary(
                id=quest.id,
                title=quest.title,
                category=quest.category,
                difficulty=quest.difficulty,
                has_boss=quest.has_boss,
                step_count=len(quest.steps),
                status=status,
                module_id=quest.module_id,  # v0.8.0
            ))
        
        return summaries
    
    def get_quest(self, quest_id: str) -> Optional[Quest]:
        """Get a quest by ID."""
        return self._quests.get(quest_id)
    
    def start_quest(self, quest_id: str, mode: str = "normal") -> Optional[RunState]:
        """Start or resume a quest."""
        quest = self._quests.get(quest_id)
        if not quest:
            return None
        
        # Check for existing active run
        if self._active_run and self._active_run.quest_id == quest_id:
            # Resume existing run
            return self._active_run
        
        # Clear any other active run
        if self._active_run:
            self.pause_quest(self._active_run.run_id, reason="starting_new")
        
        # Check if we're resuming a paused quest
        progress = self._progress.quest_runs.get(quest_id)
        start_index = 0
        if progress and progress.status == "in_progress" and progress.last_step_id:
            # Find the step index
            for i, step in enumerate(quest.steps):
                if step.id == progress.last_step_id:
                    start_index = i
                    break
        
        # Create new run
        run = RunState(
            run_id=str(uuid.uuid4())[:8],
            quest_id=quest_id,
            status="in_progress",
            current_step_index=start_index,
            mode=mode,
        )
        
        # Update progress
        if quest_id not in self._progress.quest_runs:
            self._progress.quest_runs[quest_id] = QuestRunProgress()
        self._progress.quest_runs[quest_id].status = "in_progress"
        self._progress.quest_runs[quest_id].attempts += 1
        self._progress.meta["last_run_id"] = quest_id
        self._progress.meta["last_run_date"] = date.today().isoformat()
        
        self._active_run = run
        self._save_active_run()
        self._save_progress()
        
        return run
    
    def advance_quest(self, run_id: str, user_input: str) -> Tuple[Optional[RunState], Optional[StepResult]]:
        """Advance the quest with user input."""
        if not self._active_run or self._active_run.run_id != run_id:
            return None, None
        
        quest = self._quests.get(self._active_run.quest_id)
        if not quest:
            return None, None
        
        run = self._active_run
        current_index = run.current_step_index
        
        if current_index >= len(quest.steps):
            # Quest already complete
            return run, None
        
        current_step = quest.steps[current_index]
        
        # Validate and score the step
        score, passed, feedback = self._validate_step(current_step, user_input)
        
        # Calculate XP
        xp_gained = current_step.xp_value if passed else 0
        
        # Update step state
        run.steps_state[current_step.id] = StepRunState(
            status="completed" if passed else "failed",
            user_input=user_input,
            validated=True,
            score=score,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
        
        # Move to next step
        quest_completed = False
        next_step = None
        
        if passed:
            run.current_step_index += 1
            if run.current_step_index >= len(quest.steps):
                # Quest complete!
                quest_completed = True
                run.status = "completed"
                self._complete_quest(quest, run, xp_gained)
            else:
                next_step = quest.steps[run.current_step_index]
        
        # Update progress tracking
        progress = self._progress.quest_runs.get(quest.id)
        if progress:
            progress.last_step_id = current_step.id
            progress.xp_earned += xp_gained
            if current_step.is_boss and passed:
                progress.boss_cleared = True
        
        # Update learning streak
        self._update_streak(quest)
        
        # Add XP to skill
        if xp_gained > 0:
            self._add_skill_xp(quest.skill_tree_path, xp_gained)
        
        run.mark_updated()
        self._save_active_run()
        self._save_progress()
        
        result = StepResult(
            step_id=current_step.id,
            status="passed" if passed else "failed",
            score=score,
            feedback_text=feedback,
            xp_gained=xp_gained,
            is_boss=current_step.is_boss,
            quest_completed=quest_completed,
            next_step=next_step,
        )
        
        return run, result
    
    def pause_quest(self, run_id: str, reason: str = "user") -> Optional[RunState]:
        """Pause the active quest."""
        if not self._active_run or self._active_run.run_id != run_id:
            return None
        
        run = self._active_run
        run.status = "paused"
        run.mark_updated()
        
        # Update progress
        progress = self._progress.quest_runs.get(run.quest_id)
        if progress:
            progress.status = "in_progress"  # Keep as in_progress, not paused
        
        self._save_progress()
        self._clear_active_run()
        
        return run
    
    def get_active_run(self) -> Optional[RunState]:
        """Get the currently active run."""
        return self._active_run
    
    def get_progress(self) -> ProgressState:
        """Get the full progress state."""
        return self._progress
    
    def reset_quest_progress(self, quest_id: str) -> bool:
        """Reset progress for a quest."""
        if quest_id in self._progress.quest_runs:
            del self._progress.quest_runs[quest_id]
        
        # Clear active run if it's this quest
        if self._active_run and self._active_run.quest_id == quest_id:
            self._clear_active_run()
        
        self._save_progress()
        return True
    
    # ─────────────────────────────────────────────────────────────────────
    # PUBLIC API - AUTHORING
    # ─────────────────────────────────────────────────────────────────────
    
    def create_quest_from_spec(self, spec: Dict[str, Any]) -> Quest:
        """Create a new quest from a specification."""
        quest = Quest.from_dict(spec)
        self._quests[quest.id] = quest
        self._save_quests()
        return quest
    
    def add_quest(self, quest: Quest) -> Quest:
        """
        Add a Quest object directly to the quest store and persist it.
        
        This is a low-level helper used when another subsystem (e.g. Inbox)
        constructs a Quest instance and wants to register it with the engine.
        
        Args:
            quest: A fully constructed Quest instance
            
        Returns:
            The same quest, for convenience
        """
        self._quests[quest.id] = quest
        self._save_quests()
        return quest
    
    def delete_quest(self, quest_id: str) -> bool:
        """Delete a quest and its progress."""
        if quest_id not in self._quests:
            return False
        
        del self._quests[quest_id]
        self._save_quests()
        
        # Also remove progress
        if quest_id in self._progress.quest_runs:
            del self._progress.quest_runs[quest_id]
            self._save_progress()
        
        # Clear active run if it's this quest
        if self._active_run and self._active_run.quest_id == quest_id:
            self._clear_active_run()
        
        return True
    
    def list_quest_definitions(self) -> List[QuestSummary]:
        """List all quest definitions (admin view)."""
        return self.list_quests()
    
    def inspect_quest(self, quest_id: str) -> Optional[Quest]:
        """Get full quest details for inspection."""
        return self.get_quest(quest_id)
    
    # ─────────────────────────────────────────────────────────────────────
    # INTERNAL HELPERS
    # ─────────────────────────────────────────────────────────────────────
    
    def _validate_step(self, step: Step, user_input: str) -> Tuple[float, bool, str]:
        """Validate user input for a step. Returns (score, passed, feedback)."""
        # Info steps always pass
        if step.type == "info":
            return 1.0, True, "Great! Moving on..."
        
        # Check minimum reflection length
        if step.min_reflection_chars and len(user_input.strip()) < step.min_reflection_chars:
            return 0.3, False, f"Please provide a more detailed response (at least {step.min_reflection_chars} characters)."
        
        # Validation based on mode
        if not step.validation or step.validation.mode == "none":
            # No validation - auto pass
            return 1.0, True, "✓ Response recorded."
        
        if step.validation.mode == "keyword":
            # Keyword matching
            keywords = step.validation.keywords or []
            input_lower = user_input.lower()
            matched = sum(1 for kw in keywords if kw.lower() in input_lower)
            score = matched / len(keywords) if keywords else 1.0
            
            if score >= 0.5:
                return score, True, "✓ Correct! You covered the key points."
            else:
                return score, False, f"Not quite. Try to include more key concepts. Hint: {step.help_text or 'Review the material.'}"
        
        if step.validation.mode == "self_check":
            # Self-check - always passes but prompts reflection
            return 1.0, True, "✓ Self-check complete. Reflect on your answer as we continue."
        
        # LLM rubric validation would go here (requires LLM integration)
        if step.validation.mode == "llm_rubric":
            # For now, auto-pass with note
            return 0.8, True, "✓ Response recorded. (LLM validation pending)"
        
        return 1.0, True, "✓ Response recorded."
    
    def _complete_quest(self, quest: Quest, run: RunState, final_step_xp: int) -> None:
        """Handle quest completion."""
        progress = self._progress.quest_runs.get(quest.id)
        if not progress:
            progress = QuestRunProgress()
            self._progress.quest_runs[quest.id] = progress
        
        progress.status = "completed"
        progress.completed_at = datetime.now(timezone.utc).isoformat()
        
        # Add reward XP
        if quest.rewards:
            progress.xp_earned += quest.rewards.xp
            self._add_skill_xp(quest.skill_tree_path, quest.rewards.xp)
        
        self._clear_active_run()
    
    def _add_skill_xp(self, skill_path: str, xp: int) -> None:
        """Add XP to a skill path."""
        if skill_path not in self._progress.skills:
            self._progress.skills[skill_path] = SkillProgress()
        
        skill = self._progress.skills[skill_path]
        skill.xp += xp
        
        # Update tier based on XP thresholds
        # Tier 1: 0-49, Tier 2: 50-149, Tier 3: 150-299, Tier 4: 300-499, Tier 5: 500+
        thresholds = [0, 50, 150, 300, 500]
        for tier, threshold in enumerate(thresholds, 1):
            if skill.xp >= threshold:
                skill.current_tier = tier
    
    def _update_streak(self, quest: Quest) -> None:
        """Update learning streak if quest has 'learning' tag."""
        if "learning" not in quest.tags:
            return
        
        today = date.today().isoformat()
        
        if "learning_days" not in self._progress.streaks:
            self._progress.streaks["learning_days"] = StreakInfo()
        
        streak = self._progress.streaks["learning_days"]
        
        if streak.last_date == today:
            # Already logged today
            return
        
        if streak.last_date:
            # Check if yesterday
            from datetime import timedelta
            yesterday = (date.today() - timedelta(days=1)).isoformat()
            if streak.last_date == yesterday:
                streak.current += 1
            else:
                # Streak broken
                streak.current = 1
        else:
            streak.current = 1
        
        streak.last_date = today
        if streak.current > streak.longest:
            streak.longest = streak.current
    
    # ─────────────────────────────────────────────────────────────────────
    # DEBUG
    # ─────────────────────────────────────────────────────────────────────
    
    def get_debug_state(self) -> Dict[str, Any]:
        """Get debug state dump."""
        return {
            "active_run": self._active_run.to_dict() if self._active_run else None,
            "progress": self._progress.to_dict(),
            "quest_count": len(self._quests),
            "quest_ids": list(self._quests.keys()),
        }
