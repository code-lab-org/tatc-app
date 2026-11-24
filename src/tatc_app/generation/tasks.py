"""
Task specifications for generation endpoints.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

from typing import Optional, Union

from tatc.generation.cells import generate_cells_uniform_spacing
from tatc.generation.points import (
    generate_points_fibonacci_lattice,
    generate_points_uniform_spacing,
)

from ..utils.serialization import to_geojson
from ..worker import app
from .masks import resolve_mask
from .schemas import PointGeneratorMethod

# point generation functions by method
POINT_GENERATORS = {
    PointGeneratorMethod.fibonacci_lattice: generate_points_fibonacci_lattice,
    PointGeneratorMethod.equally_spaced: generate_points_uniform_spacing,
}


@app.task
def generate_points_task(
    method: str,
    distance: float,
    elevation: float,
    mask: Optional[Union[dict, str]] = None,
) -> str:
    """
    Task to generate points.

    Args:
        method (str): The generation method (see `PointGeneratorMethod`).
        distance (float): The characteristic distance between points.
        elevation (float): Elevation (meters) above datum in the WGS 84 coordinate system.
        mask (Optional[Union[dict, str]]): Optional mask to constrain points
            (see `resolve_mask`).

    Returns:
        str: GeoJSON serialized points.
    """
    generate = POINT_GENERATORS[PointGeneratorMethod(method)]
    return to_geojson(generate(distance, elevation, resolve_mask(mask)))


@app.task
def generate_cells_task(
    distance: float,
    elevation: float,
    mask: Optional[Union[dict, str]] = None,
    strips: Optional[str] = None,
) -> str:
    """
    Task to generate equally spaced cells.

    Args:
        distance (float): The characteristic distance between cell centroids.
        elevation (float): Elevation (meters) above datum in the WGS 84 coordinate system.
        mask (Optional[Union[dict, str]]): Optional mask to constrain cells
            (see `resolve_mask`).
        strips (Optional[str]): Optional strips (`lat` or `lon`).

    Returns:
        str: GeoJSON serialized cells.
    """
    return to_geojson(
        generate_cells_uniform_spacing(distance, elevation, resolve_mask(mask), strips)
    )
