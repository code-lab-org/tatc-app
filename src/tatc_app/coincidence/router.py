"""
Router specifications for coincident observation analysis endpoints.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import logging
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends

from ..analysis.endpoints import (
    chunk,
    enqueue_analysis,
    get_analysis_result,
    serialize_members,
)
from ..analysis.summary import get_weighting
from ..celery.quota import TaskSlot, analysis_slot
from ..celery.schemas import CeleryTask
from ..cesium.czml import animation_packets
from ..coverage.tasks import combine_coverage_task
from ..generation.utils import resolve_cells, resolve_points
from ..utils.serialization import MSGPACK_RESPONSES, to_geojson
from .schemas import CoincidenceAnalysisRequest, CoincidenceAnalysisResult
from .tasks import collect_coincidence_task

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/coincidence", response_model=CeleryTask)
def enqueue_coincidence_analysis(
    request: CoincidenceAnalysisRequest, slot: TaskSlot = Depends(analysis_slot)
):
    """
    Endpoint to enqueue a task to analyze coincident observations, in
    parallel by chunks of points (each observed by all member satellites),
    combined as the observations of a coverage analysis.

    Args:
        request (CoincidenceAnalysisRequest): User request.
        slot (TaskSlot): Slot reserved for the user's analysis.

    Returns:
        CeleryTask: Queued task.
    """
    members = request.get_members()
    serialized = serialize_members(members)
    points = resolve_points(request.points)
    cells = resolve_cells(request.cells)
    return enqueue_analysis(
        request,
        members,
        [
            collect_coincidence_task.s(
                to_geojson(points_chunk),
                serialized,
                request.start.isoformat(),
                request.end.isoformat(),
                request.min_platforms,
                request.max_time_difference.total_seconds(),
                request.instantaneous,
                request.get_platform_systems(),
            )
            for points_chunk in chunk(points)
        ],
        combine_coverage_task.s(
            to_geojson(points),
            to_geojson(cells),
            request.start.isoformat(),
            request.get_member_colors(),
            request.end.isoformat(),
            get_weighting(request.points).value,
            sufficiency=(
                None
                if request.sufficiency is None
                else request.sufficiency.model_dump(mode="json")
            ),
        ),
        slot,
    )


def _get_coincidence_result(task_id: UUID) -> CoincidenceAnalysisResult:
    return get_analysis_result(
        CoincidenceAnalysisResult, task_id, "Coincidence analysis", logger
    )


@router.get(
    "/coincidence/{task_id}",
    response_model=CoincidenceAnalysisResult,
    response_model_exclude_none=True,
    responses=MSGPACK_RESPONSES,
)
def retrieve_coincidence_analysis(task_id: UUID):
    """
    Endpoint to retrieve results of a completed coincidence analysis task.

    Args:
        task_id (UUID): Task unique identifier.

    Returns:
        CoincidenceAnalysisResult: Coincidence analysis results.
    """
    return _get_coincidence_result(task_id)


@router.get("/coincidence/{task_id}/czml", response_model=List[dict])
def retrieve_coincidence_analysis_czml(task_id: UUID):
    """
    Endpoint to retrieve the satellites of a completed coincidence analysis
    task as a CZML document (points and cells are animated by clients from
    the timeline of coincident observations).

    Args:
        task_id (UUID): Task unique identifier.

    Returns:
        List[dict]: CZML packets.
    """
    return animation_packets("Coincidence analysis", _get_coincidence_result(task_id))
