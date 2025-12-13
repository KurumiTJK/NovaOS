# kernel/workers/job_worker.py
"""
NovaOS Job Worker — v1.0.0

Background worker that processes async jobs from the Redis queue.

Usage:
    python -m kernel.workers.job_worker
    
Or programmatically:
    from kernel.workers.job_worker import run_worker
    run_worker()
"""

from __future__ import annotations

import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, Optional

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Load .env BEFORE any other imports that need env vars
try:
    from dotenv import load_dotenv
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=True)
        print(f"[Worker] Loaded .env from {env_path}", flush=True)
except ImportError:
    print("[Worker] WARNING: python-dotenv not installed", flush=True)

from kernel.utils.job_queue import (
    dequeue_job,
    get_job,
    set_job_running,
    set_job_progress,
    set_job_done,
    set_job_error,
)


# =============================================================================
# CONFIGURATION
# =============================================================================

POLL_INTERVAL = float(os.getenv("WORKER_POLL_INTERVAL", "1.0"))  # seconds
QUEUE_NAME = os.getenv("WORKER_QUEUE", "default")
MAX_RETRIES = int(os.getenv("WORKER_MAX_RETRIES", "3"))


# =============================================================================
# JOB HANDLERS
# =============================================================================

def handle_quest_compose(job: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle quest_compose job type.
    
    Args:
        job: Job record with input payload
        
    Returns:
        Result dict
    """
    job_id = job["id"]
    input_data = job.get("input", {})
    
    print(f"[Worker] Processing quest_compose: {job_id}", flush=True)
    
    # Extract input parameters
    session_id = input_data.get("session_id", "worker")
    text = input_data.get("text", "")
    
    # Import kernel components
    from system.config import Config
    from kernel.nova_kernel import NovaKernel
    from backend.llm_client import LLMClient
    
    # Initialize kernel (same pattern as nova_api.py)
    data_dir = Path(os.getenv("NOVA_DATA_DIR", "data"))
    config = Config(data_dir=data_dir)
    llm_client = LLMClient()
    kernel = NovaKernel(config=config, llm_client=llm_client)
    
    # Update progress
    set_job_progress(job_id, {"step": 1, "message": "Initializing quest compose..."})
    
    try:
        # Import quest compose handler
        from kernel.quests.quest_compose_wizard import (
            handle_quest_compose_wizard,
            has_active_compose_session,
            process_compose_wizard_input,
        )
        
        # Process through the wizard
        # This is a simplified version - real implementation would need
        # to handle multi-step wizard state
        
        set_job_progress(job_id, {"step": 2, "message": "Extracting domains..."})
        
        # For now, return a placeholder indicating the job ran
        # Full implementation would run the complete wizard flow
        result = {
            "status": "completed",
            "message": "Quest compose job processed",
            "session_id": session_id,
        }
        
        return result
        
    except Exception as e:
        raise RuntimeError(f"Quest compose failed: {str(e)}")


def handle_engine_run(job: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle engine_run job type (generic multi-pass pipeline).
    
    Args:
        job: Job record with input payload
        
    Returns:
        Result dict
    """
    job_id = job["id"]
    input_data = job.get("input", {})
    
    print(f"[Worker] Processing engine_run: {job_id}", flush=True)
    
    # Get pipeline config
    total_passes = input_data.get("total_passes", 4)
    pipeline_name = input_data.get("pipeline", "default")
    
    results = []
    
    for pass_num in range(1, total_passes + 1):
        # Update progress
        set_job_progress(job_id, {
            "pass": pass_num,
            "total_passes": total_passes,
            "message": f"Running pass {pass_num}/{total_passes}",
        })
        
        print(f"[Worker] {job_id} pass {pass_num}/{total_passes}", flush=True)
        
        # Simulate pass work (replace with actual pipeline logic)
        time.sleep(0.5)
        
        results.append({
            "pass": pass_num,
            "status": "completed",
        })
    
    return {
        "pipeline": pipeline_name,
        "total_passes": total_passes,
        "passes": results,
        "status": "completed",
    }


def handle_lesson_generate(job: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle lesson_generate job type.
    
    Args:
        job: Job record with input payload
        
    Returns:
        Result dict
    """
    job_id = job["id"]
    input_data = job.get("input", {})
    
    print(f"[Worker] Processing lesson_generate: {job_id}", flush=True)
    
    # Update progress through 4 phases
    phases = [
        "Retrieving resources",
        "Detecting gaps",
        "Building steps",
        "Refining plan",
    ]
    
    for i, phase in enumerate(phases, 1):
        set_job_progress(job_id, {
            "phase": i,
            "total_phases": len(phases),
            "message": phase,
        })
        
        print(f"[Worker] {job_id} phase {i}: {phase}", flush=True)
        
        # Simulate phase work
        time.sleep(1.0)
    
    return {
        "status": "completed",
        "phases_completed": len(phases),
        "message": "Lesson generation complete",
    }


# Job type -> handler mapping
JOB_HANDLERS = {
    "quest_compose": handle_quest_compose,
    "engine_run": handle_engine_run,
    "lesson_generate": handle_lesson_generate,
}


# =============================================================================
# MAIN WORKER
# =============================================================================

def process_job(job_id: str) -> bool:
    """
    Process a single job by ID.
    
    Args:
        job_id: Job identifier
        
    Returns:
        True if job completed successfully
    """
    # Load job record
    job = get_job(job_id)
    
    if not job:
        print(f"[Worker] Job {job_id} not found", flush=True)
        return False
    
    job_type = job.get("type", "unknown")
    
    print(f"[Worker] Starting job {job_id} type={job_type}", flush=True)
    
    # Mark as running
    set_job_running(job_id)
    
    try:
        # Get handler for job type
        handler = JOB_HANDLERS.get(job_type)
        
        if not handler:
            raise ValueError(f"Unknown job type: {job_type}")
        
        # Execute handler
        result = handler(job)
        
        # Mark as done
        set_job_done(job_id, result)
        
        print(f"[Worker] Completed job {job_id}", flush=True)
        return True
        
    except Exception as e:
        # Mark as error
        error_msg = str(e)
        
        # Don't expose internal details
        if "Traceback" in error_msg or len(error_msg) > 200:
            error_msg = f"Job failed: {type(e).__name__}"
        
        set_job_error(job_id, error_msg)
        
        print(f"[Worker] Job {job_id} failed: {e}", flush=True)
        traceback.print_exc()
        
        return False


def run_worker(
    queue_name: str = QUEUE_NAME,
    poll_interval: float = POLL_INTERVAL,
    max_iterations: Optional[int] = None,
) -> None:
    """
    Run the worker loop.
    
    Args:
        queue_name: Queue to poll
        poll_interval: Seconds between polls when queue is empty
        max_iterations: Max jobs to process (None = infinite)
    """
    # Check KV is configured
    from kernel.utils.kv_factory import is_kv_configured, get_kv_store
    
    if not is_kv_configured():
        print("[Worker] ERROR: KV store not configured!", flush=True)
        print("[Worker] Set KV_URL and KV_TOKEN in .env", flush=True)
        return
    
    # Connect to KV and verify
    try:
        kv = get_kv_store()
        print(f"[Worker] Connected to KV store", flush=True)
    except Exception as e:
        print(f"[Worker] ERROR: Failed to connect to KV: {e}", flush=True)
        return
    
    print(f"[Worker] Starting worker for queue:{queue_name}", flush=True)
    print(f"[Worker] Poll interval: {poll_interval}s", flush=True)
    
    iterations = 0
    
    while True:
        try:
            # Check iteration limit
            if max_iterations is not None and iterations >= max_iterations:
                print(f"[Worker] Reached max iterations ({max_iterations})", flush=True)
                break
            
            # Try to dequeue a job
            job_id = dequeue_job(queue_name)
            
            if job_id:
                process_job(job_id)
                iterations += 1
            else:
                # No job available, sleep
                time.sleep(poll_interval)
                
        except KeyboardInterrupt:
            print("\n[Worker] Shutting down...", flush=True)
            break
            
        except Exception as e:
            print(f"[Worker] Error in worker loop: {e}", flush=True)
            traceback.print_exc()
            time.sleep(poll_interval)
    
    print("[Worker] Worker stopped", flush=True)


# =============================================================================
# CLI ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="NovaOS Job Worker")
    parser.add_argument(
        "--queue", 
        default=QUEUE_NAME,
        help="Queue name to process"
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=POLL_INTERVAL,
        help="Poll interval in seconds"
    )
    parser.add_argument(
        "--max-jobs",
        type=int,
        default=None,
        help="Max jobs to process (default: unlimited)"
    )
    
    args = parser.parse_args()
    
    run_worker(
        queue_name=args.queue,
        poll_interval=args.interval,
        max_iterations=args.max_jobs,
    )
