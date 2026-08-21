"""
Shared utilities for debugging failed Celery tasks.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import logging

from celery.result import AsyncResult, GroupResult


def log_task_failure(
    logger: logging.Logger, label: str, task_id: str, task: AsyncResult
) -> None:
    """
    Logs debug information about a failed Celery task.

    A chain whose `group` step fails typically surfaces only a generic,
    detail-free `ChordError` on the chain's own result, since the
    original member's exception is not always reconstructable once it
    has been serialized through the result backend (e.g. a
    `pydantic_core.ValidationError`, which loses its structured error
    list entirely). Each group member still has its own stored
    traceback, unaffected by that join failure, so it is logged
    separately here to recover the real error.

    Args:
        logger (logging.Logger): Logger to write to.
        label (str): Human-readable task label (e.g. "Orbit track analysis").
        task_id (str): Unique task identifier, for correlating log lines.
        task (AsyncResult): The failed task result.
    """
    logger.error(
        "%s task %s failed: %s\n%s", label, task_id, task.result, task.traceback
    )
    parent = getattr(task, "parent", None)
    if isinstance(parent, GroupResult):
        for child in parent.results:
            if child.failed():
                logger.error(
                    "%s task %s: group member %s failed: %s\n%s",
                    label,
                    task_id,
                    child.id,
                    child.result,
                    child.traceback,
                )
