"""
Task specifications for generation endpoints.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import io
from functools import lru_cache
from importlib import resources

import geopandas as gpd
from shapely.geometry import shape
from tatc.generation.cells import generate_cells_uniform_spacing
from tatc.generation.points import (
    generate_points_fibonacci_lattice,
    generate_points_uniform_spacing,
)

from ..worker import app
from .schemas import KnownShape


@lru_cache(maxsize=None)
def _load_resource(filename: str) -> gpd.GeoDataFrame:
    """
    Loads a zipped shapefile bundled in the `tatc_app` package's `resources`
    directory (declared as package data in `pyproject.toml`), independent of
    the process's current working directory. Cached since parsing a bundled
    shapefile takes tens of milliseconds and its contents never change
    within a process's lifetime.
    """
    data = (resources.files("tatc_app") / "resources" / filename).read_bytes()
    return gpd.read_file(io.BytesIO(data))


def load_country_mask(iso_3166_1_alpha3: str):
    """
    Load a country geometry from its ISO 3166-1 alpha-3 code.

    Args:
        iso_3166_1_alpha3 (str): The ISO 3166-1 alpha-3 country code.

    Returns:
        Union[Polygon, MultiPolygon]: the country's border geometry
    """
    # `geopandas.datasets` (and its bundled `naturalearth_lowres` sample) was
    # removed in geopandas 1.0, so this dataset (Natural Earth 110m admin-0
    # countries) is instead bundled directly with the application.
    world = _load_resource("ne_110m_admin_0_countries.zip")
    # `ISO_A3_EH` (rather than `ISO_A3`) is used because several countries
    # (e.g. France, Norway) have a placeholder `-99` in `ISO_A3` due to a
    # long-standing Natural Earth data issue.
    return (
        world.query(f'ISO_A3_EH == "{iso_3166_1_alpha3}"').to_crs("EPSG:4326").geometry
    )


def load_known_shape(shape: KnownShape):
    """
    Loads a known shape.

    Args:
        shape (KnownShape): A known shape.

    Returns:
        Union[Polygon, MultiPolygon]: the known shape's geometry
    """
    if shape == KnownShape.conus:
        usa = _load_resource("cb_2020_us_state_20m.zip")
        return (
            usa[(usa.STUSPS != "AK") & (usa.STUSPS != "HI") & (usa.STUSPS != "PR")]
            .dissolve()
            .to_crs("EPSG:4326")
            .geometry
        )


@app.task
def generate_equally_spaced_points_task(
    distance: float, elevation: float, mask: str = None
) -> str:
    """
    Task to generate equally spaced points.

    Args:
        distance (float): The characteristic distance between points.
        elevation (float): Elevation (meters) above datum in the WGS 84 coordinate system.
        mask (str): Optional GeoJSON serialized mask to constrain points.

    Returns:
        str: GeoJSON serialized points.
    """
    return generate_points_uniform_spacing(
        distance,
        elevation,
        (
            load_country_mask(mask)
            if isinstance(mask, str) and len(mask) == 3
            else (
                load_known_shape(mask)
                if isinstance(mask, str) and mask in KnownShape.__members__
                else shape(mask) if mask is not None else None
            )
        ),
    ).to_json(show_bbox=False, drop_id=True)


@app.task
def generate_fibonacci_lattice_points_task(
    distance: float, elevation: float, mask: str = None
) -> str:
    """
    Task to generate Fibonacci lattice points.

    Args:
        distance (float): The characteristic distance between points.
        elevation (float): Elevation (meters) above datum in the WGS 84 coordinate system.
        mask (str): Optional GeoJSON serialized mask to constrain points.

    Returns:
        str: GeoJSON serialized points.
    """
    return generate_points_fibonacci_lattice(
        distance,
        elevation,
        (
            load_country_mask(mask)
            if isinstance(mask, str) and len(mask) == 3
            else (
                load_known_shape(mask)
                if isinstance(mask, str) and mask in KnownShape.__members__
                else shape(mask) if mask is not None else None
            )
        ),
    ).to_json(show_bbox=False, drop_id=True)


@app.task
def generate_equally_spaced_cells_task(
    distance: float, elevation: float, mask: str = None, strips: str = None
) -> str:
    """
    Task to generate equally spaced cells.

    Args:
        distance (float): The characteristic distance between points.
        elevation (float): Elevation (meters) above datum in the WGS 84 coordinate system.
        mask (str): Optional GeoJSON serialized mask to constrain cells.
        strips (str): Optional strips (`lat` or `lon`).

    Returns:
        str: GeoJSON serialized cells.
    """
    return generate_cells_uniform_spacing(
        distance,
        elevation,
        (
            load_country_mask(mask)
            if isinstance(mask, str) and len(mask) == 3
            else (
                load_known_shape(mask)
                if isinstance(mask, str) and mask in KnownShape.__members__
                else shape(mask) if mask is not None else None
            )
        ),
        strips,
    ).to_json(show_bbox=False, drop_id=True)
