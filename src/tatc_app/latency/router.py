"""
Router specifications for latency analysis endpoints.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import logging
from typing import List
from uuid import UUID

from celery import chord, group
from fastapi import APIRouter

from ..celery.schemas import CeleryTask
from ..celery.utils import enqueue, get_task_result
from ..czml import document_packet, link_packets, satellite_packets, site_packets
from ..generation.utils import chunk, resolve_cells, resolve_points
from ..tracking.tasks import member_track_signatures
from ..utils.analysis import serialize_members
from ..utils.serialization import to_geojson
from .schemas import LatencyAnalysisRequest, LatencyAnalysisResult
from .tasks import collect_latencies_task, combine_latency_task

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/latency", response_model=CeleryTask)
def enqueue_latency_analysis(request: LatencyAnalysisRequest):
    """
    Endpoint to enqueue a task to perform latency analysis, in parallel by
    member satellite and chunk of points.

    Args:
        request (LatencyAnalysisRequest): User request.

    Returns:
        CeleryTask: Queued task.
    """
    members = serialize_members(request.get_members())
    points = resolve_points(request.points)
    cells = resolve_cells(request.cells)
    stations = [station.model_dump_json() for station in request.stations]
    chunks = [to_geojson(points_chunk) for points_chunk in chunk(points)]
    return enqueue(
        chord(
            group(
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
                    for member in members
                    for i, points_chunk in enumerate(chunks)
                ]
                + member_track_signatures(members, request)
            ),
            combine_latency_task.s(
                to_geojson(points),
                to_geojson(cells),
                stations,
                request.start.isoformat(),
                request.get_member_colors(),
            ),
        )
    )


def _get_latency_result(task_id: UUID) -> LatencyAnalysisResult:
    return LatencyAnalysisResult.model_validate_json(
        get_task_result(task_id, "Latency analysis", logger)
    )


@router.get(
    "/latency/{task_id}",
    response_model=LatencyAnalysisResult,
    response_model_exclude_none=True,
    responses={
        "200": {"content": {"application/json": {}, "application/x-msgpack": {}}}
    },
)
def retrieve_latency_analysis(task_id: UUID):
    """
    Endpoint to retrieve results of a completed latency analysis task.

    Args:
        task_id (UUID): Task unique identifier.

    Returns:
        LatencyAnalysisResult: Latency analysis results.
    """
    return _get_latency_result(task_id)


@router.get("/latency/{task_id}/czml", response_model=List[dict])
def retrieve_latency_analysis_czml(task_id: UUID):
    """
    Endpoint to retrieve the satellites, ground stations, and contacts of a
    completed latency analysis task as a CZML document (points and cells are
    animated by clients from the observation timeline).

    Args:
        task_id (UUID): Task unique identifier.

    Returns:
        List[dict]: CZML packets.
    """
    result = _get_latency_result(task_id)
    return (
        [
            document_packet(
                "Latency analysis", result.tracks.epoch, result.tracks.get_end()
            )
        ]
        + satellite_packets(result.tracks, result.colors)
        + site_packets(
            "gs",
            [(s.name, s.name, s.longitude, s.latitude) for s in result.stations],
            color="#ffd166",
            pixel_size=9,
            label=True,
        )
        + link_packets(result.contacts, "gs", result.colors)
    )
