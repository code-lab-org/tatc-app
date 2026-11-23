"""
Router specifications for tracking analysis endpoints.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import json
import logging
from typing import List
from uuid import UUID

import numpy as np
from celery import chord, group
from fastapi import APIRouter
from geojson_pydantic import FeatureCollection

from ..celery.schemas import CeleryTask
from ..celery.utils import enqueue, get_task_result
from ..czml import document_packet, satellite_packets, swath_packets
from ..satellites import expand_members
from ..utils.analysis import serialize_members
from ..utils.serialization import from_geojson
from ..utils.tasks import merge_feature_collections_task
from .schemas import (
    GroundTrackAnalysisRequest,
    OrbitTrackAnalysisRequest,
    SwathAnalysisRequest,
    SwathAnalysisResult,
)
from .tasks import (
    collect_ground_track_task,
    collect_orbit_track_task,
    collect_swaths_task,
    combine_swaths_task,
    member_track_signatures,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# number of times analyzed by each parallel task
TRACK_CHUNK_SIZE = 100


def _enqueue_track(task, request: OrbitTrackAnalysisRequest) -> dict:
    times = request.get_times()
    members = expand_members([request.satellite])
    mask = request.model_dump(mode="json").get("mask", None)
    return enqueue(
        chord(
            group(
                task.s(
                    satellite,
                    request.instrument_index,
                    [time.isoformat() for time in chunk],
                    request.elevation,
                    mask,
                )
                for chunk in np.array_split(
                    times, max(1, len(times) // TRACK_CHUNK_SIZE)
                )
                for satellite in serialize_members(members)
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
    responses={
        "200": {"content": {"application/json": {}, "application/x-msgpack": {}}}
    },
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
    responses={
        "200": {"content": {"application/json": {}, "application/x-msgpack": {}}}
    },
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
def enqueue_swath_analysis(request: SwathAnalysisRequest):
    """
    Endpoint to enqueue a task to analyze instrument swaths (and orbit
    tracks) of satellites and constellations, in parallel by member
    satellite.

    Args:
        request (SwathAnalysisRequest): User request.

    Returns:
        CeleryTask: Queued task.
    """
    members = serialize_members(expand_members(request.satellites))
    times = [time.isoformat() for time in request.get_display_times()]
    tasks = member_track_signatures(members, request)
    if request.segment is not None:
        tasks += [
            collect_swaths_task.s(
                member,
                times,
                request.instrument_index,
                request.step.total_seconds(),
                request.segment.total_seconds(),
            )
            for member in members
        ]
    return enqueue(
        chord(
            group(tasks),
            combine_swaths_task.s(
                request.start.isoformat(), request.get_member_colors()
            ),
        )
    )


def _get_swath_result(task_id: UUID) -> SwathAnalysisResult:
    return SwathAnalysisResult.model_validate_json(
        get_task_result(task_id, "Swath analysis", logger)
    )


@router.get(
    "/swaths/{task_id}",
    response_model=SwathAnalysisResult,
    response_model_exclude_none=True,
    responses={
        "200": {"content": {"application/json": {}, "application/x-msgpack": {}}}
    },
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
    tracks = result.tracks
    start = tracks.epoch
    end = tracks.get_end()
    swaths = from_geojson(
        result.swaths.model_dump_json(),
        datetimes=["start", "end"],
        columns=["satellite", "start", "end", "geometry"],
    )
    return (
        [document_packet("Swath analysis", start, end)]
        + satellite_packets(tracks, result.colors)
        + swath_packets(swaths, end, result.colors)
    )
