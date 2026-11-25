"""
Router specifications for coverage analysis endpoints.

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
from ..generation.utils import resolve_cells, resolve_points
from ..utils.serialization import MSGPACK_RESPONSES, to_geojson
from .schemas import CoverageAnalysisRequest, CoverageAnalysisResult
from .tasks import collect_coverage_task, combine_coverage_task

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/coverage", response_model=CeleryTask)
def enqueue_coverage_analysis(
    request: CoverageAnalysisRequest, slot: TaskSlot = Depends(analysis_slot)
):
    """
    Endpoint to enqueue a task to perform coverage analysis, in parallel by
    chunks of points (each observed by all member satellites).

    Args:
        request (CoverageAnalysisRequest): User request.
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
            collect_coverage_task.s(
                to_geojson(points_chunk),
                serialized,
                request.start.isoformat(),
                request.end.isoformat(),
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
        ),
        slot,
    )


def _get_coverage_result(task_id: UUID) -> CoverageAnalysisResult:
    return get_analysis_result(
        CoverageAnalysisResult, task_id, "Coverage analysis", logger
    )


@router.get(
    "/coverage/{task_id}",
    response_model=CoverageAnalysisResult,
    response_model_exclude_none=True,
    responses=MSGPACK_RESPONSES,
)
def retrieve_coverage_analysis(task_id: UUID):
    """
    Endpoint to retrieve results of a completed coverage analysis task.

    Args:
        task_id (UUID): Task unique identifier.

    Returns:
        CoverageAnalysisResult: Coverage analysis results.
    """
    return _get_coverage_result(task_id)


@router.get("/coverage/{task_id}/czml", response_model=List[dict])
def retrieve_coverage_analysis_czml(task_id: UUID):
    """
    Endpoint to retrieve the satellites of a completed coverage analysis task
    as a CZML document (points and cells are animated by clients from the
    observation timeline).

    Args:
        task_id (UUID): Task unique identifier.

    Returns:
        List[dict]: CZML packets.
    """
    return animation_packets("Coverage analysis", _get_coverage_result(task_id))
