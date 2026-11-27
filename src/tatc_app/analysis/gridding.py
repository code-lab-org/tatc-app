"""
Gridding of statistics of points to the cells that contain them.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import itertools
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
    # the (cell, point) pairs: the position of each cell, and its points
    members = [cell_targets.get(str(cell_id), []) for cell_id in cells["cell_id"]]
    cell_index = np.repeat(np.arange(len(members)), [len(m) for m in members])
    point_index = np.fromiter(
        itertools.chain.from_iterable(members), dtype=int, count=len(cell_index)
    )
    for column, reduction in reductions.items():
        if reduction not in REDUCTIONS:
            raise ValueError(f"Unknown reduction: {reduction}")
        timedeltas = pd.api.types.is_timedelta64_dtype(points[column])
        values = (
            points[column].dt.total_seconds() if timedeltas else points[column]
        ).to_numpy(dtype=float)
        if masks is not None and column in masks:
            values = np.where(masks[column], values, np.nan)
        gridded = _reduce(values[point_index], cell_index, len(cells), reduction)
        result[column] = pd.to_timedelta(gridded, unit="s") if timedeltas else gridded
    return result


def _reduce(
    values: np.ndarray, cell_index: np.ndarray, count: int, reduction: str
) -> np.ndarray:
    """
    Reduces the finite values of the points of each cell (`NaN` for a cell
    without any).

    Args:
        values (numpy.ndarray): The value of each (cell, point) pair.
        cell_index (numpy.ndarray): The cell (position) of each pair.
        count (int): The number of cells.
        reduction (str): The reduction (see `REDUCTIONS`).

    Returns:
        numpy.ndarray: The reduced value of each cell.
    """
    finite = np.isfinite(values)
    values, cell_index = values[finite], cell_index[finite]
    grouped = pd.Series(values**2 if reduction == "rms" else values).groupby(cell_index)
    reduced = grouped.agg("mean" if reduction == "rms" else reduction)
    gridded = reduced.reindex(np.arange(count)).to_numpy(dtype=float)
    return np.sqrt(gridded) if reduction == "rms" else gridded
