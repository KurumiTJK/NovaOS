# kernel/strategist.py
"""
v0.8.0 — Strategist Module for NovaOS Life RPG

The Strategist provides READ-ONLY analysis and recommendations:
- Analyze current state and suggest actions
- Route goals to relevant modules/quests
- Provide insights on patterns and progress

This module NEVER modifies state - it only reads and interprets.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .command_types import CommandResponse


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class Recommendation:
    """A recommended action."""
    action: str
    reason: str
    priority: int  # 1=high, 2=medium, 3=low
    command: Optional[str] = None  # Suggested command to run
    
    @property
    def priority_icon(self) -> str:
        if self.priority == 1:
            return "🔴"
        elif self.priority == 2:
            return "🟡"
        return "🟢"


@dataclass
class RouteResult:
    """Result of routing a goal."""
    goal: str
    relevant_modules: List[Dict[str, Any]]
    relevant_quests: List[Dict[str, Any]]
    suggested_actions: List[str]
    new_quest_suggested: bool = False


@dataclass
class InsightReport:
    """Analysis insights."""
    strengths: List[str]
    areas_for_growth: List[str]
    patterns: List[str]
    recommendations: List[str]


# =============================================================================
# HELPERS
# =============================================================================

def _base_response(cmd: str, summary: str, data: Dict[str, Any] = None) -> CommandResponse:
    return CommandResponse(
        ok=True,
        command=cmd,
        summary=summary,
        data=data or {},
    )


def _error_response(cmd: str, message: str, code: str) -> CommandResponse:
    return CommandResponse(
        ok=False,
        command=cmd,
        summary=message,
        error_code=code,
    )


# =============================================================================
# ANALYZE COMMAND
# =============================================================================

def handle_analyze(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """
    Analyze current state and suggest best actions for right now.
    
    This is a READ-ONLY command that examines:
    - Active quests and progress
    - Inbox items (especially high priority)
    - Player energy/state (if available)
    - Recent activity patterns
    
    Usage:
        #analyze
    """
    recommendations: List[Recommendation] = []
    
    # Get assistant mode for formatting
    mode_mgr = getattr(kernel, 'assistant_mode_manager', None)
    show_fancy = mode_mgr and mode_mgr.is_story_mode()
    
    # --- Check for active quest ---
    quest_engine = getattr(kernel, 'quest_engine', None)
    if quest_engine:
        active_run = quest_engine.get_active_run()
        if active_run:
            quest = quest_engine.get_quest(active_run.quest_id)
            if quest:
                step_num = active_run.current_step_index + 1
                total_steps = len(quest.steps)
                recommendations.append(Recommendation(
                    action=f"Continue quest: {quest.title}",
                    reason=f"You're on step {step_num}/{total_steps}",
                    priority=1,
                    command="#next",
                ))
    
    # --- Check inbox for high priority items ---
    inbox = getattr(kernel, 'inbox_store', None)
    if inbox:
        unprocessed = inbox.list_unprocessed()
        high_priority = [i for i in unprocessed if i.priority == 1]
        
        if high_priority:
            item = high_priority[0]
            recommendations.append(Recommendation(
                action=f"Process urgent inbox: {item.content[:40]}...",
                reason="High priority item waiting",
                priority=1,
                command=f"#inbox {item.id}",
            ))
        elif len(unprocessed) >= 5:
            recommendations.append(Recommendation(
                action="Process inbox backlog",
                reason=f"{len(unprocessed)} items waiting",
                priority=2,
                command="#inbox",
            ))
    
    # --- Check for quests to start ---
    if quest_engine:
        active_run = quest_engine.get_active_run()
        if not active_run:
            quests = quest_engine.list_quests()
            available = [q for q in quests if q.status in ("available", "not_started")]
            if available:
                recommendations.append(Recommendation(
                    action="Start a new quest",
                    reason=f"{len(available)} quest(s) available",
                    priority=2,
                    command="#quest",
                ))
    
    # --- Check player profile for domain suggestions ---
    profile_mgr = getattr(kernel, 'player_profile_manager', None)
    module_store = getattr(kernel, 'module_store', None)
    
    if profile_mgr and module_store:
        profile = profile_mgr.get_profile()
        modules = module_store.list_all()
        
        # Find modules with no progress
        for module in modules:
            if module.id not in profile.domains or profile.domains[module.id].xp == 0:
                recommendations.append(Recommendation(
                    action=f"Explore {module.realm_name}",
                    reason="No progress in this domain yet",
                    priority=3,
                    command=f"#quest {module.id}",
                ))
                break  # Only suggest one
    
    # --- Build output ---
    if not recommendations:
        if show_fancy:
            summary = (
                "🔮 **Strategist Analysis**\n\n"
                "All clear! No urgent actions detected.\n\n"
                "Consider:\n"
                "• `#capture` — Capture a new idea\n"
                "• `#quest-compose` — Create a new quest\n"
                "• `#modules` — Explore the world map"
            )
        else:
            summary = "No urgent actions. Consider capturing ideas or creating quests."
    else:
        if show_fancy:
            lines = ["🔮 **Strategist Analysis**", ""]
            for i, rec in enumerate(recommendations, 1):
                lines.append(f"{rec.priority_icon} **{rec.action}**")
                lines.append(f"   {rec.reason}")
                if rec.command:
                    lines.append(f"   → `{rec.command}`")
                lines.append("")
        else:
            lines = ["Recommended actions:", ""]
            for i, rec in enumerate(recommendations, 1):
                lines.append(f"{i}. {rec.action}")
                if rec.command:
                    lines.append(f"   Command: {rec.command}")
        
        summary = "\n".join(lines)
    
    return _base_response(cmd_name, summary, {
        "recommendations": [
            {"action": r.action, "reason": r.reason, "priority": r.priority, "command": r.command}
            for r in recommendations
        ]
    })


# =============================================================================
# ROUTE COMMAND
# =============================================================================

def handle_route(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """
    Map a goal to relevant modules, quests, and suggested actions.
    
    This is a READ-ONLY command that helps you figure out
    how to achieve a goal using your existing NovaOS setup.
    
    Usage:
        #route Learn JWT attacks
        #route goal="Improve my cloud security skills"
    """
    # Parse goal from args
    goal = ""
    if isinstance(args, dict):
        goal = args.get("goal", "")
        positional = args.get("_", [])
        if not goal and positional:
            goal = " ".join(str(p) for p in positional)
    elif isinstance(args, str):
        goal = args
    
    if not goal:
        return _error_response(
            cmd_name,
            "Usage: `#route <goal>` or `#route goal=\"...\"`\n\n"
            "Example: `#route Learn about Kubernetes networking`",
            "MISSING_GOAL",
        )
    
    # Get assistant mode
    mode_mgr = getattr(kernel, 'assistant_mode_manager', None)
    show_fancy = mode_mgr and mode_mgr.is_story_mode()
    
    # Analyze goal keywords (simple keyword matching)
    goal_lower = goal.lower()
    keywords = goal_lower.split()
    
    # --- Find relevant modules ---
    module_store = getattr(kernel, 'module_store', None)
    relevant_modules = []
    
    if module_store:
        modules = module_store.list_all()
        for module in modules:
            # Check if module name/description matches goal keywords
            module_text = f"{module.name} {module.description} {module.id}".lower()
            matches = sum(1 for kw in keywords if kw in module_text)
            if matches > 0:
                relevant_modules.append({
                    "id": module.id,
                    "name": module.realm_name,
                    "icon": module.icon,
                    "match_score": matches,
                })
        
        # Sort by match score
        relevant_modules.sort(key=lambda x: -x["match_score"])
    
    # --- Find relevant quests ---
    quest_engine = getattr(kernel, 'quest_engine', None)
    relevant_quests = []
    
    if quest_engine:
        quests = quest_engine.list_quests()
        for quest in quests:
            # Check if quest title/category matches
            quest_text = f"{quest.title} {quest.category} {quest.id}".lower()
            matches = sum(1 for kw in keywords if kw in quest_text)
            if matches > 0:
                relevant_quests.append({
                    "id": quest.id,
                    "title": quest.title,
                    "status": quest.status,
                    "match_score": matches,
                })
        
        relevant_quests.sort(key=lambda x: -x["match_score"])
    
    # --- Build suggestions ---
    suggestions = []
    
    if relevant_quests:
        best_quest = relevant_quests[0]
        if best_quest["status"] in ("available", "not_started"):
            suggestions.append(f"Start quest: **{best_quest['title']}** (`#quest {best_quest['id']}`)")
        elif best_quest["status"] == "in_progress":
            suggestions.append(f"Continue quest: **{best_quest['title']}** (`#next`)")
    
    if relevant_modules and not relevant_quests:
        best_module = relevant_modules[0]
        suggestions.append(f"Explore {best_module['icon']} {best_module['name']} (`#quest {best_module['id']}`)")
    
    if not relevant_quests:
        suggestions.append(f"Create a new quest: `#quest-compose` with goal: \"{goal}\"")
    
    # Add to inbox suggestion
    suggestions.append(f"Capture for later: `#capture {goal}`")
    
    # --- Build output ---
    if show_fancy:
        lines = [
            "🧭 **Goal Router**",
            "",
            f"**Goal:** {goal}",
            "",
        ]
        
        if relevant_modules:
            lines.append("**Relevant Domains:**")
            for mod in relevant_modules[:3]:
                lines.append(f"  {mod['icon']} {mod['name']}")
            lines.append("")
        
        if relevant_quests:
            lines.append("**Related Quests:**")
            for quest in relevant_quests[:3]:
                status_icon = "🎯" if quest["status"] == "in_progress" else "📜"
                lines.append(f"  {status_icon} {quest['title']}")
            lines.append("")
        
        lines.append("**Suggested Path:**")
        for i, sug in enumerate(suggestions, 1):
            lines.append(f"  {i}. {sug}")
    else:
        lines = [f"Goal: {goal}", ""]
        
        if relevant_modules:
            lines.append(f"Modules: {', '.join(m['name'] for m in relevant_modules[:3])}")
        if relevant_quests:
            lines.append(f"Quests: {', '.join(q['title'] for q in relevant_quests[:3])}")
        
        lines.append("")
        lines.append("Actions:")
        for sug in suggestions:
            lines.append(f"- {sug}")
    
    summary = "\n".join(lines)
    
    return _base_response(cmd_name, summary, {
        "goal": goal,
        "relevant_modules": relevant_modules[:3],
        "relevant_quests": relevant_quests[:3],
        "suggestions": suggestions,
    })


# =============================================================================
# INSIGHT COMMAND
# =============================================================================

def handle_insight(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """
    Summarize patterns, strengths, and areas for growth.
    
    This is a READ-ONLY command that analyzes your overall
    NovaOS usage and progress to provide strategic insights.
    
    Usage:
        #insight
        #insight domain=cyber
    """
    # Get assistant mode
    mode_mgr = getattr(kernel, 'assistant_mode_manager', None)
    show_fancy = mode_mgr and mode_mgr.is_story_mode()
    
    # Parse optional domain filter
    domain_filter = None
    if isinstance(args, dict):
        domain_filter = args.get("domain") or args.get("module")
        positional = args.get("_", [])
        if not domain_filter and positional:
            domain_filter = positional[0]
    elif isinstance(args, str):
        domain_filter = args
    
    # Gather data
    profile_mgr = getattr(kernel, 'player_profile_manager', None)
    quest_engine = getattr(kernel, 'quest_engine', None)
    module_store = getattr(kernel, 'module_store', None)
    inbox = getattr(kernel, 'inbox_store', None)
    
    strengths = []
    growth_areas = []
    patterns = []
    recommendations = []
    
    # --- Analyze player profile ---
    if profile_mgr:
        profile = profile_mgr.get_profile()
        
        # Find strongest domains
        sorted_domains = sorted(
            profile.domains.items(),
            key=lambda x: x[1].xp,
            reverse=True
        )
        
        if sorted_domains:
            top_domains = [(k, v) for k, v in sorted_domains if v.xp > 0][:3]
            if top_domains:
                for domain_id, domain_data in top_domains:
                    # Get module name if available
                    module = module_store.get(domain_id) if module_store else None
                    name = module.realm_name if module else domain_id.title()
                    strengths.append(f"{name}: {domain_data.xp} XP (Tier {domain_data.tier})")
        
        # Check for domains with no progress
        if module_store:
            modules = module_store.list_all()
            for module in modules:
                if module.id not in profile.domains or profile.domains[module.id].xp == 0:
                    growth_areas.append(f"{module.realm_name} — unexplored")
        
        # Level insight
        if profile.level >= 5:
            patterns.append(f"Veteran player at Level {profile.level}")
        elif profile.level >= 2:
            patterns.append(f"Growing player at Level {profile.level}")
        else:
            patterns.append("New player — just getting started!")
    
    # --- Analyze quest completion ---
    if quest_engine:
        progress = quest_engine.get_progress()
        # Check status == "completed" or completed_at is set
        completed_count = sum(
            1 for q in progress.quest_runs.values() 
            if q.status == "completed" or q.completed_at is not None
        )
        total_quests = len(quest_engine.list_quests())
        
        if completed_count > 0:
            patterns.append(f"Completed {completed_count} quest(s)")
        
        if total_quests > completed_count + 3:
            recommendations.append("Many quests available — consider focusing on one domain")
    
    # --- Analyze inbox ---
    if inbox:
        unprocessed = inbox.count_unprocessed()
        if unprocessed > 10:
            patterns.append(f"Large inbox backlog ({unprocessed} items)")
            recommendations.append("Consider processing inbox to stay organized")
        elif unprocessed > 0:
            patterns.append(f"{unprocessed} item(s) in inbox")
    
    # --- Default insights if empty ---
    if not strengths:
        strengths.append("No domain progress yet — start a quest to begin!")
    
    if not growth_areas and module_store and module_store.count() == 0:
        growth_areas.append("Create modules to define your learning domains")
    
    if not recommendations:
        recommendations.append("Keep exploring and completing quests!")
    
    # --- Build output ---
    if show_fancy:
        lines = ["🔮 **Strategic Insight Report**", ""]
        
        lines.append("**Strengths:**")
        for s in strengths:
            lines.append(f"  ✨ {s}")
        lines.append("")
        
        if growth_areas:
            lines.append("**Areas for Growth:**")
            for g in growth_areas:
                lines.append(f"  🌱 {g}")
            lines.append("")
        
        lines.append("**Patterns:**")
        for p in patterns:
            lines.append(f"  📊 {p}")
        lines.append("")
        
        lines.append("**Recommendations:**")
        for r in recommendations:
            lines.append(f"  💡 {r}")
    else:
        lines = ["Insight Report", ""]
        
        lines.append("Strengths: " + "; ".join(strengths))
        if growth_areas:
            lines.append("Growth areas: " + "; ".join(growth_areas))
        lines.append("Patterns: " + "; ".join(patterns))
        lines.append("Recommendations: " + "; ".join(recommendations))
    
    summary = "\n".join(lines)
    
    return _base_response(cmd_name, summary, {
        "strengths": strengths,
        "growth_areas": growth_areas,
        "patterns": patterns,
        "recommendations": recommendations,
    })


# =============================================================================
# HANDLER REGISTRY
# =============================================================================

STRATEGIST_HANDLERS = {
    "handle_analyze": handle_analyze,
    "handle_route": handle_route,
    "handle_insight": handle_insight,
}


def get_strategist_handlers():
    """Get all strategist handlers for registration."""
    return STRATEGIST_HANDLERS
