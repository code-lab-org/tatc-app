"""
Task specifications for coverage analysis endpoints.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import json
from datetime import datetime
from typing import List, Optional, Tuple, Union

import geopandas as gpd
import pandas as pd
from tatc.analysis import (
    aggregate_observations,
    collect_observations,
    grid_observations,
    reduce_observations,
)
from tatc.schemas import Satellite

from ..analysis.sample_sizes import (
    POINT_COLUMNS,
    add_point_sizes,
    drop_coarse,
    grid_sample_sizes,
    size_observations,
    summarize_point_sizes,
)
from ..analysis.sufficiency import compute_sufficiency, grid_sufficiency
from ..analysis.summary import (
    Weighting,
    summarize_coverage,
    summarize_sample_sizes,
    summarize_sufficiency,
)
from ..analysis.tasks import (
    combine_animation,
    deserialize_members,
    get_cell_targets,
    tag,
    untag,
)
from ..analysis.timeline import build_timeline
from ..utils.serialization import (
    concat,
    empty_frame,
    from_geojson,
    to_geojson,
    to_response_json,
)
from ..worker import app
from .schemas import CoverageAnalysisResult, SampleSizeOptions, SufficiencyOptions

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


def collect_sized_observations(
    points: gpd.GeoDataFrame,
    satellites: List[Satellite],
    start: datetime,
    end: datetime,
    sample_size: Optional[SampleSizeOptions] = None,
) -> Tuple[gpd.GeoDataFrame, Optional[pd.DataFrame]]:
    """
    Collects and aggregates observations of points by all instruments of
    satellites, sizing their ground samples (if requested): the observations
    coarser than a maximum sample size (if any) are dropped before they are
    aggregated.

    Args:
        points (geopandas.GeoDataFrame): The points.
        satellites (List[tatc.schemas.Satellite]): The satellites.
        start (datetime.datetime): The start of the analysis period.
        end (datetime.datetime): The end of the analysis period.
        sample_size (Optional[SampleSizeOptions]): Options to size the
            samples, or `None`.

    Returns:
        Tuple[geopandas.GeoDataFrame, Optional[pandas.DataFrame]]: The
            aggregated observations, and the sample sizes of the observed
            points (see `sample_sizes.summarize_point_sizes`; of all their
            observations, before any are dropped), if sized.
    """
    observations = collect_observations(
        points, satellites, start, end, instrument_index=None
    )
    sizes = None
    if sample_size is not None:
        sized = size_observations(observations, satellites)
        sizes = summarize_point_sizes(sized, sample_size.max_sample_size)
        observations = drop_coarse(sized, sample_size.max_sample_size)
    if observations.empty:
        return empty_frame(OBSERVATION_COLUMNS), sizes
    return aggregate_observations(observations)[OBSERVATION_COLUMNS], sizes


@app.task
def collect_coverage_task(
    points: str,
    satellites: list,
    start: str,
    end: str,
    sample_size: Optional[dict] = None,
) -> Union[dict, list]:
    """
    Task to collect and aggregate observations of a chunk of points.

    Args:
        points (str): GeoJSON serialized points.
        satellites (list): List of JSON serialized :class:`tatc.schemas.Satellite` objects.
        start (str): ISO 8601 serialized start time.
        end (str): ISO 8601 serialized end time.
        sample_size (Optional[dict]): JSON serialized `SampleSizeOptions`, or
            `None` not to size samples.

    Returns:
        Union[dict, list]: Tagged (`obs`) GeoJSON serialized aggregated
            observations, and, if sized, tagged (`size`) JSON serialized
            sample sizes of the observed points.
    """
    options = (
        None if sample_size is None else SampleSizeOptions.model_validate(sample_size)
    )
    observations, sizes = collect_sized_observations(
        from_geojson(points),
        deserialize_members(satellites),
        datetime.fromisoformat(start),
        datetime.fromisoformat(end),
        options,
    )
    result = tag("obs", to_geojson(observations))
    if sizes is None:
        return result
    return [result, tag("size", sizes.to_json(orient="records"))]


def compute_coverage(  # pylint: disable=too-many-arguments
    observations: gpd.GeoDataFrame,
    points: gpd.GeoDataFrame,
    cells: gpd.GeoDataFrame,
    epoch: datetime,
    end: datetime,
    members: List[str],
    weighting: Weighting,
    sufficiency: Optional[SufficiencyOptions] = None,
    sample_size: Optional[SampleSizeOptions] = None,
    sizes: Optional[pd.DataFrame] = None,
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
        end (datetime.datetime): The end of the analysis period.
        members (List[str]): The member satellite names.
        weighting (Weighting): The weighting of points in the summary.
        sufficiency (Optional[SufficiencyOptions]): Options to also assess
            the sampling sufficiency of points and cells, or `None`.
        sample_size (Optional[SampleSizeOptions]): Options of the ground
            sample sizes of points and cells, or `None` (without sizes).
        sizes (Optional[pandas.DataFrame]): The sample sizes of the observed
            points (see `sample_sizes.summarize_point_sizes`), if sized.

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
    cell_targets = get_cell_targets(reduced, cells)
    summary = summarize_coverage(reduced, observations, weighting, epoch, end)
    if sufficiency is not None:
        assessed = compute_sufficiency(
            observations,
            reduced,
            epoch,
            end,
            sufficiency.decorrelation_time,
            sufficiency.standard_deviation,
            sufficiency.local_time_bins,
        )
        reduced = assessed.points
        gridded = grid_sufficiency(reduced, gridded, cell_targets)
        summary.sufficiency = summarize_sufficiency(
            reduced,
            assessed.local_time_samples,
            weighting,
            sufficiency.decorrelation_time,
            sufficiency.standard_deviation,
            sufficiency.target_relative_error,
        )
    if sample_size is not None:
        reduced = add_point_sizes(
            reduced,
            sizes if sizes is not None else pd.DataFrame(columns=POINT_COLUMNS),
        )
        gridded = grid_sample_sizes(reduced, gridded, cell_targets)
        summary.sample_size = summarize_sample_sizes(
            reduced, weighting, sample_size.max_sample_size
        )
    return {
        "points": json.loads(to_geojson(reduced)),
        "cells": json.loads(to_geojson(gridded)),
        "timeline": timeline,
        "cell_targets": cell_targets,
        "summary": summary,
    }


@app.task
def combine_coverage_task(
    results: list,
    points: str,
    cells: str,
    start: str,
    end: str,
    colors: dict,
    weighting: str,
    sufficiency: Optional[dict] = None,
    sample_size: Optional[dict] = None,
) -> str:
    """
    Task to combine the observations of chunks of points into coverage
    statistics.

    Args:
        results (list): Tagged results of parallel tasks.
        points (str): GeoJSON serialized points.
        cells (str): GeoJSON serialized cells.
        start (str): ISO 8601 serialized start time (reference time).
        end (str): ISO 8601 serialized end time.
        colors (dict): Display colors by member satellite name.
        weighting (str): The weighting of points in the summary (see
            `Weighting`).
        sufficiency (Optional[dict]): JSON serialized `SufficiencyOptions`,
            or `None` to skip sampling sufficiency.
        sample_size (Optional[dict]): JSON serialized `SampleSizeOptions` of
            the sample sizes the parallel tasks give (tagged `size`), or
            `None` without sizes.

    Returns:
        str: JSON serialized `CoverageAnalysisResult`.
    """
    animation = combine_animation(results, start, colors)
    sizes = pd.DataFrame(
        [row for data in untag(results, "size") for row in json.loads(data)],
        columns=POINT_COLUMNS,
    )
    observations = concat(
        from_geojson(
            data,
            datetimes=["start", "epoch", "end"],
            timedeltas=["access", "revisit"],
            columns=OBSERVATION_COLUMNS,
        )
        for data in untag(results, "obs")
    )
    return to_response_json(
        CoverageAnalysisResult(
            **compute_coverage(
                observations,
                from_geojson(points),
                from_geojson(cells, columns=["cell_id", "geometry"]),
                animation.epoch,
                datetime.fromisoformat(end),
                animation.members,
                Weighting(weighting),
                (
                    None
                    if sufficiency is None
                    else SufficiencyOptions.model_validate(sufficiency)
                ),
                (
                    None
                    if sample_size is None
                    else SampleSizeOptions.model_validate(sample_size)
                ),
                sizes,
            ),
            tracks=animation.tracks,
            colors=animation.colors,
        )
    )
