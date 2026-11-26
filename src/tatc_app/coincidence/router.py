"""
Router specifications for coincident observation analysis endpoints.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import logging

from fastapi import APIRouter, Depends

from ..analysis.endpoints import (
    add_result_routes,
    chunk,
    enqueue_analysis,
    serialize_members,
)
from ..celery.quota import TaskSlot, analysis_slot
from ..celery.schemas import CeleryTask
from ..coverage.router import combine_coverage_signature
from ..generation.utils import resolve_cells, resolve_points
from ..utils.serialization import to_geojson
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
                (
                    None
                    if request.sample_size is None
                    else request.sample_size.max_sample_size
                ),
            )
            for points_chunk in chunk(points)
        ],
        # coincident observations give no sample sizes of points
        combine_coverage_signature(request, points, cells, sized=False),
        slot,
    )


add_result_routes(
    router,
    "coincidence",
    CoincidenceAnalysisResult,
    "Coincidence analysis",
    logger,
    czml_description="its member satellites (clients animate its points and "
    "cells from the timeline of coincident observations)",
)
