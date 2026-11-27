"""
Router specifications for tracking analysis endpoints.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import logging
from uuid import UUID

from celery import chord, group
from fastapi import APIRouter, Depends, Response
from geojson_pydantic import FeatureCollection

from ..analysis.endpoints import chunk, serialize_members
from ..celery.quota import TaskSlot, analysis_slot
from ..celery.schemas import CeleryTask
from ..celery.utils import enqueue, get_task_result
from ..utils.serialization import MSGPACK_RESPONSES
from .schemas import GroundTrackAnalysisRequest, OrbitTrackAnalysisRequest
from .tasks import collect_track_task, merge_feature_collections_task

logger = logging.getLogger(__name__)

router = APIRouter()

# number of positions (member satellites times sample times) analyzed by
# each parallel task: requests have at most `limits.MAX_TRACK_POSITIONS`
# positions, so at most a few hundred tasks
TRACK_CHUNK_SIZE = 1000


def _enqueue_track(
    kind: str, request: OrbitTrackAnalysisRequest, slot: TaskSlot
) -> dict:
    """
    Enqueues tasks to collect the (orbit or ground) tracks of the members of
    a satellite or constellation, in parallel by chunks of about
    `TRACK_CHUNK_SIZE` positions (of up to that many times, for as many
    members as fit), followed by a task that merges their feature
    collections.

    Args:
        kind (str): The kind of track (see `tasks.TRACKS`).
        request (OrbitTrackAnalysisRequest): The request.
        slot (TaskSlot): Slot reserved for the user's analysis (see
            `celery.quota.analysis_slot`), counting it as running until its
            result is ready.

    Returns:
        dict: The enqueued task (see `celery.utils.enqueue`).
    """
    members = serialize_members(request.get_members())
    times = request.get_times()
    times_per_task = max(1, min(TRACK_CHUNK_SIZE, len(times)))
    members_per_task = max(1, TRACK_CHUNK_SIZE // times_per_task)
    member_chunks = [
        members[i : i + members_per_task]
        for i in range(0, len(members), members_per_task)
    ]
    mask = request.mask.model_dump(mode="json") if request.mask else None
    task = enqueue(
        chord(
            group(
                collect_track_task.s(
                    kind,
                    member_chunk,
                    request.instrument_index,
                    [time.isoformat() for time in time_chunk],
                    request.elevation,
                    mask,
                )
                for time_chunk in chunk(times, times_per_task)
                for member_chunk in member_chunks
            ),
            merge_feature_collections_task.s(),
        )
    )
    return slot.track(task)


@router.post("/orbit-track", response_model=CeleryTask)
def enqueue_orbit_track_analysis(
    request: OrbitTrackAnalysisRequest, slot: TaskSlot = Depends(analysis_slot)
):
    """
    Endpoint to enqueue a task to perform orbit track analysis.

    Args:
        request (OrbitTrackAnalysisRequest): User request.
        slot (TaskSlot): Slot reserved for the user's analysis.

    Returns:
        CeleryTask: Queued task.
    """
    return _enqueue_track("orbit", request, slot)


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
    return Response(
        get_task_result(task_id, "Orbit track analysis", logger),
        media_type="application/json",
    )


@router.post("/ground-track", response_model=CeleryTask)
def enqueue_ground_track_analysis(
    request: GroundTrackAnalysisRequest, slot: TaskSlot = Depends(analysis_slot)
):
    """
    Endpoint to enqueue a task to perform ground track analysis.

    Args:
        request (GroundTrackAnalysisRequest): User request.
        slot (TaskSlot): Slot reserved for the user's analysis.

    Returns:
        CeleryTask: Queued task.
    """
    return _enqueue_track("ground", request, slot)


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
    return Response(
        get_task_result(task_id, "Ground track analysis", logger),
        media_type="application/json",
    )
