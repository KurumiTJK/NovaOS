# kernel/jobs_api.py
"""
NovaOS Jobs API — v1.0.0

Flask routes for async job management.

Usage in app.py or nova_api.py:
    
    from kernel.jobs_api import register_jobs_routes
    register_jobs_routes(app)
    
Or manually add routes:
    
    from kernel.jobs_api import (
        api_create_quest_compose_job,
        api_get_job,
    )
"""

from __future__ import annotations

from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from flask import Flask


# =============================================================================
# ROUTE HANDLERS
# =============================================================================

def api_create_quest_compose_job(request_data: Dict[str, Any], user_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Create an async quest compose job.
    
    Args:
        request_data: Request payload with text, session_id, etc.
        user_id: Optional user identifier
        
    Returns:
        {"job_id": "...", "status": "queued"}
    """
    from kernel.utils.job_queue import create_and_enqueue_job
    from kernel.utils.kv_factory import is_kv_configured
    
    if not is_kv_configured():
        return {
            "error": "Async jobs not configured. Set KV_URL and KV_TOKEN.",
            "status": "error",
        }
    
    # Get the session draft for the worker
    session_id = request_data.get("session_id", "")
    draft = None
    
    try:
        from kernel.quests.quest_compose_wizard import get_compose_session
        session = get_compose_session(session_id)
        if session and session.draft:
            draft = session.draft
            print(f"[JobsAPI] Got draft for session {session_id}: {draft.get('title', 'untitled')}", flush=True)
    except Exception as e:
        print(f"[JobsAPI] Could not get session draft: {e}", flush=True)
    
    if not draft:
        return {
            "error": "No active quest compose session found. Start with #quest-compose first.",
            "status": "error",
        }
    
    try:
        # Include the draft in the job payload
        input_payload = {
            **request_data,
            "draft": draft,
        }
        
        job_id = create_and_enqueue_job(
            job_type="quest_compose",
            input_payload=input_payload,
            user_id=user_id,
        )
        
        return {
            "job_id": job_id,
            "status": "queued",
            "message": "Job created. Poll /api/jobs/{job_id} for status.",
        }
        
    except Exception as e:
        return {
            "error": str(e),
            "status": "error",
        }


def api_create_lesson_generate_job(request_data: Dict[str, Any], user_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Create an async lesson generation job.
    
    Args:
        request_data: Request payload with quest_id, etc.
        user_id: Optional user identifier
        
    Returns:
        {"job_id": "...", "status": "queued"}
    """
    from kernel.utils.job_queue import create_and_enqueue_job
    from kernel.utils.kv_factory import is_kv_configured
    
    if not is_kv_configured():
        return {
            "error": "Async jobs not configured. Set KV_URL and KV_TOKEN.",
            "status": "error",
        }
    
    try:
        job_id = create_and_enqueue_job(
            job_type="lesson_generate",
            input_payload=request_data,
            user_id=user_id,
        )
        
        return {
            "job_id": job_id,
            "status": "queued",
            "message": "Job created. Poll /api/jobs/{job_id} for status.",
        }
        
    except Exception as e:
        return {
            "error": str(e),
            "status": "error",
        }


def api_create_engine_job(
    request_data: Dict[str, Any], 
    pipeline: str = "default",
    total_passes: int = 4,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a generic async engine job (multi-pass pipeline).
    
    Args:
        request_data: Request payload
        pipeline: Pipeline name
        total_passes: Number of passes
        user_id: Optional user identifier
        
    Returns:
        {"job_id": "...", "status": "queued"}
    """
    from kernel.utils.job_queue import create_and_enqueue_job
    from kernel.utils.kv_factory import is_kv_configured
    
    if not is_kv_configured():
        return {
            "error": "Async jobs not configured. Set KV_URL and KV_TOKEN.",
            "status": "error",
        }
    
    try:
        input_payload = {
            **request_data,
            "pipeline": pipeline,
            "total_passes": total_passes,
        }
        
        job_id = create_and_enqueue_job(
            job_type="engine_run",
            input_payload=input_payload,
            user_id=user_id,
        )
        
        return {
            "job_id": job_id,
            "status": "queued",
            "message": "Job created. Poll /api/jobs/{job_id} for status.",
        }
        
    except Exception as e:
        return {
            "error": str(e),
            "status": "error",
        }


def api_get_job(job_id: str) -> Dict[str, Any]:
    """
    Get job status and result.
    
    Args:
        job_id: Job identifier
        
    Returns:
        Job record or error
    """
    from kernel.utils.job_queue import get_job
    from kernel.utils.kv_factory import is_kv_configured
    
    if not is_kv_configured():
        return {
            "error": "Async jobs not configured.",
            "status": "error",
        }
    
    job = get_job(job_id)
    
    if not job:
        return {
            "error": f"Job {job_id} not found",
            "status": "error",
        }
    
    return job


def api_sync_quest_steps(session_id: str, steps: list) -> Dict[str, Any]:
    """
    Sync generated steps back to the session.
    
    Called by frontend after async job completes to update the in-memory session.
    
    Args:
        session_id: Session ID
        steps: Generated steps from async job
        
    Returns:
        {"ok": True, "formatted": "..."} with formatted steps for display
    """
    try:
        from kernel.quests.quest_compose_wizard import (
            get_compose_session,
            _format_steps_with_actions,
        )
        
        session = get_compose_session(session_id)
        if not session:
            return {
                "ok": False,
                "error": "No active session found",
            }
        
        # Update session draft with steps
        session.draft["steps"] = steps
        
        # CRITICAL: Set stage to "confirm" so "yes" will save
        session.stage = "confirm"
        session.substage = ""
        
        print(f"[JobsAPI] Synced {len(steps)} steps to session {session_id}, stage=confirm", flush=True)
        
        # Use the existing formatting function
        step_list = _format_steps_with_actions(steps, verbose=True)
        
        # Build quest summary from draft
        draft = session.draft
        title = draft.get("title", "Untitled Quest")
        difficulty = draft.get("difficulty", "intermediate")
        module_id = draft.get("module_id", "unassigned")
        domains = draft.get("domains", [])
        xp = draft.get("xp", 100)
        
        # Format domains
        if domains:
            domain_names = [d.get("name", d) if isinstance(d, dict) else d for d in domains]
            domains_str = ", ".join(domain_names)
        else:
            domains_str = "None"
        
        formatted = f"""══════════════════════════════════════
  QUEST PREVIEW
══════════════════════════════════════

**Title:** {title}
**Difficulty:** {difficulty}
**Module:** {module_id}
**Domains:** {domains_str}
**XP Reward:** {xp}

────────────────────────────────────────
  GENERATED STEPS ({len(steps)})
────────────────────────────────────────

{step_list}

Type **confirm** to save this quest, **edit** to modify, or **cancel** to discard."""
        
        return {
            "ok": True,
            "message": f"Synced {len(steps)} steps",
            "formatted": formatted,
            "step_count": len(steps),
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            "ok": False,
            "error": str(e),
        }


# =============================================================================
# FLASK ROUTE REGISTRATION
# =============================================================================

def register_jobs_routes(app: "Flask") -> None:
    """
    Register async job routes with Flask app.
    
    Routes added:
        POST /api/quests/compose/async - Create async quest compose job
        POST /api/quests/compose/sync-steps - Sync steps to session
        POST /api/lessons/generate/async - Create async lesson generate job
        POST /api/jobs/engine - Create generic engine job
        GET /api/jobs/<job_id> - Get job status
    """
    from flask import request, jsonify
    
    @app.route("/api/quests/compose/async", methods=["POST"])
    def route_quest_compose_async():
        """Create async quest compose job."""
        data = request.get_json() or {}
        user_id = data.pop("user_id", None)
        result = api_create_quest_compose_job(data, user_id)
        
        status_code = 202 if "job_id" in result else 500
        return jsonify(result), status_code
    
    @app.route("/api/quests/compose/sync-steps", methods=["POST"])
    def route_sync_steps():
        """Sync generated steps back to session."""
        data = request.get_json() or {}
        session_id = data.get("session_id")
        steps = data.get("steps", [])
        
        if not session_id:
            return jsonify({"ok": False, "error": "session_id required"}), 400
        
        result = api_sync_quest_steps(session_id, steps)
        status_code = 200 if result.get("ok") else 400
        return jsonify(result), status_code
    
    @app.route("/api/lessons/generate/async", methods=["POST"])
    def route_lesson_generate_async():
        """Create async lesson generation job."""
        data = request.get_json() or {}
        user_id = data.pop("user_id", None)
        result = api_create_lesson_generate_job(data, user_id)
        
        status_code = 202 if "job_id" in result else 500
        return jsonify(result), status_code
    
    @app.route("/api/jobs/engine", methods=["POST"])
    def route_engine_job():
        """Create generic engine job."""
        data = request.get_json() or {}
        user_id = data.pop("user_id", None)
        pipeline = data.pop("pipeline", "default")
        total_passes = data.pop("total_passes", 4)
        
        result = api_create_engine_job(data, pipeline, total_passes, user_id)
        
        status_code = 202 if "job_id" in result else 500
        return jsonify(result), status_code
    
    @app.route("/api/jobs/<job_id>", methods=["GET"])
    def route_get_job(job_id: str):
        """Get job status."""
        result = api_get_job(job_id)
        
        status_code = 200 if result.get("status") != "error" else 404
        return jsonify(result), status_code
    
    print("[JobsAPI] Registered async job routes", flush=True)


__all__ = [
    "api_create_quest_compose_job",
    "api_create_lesson_generate_job",
    "api_create_engine_job",
    "api_get_job",
    "register_jobs_routes",
]
