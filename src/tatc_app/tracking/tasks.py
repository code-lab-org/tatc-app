"""
Task specifications for tracking analysis endpoints.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import json
from datetime import timedelta
from typing import List, Optional

import geopandas as gpd
import pandas as pd
from shapely.geometry import shape
from tatc.analysis import collect_ground_track, collect_orbit_track
from tatc.schemas import Satellite

from ..analysis.tasks import combine_animation, parse_times, tag, untag
from ..utils.serialization import concat, empty_frame, from_geojson, to_geojson
from ..worker import app
from .schemas import SwathAnalysisResult

# columns of swath segments
SWATH_COLUMNS = ["satellite", "instrument", "start", "end", "geometry"]


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
        parse_times(times),
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
        parse_times(times),
        instrument_index,
        elevation,
        shape(mask) if mask is not None else None,
    )
    return to_geojson(results)


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
    track = collect_ground_track(satellite, times, instrument_index, time_step=step)
    track = track[track.valid_obs & ~track.geometry.is_empty]
    if track.empty:
        return empty_frame(SWATH_COLUMNS)
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
    return swaths[SWATH_COLUMNS].sort_values("start", ignore_index=True)


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
        parse_times(times),
        instrument_index,
        timedelta(seconds=step),
        timedelta(seconds=segment),
    )
    return tag("swath", to_geojson(swaths))


@app.task
def combine_swaths_task(
    results: list, start: str, colors: dict, systems: Optional[dict] = None
) -> str:
    """
    Task to combine swath segments and orbit tracks of member satellites.

    Args:
        results (list): Tagged results of parallel tasks.
        start (str): ISO 8601 serialized start time (reference time).
        colors (dict): Display colors by member satellite name.
        systems (Optional[dict]): Index of the satellite or constellation by
            member satellite name.

    Returns:
        str: JSON serialized `SwathAnalysisResult`.
    """
    animation = combine_animation(results, start, colors)
    swaths = concat(
        from_geojson(data, datetimes=["start", "end"])
        for data in untag(results, "swath")
    )
    return SwathAnalysisResult(
        swaths=json.loads(to_geojson(swaths)),
        tracks=animation.tracks,
        colors=animation.colors,
        systems=systems or {},
    ).model_dump_json()


@app.task
def merge_feature_collections_task(collections: List[str]) -> str:
    """
    Task to merge feature collections into one feature collection.

    Args:
        collections (List[str]): GeoJSON serialized feature collections.

    Returns:
        str: GeoJSON serialized feature collection.
    """
    return json.dumps(
        {
            "type": "FeatureCollection",
            "features": [
                feature
                for collection in collections
                for feature in json.loads(collection)["features"]
            ],
        }
    )
