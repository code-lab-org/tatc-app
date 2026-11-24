"""
Router specifications for coverage analysis endpoints.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import logging
from typing import List
from uuid import UUID

from celery import chord, group
from fastapi import APIRouter

from ..celery.schemas import CeleryTask
from ..celery.utils import enqueue, get_task_result
from ..czml import document_packet, satellite_packets
from ..generation.utils import chunk, resolve_cells, resolve_points
from ..tracking.tasks import member_track_signatures
from ..utils.analysis import serialize_members
from ..utils.serialization import to_geojson
from .schemas import CoverageAnalysisRequest, CoverageAnalysisResult
from .tasks import collect_coverage_task, combine_coverage_task

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/coverage", response_model=CeleryTask)
def enqueue_coverage_analysis(request: CoverageAnalysisRequest):
    """
    Endpoint to enqueue a task to perform coverage analysis, in parallel by
    chunks of points (each observed by all member satellites).

    Args:
        request (CoverageAnalysisRequest): User request.

    Returns:
        CeleryTask: Queued task.
    """
    members = serialize_members(request.get_members())
    points = resolve_points(request.points)
    cells = resolve_cells(request.cells)
    return enqueue(
        chord(
            group(
                [
                    collect_coverage_task.s(
                        to_geojson(points_chunk),
                        members,
                        request.start.isoformat(),
                        request.end.isoformat(),
                    )
                    for points_chunk in chunk(points)
                ]
                + member_track_signatures(members, request)
            ),
            combine_coverage_task.s(
                to_geojson(points),
                to_geojson(cells),
                request.start.isoformat(),
                request.get_member_colors(),
            ),
        )
    )


def _get_coverage_result(task_id: UUID) -> CoverageAnalysisResult:
    return CoverageAnalysisResult.model_validate_json(
        get_task_result(task_id, "Coverage analysis", logger)
    )


@router.get(
    "/coverage/{task_id}",
    response_model=CoverageAnalysisResult,
    response_model_exclude_none=True,
    responses={
        "200": {"content": {"application/json": {}, "application/x-msgpack": {}}}
    },
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
    result = _get_coverage_result(task_id)
    return [
        document_packet(
            "Coverage analysis", result.tracks.epoch, result.tracks.get_end()
        )
    ] + satellite_packets(result.tracks, result.colors)
