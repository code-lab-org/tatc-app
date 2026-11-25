"""
Router specifications for tracking analysis endpoints.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import json
import logging
from typing import List
from uuid import UUID

from celery import chord, group
from fastapi import APIRouter, Depends
from geojson_pydantic import FeatureCollection

from ..analysis.endpoints import (
    chunk,
    enqueue_analysis,
    get_analysis_result,
    serialize_members,
)
from ..celery.quota import TaskSlot, analysis_slot
from ..celery.schemas import CeleryTask
from ..celery.utils import enqueue, get_task_result
from ..cesium.czml import animation_packets, swath_packets
from ..utils.serialization import MSGPACK_RESPONSES, from_geojson
from .schemas import (
    GroundTrackAnalysisRequest,
    OrbitTrackAnalysisRequest,
    SwathAnalysisRequest,
    SwathAnalysisResult,
)
from .tasks import (
    SWATH_COLUMNS,
    collect_ground_track_task,
    collect_orbit_track_task,
    collect_swaths_task,
    combine_swaths_task,
    merge_feature_collections_task,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# number of times analyzed by each parallel task
TRACK_CHUNK_SIZE = 100


def _enqueue_track(task, request: OrbitTrackAnalysisRequest) -> dict:
    """
    Enqueues tasks to collect the (orbit or ground) tracks of the members of
    a satellite or constellation, in parallel by member and chunk of times,
    followed by a task that merges their feature collections.

    Args:
        task (celery.Task): The task to collect a track.
        request (OrbitTrackAnalysisRequest): The request.

    Returns:
        dict: The enqueued task (see `celery.utils.enqueue`).
    """
    members = serialize_members(request.get_members())
    mask = request.mask.model_dump(mode="json") if request.mask else None
    return enqueue(
        chord(
            group(
                task.s(
                    member,
                    request.instrument_index,
                    [time.isoformat() for time in times],
                    request.elevation,
                    mask,
                )
                for times in chunk(request.get_times(), TRACK_CHUNK_SIZE)
                for member in members
            ),
            merge_feature_collections_task.s(),
        )
    )


@router.post("/orbit-track", response_model=CeleryTask)
def enqueue_orbit_track_analysis(request: OrbitTrackAnalysisRequest):
    """
    Endpoint to enqueue a task to perform orbit track analysis.

    Args:
        request (OrbitTrackAnalysisRequest): User request.

    Returns:
        CeleryTask: Queued task.
    """
    return _enqueue_track(collect_orbit_track_task, request)


@router.get(
    "/orbit-track/{task_id}",
    response_model=FeatureCollection,
    response_model_exclude_none=True,
    responses=MSGPACK_RESPONSES,
)
def retrieve_orbit_track_analysis(task_id: UUID):
    """
    Endpoint to retrieve results of a completed orbit track analysis task.

    Args:
        task_id (UUID): Task unique identifier.

    Returns:
        FeatureCollection: Orbit track analysis results.
    """
    return json.loads(get_task_result(task_id, "Orbit track analysis", logger))


@router.post("/ground-track", response_model=CeleryTask)
def enqueue_ground_track_analysis(request: GroundTrackAnalysisRequest):
    """
    Endpoint to enqueue a task to perform ground track analysis.

    Args:
        request (GroundTrackAnalysisRequest): User request.

    Returns:
        CeleryTask: Queued task.
    """
    return _enqueue_track(collect_ground_track_task, request)


@router.get(
    "/ground-track/{task_id}",
    response_model=FeatureCollection,
    response_model_exclude_none=True,
    responses=MSGPACK_RESPONSES,
)
def retrieve_ground_track_analysis(task_id: UUID):
    """
    Endpoint to retrieve results of a completed ground track analysis task.

    Args:
        task_id (UUID): Task unique identifier.

    Returns:
        FeatureCollection: Ground track analysis results.
    """
    return json.loads(get_task_result(task_id, "Ground track analysis", logger))


@router.post("/swaths", response_model=CeleryTask)
def enqueue_swath_analysis(
    request: SwathAnalysisRequest, slot: TaskSlot = Depends(analysis_slot)
):
    """
    Endpoint to enqueue a task to analyze instrument swaths (and orbit
    tracks) of satellites and constellations, in parallel by member
    satellite.

    Args:
        request (SwathAnalysisRequest): User request.
        slot (TaskSlot): Slot reserved for the user's analysis.

    Returns:
        CeleryTask: Queued task.
    """
    members = request.get_members()
    times = [time.isoformat() for time in request.get_display_times()]
    tasks = []
    if request.segment is not None:
        tasks = [
            collect_swaths_task.s(
                member,
                times,
                request.instrument_index,
                request.step.total_seconds(),
                request.segment.total_seconds(),
            )
            for member in serialize_members(members)
        ]
    return enqueue_analysis(
        request,
        members,
        tasks,
        combine_swaths_task.s(
            request.start.isoformat(),
            request.get_member_colors(),
            request.get_member_systems(),
        ),
        slot,
    )


def _get_swath_result(task_id: UUID) -> SwathAnalysisResult:
    return get_analysis_result(SwathAnalysisResult, task_id, "Swath analysis", logger)


@router.get(
    "/swaths/{task_id}",
    response_model=SwathAnalysisResult,
    response_model_exclude_none=True,
    responses=MSGPACK_RESPONSES,
)
def retrieve_swath_analysis(task_id: UUID):
    """
    Endpoint to retrieve results of a completed swath analysis task.

    Args:
        task_id (UUID): Task unique identifier.

    Returns:
        SwathAnalysisResult: Swath analysis results.
    """
    return _get_swath_result(task_id)


@router.get("/swaths/{task_id}/czml", response_model=List[dict])
def retrieve_swath_analysis_czml(task_id: UUID):
    """
    Endpoint to retrieve results of a completed swath analysis task as a
    CZML document, animating satellites, their footprints, and swath
    segments that accumulate over time.

    Args:
        task_id (UUID): Task unique identifier.

    Returns:
        List[dict]: CZML packets.
    """
    result = _get_swath_result(task_id)
    swaths = from_geojson(
        result.swaths.model_dump_json(),
        datetimes=["start", "end"],
        columns=SWATH_COLUMNS,
    )
    return animation_packets("Swath analysis", result) + swath_packets(
        swaths, result.tracks.get_end(), result.colors, tracks=result.tracks
    )
