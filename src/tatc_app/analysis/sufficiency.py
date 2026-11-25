"""
Sampling sufficiency of the observations of points: how well each point's
samples estimate the mean of a field over the analysis period (for a model
of the field with a decorrelation time, see
`tatc.analysis.estimate_sampling_error`), and how the samples are spread in
time (`tatc.analysis.compute_revisit_statistics`) and in local time of day
(`tatc.analysis.compute_local_time_coverage`).

The observations are aggregated (see `tatc.analysis.aggregate_observations`):
overlapping observations by several satellites are one sample, at the
midpoint of their merged period, as they count once in `samples`.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

from datetime import datetime, timedelta
from typing import Dict, List, NamedTuple, Optional

import geopandas as gpd
import numpy as np
import pandas as pd
from tatc.analysis import (
    compute_local_time_coverage,
    compute_revisit_statistics,
    estimate_sampling_error,
)

# columns of the sampling error, with how each is gridded to cells:
# root-mean-square ("rms"), mean, or maximum ("max")
ERROR_COLUMNS = {"relative_error": "rms", "effective_samples": "mean"}
SAMPLING_ERROR_COLUMN = "sampling_error"
TIME_COLUMNS = {"max_gap": "max", "local_time_coverage": "mean"}


class Sufficiency(NamedTuple):
    """
    Sampling sufficiency of points.
    """

    points: gpd.GeoDataFrame
    """The points, with the columns of their sufficiency."""
    local_time_samples: np.ndarray
    """The number of samples of each point (rows) in each local-time bin."""


def compute_sufficiency(  # pylint: disable=too-many-arguments,too-many-locals
    observations: pd.DataFrame,
    points: gpd.GeoDataFrame,
    start: datetime,
    end: datetime,
    decorrelation_time: timedelta,
    standard_deviation: Optional[float] = None,
    local_time_bins: int = 8,
) -> Sufficiency:
    """
    Computes the sampling sufficiency of points from their aggregated
    observations.

    Args:
        observations (pandas.DataFrame): The aggregated observations
            (`target_hash`, `start`, `epoch`, `end`, and point `geometry`).
        points (geopandas.GeoDataFrame): The reduced statistics of points
            (`target_hash` and point `geometry`), including those not
            observed.
        start (datetime.datetime): The start of the analysis period.
        end (datetime.datetime): The end of the analysis period.
        decorrelation_time (datetime.timedelta): The decorrelation time of
            the field.
        standard_deviation (Optional[float]): The standard deviation of the
            field, to add the `sampling_error` in its units.
        local_time_bins (int): The number of intervals of the day.

    Returns:
        Sufficiency: the points (in order) with their `relative_error`,
            `sampling_error` (given the standard deviation),
            `effective_samples`, `revisit_p50`, `revisit_p90`, `max_gap`, and
            `local_time_coverage`, and their samples in each local-time bin.
    """
    targets = gpd.GeoDataFrame(
        points[["target_hash"]].reset_index(drop=True),
        geometry=points.geometry.values,
        crs=points.crs or "EPSG:4326",
    )
    if observations is None or observations.empty:
        # (the sampling error of no observations is undefined)
        error = pd.DataFrame(
            {
                "target_hash": targets["target_hash"],
                "relative_error": np.nan,
                "sampling_error": np.nan,
                "effective_samples": np.nan,
            }
        )
        observations = observations if observations is not None else pd.DataFrame()
    else:
        error = estimate_sampling_error(
            observations,
            start,
            end,
            decorrelation_time,
            standard_deviation or 1.0,
            targets=targets,
        )
    revisits = compute_revisit_statistics(
        observations, start, end, quantiles=(0.5, 0.9), targets=targets
    )
    local = compute_local_time_coverage(
        observations, bins=local_time_bins, targets=targets
    )
    columns = {
        "relative_error": _by_point(points, error, "relative_error"),
        **(
            {}
            if standard_deviation is None
            else {SAMPLING_ERROR_COLUMN: _by_point(points, error, "sampling_error")}
        ),
        "effective_samples": _by_point(points, error, "effective_samples"),
        "revisit_p50": _by_point(points, revisits, "revisit p50"),
        "revisit_p90": _by_point(points, revisits, "revisit p90"),
        "max_gap": _by_point(points, revisits, "max_gap"),
        "local_time_coverage": _by_point(points, local, "local_time_coverage"),
    }
    result = points.copy()
    for column, values in columns.items():
        result[column] = values
    bins = [column for column in local.columns if column.startswith("local ")]
    local_time_samples = (
        local.drop_duplicates("target_hash")
        .set_index("target_hash")[bins]
        .reindex(points["target_hash"])
        .fillna(0)
        .to_numpy(dtype=float)
    )
    return Sufficiency(result, local_time_samples)


def _by_point(points: pd.DataFrame, values: pd.DataFrame, column: str) -> np.ndarray:
    """
    Gets the values of a column for each point (by `target_hash`, in the
    order of the points).
    """
    lookup = values.drop_duplicates("target_hash").set_index("target_hash")[column]
    return points["target_hash"].map(lookup).to_numpy()


def grid_sufficiency(
    points: pd.DataFrame,
    cells: gpd.GeoDataFrame,
    cell_targets: Dict[str, List[int]],
) -> gpd.GeoDataFrame:
    """
    Grids the sampling sufficiency of points to cells: the root-mean-square
    `relative_error` (and `sampling_error`) of the points in each cell (a
    typical error of a point, not the error of the cell's mean, which would
    need a spatial correlation of the field), their mean `effective_samples`
    and `local_time_coverage`, and their longest `max_gap`, over the points
    with a value (`NaN`, or `NaT`, for a cell without any).

    Args:
        points (pandas.DataFrame): The points, with their sufficiency (see
            `compute_sufficiency`).
        cells (geopandas.GeoDataFrame): The cells (with a `cell_id` column).
        cell_targets (Dict[str, List[int]]): The indices of the points in
            each cell, by `cell_id` (see `tasks.get_cell_targets`).

    Returns:
        geopandas.GeoDataFrame: the cells, with the sufficiency of each.
    """
    reductions = dict(ERROR_COLUMNS)
    if SAMPLING_ERROR_COLUMN in points.columns:
        reductions[SAMPLING_ERROR_COLUMN] = "rms"
    reductions.update(TIME_COLUMNS)
    result = cells.copy()
    members = [cell_targets.get(str(cell_id), []) for cell_id in cells["cell_id"]]
    for column, reduction in reductions.items():
        timedeltas = pd.api.types.is_timedelta64_dtype(points[column])
        values = (
            points[column].dt.total_seconds() if timedeltas else points[column]
        ).to_numpy(dtype=float)
        gridded = np.array([_reduce(values[m], reduction) for m in members])
        result[column] = pd.to_timedelta(gridded, unit="s") if timedeltas else gridded
    return result


def _reduce(values: np.ndarray, reduction: str) -> float:
    """
    Reduces the finite values of the points of a cell (`NaN` if none).
    """
    values = values[np.isfinite(values)]
    if len(values) == 0:
        return np.nan
    if reduction == "rms":
        return float(np.sqrt(np.mean(values**2)))
    if reduction == "max":
        return float(values.max())
    return float(values.mean())
