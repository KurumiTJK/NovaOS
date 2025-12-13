# kernel/workers/__init__.py
"""
NovaOS Workers — Background Job Processing

Workers run in separate processes to handle async jobs.

Usage:
    python -m kernel.workers.job_worker
"""

# Don't import at module level to avoid circular import issues
# Use: from kernel.workers.job_worker import run_worker