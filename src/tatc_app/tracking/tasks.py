"""
Task specifications for tracking analysis endpoints.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import json
from datetime import datetime, timedelta
from typing import List, Optional

import geopandas as gpd
import pandas as pd
from shapely.geometry import shape
from tatc.analysis import collect_ground_track, collect_orbit_track
from tatc.schemas import Satellite

from ..czml import assign_colors
from ..utils.analysis import tag, untag
from ..utils.serialization import concat, from_geojson, to_geojson
from ..utils.timeline import OrbitTracks, build_member_track
from ..worker import app
from .schemas import SwathAnalysisResult


def _parse_times(times: List[str]) -> pd.DatetimeIndex:
    return pd.DatetimeIndex([datetime.fromisoformat(t) for t in times]).tz_convert(
        "UTC"
    )


@app.task
def collect_orbit_track_task(
    satellite: str,
    instrument_index: Optional[int],
    times: list,
    elevation: float,
    mask: Optional[dict],
) -> str:
    """
    Task to collect orbit track.

    Args:
        satellite (str): JSON serialized :class:`tatc.schemas.Satellite` object.
        instrument_index (Optional[int]): Instrument index, or `None` for all.
        times (list): List of ISO 8601 serialized times.
        elevation (float): Elevation (meters) above datum in the WGS 84 coordinate system.
        mask (Optional[dict]): Optional GeoJSON mask to constrain points.

    Returns:
        str: GeoJSON serialized orbit track.
    """
    results = collect_orbit_track(
        Satellite.model_validate_json(satellite),
        _parse_times(times),
        instrument_index,
        elevation,
        shape(mask) if mask is not None else None,
    )
    return to_geojson(results)


@app.task
def collect_ground_track_task(
    satellite: str,
    instrument_index: Optional[int],
    times: list,
    elevation: Optional[float],
    mask: Optional[dict],
) -> str:
    """
    Task to collect ground track.

    Args:
        satellite (str): JSON serialized :class:`tatc.schemas.Satellite` object.
        instrument_index (Optional[int]): Instrument index, or `None` for all.
        times (list): List of ISO 8601 serialized times.
        elevation (Optional[float]): Elevation (meters) above datum in the WGS 84 coordinate system.
        mask (Optional[dict]): Optional GeoJSON mask to constrain points.

    Returns:
        str: GeoJSON serialized ground track.
    """
    results = collect_ground_track(
        Satellite.model_validate_json(satellite),
        _parse_times(times),
        instrument_index,
        elevation,
        shape(mask) if mask is not None else None,
    )
    return to_geojson(results)


def compute_member_track(satellite: Satellite, times: pd.DatetimeIndex, epoch):
    """
    Computes the orbit track of a member satellite to animate results.

    Args:
        satellite (tatc.schemas.Satellite): The satellite.
        times (pandas.DatetimeIndex): The times.
        epoch (datetime.datetime): The reference time.

    Returns:
        MemberTrack: The member track.
    """
    return build_member_track(collect_orbit_track(satellite, times, 0), epoch)


@app.task
def collect_member_track_task(satellite: str, times: list, epoch: str) -> dict:
    """
    Task to collect the orbit track of a member satellite to animate results.

    Args:
        satellite (str): JSON serialized :class:`tatc.schemas.Satellite` object.
        times (list): List of ISO 8601 serialized times.
        epoch (str): ISO 8601 serialized reference time.

    Returns:
        dict: Tagged (`track`) JSON serialized `MemberTrack`.
    """
    track = compute_member_track(
        Satellite.model_validate_json(satellite),
        _parse_times(times),
        datetime.fromisoformat(epoch),
    )
    return tag("track", track.model_dump_json())


def compute_swaths(
    satellite: Satellite,
    times: pd.DatetimeIndex,
    instrument_index: Optional[int],
    step: timedelta,
    segment: timedelta,
) -> gpd.GeoDataFrame:
    """
    Computes the swath of a satellite's instrument(s), dissolved into
    segments of a fixed duration.

    Args:
        satellite (tatc.schemas.Satellite): The satellite.
        times (pandas.DatetimeIndex): The times at which to sample footprints.
        instrument_index (Optional[int]): The instrument index, or `None` for all.
        step (datetime.timedelta): The time step (over which footprints sweep).
        segment (datetime.timedelta): The duration of each segment.

    Returns:
        geopandas.GeoDataFrame: The swath segments, with columns `satellite`,
            `instrument`, `start`, `end`, and `geometry`.
    """
    columns = ["satellite", "instrument", "start", "end", "geometry"]
    track = collect_ground_track(satellite, times, instrument_index, time_step=step)
    track = track[track.valid_obs & ~track.geometry.is_empty]
    if track.empty:
        return gpd.GeoDataFrame(columns=columns, geometry="geometry", crs="EPSG:4326")
    track = track.assign(
        # samples on a boundary belong to the preceding segment
        segment=((track.time - times[0] - pd.Timedelta(1, "ns")) // segment)
        .clip(lower=0)
        .astype(int),
        start=track.time - step / 2,
        end=track.time + step / 2,
    )
    swaths = track.dissolve(
        by=["satellite", "instrument", "segment"],
        aggfunc={"start": "min", "end": "max"},
        as_index=False,
    )
    swaths["start"] = swaths["start"].clip(lower=times[0])
    swaths["end"] = swaths["end"].clip(upper=times[-1])
    return swaths[columns].sort_values("start", ignore_index=True)


@app.task
def collect_swaths_task(
    satellite: str,
    times: list,
    instrument_index: Optional[int],
    step: float,
    segment: float,
) -> dict:
    """
    Task to collect the swath segments of a member satellite.

    Args:
        satellite (str): JSON serialized :class:`tatc.schemas.Satellite` object.
        times (list): List of ISO 8601 serialized times.
        instrument_index (Optional[int]): Instrument index, or `None` for all.
        step (float): Time step (seconds).
        segment (float): Segment duration (seconds).

    Returns:
        dict: Tagged (`swath`) GeoJSON serialized swath segments.
    """
    swaths = compute_swaths(
        Satellite.model_validate_json(satellite),
        _parse_times(times),
        instrument_index,
        timedelta(seconds=step),
        timedelta(seconds=segment),
    )
    return tag("swath", to_geojson(swaths))


def combine_tracks(results: list, epoch: datetime) -> OrbitTracks:
    """
    Combines the tagged member tracks of parallel tasks.

    Args:
        results (list): The tagged results of parallel tasks.
        epoch (datetime.datetime): The reference time.

    Returns:
        OrbitTracks: The orbit tracks.
    """
    return OrbitTracks.model_validate(
        {
            "epoch": epoch,
            "tracks": [json.loads(track) for track in untag(results, "track")],
        }
    )


@app.task
def combine_swaths_task(results: list, start: str, colors: dict) -> str:
    """
    Task to combine swath segments and orbit tracks of member satellites.

    Args:
        results (list): Tagged results of parallel tasks.
        start (str): ISO 8601 serialized start time (reference time).
        colors (dict): Display colors by member satellite name.

    Returns:
        str: JSON serialized `SwathAnalysisResult`.
    """
    tracks = combine_tracks(results, datetime.fromisoformat(start))
    swaths = concat(
        from_geojson(data, datetimes=["start", "end"])
        for data in untag(results, "swath")
    )
    return SwathAnalysisResult(
        swaths=json.loads(to_geojson(swaths)),
        tracks=tracks,
        colors=assign_colors([track.name for track in tracks.tracks], colors),
    ).model_dump_json()


def member_track_signatures(members: List[str], request) -> list:
    """
    Builds the signatures of tasks to collect the orbit tracks of member
    satellites over the display window of an analysis request.

    Args:
        members (List[str]): JSON serialized member satellites.
        request (AnalysisRequest): The analysis request.

    Returns:
        list: The task signatures.
    """
    times = [time.isoformat() for time in request.get_display_times()]
    return [
        collect_member_track_task.s(member, times, request.start.isoformat())
        for member in members
    ]
