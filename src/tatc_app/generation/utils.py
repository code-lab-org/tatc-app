"""
Utility functions to resolve the points and cells of analysis requests.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

from typing import List, Union

import geopandas as gpd
from shapely.geometry import Point as GeoPoint
from shapely.geometry import shape
from tatc.schemas import Point
from tatc.utils.geometry import hash_geometry

from ..utils.serialization import from_geojson
from .schemas import Cell, CellGenerator, PointGenerator
from .tasks import generate_cells_task, generate_points_task


def generate_points_geojson(generator: PointGenerator) -> str:
    """
    Generates points from a generator specification (using a worker).

    Args:
        generator (PointGenerator): The specification.

    Returns:
        str: The GeoJSON serialized points (with a `point_id` hash).
    """
    data = generator.model_dump(mode="json")
    return generate_points_task.delay(
        data["method"], generator.distance, generator.elevation, data["mask"]
    ).get()


def generate_cells_geojson(generator: CellGenerator) -> str:
    """
    Generates cells from a generator specification (using a worker).

    Args:
        generator (CellGenerator): The specification.

    Returns:
        str: The GeoJSON serialized cells (with a `cell_id` hash).
    """
    data = generator.model_dump(mode="json")
    return generate_cells_task.delay(
        generator.distance, generator.elevation, data["mask"], data["strips"]
    ).get()


def resolve_points(points: Union[List[Point], PointGenerator]) -> gpd.GeoDataFrame:
    """
    Resolves the points of a request, from either a generator specification
    or a list of points.

    Args:
        points (Union[List[Point], PointGenerator]): The points.

    Returns:
        geopandas.GeoDataFrame: The points, with columns `point_id` (the hash
            of the geometry, equal to the `target_hash` of observations) and
            `geometry` (and `id`, for a list of points).
    """
    if isinstance(points, PointGenerator):
        return from_geojson(
            generate_points_geojson(points), columns=["point_id", "geometry"]
        )
    geometries = [GeoPoint(p.longitude, p.latitude, p.elevation) for p in points]
    return gpd.GeoDataFrame(
        {
            "point_id": [hash_geometry(g) for g in geometries],
            "id": [p.id for p in points],
        },
        geometry=geometries,
        crs="EPSG:4326",
    ).drop_duplicates("point_id", ignore_index=True)


def resolve_cells(cells: Union[List[Cell], CellGenerator]) -> gpd.GeoDataFrame:
    """
    Resolves the cells of a request, from either a generator specification
    or a list of cells.

    Args:
        cells (Union[List[Cell], CellGenerator]): The cells.

    Returns:
        geopandas.GeoDataFrame: The cells, with columns `cell_id` (the hash
            of the geometry) and `geometry`.
    """
    if isinstance(cells, CellGenerator):
        return from_geojson(
            generate_cells_geojson(cells), columns=["cell_id", "geometry"]
        )
    geometries = [shape(cell.model_dump(exclude_none=True)) for cell in cells]
    return gpd.GeoDataFrame(
        {"cell_id": [hash_geometry(g) for g in geometries]},
        geometry=geometries,
        crs="EPSG:4326",
    ).drop_duplicates("cell_id", ignore_index=True)
