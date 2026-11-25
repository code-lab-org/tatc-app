"""
Router specifications for analyses of the swath coverage of a region.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import json
import logging
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends
from shapely.geometry import mapping

from ..analysis.endpoints import (
    enqueue_analysis,
    get_analysis_result,
    serialize_members,
)
from ..celery.quota import TaskSlot, analysis_slot
from ..celery.schemas import CeleryTask
from ..cesium.czml import animation_packets, coincident_packets, swath_packets
from ..utils.serialization import MSGPACK_RESPONSES, from_geojson
from .schemas import RegionAnalysisRequest, RegionAnalysisResult
from .tasks import WINDOW_STEPS, collect_region_window_task, combine_region_task

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/region", response_model=CeleryTask)
def enqueue_region_analysis(
    request: RegionAnalysisRequest, slot: TaskSlot = Depends(analysis_slot)
):
    """
    Endpoint to enqueue a task to analyze the swath coverage of a region, in
    parallel by windows of time (each with all member satellites, so that
    their footprints may coincide).

    Args:
        request (RegionAnalysisRequest): User request.
        slot (TaskSlot): Slot reserved for the user's analysis.

    Returns:
        CeleryTask: Queued task.
    """
    members = request.get_members()
    serialized = serialize_members(members)
    region = json.dumps(mapping(request.get_region()))
    times = request.get_display_times()
    difference = (
        None if request.coincidence is None else request.coincidence.max_time_difference
    )
    tasks = []
    for first in range(0, len(times), WINDOW_STEPS):
        own = times[first : first + WINDOW_STEPS]
        # the window ends at the next window's first time (or the end)
        window_end = (
            times[first + WINDOW_STEPS]
            if first + WINDOW_STEPS < len(times)
            else request.end
        )
        # with the times after it within the maximum time difference
        window = (
            own
            if difference is None
            else times[(times >= own[0]) & (times <= own[-1] + difference)]
        )
        tasks.append(
            collect_region_window_task.s(
                serialized,
                region,
                [time.isoformat() for time in window],
                window_end.isoformat(),
                request.start.isoformat(),
                request.end.isoformat(),
                request.step.total_seconds(),
                request.segment.total_seconds(),
                request.instrument_index,
                None if difference is None else difference.total_seconds(),
                request.get_platform_systems(),
            )
        )
    return enqueue_analysis(
        request,
        members,
        tasks,
        combine_region_task.s(
            region,
            request.start.isoformat(),
            request.end.isoformat(),
            request.get_member_colors(),
            request.get_member_systems(),
            request.coincidence is not None,
        ),
        slot,
    )


def _get_region_result(task_id: UUID) -> RegionAnalysisResult:
    return get_analysis_result(RegionAnalysisResult, task_id, "Region analysis", logger)


@router.get(
    "/region/{task_id}",
    response_model=RegionAnalysisResult,
    response_model_exclude_none=True,
    responses=MSGPACK_RESPONSES,
)
def retrieve_region_analysis(task_id: UUID):
    """
    Endpoint to retrieve results of a completed region analysis task.

    Args:
        task_id (UUID): Task unique identifier.

    Returns:
        RegionAnalysisResult: Region analysis results.
    """
    return _get_region_result(task_id)


@router.get("/region/{task_id}/czml", response_model=List[dict])
def retrieve_region_analysis_czml(task_id: UUID):
    """
    Endpoint to retrieve results of a completed region analysis task as a
    CZML document, animating satellites, their footprints, their swath
    segments over the region, and the areas observed in common (if found).

    Args:
        task_id (UUID): Task unique identifier.

    Returns:
        List[dict]: CZML packets.
    """
    result = _get_region_result(task_id)
    end = result.tracks.get_end()
    swaths = from_geojson(
        result.swaths.model_dump_json(),
        datetimes=["start", "end"],
        columns=["satellite", "instrument", "start", "end", "geometry"],
    )
    packets = animation_packets("Region analysis", result) + swath_packets(
        swaths, end, result.colors, tracks=result.tracks
    )
    if result.coincident is not None:
        pairs = from_geojson(
            result.coincident.model_dump_json(),
            datetimes=["start", "end"],
            columns=["satellite_1", "satellite_2", "start", "end", "geometry"],
        )
        packets += coincident_packets(pairs, end)
    return packets
