"""
Router specifications for overflight (point access) analysis endpoints.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import logging
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends

from ..analysis.endpoints import (
    enqueue_analysis,
    get_analysis_result,
    serialize_members,
)
from ..celery.quota import TaskSlot, analysis_slot
from ..celery.schemas import CeleryTask
from ..cesium.czml import animation_packets, link_packets, site_packets
from ..generation.utils import resolve_points
from ..utils.serialization import MSGPACK_RESPONSES, to_geojson
from .schemas import OverflightAnalysisRequest, OverflightAnalysisResult
from .tasks import collect_observations_task, combine_overflights_task

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/overflight", response_model=CeleryTask)
def enqueue_overflight_analysis(
    request: OverflightAnalysisRequest, slot: TaskSlot = Depends(analysis_slot)
):
    """
    Endpoint to enqueue a task to collect overflights (accesses) of points,
    in parallel by member satellite.

    Args:
        request (OverflightAnalysisRequest): User request.
        slot (TaskSlot): Slot reserved for the user's analysis.

    Returns:
        CeleryTask: Queued task.
    """
    members = request.get_members()
    points_json = to_geojson(resolve_points(request.points))
    return enqueue_analysis(
        request,
        members,
        [
            collect_observations_task.s(
                points_json,
                member,
                request.instrument_index,
                request.start.isoformat(),
                request.end.isoformat(),
                request.omit_solar,
            )
            for member in serialize_members(members)
        ],
        combine_overflights_task.s(
            points_json,
            request.start.isoformat(),
            request.get_member_colors(),
        ),
        slot,
    )


def _get_overflight_result(task_id: UUID) -> OverflightAnalysisResult:
    return get_analysis_result(
        OverflightAnalysisResult, task_id, "Overflight analysis", logger
    )


@router.get(
    "/overflight/{task_id}",
    response_model=OverflightAnalysisResult,
    response_model_exclude_none=True,
    responses=MSGPACK_RESPONSES,
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
        animation_packets("Overflight analysis", result)
        + site_packets("tgt", sites, color="#ffffff", pixel_size=8, label=True)
        + link_packets(result.timeline, "tgt", result.colors)
    )
