"""
Router specification for celery endpoints.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

from typing import Optional
from uuid import UUID

from celery.result import GroupResult
from fastapi import APIRouter, HTTPException, Response

from ..worker import app as celery_app
from .schemas import CeleryResultProgress, CeleryResultStatus

router = APIRouter()


@router.get("/{task_id}/status", response_model=CeleryResultStatus)
async def get_task_status(task_id: UUID):
    """
    Endpoint to retrieve enqueued task status. (The result backend does not
    distinguish unknown tasks from pending ones: both are not ready.)

    Args:
        task_id (UUID): Task unique identifier.

    Returns:
        CeleryResultStatus: Task results status.
    """
    task = celery_app.AsyncResult(str(task_id))
    return {"ready": task.ready(), "successful": task.successful()}


@router.get("/{group_id}/progress", response_model=CeleryResultProgress)
async def get_group_progress(group_id: UUID):
    """
    Endpoint to retrieve enqueued group task progress.

    Args:
        group_id (UUID): Group task unique identifier.

    Returns:
        CeleryResultProgress: Group task progress.
    """
    task = GroupResult.restore(str(group_id), app=celery_app)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    return {"task_count": len(task.children), "completed_count": task.completed_count()}


@router.post("/{task_id}/revoke", status_code=204)
async def revoke_task(task_id: UUID, group_id: Optional[UUID] = None):
    """
    Endpoint to cancel an enqueued task workflow, for example when a client
    no longer needs its results.

    Workers skip revoked tasks that have not started yet; tasks already
    running finish, but their results are discarded. Revoking a task that
    has already completed has no effect.

    Args:
        task_id (UUID): Task unique identifier (of the workflow's final result).
        group_id (Optional[UUID]): Group task unique identifier (of the
            workflow's group of parallel tasks), if any.
    """
    task_ids = [str(task_id)]
    if group_id is not None:
        group = GroupResult.restore(str(group_id), app=celery_app)
        if group is not None:
            task_ids.extend(child.id for child in group.children)
    celery_app.control.revoke(task_ids)
    return Response(status_code=204)
