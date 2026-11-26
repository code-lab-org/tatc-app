"""
Ground sample sizes of the observations of points: the extent on the ground
of the observing instrument's pixel at each point, and the spacing between
pixels (see `tatc.analysis.compute_sample_sizes`), as one size per
observation (the larger of the pixel and its spacing, along and across
track: the finest detail it resolves in both directions), summarized for
each point, and a requirement that drops coarser observations.

Sizes are defined for pointed instruments, and for conical instruments with a
beam width and a scan sample spacing; observations by other instruments have
no size (`NaN`).

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

from typing import Dict, List, Optional

import geopandas as gpd
import numpy as np
import pandas as pd
from tatc.analysis import compute_sample_sizes
from tatc.schemas import ConicalInstrument, PointedInstrument, Satellite

from .gridding import grid_columns

# columns of the sizes of samples and their spacing (meters)
SIZE_COLUMNS = ["sample_along", "sample_cross", "spacing_along", "spacing_cross"]

# columns of the sample sizes of each point (see `summarize_point_sizes`)
POINT_COLUMNS = [
    "target_hash",
    "sample_size_median",
    "sample_size_min",
    "observations",
    "observations_sized",
    "observations_meeting",
]


def is_sized(instrument) -> bool:
    """
    Tests whether the samples of an instrument have sizes: a pointed
    instrument, or a conical instrument with a beam width and a scan sample
    spacing.
    """
    if isinstance(instrument, PointedInstrument):
        return True
    return (
        isinstance(instrument, ConicalInstrument)
        and instrument.beam_width is not None
        and instrument.scan_sample_spacing is not None
    )


def size_observations(
    observations: gpd.GeoDataFrame, satellites: List[Satellite]
) -> gpd.GeoDataFrame:
    """
    Sizes the samples of observations of points by satellites.

    Args:
        observations (geopandas.GeoDataFrame): The observations (by
            `satellite` and `instrument`, see
            `tatc.analysis.collect_observations`).
        satellites (List[tatc.schemas.Satellite]): The satellites.

    Returns:
        geopandas.GeoDataFrame: the observations, with the `sample_size` of
            each (meters, `NaN` if not defined).
    """
    result = observations.copy()
    if observations.empty:
        result["sample_size"] = pd.Series([], dtype=float)
        return result
    sized = compute_sample_sizes(observations, satellites)
    # the larger of the pixel and spacing in both directions (NaN if any is)
    result["sample_size"] = sized[SIZE_COLUMNS].to_numpy(dtype=float).max(axis=1)
    return result


def meets_requirement(
    observations: pd.DataFrame, max_sample_size: Optional[float]
) -> np.ndarray:
    """
    Tests which sized observations meet a maximum sample size (all, without
    one; none without a size, otherwise).
    """
    sizes = observations["sample_size"].to_numpy(dtype=float)
    if max_sample_size is None:
        return np.ones(len(sizes), dtype=bool)
    return np.nan_to_num(sizes, nan=np.inf) <= max_sample_size


def drop_coarse(sized: pd.DataFrame, max_sample_size: Optional[float]) -> pd.DataFrame:
    """
    Drops the sized observations that do not meet a maximum sample size (see
    `meets_requirement`), and their sizes.
    """
    return sized[meets_requirement(sized, max_sample_size)].drop(columns="sample_size")


def summarize_point_sizes(
    sized: pd.DataFrame, max_sample_size: Optional[float] = None
) -> pd.DataFrame:
    """
    Summarizes the sample sizes of the observations of each observed point:
    the median and smallest size (meters) of its sized observations, and the
    numbers of its observations, sized observations, and observations that
    meet the maximum sample size (if any; else, the sized ones).

    Args:
        sized (pandas.DataFrame): The sized observations (see
            `size_observations`).
        max_sample_size (Optional[float]): The maximum sample size (meters).

    Returns:
        pandas.DataFrame: a row per observed point (`POINT_COLUMNS`).
    """
    if sized.empty:
        return pd.DataFrame({column: [] for column in POINT_COLUMNS})
    sizes = sized["sample_size"].astype(float)
    meeting = meets_requirement(sized, max_sample_size) & sizes.notna().to_numpy()
    grouped = pd.DataFrame(
        {
            "target_hash": sized["target_hash"].to_numpy(),
            "size": sizes.to_numpy(),
            "sized": sizes.notna().to_numpy(),
            "meeting": meeting,
        }
    ).groupby("target_hash", sort=False)
    return pd.DataFrame(
        {
            "sample_size_median": grouped["size"].median(),
            "sample_size_min": grouped["size"].min(),
            "observations": grouped.size(),
            "observations_sized": grouped["sized"].sum(),
            "observations_meeting": grouped["meeting"].sum(),
        }
    ).reset_index()[POINT_COLUMNS]


def add_point_sizes(points: pd.DataFrame, sizes: pd.DataFrame) -> pd.DataFrame:
    """
    Adds the sample sizes of points (see `summarize_point_sizes`) to their
    statistics, by `target_hash`, in their order: points without
    observations have no sizes and none of the counts.
    """
    lookup = sizes.drop_duplicates("target_hash").set_index("target_hash")
    result = points.copy()
    for column in POINT_COLUMNS[1:]:
        values = points["target_hash"].map(lookup[column])
        if column.startswith("observations"):
            values = values.fillna(0).astype(int)
        result[column] = values.to_numpy()
    return result


def grid_sample_sizes(
    points: pd.DataFrame,
    cells: gpd.GeoDataFrame,
    cell_targets: Dict[str, List[int]],
) -> gpd.GeoDataFrame:
    """
    Grids the sample sizes of points to cells: the mean of the median sample
    sizes of the points in each cell, and the smallest sample size of any.

    Args:
        points (pandas.DataFrame): The points, with their sample sizes (see
            `add_point_sizes`).
        cells (geopandas.GeoDataFrame): The cells (with a `cell_id` column).
        cell_targets (Dict[str, List[int]]): The indices of the points in
            each cell, by `cell_id`.

    Returns:
        geopandas.GeoDataFrame: the cells, with their sample sizes.
    """
    return grid_columns(
        points,
        cells,
        cell_targets,
        {"sample_size_median": "mean", "sample_size_min": "min"},
    )
