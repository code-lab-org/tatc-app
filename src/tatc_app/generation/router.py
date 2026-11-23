"""
Router specifications for generation endpoints.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import json

from fastapi import APIRouter
from geojson_pydantic import FeatureCollection

from .schemas import CellGenerator, PointGenerator
from .utils import generate_cells_geojson, generate_points_geojson

router = APIRouter()


@router.post(
    "/points",
    response_model=FeatureCollection,
    response_model_exclude_none=True,
    responses={"200": {"content": {"application/x-msgpack": {}}}},
)
def generate_points(generator: PointGenerator):
    """
    Endpoint to generate a set of points.

    Args:
        generator (PointGenerator): specification for point generation

    Returns:
        FeatureCollection: generated points
    """
    return json.loads(generate_points_geojson(generator))


@router.post(
    "/cells",
    response_model=FeatureCollection,
    response_model_exclude_none=True,
    responses={"200": {"content": {"application/x-msgpack": {}}}},
)
def generate_cells(generator: CellGenerator):
    """
    Endpoint to generate a set of cells.

    Args:
        generator (CellGenerator): specification for cell generation

    Returns:
        FeatureCollection: generated cells
    """
    return json.loads(generate_cells_geojson(generator))
