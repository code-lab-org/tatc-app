"""
Router specifications for overflight (point access) analysis endpoints.

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
from ..generation.utils import resolve_points
from ..tracking.tasks import member_track_signatures
from ..utils.analysis import serialize_members
from ..utils.serialization import to_geojson
from .schemas import OverflightAnalysisRequest, OverflightAnalysisResult
from .tasks import collect_observations_task, combine_overflights_task

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/overflight", response_model=CeleryTask)
def enqueue_overflight_analysis(request: OverflightAnalysisRequest):
    """
    Endpoint to enqueue a task to collect overflights (accesses) of points,
    in parallel by member satellite.

    Args:
        request (OverflightAnalysisRequest): User request.

    Returns:
        CeleryTask: Queued task.
    """
    members = serialize_members(request.get_members())
    points = resolve_points(request.points)
    points_json = to_geojson(points)
    return enqueue(
        chord(
            group(
                [
                    collect_observations_task.s(
                        points_json,
                        member,
                        request.instrument_index,
                        request.start.isoformat(),
                        request.end.isoformat(),
                        request.omit_solar,
                    )
                    for member in members
                ]
                + member_track_signatures(members, request)
            ),
            combine_overflights_task.s(
                points_json,
                request.start.isoformat(),
                request.get_member_colors(),
            ),
        )
    )


def _get_overflight_result(task_id: UUID) -> OverflightAnalysisResult:
    return OverflightAnalysisResult.model_validate_json(
        get_task_result(task_id, "Overflight analysis", logger)
    )


@router.get(
    "/overflight/{task_id}",
    response_model=OverflightAnalysisResult,
    response_model_exclude_none=True,
    responses={
        "200": {"content": {"application/json": {}, "application/x-msgpack": {}}}
    },
)
def retrieve_overflight_analysis(task_id: UUID):
    """
    Endpoint to retrieve results of a completed overflight analysis task.

    Args:
        task_id (UUID): Task unique identifier.

    Returns:
        OverflightAnalysisResult: Overflight analysis results.
    """
    return _get_overflight_result(task_id)


@router.get("/overflight/{task_id}/czml", response_model=List[dict])
def retrieve_overflight_analysis_czml(task_id: UUID):
    """
    Endpoint to retrieve a completed overflight analysis as a CZML document,
    animating satellites, points, and lines of sight during each access.

    Args:
        task_id (UUID): Task unique identifier.

    Returns:
        List[dict]: CZML packets.
    """
    result = _get_overflight_result(task_id)
    sites = [
        (
            feature.properties["point_id"],
            f"Point {feature.properties.get('id', i)}",
            feature.geometry.coordinates[0],
            feature.geometry.coordinates[1],
        )
        for i, feature in enumerate(result.points.features)
    ]
    return (
        [
            document_packet(
                "Overflight analysis", result.tracks.epoch, result.tracks.get_end()
            )
        ]
        + satellite_packets(result.tracks, result.colors)
        + site_packets("tgt", sites, color="#ffffff", pixel_size=8, label=True)
        + link_packets(result.timeline, "tgt", result.colors)
    )
