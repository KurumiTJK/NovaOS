# kernel/continuity_helpers.py
"""
v0.5.8 — Memory & Continuity (Refined)

Provides continuity helpers that use the Memory Engine to:
- Retrieve user preferences without binding identity
- Track active projects and goals
- Generate gentle re-confirmation prompts
- Frame interpretation responses with context

Core Principle: Continuity Without Constraint
- Memory informs but doesn't dictate
- Preferences are suggestions, not mandates
- Past goals can be questioned, not assumed
- Identity remains fluid and user-controlled
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from .memory_manager import MemoryManager
    from .identity_manager import IdentityManager


# -----------------------------------------------------------------------------
# Data Models
# -----------------------------------------------------------------------------

@dataclass
class UserPreference:
    """A user preference extracted from memory."""
    key: str
    value: Any
    source_memory_id: int
    confidence: float  # How confident we are this is current
    last_confirmed: Optional[str] = None  # ISO timestamp
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "source_memory_id": self.source_memory_id,
            "confidence": self.confidence,
            "last_confirmed": self.last_confirmed,
        }


@dataclass
class ActiveProject:
    """An active project/goal extracted from memory."""
    name: str
    description: str
    source_memory_id: int
    priority: int  # 1 = highest
    status: str  # active, paused, completed, stale
    tags: List[str] = field(default_factory=list)
    last_activity: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "source_memory_id": self.source_memory_id,
            "priority": self.priority,
            "status": self.status,
            "tags": self.tags,
            "last_activity": self.last_activity,
        }


@dataclass
class ContinuityContext:
    """
    Context package for interpretation/response framing.
    """
    preferences: List[UserPreference] = field(default_factory=list)
    projects: List[ActiveProject] = field(default_factory=list)
    identity_summary: Optional[Dict[str, Any]] = None
    stale_items: List[Dict[str, Any]] = field(default_factory=list)  # Items needing re-confirmation
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "preferences": [p.to_dict() for p in self.preferences],
            "projects": [p.to_dict() for p in self.projects],
            "identity_summary": self.identity_summary,
            "stale_items": self.stale_items,
        }

    def get_context_prompt(self) -> str:
        """Generate a context string for LLM prompts."""
        lines = []
        
        if self.identity_summary:
            name = self.identity_summary.get("name")
            if name:
                lines.append(f"User: {name}")
            
            goals = self.identity_summary.get("goals", [])
            if goals:
                lines.append(f"Goals: {', '.join(goals[:3])}")
        
        if self.projects:
            active = [p for p in self.projects if p.status == "active"][:3]
            if active:
                lines.append("Active projects: " + ", ".join(p.name for p in active))
        
        if self.preferences:
            top_prefs = self.preferences[:3]
            pref_strs = [f"{p.key}={p.value}" for p in top_prefs]
            lines.append("Preferences: " + ", ".join(pref_strs))
        
        return "\n".join(lines) if lines else ""


# -----------------------------------------------------------------------------
# Continuity Helpers
# -----------------------------------------------------------------------------

class ContinuityHelpers:
    """
    v0.5.8 Continuity Helpers
    
    Provides memory-based continuity without identity binding:
    - get_user_preferences(): Extract preferences from memory
    - get_active_projects(): Extract active projects/goals
    - get_continuity_context(): Full context for framing
    - generate_reconfirmation_prompts(): Gentle check-in suggestions
    
    All methods are read-only and non-binding.
    """

    # Tags that indicate preferences
    PREFERENCE_TAGS = {
        "preference", "pref", "setting", "like", "dislike",
        "style", "format", "approach",
    }
    
    # Tags that indicate projects/goals
    PROJECT_TAGS = {
        "project", "goal", "objective", "task", "initiative",
        "milestone", "target", "plan",
    }
    
    # Tags that indicate high priority
    PRIORITY_TAGS = {
        "priority", "important", "urgent", "critical", "top",
    }

    def __init__(
        self,
        memory_manager: "MemoryManager",
        identity_manager: Optional["IdentityManager"] = None,
    ):
        self.memory = memory_manager
        self.identity = identity_manager

    # ---------- User Preferences ----------

    def get_user_preferences(
        self,
        limit: int = 20,
        min_confidence: float = 0.3,
    ) -> List[UserPreference]:
        """
        Extract user preferences from memory.
        
        Looks for:
        - Memories tagged with preference-related tags
        - Semantic memories with preference patterns
        - Identity traits (if available)
        
        Returns preferences sorted by confidence.
        """
        preferences: List[UserPreference] = []
        seen_keys: set = set()
        
        # 1. From identity traits
        if self.identity:
            try:
                traits = self.identity.get_traits()
                
                if traits.name:
                    preferences.append(UserPreference(
                        key="name",
                        value=traits.name,
                        source_memory_id=-1,  # From identity, not memory
                        confidence=0.95,
                    ))
                    seen_keys.add("name")
                
                # Values as preferences
                for i, value in enumerate(traits.values[:5]):
                    key = f"value_{i+1}"
                    preferences.append(UserPreference(
                        key=key,
                        value=value,
                        source_memory_id=-1,
                        confidence=0.9,
                    ))
                
                # Custom fields
                for key, value in traits.custom.items():
                    if key not in seen_keys:
                        preferences.append(UserPreference(
                            key=key,
                            value=value,
                            source_memory_id=-1,
                            confidence=0.85,
                        ))
                        seen_keys.add(key)
            except Exception:
                pass
        
        # 2. From memory with preference tags
        pref_tags = list(self.PREFERENCE_TAGS)
        try:
            memories = self.memory.recall(
                tags=pref_tags,
                limit=limit,
            )
            
            for mem in memories:
                # Extract key-value from payload
                extracted = self._extract_preference_from_payload(mem.payload)
                if extracted:
                    key, value = extracted
                    if key not in seen_keys:
                        # Calculate confidence based on memory salience
                        confidence = getattr(mem, "salience", 0.5) * 0.8
                        
                        preferences.append(UserPreference(
                            key=key,
                            value=value,
                            source_memory_id=mem.id,
                            confidence=confidence,
                            last_confirmed=getattr(mem, "last_used_at", None),
                        ))
                        seen_keys.add(key)
        except Exception:
            pass
        
        # 3. From semantic memories with patterns
        try:
            semantic = self.memory.recall(
                mem_type="semantic",
                limit=limit * 2,
            )
            
            for mem in semantic:
                # Look for preference patterns
                extracted = self._extract_preference_from_payload(mem.payload)
                if extracted:
                    key, value = extracted
                    if key not in seen_keys:
                        confidence = getattr(mem, "salience", 0.5) * 0.6
                        if confidence >= min_confidence:
                            preferences.append(UserPreference(
                                key=key,
                                value=value,
                                source_memory_id=mem.id,
                                confidence=confidence,
                            ))
                            seen_keys.add(key)
        except Exception:
            pass
        
        # Sort by confidence
        preferences.sort(key=lambda p: -p.confidence)
        
        return preferences[:limit]

    def _extract_preference_from_payload(
        self,
        payload: str,
    ) -> Optional[Tuple[str, Any]]:
        """
        Try to extract a key-value preference from payload text.
        
        Looks for patterns like:
        - "prefers X"
        - "likes X"
        - "X: Y"
        - "X = Y"
        """
        payload_lower = payload.lower().strip()
        
        # Pattern: "prefers X" or "preference: X"
        for prefix in ["prefers ", "preference: ", "likes ", "favorite "]:
            if payload_lower.startswith(prefix):
                value = payload[len(prefix):].strip()
                key = prefix.replace(":", "").strip()
                return (key, value[:100])
        
        # Pattern: "X: Y" or "X = Y"
        for sep in [": ", " = ", " is "]:
            if sep in payload:
                parts = payload.split(sep, 1)
                if len(parts) == 2:
                    key = parts[0].strip()[:30]
                    value = parts[1].strip()[:100]
                    # Filter out very long keys (probably not a preference)
                    if len(key) <= 30 and len(key) >= 2:
                        return (key.lower().replace(" ", "_"), value)
        
        return None

    # ---------- Active Projects ----------

    def get_active_projects(
        self,
        limit: int = 10,
        include_stale: bool = False,
    ) -> List[ActiveProject]:
        """
        Extract active projects/goals from memory.
        
        Looks for:
        - Memories tagged with project-related tags
        - Procedural memories with goal patterns
        - Identity goals (if available)
        
        Returns projects sorted by priority.
        """
        projects: List[ActiveProject] = []
        seen_names: set = set()
        
        # 1. From identity goals
        if self.identity:
            try:
                traits = self.identity.get_traits()
                
                for i, goal in enumerate(traits.goals[:5]):
                    name = self._normalize_project_name(goal)
                    if name not in seen_names:
                        projects.append(ActiveProject(
                            name=name,
                            description=goal,
                            source_memory_id=-1,
                            priority=i + 1,
                            status="active",
                            tags=["identity_goal"],
                        ))
                        seen_names.add(name)
            except Exception:
                pass
        
        # 2. From memory with project tags
        project_tags = list(self.PROJECT_TAGS)
        try:
            memories = self.memory.recall(
                tags=project_tags,
                limit=limit * 2,
            )
            
            for mem in memories:
                name = self._normalize_project_name(mem.payload[:50])
                if name not in seen_names:
                    # Determine priority from tags
                    priority = 5  # Default medium
                    if any(tag in self.PRIORITY_TAGS for tag in mem.tags):
                        priority = 2
                    
                    # Determine status
                    status = "active"
                    mem_status = getattr(mem, "status", "active")
                    if mem_status == "stale":
                        status = "stale" if include_stale else "active"
                    elif mem_status == "archived":
                        continue  # Skip archived
                    
                    projects.append(ActiveProject(
                        name=name,
                        description=mem.payload[:200],
                        source_memory_id=mem.id,
                        priority=priority,
                        status=status,
                        tags=mem.tags,
                        last_activity=getattr(mem, "last_used_at", None),
                    ))
                    seen_names.add(name)
        except Exception:
            pass
        
        # 3. From procedural memories (skills often relate to projects)
        try:
            procedural = self.memory.recall(
                mem_type="procedural",
                limit=limit,
            )
            
            for mem in procedural:
                # Look for project-like patterns
                payload_lower = mem.payload.lower()
                if any(word in payload_lower for word in ["build", "create", "develop", "learn", "master"]):
                    name = self._normalize_project_name(mem.payload[:50])
                    if name not in seen_names:
                        projects.append(ActiveProject(
                            name=name,
                            description=mem.payload[:200],
                            source_memory_id=mem.id,
                            priority=4,
                            status="active",
                            tags=mem.tags + ["procedural"],
                            last_activity=getattr(mem, "last_used_at", None),
                        ))
                        seen_names.add(name)
        except Exception:
            pass
        
        # Sort by priority
        projects.sort(key=lambda p: p.priority)
        
        return projects[:limit]

    def _normalize_project_name(self, text: str) -> str:
        """Normalize text to a project name."""
        # Remove common prefixes
        prefixes = ["project:", "goal:", "task:", "build ", "create ", "learn "]
        text_lower = text.lower()
        for prefix in prefixes:
            if text_lower.startswith(prefix):
                text = text[len(prefix):]
        
        # Clean up
        name = text.strip()[:50]
        
        # Capitalize first letter of each word
        return " ".join(word.capitalize() for word in name.split()[:6])

    # ---------- Full Context ----------

    def get_continuity_context(self) -> ContinuityContext:
        """
        Get full continuity context for interpretation framing.
        
        Combines preferences, projects, identity, and stale items.
        """
        ctx = ContinuityContext()
        
        # Get preferences
        ctx.preferences = self.get_user_preferences(limit=10)
        
        # Get projects
        ctx.projects = self.get_active_projects(limit=5, include_stale=True)
        
        # Get identity summary
        if self.identity:
            try:
                profile = self.identity.get_current()
                if profile:
                    traits = profile.traits
                    ctx.identity_summary = {
                        "name": traits.name,
                        "goals": traits.goals[:5],
                        "values": traits.values[:5],
                        "context": traits.context,
                        "roles": traits.roles[:3],
                    }
            except Exception:
                pass
        
        # Identify stale items needing re-confirmation
        stale_projects = [p for p in ctx.projects if p.status == "stale"]
        for proj in stale_projects[:3]:
            ctx.stale_items.append({
                "type": "project",
                "name": proj.name,
                "source_id": proj.source_memory_id,
                "suggestion": f"Is '{proj.name}' still an active goal?",
            })
        
        # Low-confidence preferences
        low_conf_prefs = [p for p in ctx.preferences if p.confidence < 0.5]
        for pref in low_conf_prefs[:2]:
            ctx.stale_items.append({
                "type": "preference",
                "key": pref.key,
                "value": pref.value,
                "source_id": pref.source_memory_id,
                "suggestion": f"Do you still prefer {pref.key} = {pref.value}?",
            })
        
        return ctx

    # ---------- Re-confirmation Prompts ----------

    def generate_reconfirmation_prompts(
        self,
        limit: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        Generate gentle re-confirmation prompts for stale items.
        
        These are suggestions, not demands. The user can ignore them.
        """
        prompts = []
        ctx = self.get_continuity_context()
        
        # From stale items
        for item in ctx.stale_items[:limit]:
            prompts.append({
                "type": item["type"],
                "prompt": item["suggestion"],
                "source_id": item["source_id"],
                "tone": "gentle",
            })
        
        # Check for very old high-salience memories
        try:
            important = self.memory.recall(
                min_salience=0.7,
                limit=20,
            ) if hasattr(self.memory, "recall") else []
            
            now = datetime.now(timezone.utc)
            for mem in important:
                last_used = getattr(mem, "last_used_at", None)
                if last_used:
                    try:
                        last_dt = datetime.fromisoformat(last_used.replace("Z", "+00:00"))
                        days_old = (now - last_dt).days
                        if days_old > 60 and len(prompts) < limit:
                            preview = mem.payload[:50]
                            prompts.append({
                                "type": "memory",
                                "prompt": f"You marked this as important {days_old} days ago: '{preview}...' — still relevant?",
                                "source_id": mem.id,
                                "tone": "curious",
                            })
                    except ValueError:
                        pass
        except Exception:
            pass
        
        return prompts[:limit]

    # ---------- Workflow Attachment ----------

    def get_goals_for_workflow(self) -> List[Dict[str, Any]]:
        """
        Get goals suitable for workflow attachment.
        
        Returns goals with enough context for the Time Rhythm engine.
        """
        projects = self.get_active_projects(limit=10)
        
        goals = []
        for proj in projects:
            if proj.status == "active":
                goals.append({
                    "name": proj.name,
                    "description": proj.description,
                    "priority": proj.priority,
                    "tags": proj.tags,
                    "source_id": proj.source_memory_id,
                })
        
        return goals

    def suggest_workflow_for_goal(
        self,
        goal_name: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Suggest a workflow structure for a goal.
        
        This is a helper for the compose command.
        """
        # Find the goal
        projects = self.get_active_projects()
        target = None
        for proj in projects:
            if proj.name.lower() == goal_name.lower():
                target = proj
                break
        
        if not target:
            return None
        
        # Generate basic workflow suggestion
        return {
            "name": f"Work on: {target.name}",
            "goal": target.name,
            "suggested_steps": [
                f"Review current state of {target.name}",
                f"Identify next concrete action",
                f"Execute action",
                f"Document progress",
            ],
            "tags": target.tags,
            "priority": target.priority,
        }


# -----------------------------------------------------------------------------
# Factory Functions
# -----------------------------------------------------------------------------

def create_continuity_helpers(
    memory_manager: "MemoryManager",
    identity_manager: Optional["IdentityManager"] = None,
) -> ContinuityHelpers:
    """Create a ContinuityHelpers instance."""
    return ContinuityHelpers(memory_manager, identity_manager)
