"""
Router specifications for latency analysis endpoints.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import logging
from typing import List

from fastapi import APIRouter, Depends

from ..analysis.endpoints import (
    add_result_routes,
    chunk,
    enqueue_analysis,
    serialize_members,
)
from ..analysis.summary import get_weighting
from ..celery.quota import TaskSlot, analysis_slot
from ..celery.schemas import CeleryTask
from ..cesium.czml import link_packets, site_packets
from ..generation.utils import resolve_cells, resolve_points
from ..utils.serialization import to_geojson
from .schemas import LatencyAnalysisRequest, LatencyAnalysisResult
from .tasks import collect_latencies_task, combine_latency_task

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/latency", response_model=CeleryTask)
def enqueue_latency_analysis(
    request: LatencyAnalysisRequest, slot: TaskSlot = Depends(analysis_slot)
):
    """
    Endpoint to enqueue a task to perform latency analysis, in parallel by
    member satellite and chunk of points.

    Args:
        request (LatencyAnalysisRequest): User request.
        slot (TaskSlot): Slot reserved for the user's analysis.

    Returns:
        CeleryTask: Queued task.
    """
    members = request.get_members()
    points = resolve_points(request.points)
    cells = resolve_cells(request.cells)
    stations = [station.model_dump_json() for station in request.stations]
    chunks = [to_geojson(points_chunk) for points_chunk in chunk(points)]
    return enqueue_analysis(
        request,
        members,
        [
            collect_latencies_task.s(
                points_chunk,
                member,
                stations,
                request.start.isoformat(),
                request.end.isoformat(),
                request.during_contact,
                i == 0,
            )
            for member in serialize_members(members)
            for i, points_chunk in enumerate(chunks)
        ],
        combine_latency_task.s(
            to_geojson(points),
            to_geojson(cells),
            stations,
            request.start.isoformat(),
            request.get_member_colors(),
            get_weighting(request.points).value,
        ),
        slot,
    )


def _latency_packets(result: LatencyAnalysisResult) -> List[dict]:
    """
    Builds the CZML packets of the ground stations of a latency analysis and
    of their contacts.
    """
    return site_packets(
        "gs",
        [(s.name, s.name, s.longitude, s.latitude) for s in result.stations],
        color="#ffd166",
        pixel_size=9,
        label=True,
    ) + link_packets(result.contacts, "gs", result.colors)


add_result_routes(
    router,
    "latency",
    LatencyAnalysisResult,
    "Latency analysis",
    logger,
    czml_description="its member satellites, ground stations, and contacts "
    "(clients animate its points and cells from the observation timeline)",
    czml_packets=_latency_packets,
)
