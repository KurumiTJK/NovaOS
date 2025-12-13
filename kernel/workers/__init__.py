# kernel/workers/__init__.py
"""
NovaOS Workers — Background Job Processing

Workers run in separate processes to handle async jobs.
"""

from .job_worker import run_worker, process_job

__all__ = ["run_worker", "process_job"]
