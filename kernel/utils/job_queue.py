# kernel/utils/job_queue.py
"""
NovaOS Job Queue — v1.0.0

Utilities for async job management backed by Redis/KV store.

Job Record Schema:
{
    "id": "job_abc123",
    "type": "quest_compose",
    "status": "queued|running|done|error",
    "created_at": "2025-12-13T01:30:00Z",
    "updated_at": "2025-12-13T01:30:05Z",
    "user_id": "user_123" or null,
    "input": { ... request payload ... },
    "progress": { "pass": 2, "message": "Running pass 2/4" } or null,
    "result": { ... final output ... } or null,
    "error": { "message": "..." } or null
}

Valid statuses: queued, running, done, error
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .kv_factory import get_kv_store, is_kv_configured


# =============================================================================
# CONSTANTS
# =============================================================================

DEFAULT_QUEUE = "default"
JOB_KEY_PREFIX = "job"

VALID_STATUSES = {"queued", "running", "done", "error"}

JOB_TYPES = {
    "quest_compose",
    "engine_run",
    "lesson_generate",
}


# =============================================================================
# JOB CREATION
# =============================================================================

def create_job(
    job_type: str,
    input_payload: Dict[str, Any],
    user_id: Optional[str] = None,
) -> str:
    """
    Create a new job record in Redis.
    
    Args:
        job_type: Type of job (quest_compose, engine_run, etc.)
        input_payload: Request data for the job
        user_id: Optional user ID
        
    Returns:
        job_id: Unique job identifier
    """
    if not is_kv_configured():
        raise RuntimeError("KV store not configured")
    
    kv = get_kv_store()
    
    # Generate unique job ID
    job_id = f"job_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()
    
    job_record = {
        "id": job_id,
        "type": job_type,
        "status": "queued",
        "created_at": now,
        "updated_at": now,
        "user_id": user_id,
        "input": input_payload,
        "progress": None,
        "result": None,
        "error": None,
    }
    
    # Store with TTL
    key = f"{JOB_KEY_PREFIX}:{job_id}"
    kv.set_json(key, job_record)
    
    print(f"[JobQueue] Created job {job_id} type={job_type}", flush=True)
    
    return job_id


def enqueue_job(job_id: str, queue_name: str = DEFAULT_QUEUE) -> bool:
    """
    Add job to the processing queue.
    
    Args:
        job_id: Job identifier
        queue_name: Queue to add to (default: "default")
        
    Returns:
        True if successful
    """
    if not is_kv_configured():
        return False
    
    kv = get_kv_store()
    result = kv.queue_push(queue_name, job_id)
    
    print(f"[JobQueue] Enqueued {job_id} to queue:{queue_name}", flush=True)
    
    return result > 0


def create_and_enqueue_job(
    job_type: str,
    input_payload: Dict[str, Any],
    user_id: Optional[str] = None,
    queue_name: str = DEFAULT_QUEUE,
) -> str:
    """
    Create a job and immediately enqueue it.
    
    Returns:
        job_id
    """
    job_id = create_job(job_type, input_payload, user_id)
    enqueue_job(job_id, queue_name)
    return job_id


# =============================================================================
# JOB RETRIEVAL
# =============================================================================

def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    """
    Get job record by ID.
    
    Args:
        job_id: Job identifier
        
    Returns:
        Job record dict or None if not found
    """
    if not is_kv_configured():
        return None
    
    kv = get_kv_store()
    key = f"{JOB_KEY_PREFIX}:{job_id}"
    return kv.get_json(key)


def dequeue_job(queue_name: str = DEFAULT_QUEUE) -> Optional[str]:
    """
    Pop next job ID from the queue.
    
    Args:
        queue_name: Queue to pop from
        
    Returns:
        job_id or None if queue is empty
    """
    if not is_kv_configured():
        return None
    
    kv = get_kv_store()
    return kv.queue_pop(queue_name)


# =============================================================================
# JOB UPDATES
# =============================================================================

def update_job(job_id: str, patch: Dict[str, Any]) -> bool:
    """
    Update job record with partial data.
    
    Args:
        job_id: Job identifier
        patch: Fields to update
        
    Returns:
        True if successful
    """
    if not is_kv_configured():
        return False
    
    kv = get_kv_store()
    key = f"{JOB_KEY_PREFIX}:{job_id}"
    
    job = kv.get_json(key)
    if not job:
        print(f"[JobQueue] Job {job_id} not found for update", flush=True)
        return False
    
    # Apply patch
    job.update(patch)
    job["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    return kv.set_json(key, job)


def set_job_status(job_id: str, status: str) -> bool:
    """Set job status."""
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {status}")
    return update_job(job_id, {"status": status})


def set_job_running(job_id: str) -> bool:
    """Mark job as running."""
    return update_job(job_id, {"status": "running", "progress": None})


def set_job_progress(job_id: str, progress: Dict[str, Any]) -> bool:
    """
    Update job progress.
    
    Args:
        job_id: Job identifier
        progress: Progress dict, e.g. {"pass": 2, "message": "Running pass 2/4"}
        
    Returns:
        True if successful
    """
    return update_job(job_id, {"progress": progress})


def set_job_done(job_id: str, result: Any) -> bool:
    """
    Mark job as done with result.
    
    Args:
        job_id: Job identifier
        result: Final result payload
        
    Returns:
        True if successful
    """
    return update_job(job_id, {
        "status": "done",
        "result": result,
        "progress": None,
    })


def set_job_error(job_id: str, message: str) -> bool:
    """
    Mark job as error with message.
    
    Args:
        job_id: Job identifier
        message: Error message (safe for display)
        
    Returns:
        True if successful
    """
    return update_job(job_id, {
        "status": "error",
        "error": {"message": message},
        "progress": None,
    })


# =============================================================================
# CLEANUP
# =============================================================================

def delete_job(job_id: str) -> bool:
    """Delete a job record (usually not needed due to TTL)."""
    if not is_kv_configured():
        return False
    
    kv = get_kv_store()
    key = f"{JOB_KEY_PREFIX}:{job_id}"
    return kv.delete(key)


__all__ = [
    # Creation
    "create_job",
    "enqueue_job",
    "create_and_enqueue_job",
    # Retrieval
    "get_job",
    "dequeue_job",
    # Updates
    "update_job",
    "set_job_status",
    "set_job_running",
    "set_job_progress",
    "set_job_done",
    "set_job_error",
    # Cleanup
    "delete_job",
    # Constants
    "JOB_TYPES",
    "VALID_STATUSES",
]
