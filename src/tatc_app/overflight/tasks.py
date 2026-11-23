"""
Task specifications for overflight (point access) analysis endpoints.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import json
from datetime import datetime
from typing import List, Optional

import geopandas as gpd
import pandas as pd
from tatc.analysis import (
    aggregate_observations,
    collect_observations,
    reduce_observations,
)
from tatc.schemas import Satellite

from ..czml import assign_colors
from ..tracking.tasks import combine_tracks
from ..utils.analysis import tag, untag
from ..utils.serialization import concat, from_geojson, to_geojson
from ..utils.timeline import build_timeline
from ..worker import app
from .schemas import OverflightAnalysisResult

TIME_COLUMNS = ["start", "epoch", "end"]


@app.task
def collect_observations_task(
    points: str,
    satellite: str,
    instrument_index: Optional[int],
    start: str,
    end: str,
    omit_solar: bool,
) -> dict:
    """
    Task to collect observations of points by one satellite.

    Args:
        points (str): GeoJSON serialized points.
        satellite (str): JSON serialized :class:`tatc.schemas.Satellite` object.
        instrument_index (Optional[int]): Instrument index, or `None` for all.
        start (str): ISO 8601 serialized start time.
        end (str): ISO 8601 serialized end time.
        omit_solar (bool): `True`, if solar angles can be omitted to improve computation speed.

    Returns:
        dict: Tagged (`obs`) GeoJSON serialized observations.
    """
    results = collect_observations(
        from_geojson(points),
        Satellite.model_validate_json(satellite),
        datetime.fromisoformat(start),
        datetime.fromisoformat(end),
        instrument_index,
        omit_solar,
    )
    return tag("obs", to_geojson(results))


def compute_overflights(
    observations: gpd.GeoDataFrame,
    points: gpd.GeoDataFrame,
    epoch: datetime,
    members: List[str],
) -> dict:
    """
    Computes the statistics of observations of each point and builds the
    timeline of observations by each satellite.

    Args:
        observations (geopandas.GeoDataFrame): The observations.
        points (geopandas.GeoDataFrame): The points.
        epoch (datetime.datetime): The reference time.
        members (List[str]): The member satellite names.

    Returns:
        dict: The `points` (with statistics), `observations`, and `timeline`.
    """
    if observations.empty:
        # access and revisit are durations (a bare pd.NaT would be a datetime)
        missing = pd.Series(pd.NaT, index=points.index, dtype="timedelta64[ns]")
        statistics = points.assign(samples=0, access=missing, revisit=missing)
    else:
        observations = observations.sort_values("start", ignore_index=True)
        # aggregation merges overlapping observations by several satellites
        statistics = reduce_observations(
            aggregate_observations(observations), targets=points
        )
    statistics = statistics.drop(columns="target_hash", errors="ignore")
    return {
        "points": json.loads(to_geojson(statistics)),
        "observations": json.loads(to_geojson(observations)),
        "timeline": build_timeline(
            observations, epoch, points["point_id"].tolist(), members
        ),
    }


@app.task
def combine_overflights_task(
    results: list, points: str, start: str, colors: dict
) -> str:
    """
    Task to combine observations of points by member satellites.

    Args:
        results (list): Tagged results of parallel tasks.
        points (str): GeoJSON serialized points.
        start (str): ISO 8601 serialized start time (reference time).
        colors (dict): Display colors by member satellite name.

    Returns:
        str: JSON serialized `OverflightAnalysisResult`.
    """
    epoch = datetime.fromisoformat(start)
    observations = concat(
        from_geojson(data, datetimes=TIME_COLUMNS) for data in untag(results, "obs")
    )
    tracks = combine_tracks(results, epoch)
    members = [track.name for track in tracks.tracks]
    return OverflightAnalysisResult(
        **compute_overflights(observations, from_geojson(points), epoch, members),
        tracks=tracks,
        colors=assign_colors(members, colors),
    ).model_dump_json()
