"""
Shared utilities to enqueue Celery task workflows and retrieve their results.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import logging
from typing import Any
from uuid import UUID

from celery.canvas import Signature
from celery.result import AsyncResult, GroupResult
from fastapi import HTTPException

from ..worker import app as celery_app


def log_task_failure(
    logger: logging.Logger, label: str, task_id: str, task: AsyncResult
) -> None:
    """
    Logs debug information about a failed Celery task.

    A workflow whose `group` step fails typically surfaces only a generic
    `ChordError` on the workflow's own result, since the original member's
    exception is not always reconstructable once it has been serialized
    through the result backend. Each group member still has its own stored
    traceback, so members of the parent group (if known) are logged
    separately to recover the real error.

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


def find_group(result: AsyncResult) -> GroupResult | None:
    """
    Finds the nearest group among a result and its parents (for example, the
    header of a chord or the first step of a chain).

    Args:
        result (AsyncResult): The result.

    Returns:
        Optional[GroupResult]: The group result, if any.
    """
    node = result
    while node is not None:
        if isinstance(node, GroupResult):
            return node
        node = getattr(node, "parent", None)
    return None


def enqueue(signature: Signature) -> dict:
    """
    Enqueues a task workflow, saving its (first) group of parallel tasks, if
    any, so clients can track progress by group identifier.

    Args:
        signature (celery.canvas.Signature): The workflow to enqueue.

    Returns:
        dict: The `task_id` of the workflow's final result and the
            `group_id` of its group of parallel tasks (if any).
    """
    result = signature.apply_async()
    group = find_group(result)
    if group is not None:
        group.save()
        return {"task_id": result.id, "group_id": group.id}
    return {"task_id": result.id}


def get_task_result(task_id: UUID, label: str, logger: logging.Logger) -> Any:
    """
    Retrieves the result of a completed task.

    Args:
        task_id (UUID): The task identifier.
        label (str): Human-readable task label, for logging.
        logger (logging.Logger): Logger to write failures to.

    Raises:
        HTTPException: (409) if the result is not ready, or (500) if it
            failed.

    Returns:
        Any: The task result.
    """
    task = celery_app.AsyncResult(str(task_id))
    if not task.ready():
        raise HTTPException(status_code=409, detail="Results not ready.")
    try:
        return task.get(propagate=True)
    except Exception as exc:
        log_task_failure(logger, label, str(task_id), task)
        raise HTTPException(status_code=500, detail=f"Task failed: {exc}") from exc
