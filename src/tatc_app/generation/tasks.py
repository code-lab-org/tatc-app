"""
Task specifications for generation endpoints.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

from typing import Optional, Union

import numpy as np
from shapely.geometry import MultiPolygon, Polygon
from tatc.constants import EARTH_MEAN_RADIUS
from tatc.generation.cells import generate_cells_uniform_spacing
from tatc.generation.points import (
    generate_points_fibonacci_lattice,
    generate_points_uniform_spacing,
)
from tatc.utils.geometry import get_planar_bounds
from tatc.utils.surface import compute_number_samples

from .. import limits
from ..utils.serialization import to_geojson
from ..worker import app
from .masks import resolve_mask
from .schemas import PointGeneratorMethod

# point generation functions by method
POINT_GENERATORS = {
    PointGeneratorMethod.fibonacci_lattice: generate_points_fibonacci_lattice,
    PointGeneratorMethod.equally_spaced: generate_points_uniform_spacing,
}


def count_uniform_candidates(
    distance: float,
    mask: Optional[Union[Polygon, MultiPolygon]] = None,
    strips: Optional[str] = None,
) -> int:
    """
    Counts the candidate points (or cells) of an equally spaced grid, before
    clipping them to a mask: the grid over the bounds of the mask (as
    `tatc.generation._grid.generate_indices_uniform_spacing` generates it).

    Args:
        distance (float): The characteristic distance (meters) between points.
        mask (Optional[Union[Polygon, MultiPolygon]]): Optional mask.
        strips (Optional[str]): Optional strips (`lat` or `lon`).

    Returns:
        int: The number of candidates.
    """
    theta = np.degrees(distance / EARTH_MEAN_RADIUS)
    min_longitude, min_latitude, max_longitude, max_latitude = get_planar_bounds(mask)

    def count(minimum: float, maximum: float, offset: float) -> int:
        return max(
            0,
            int(np.round((maximum + offset) / theta))
            - int(np.round((minimum + offset) / theta)),
        )

    longitudes = 1 if strips == "lat" else count(min_longitude, max_longitude, 180)
    latitudes = 1 if strips == "lon" else count(min_latitude, max_latitude, 90)
    return longitudes * latitudes


def count_candidates(
    method: PointGeneratorMethod,
    distance: float,
    mask: Optional[Union[Polygon, MultiPolygon]] = None,
) -> int:
    """
    Counts the candidate points generated before clipping them to a mask.

    Args:
        method (PointGeneratorMethod): The generation method.
        distance (float): The characteristic distance (meters) between points.
        mask (Optional[Union[Polygon, MultiPolygon]]): Optional mask.

    Returns:
        int: The number of candidates.
    """
    if method == PointGeneratorMethod.fibonacci_lattice:
        # a Fibonacci lattice covers the globe before clipping
        return compute_number_samples(distance)
    return count_uniform_candidates(distance, mask)


def check_candidates(count: int, kind: str, hint: str = "") -> None:
    """
    Checks the number of candidates to generate is within limits.

    Raises:
        ValueError: if there are too many candidates.
    """
    if count > limits.MAX_GRID_CANDIDATES:
        raise ValueError(
            f"Too many {kind}: the distance would generate {count:,} candidate "
            f"{kind} (at most {limits.MAX_GRID_CANDIDATES:,}) before applying "
            f"the mask. Increase the distance{hint}."
        )


def check_count(count: int, max_count: Optional[int], kind: str) -> None:
    """
    Checks the number of generated points or cells is within limits.

    Raises:
        ValueError: if there are too many points or cells.
    """
    if max_count is not None and count > max_count:
        raise ValueError(
            f"Too many {kind}: {count:,} generated (at most {max_count:,}). "
            "Increase the distance or reduce the region."
        )


@app.task
def generate_points_task(
    method: str,
    distance: float,
    elevation: float,
    mask: Optional[Union[dict, str]] = None,
    max_count: Optional[int] = None,
) -> str:
    """
    Task to generate points.

    Args:
        method (str): The generation method (see `PointGeneratorMethod`).
        distance (float): The characteristic distance between points.
        elevation (float): Elevation (meters) above datum in the WGS 84 coordinate system.
        mask (Optional[Union[dict, str]]): Optional mask to constrain points
            (see `resolve_mask`).
        max_count (Optional[int]): Optional maximum number of points.

    Raises:
        ValueError: if the generation would exceed `limits.MAX_GRID_CANDIDATES`
            candidates, or generates more than `max_count` points.

    Returns:
        str: GeoJSON serialized points.
    """
    method = PointGeneratorMethod(method)
    shape = resolve_mask(mask)
    check_candidates(
        count_candidates(method, distance, shape),
        "points",
        (
            " or generate equally spaced points (which cover only the mask's bounds)"
            if method == PointGeneratorMethod.fibonacci_lattice and shape is not None
            else ""
        ),
    )
    points = POINT_GENERATORS[method](distance, elevation, shape)
    check_count(len(points), max_count, "points")
    return to_geojson(points)


@app.task
def generate_cells_task(
    distance: float,
    elevation: float,
    mask: Optional[Union[dict, str]] = None,
    strips: Optional[str] = None,
    max_count: Optional[int] = None,
) -> str:
    """
    Task to generate equally spaced cells.

    Args:
        distance (float): The characteristic distance between cell centroids.
        elevation (float): Elevation (meters) above datum in the WGS 84 coordinate system.
        mask (Optional[Union[dict, str]]): Optional mask to constrain cells
            (see `resolve_mask`).
        strips (Optional[str]): Optional strips (`lat` or `lon`).
        max_count (Optional[int]): Optional maximum number of cells.

    Raises:
        ValueError: if the generation would exceed `limits.MAX_GRID_CANDIDATES`
            candidates, or generates more than `max_count` cells.

    Returns:
        str: GeoJSON serialized cells.
    """
    shape = resolve_mask(mask)
    check_candidates(count_uniform_candidates(distance, shape, strips), "cells")
    cells = generate_cells_uniform_spacing(distance, elevation, shape, strips)
    check_count(len(cells), max_count, "cells")
    return to_geojson(cells)
