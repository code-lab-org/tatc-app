"""
Task specifications for coverage analysis endpoints.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import json
from datetime import datetime
from typing import List, Optional

import geopandas as gpd
from tatc.analysis import (
    aggregate_observations,
    collect_observations,
    grid_observations,
    reduce_observations,
)
from tatc.schemas import Satellite

from ..analysis.summary import Weighting, summarize_coverage
from ..analysis.tasks import (
    combine_animation,
    deserialize_members,
    get_cell_targets,
    tag,
    untag,
)
from ..analysis.timeline import build_timeline
from ..utils.serialization import concat, empty_frame, from_geojson, to_geojson
from ..worker import app
from .schemas import CoverageAnalysisResult

OBSERVATION_COLUMNS = [
    "target_hash",
    "satellite",
    "instrument",
    "start",
    "epoch",
    "end",
    "access",
    "revisit",
    "geometry",
]


def collect_aggregated_observations(
    points: gpd.GeoDataFrame,
    satellites: List[Satellite],
    start: datetime,
    end: datetime,
) -> gpd.GeoDataFrame:
    """
    Collects and aggregates observations of points by all instruments of
    satellites.

    Args:
        points (geopandas.GeoDataFrame): The points.
        satellites (List[tatc.schemas.Satellite]): The satellites.
        start (datetime.datetime): The start of the analysis period.
        end (datetime.datetime): The end of the analysis period.

    Returns:
        geopandas.GeoDataFrame: The aggregated observations.
    """
    observations = collect_observations(
        points, satellites, start, end, instrument_index=None
    )
    if observations.empty:
        return empty_frame(OBSERVATION_COLUMNS)
    return aggregate_observations(observations)[OBSERVATION_COLUMNS]


@app.task
def collect_coverage_task(points: str, satellites: list, start: str, end: str) -> dict:
    """
    Task to collect and aggregate observations of a chunk of points.

    Args:
        points (str): GeoJSON serialized points.
        satellites (list): List of JSON serialized :class:`tatc.schemas.Satellite` objects.
        start (str): ISO 8601 serialized start time.
        end (str): ISO 8601 serialized end time.

    Returns:
        dict: Tagged (`obs`) GeoJSON serialized aggregated observations.
    """
    results = collect_aggregated_observations(
        from_geojson(points),
        deserialize_members(satellites),
        datetime.fromisoformat(start),
        datetime.fromisoformat(end),
    )
    return tag("obs", to_geojson(results))


def compute_coverage(
    observations: gpd.GeoDataFrame,
    points: gpd.GeoDataFrame,
    cells: gpd.GeoDataFrame,
    epoch: datetime,
    members: List[str],
    end: Optional[datetime] = None,
    weighting: Weighting = Weighting.uniform,
) -> dict:
    """
    Reduces aggregated observations to coverage statistics of points and
    cells, a timeline of observations, and a summary over the points.

    Args:
        observations (geopandas.GeoDataFrame): The aggregated observations.
        points (geopandas.GeoDataFrame): The points.
        cells (geopandas.GeoDataFrame): The cells.
        epoch (datetime.datetime): The reference time (the start of the
            analysis period).
        members (List[str]): The member satellite names.
        end (Optional[datetime.datetime]): The end of the analysis period
            (without it, no summary).
        weighting (Weighting): The weighting of points in the summary.

    Returns:
        dict: The `points`, `cells`, `timeline`, `cell_targets`, and
            `summary`.
    """
    reduced = reduce_observations(observations, targets=points).reset_index(drop=True)
    gridded = grid_observations(reduced, cells)
    timeline = build_timeline(
        observations,
        epoch,
        reduced["target_hash"].tolist(),
        members,
    )
    return {
        "points": json.loads(to_geojson(reduced)),
        "cells": json.loads(to_geojson(gridded)),
        "timeline": timeline,
        "cell_targets": get_cell_targets(reduced, cells),
        "summary": (
            None
            if end is None
            else summarize_coverage(reduced, observations, weighting, epoch, end)
        ),
    }


@app.task
def combine_coverage_task(
    results: list,
    points: str,
    cells: str,
    start: str,
    colors: dict,
    end: Optional[str] = None,
    weighting: str = Weighting.uniform.value,
) -> str:
    """
    Task to combine the observations of chunks of points into coverage
    statistics.

    Args:
        results (list): Tagged results of parallel tasks.
        points (str): GeoJSON serialized points.
        cells (str): GeoJSON serialized cells.
        start (str): ISO 8601 serialized start time (reference time).
        colors (dict): Display colors by member satellite name.
        end (Optional[str]): ISO 8601 serialized end time (without it, no
            summary).
        weighting (str): The weighting of points in the summary (see
            `Weighting`).

    Returns:
        str: JSON serialized `CoverageAnalysisResult`.
    """
    animation = combine_animation(results, start, colors)
    observations = concat(
        from_geojson(
            data,
            datetimes=["start", "epoch", "end"],
            timedeltas=["access", "revisit"],
            columns=OBSERVATION_COLUMNS,
        )
        for data in untag(results, "obs")
    )
    return CoverageAnalysisResult(
        **compute_coverage(
            observations,
            from_geojson(points),
            from_geojson(cells, columns=["cell_id", "geometry"]),
            animation.epoch,
            animation.members,
            None if end is None else datetime.fromisoformat(end),
            Weighting(weighting),
        ),
        tracks=animation.tracks,
        colors=animation.colors,
    ).model_dump_json()
