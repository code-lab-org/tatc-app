"""
Router specifications for overflight (point access) analysis endpoints.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import logging
from typing import List

from fastapi import APIRouter, Depends

from ..analysis.endpoints import (
    add_result_routes,
    enqueue_analysis,
    serialize_members,
)
from ..celery.quota import TaskSlot, analysis_slot
from ..celery.schemas import CeleryTask
from ..cesium.czml import link_packets, site_packets
from ..generation.utils import resolve_points
from ..utils.serialization import to_geojson
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


def _overflight_packets(result: OverflightAnalysisResult) -> List[dict]:
    """
    Builds the CZML packets of the points of an overflight analysis and of
    the lines of sight to them during each access.
    """
    sites = [
        (
            feature.properties["point_id"],
            f"Point {feature.properties.get('id', i)}",
            feature.geometry.coordinates[0],
            feature.geometry.coordinates[1],
        )
        for i, feature in enumerate(result.points.features)
    ]
    return site_packets(
        "tgt", sites, color="#ffffff", pixel_size=8, label=True
    ) + link_packets(result.timeline, "tgt", result.colors)


add_result_routes(
    router,
    "overflight",
    OverflightAnalysisResult,
    "Overflight analysis",
    logger,
    czml_description="its member satellites, points, and lines of sight "
    "during each access",
    czml_packets=_overflight_packets,
)
