"""
Router specifications for generation endpoints.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import json

from fastapi import APIRouter, HTTPException
from geojson_pydantic import FeatureCollection
from shapely.geometry import mapping

from ..utils.serialization import MSGPACK_RESPONSES
from .masks import resolve_mask
from .schemas import CellGenerator, PointGenerator, RegionOutlineRequest, mask_spec
from .utils import generate_cells_geojson, generate_points_geojson

router = APIRouter()


@router.post(
    "/points",
    response_model=FeatureCollection,
    response_model_exclude_none=True,
    responses=MSGPACK_RESPONSES,
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
    responses=MSGPACK_RESPONSES,
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


# the tolerance (degrees) to simplify outlines, and the longest segment
# (degrees) of an outline, so that edges spanning the globe (such as of a
# band of latitude) display along their parallels
OUTLINE_TOLERANCE = 0.01
OUTLINE_SEGMENT = 1.0


@router.post(
    "/region",
    response_model=FeatureCollection,
    response_model_exclude_none=True,
    responses=MSGPACK_RESPONSES,
)
def generate_region_outline(request: RegionOutlineRequest):
    """
    Endpoint to get the outline of a region (simplified, with edges
    subdivided) to display it: no features for the globe.

    Args:
        request (RegionOutlineRequest): The region.

    Returns:
        FeatureCollection: The region's outline.
    """
    try:
        region = resolve_mask(mask_spec(request.mask))
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid region: {exc}") from exc
    features = []
    if region is not None and not region.is_empty:
        outline = region.simplify(OUTLINE_TOLERANCE, preserve_topology=True).segmentize(
            OUTLINE_SEGMENT
        )
        features.append(
            {"type": "Feature", "geometry": mapping(outline), "properties": {}}
        )
    return {"type": "FeatureCollection", "features": features}
