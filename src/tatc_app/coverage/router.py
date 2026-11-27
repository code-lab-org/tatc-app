"""
Router specifications for coverage analysis endpoints.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import logging
from typing import Optional

import geopandas as gpd
from celery.canvas import Signature
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..analysis.endpoints import (
    add_result_routes,
    chunk,
    enqueue_analysis,
    serialize_members,
)
from ..analysis.summary import get_weighting
from ..celery.quota import TaskSlot, analysis_slot
from ..celery.schemas import CeleryTask
from ..generation.utils import resolve_cells, resolve_points
from ..utils.serialization import to_geojson
from .schemas import CoverageAnalysisRequest, CoverageAnalysisResult
from .tasks import collect_coverage_task, combine_coverage_task

logger = logging.getLogger(__name__)

router = APIRouter()


def _dump(options: Optional[BaseModel]) -> Optional[dict]:
    return None if options is None else options.model_dump(mode="json")


def combine_coverage_signature(
    request: CoverageAnalysisRequest,
    points: gpd.GeoDataFrame,
    cells: gpd.GeoDataFrame,
    sized: bool,
) -> Signature:
    """
    Builds the signature of the task that combines the observations of
    chunks of points into coverage statistics (see
    `tasks.combine_coverage_task`), of a coverage analysis or of analyses
    combined as one (such as coincidence analyses).

    Args:
        request (CoverageAnalysisRequest): The analysis request.
        points (geopandas.GeoDataFrame): The points.
        cells (geopandas.GeoDataFrame): The cells.
        sized (bool): Whether the chunk tasks give the sample sizes of
            points (as requested by `request.sample_size`).

    Returns:
        celery.canvas.Signature: The task signature.
    """
    return combine_coverage_task.s(
        to_geojson(points),
        to_geojson(cells),
        request.start.isoformat(),
        request.end.isoformat(),
        request.get_member_colors(),
        get_weighting(request.points).value,
        sufficiency=_dump(request.sufficiency),
        sample_size=_dump(request.sample_size) if sized else None,
    )


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
                sample_size=_dump(request.sample_size),
            )
            for points_chunk in chunk(points)
        ],
        combine_coverage_signature(request, points, cells, sized=True),
        slot,
    )


add_result_routes(
    router,
    "coverage",
    CoverageAnalysisResult,
    "Coverage analysis",
    logger,
    czml_description="its member satellites (clients animate its points and "
    "cells from the observation timeline)",
)
