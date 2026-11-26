"""
Router specifications for analyses of ground track swaths, optionally over a
region.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import json
import logging
from datetime import timedelta
from typing import List, Optional, Tuple

import pandas as pd
from fastapi import APIRouter, Depends
from shapely.geometry import mapping

from ..analysis.endpoints import (
    add_result_routes,
    enqueue_analysis,
    serialize_members,
)
from ..celery.quota import TaskSlot, analysis_slot
from ..celery.schemas import CeleryTask
from ..cesium.czml import coincident_packets, swath_packets
from ..utils.serialization import from_geojson
from .schemas import SwathAnalysisRequest, SwathAnalysisResult
from .tasks import WINDOW_STEPS, collect_swath_window_task, combine_swaths_task

logger = logging.getLogger(__name__)

router = APIRouter()


def _windows(
    times: pd.DatetimeIndex, step: timedelta, difference: Optional[timedelta]
) -> List[Tuple[pd.DatetimeIndex, pd.Timestamp]]:
    """
    Splits sample times into windows of `WINDOW_STEPS` to analyze in
    parallel: the times of each (its own, and those after them within the
    maximum time difference of coincident footprints, if any) and its end
    (exclusive: the next window's first time, or a step after the last).
    """
    windows = []
    for first in range(0, len(times), WINDOW_STEPS):
        own = times[first : first + WINDOW_STEPS]
        window_end = (
            times[first + WINDOW_STEPS]
            if first + WINDOW_STEPS < len(times)
            else times[-1] + step
        )
        window = (
            own
            if difference is None
            else times[(times >= own[0]) & (times <= own[-1] + difference)]
        )
        windows.append((window, window_end))
    return windows


@router.post("/swaths", response_model=CeleryTask)
def enqueue_swath_analysis(
    request: SwathAnalysisRequest, slot: TaskSlot = Depends(analysis_slot)
):
    """
    Endpoint to enqueue a task to analyze the swaths of satellites and
    constellations (and their orbit tracks), optionally over a region, in
    parallel by windows of time: each with all member satellites if their
    footprints may coincide, or else with each member.

    Args:
        request (SwathAnalysisRequest): User request.
        slot (TaskSlot): Slot reserved for the user's analysis.

    Returns:
        CeleryTask: Queued task.
    """
    members = request.get_members()
    serialized = serialize_members(members)
    region = request.get_region()
    region = None if region is None else json.dumps(mapping(region))
    times = request.get_sample_times()
    difference = (
        None if request.coincidence is None else request.coincidence.max_time_difference
    )
    # without swath segments or a region, only orbit tracks are needed
    analyzed = request.segment is not None or region is not None
    # all members together if their footprints may coincide
    groups = [serialized] if difference is not None else [[m] for m in serialized]
    tasks = [
        collect_swath_window_task.s(
            group,
            region,
            [time.isoformat() for time in window],
            window_end.isoformat(),
            request.start.isoformat(),
            request.end.isoformat(),
            request.get_display_end().isoformat(),
            request.step.total_seconds(),
            None if request.segment is None else request.segment.total_seconds(),
            request.instrument_index,
            None if difference is None else difference.total_seconds(),
            request.get_platform_systems(),
        )
        for window, window_end in (
            _windows(times, request.step, difference) if analyzed else []
        )
        for group in groups
    ]
    return enqueue_analysis(
        request,
        members,
        tasks,
        combine_swaths_task.s(
            region,
            request.start.isoformat(),
            request.end.isoformat(),
            request.get_member_colors(),
            request.get_member_systems(),
            request.coincidence is not None,
        ),
        slot,
    )


def _swath_packets(result: SwathAnalysisResult) -> List[dict]:
    """
    Builds the CZML packets of the footprints and swath segments of a swath
    analysis, and of the areas of its region observed in common (if found).
    """
    end = result.tracks.get_end()
    swaths = from_geojson(
        result.swaths.model_dump_json(),
        datetimes=["start", "end"],
        columns=["satellite", "instrument", "start", "end", "geometry"],
    )
    packets = swath_packets(swaths, end, result.colors, tracks=result.tracks)
    if result.coincident is not None:
        pairs = from_geojson(
            result.coincident.model_dump_json(),
            datetimes=["start", "end"],
            columns=["satellite_1", "satellite_2", "start", "end", "geometry"],
        )
        packets += coincident_packets(pairs, end)
    return packets


add_result_routes(
    router,
    "swaths",
    SwathAnalysisResult,
    "Swath analysis",
    logger,
    czml_description="its member satellites, their footprints and swath "
    "segments, and the areas of its region observed in common (if found)",
    czml_packets=_swath_packets,
)
