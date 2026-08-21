"""
Router specifications for tracking analysis endpoints.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import logging
from datetime import timezone
from uuid import UUID

import numpy as np
import pandas as pd
from celery import chain, group
from celery.result import GroupResult
from fastapi import APIRouter, HTTPException
from geojson_pydantic import FeatureCollection

from ..celery.schemas import CeleryTask
from ..generation.schemas import TimeGenerator
from ..satellites import generate_members
from ..utils.tasks import merge_feature_collections_task
from ..worker import app as celery_app
from .schemas import GroundTrackAnalysisRequest, OrbitTrackAnalysisRequest
from .tasks import collect_ground_track_task, collect_orbit_track_task

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/orbit-track", response_model=CeleryTask)
async def enqueue_orbit_track_analysis(request: OrbitTrackAnalysisRequest):
    """
    Endpoint to enqueue a task to perform orbit track analysis.

    Args:
        request (OrbitTrackAnalysisRequest): User request.

    Returns:
        CeleryTask: Queued task.
    """
    if isinstance(request.times, TimeGenerator):
        times = pd.date_range(
            request.times.start, request.times.end, freq=request.times.delta
        ).tz_convert(timezone.utc)
    else:
        times = pd.DatetimeIndex(request.times).tz_convert(timezone.utc)
    task = chain(
        group(
            collect_orbit_track_task.s(
                satellite.model_dump_json(),
                (
                    satellite.instruments[request.instrument].model_dump_json()
                    if isinstance(request.instrument, int)
                    else (
                        request.instrument.model_dump_json()
                        if request.instrument is not None
                        else None
                    )
                ),
                [time.isoformat() for time in times],
                request.elevation,
                request.model_dump().get("mask", None),
            )
            for times in np.array_split(times, max(1, len(times) // 100))
            for satellite in generate_members(request.satellite)
        ),
        merge_feature_collections_task.s(),
    )()
    if isinstance(task.parent, GroupResult):
        task.parent.save()
        return {"task_id": task.id, "group_id": task.parent.id}
    else:
        return {"task_id": task.id}


@router.get(
    "/orbit-track/{task_id}",
    response_model=FeatureCollection,
    response_model_exclude_none=True,
    responses={"200": {"content": {"application/x-msgpack": {}}}},
)
async def retrieve_orbit_track_analysis(task_id: UUID):
    """
    Endpoint to retrieve orbit track analysis results.

    Args:
        task_id (UUID): Task unique identifier.

    Returns:
        FeatureCollection: Orbit track analysis results.
    """
    task = celery_app.AsyncResult(str(task_id))
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    if not task.ready():
        raise HTTPException(status_code=409, detail="Results not ready.")
    try:
        results = task.get()
    except Exception as exc:
        logger.error(
            "Orbit track analysis task %s failed: %s\n%s",
            task_id,
            exc,
            task.traceback,
        )
        raise HTTPException(status_code=500, detail=f"Task failed: {exc}") from exc
    return FeatureCollection.model_validate_json(results)


@router.post("/ground-track", response_model=CeleryTask)
async def enqueue_ground_track_analysis(request: GroundTrackAnalysisRequest):
    """
    Endpoint to enqueue a task to perform ground track analysis.

    Args:
        request (GroundTrackAnalysisRequest): User request.

    Returns:
        CeleryTask: Queued task.
    """
    if isinstance(request.times, TimeGenerator):
        times = pd.date_range(
            request.times.start, request.times.end, freq=request.times.delta
        ).tz_convert(timezone.utc)
    else:
        times = pd.DatetimeIndex(request.times).tz_convert(timezone.utc)
    task = chain(
        group(
            collect_ground_track_task.s(
                satellite.model_dump_json(),
                (
                    satellite.instruments[request.instrument].model_dump_json()
                    if isinstance(request.instrument, int)
                    else (
                        request.instrument.model_dump_json()
                        if request.instrument is not None
                        else None
                    )
                ),
                [time.isoformat() for time in times],
                request.elevation,
                request.model_dump().get("mask", None),
            )
            for times in np.array_split(times, max(1, len(times) // 100))
            for satellite in generate_members(request.satellite)
        ),
        merge_feature_collections_task.s(),
    )()
    if isinstance(task.parent, GroupResult):
        task.parent.save()
        return {"task_id": task.id, "group_id": task.parent.id}
    else:
        return {"task_id": task.id}


@router.get(
    "/ground-track/{task_id}",
    response_model=FeatureCollection,
    response_model_exclude_none=True,
    responses={"200": {"content": {"application/x-msgpack": {}}}},
)
async def retrieve_ground_track_progress(task_id: UUID):
    """
    Endpoint to retrieve ground track analysis results.

    Args:
        task_id (UUID): Task unique identifier.

    Returns:
        FeatureCollection: Ground track analysis results.
    """
    task = celery_app.AsyncResult(str(task_id))
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    if not task.ready():
        raise HTTPException(status_code=409, detail="Results not ready.")
    try:
        results = task.get()
    except Exception as exc:
        logger.error(
            "Ground track analysis task %s failed: %s\n%s",
            task_id,
            exc,
            task.traceback,
        )
        raise HTTPException(status_code=500, detail=f"Task failed: {exc}") from exc
    return FeatureCollection.model_validate_json(results)
