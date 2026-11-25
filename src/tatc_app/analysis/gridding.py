"""
Gridding of statistics of points to the cells that contain them.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

from typing import Dict, List, Optional

import geopandas as gpd
import numpy as np
import pandas as pd

# reductions of the values of the points of a cell
REDUCTIONS = ("mean", "rms", "min", "max")


def grid_columns(
    points: pd.DataFrame,
    cells: gpd.GeoDataFrame,
    cell_targets: Dict[str, List[int]],
    reductions: Dict[str, str],
    masks: Optional[Dict[str, np.ndarray]] = None,
) -> gpd.GeoDataFrame:
    """
    Grids columns of points to cells: reduces the finite values of the
    points in each cell (`NaN`, or `NaT` for durations, for a cell without
    any) by the mean, root-mean-square (`rms`), minimum, or maximum.

    Args:
        points (pandas.DataFrame): The points, with the columns.
        cells (geopandas.GeoDataFrame): The cells (with a `cell_id` column).
        cell_targets (Dict[str, List[int]]): The indices of the points in
            each cell, by `cell_id` (see `tasks.get_cell_targets`).
        reductions (Dict[str, str]): The reduction of each column.
        masks (Optional[Dict[str, numpy.ndarray]]): The points whose values
            of a column count (by column; all, if not given).

    Returns:
        geopandas.GeoDataFrame: the cells, with the gridded columns.
    """
    result = cells.copy()
    members = [cell_targets.get(str(cell_id), []) for cell_id in cells["cell_id"]]
    for column, reduction in reductions.items():
        if reduction not in REDUCTIONS:
            raise ValueError(f"Unknown reduction: {reduction}")
        timedeltas = pd.api.types.is_timedelta64_dtype(points[column])
        values = (
            points[column].dt.total_seconds() if timedeltas else points[column]
        ).to_numpy(dtype=float)
        if masks is not None and column in masks:
            values = np.where(masks[column], values, np.nan)
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
    if reduction == "min":
        return float(values.min())
    if reduction == "max":
        return float(values.max())
    return float(values.mean())
