"""
Preparation of polygons in longitude/latitude (as TAT-C's footprints and
swaths) to draw in Cesium: the arc types of their edges, and polygons that
touch a pole or cross the antimeridian re-formed so Cesium can draw them.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import functools
from typing import Dict, List, Sequence, Tuple

import numpy as np
import shapely
from pyproj import Transformer
from shapely.affinity import translate
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from ..analysis.tracks import polygon_parts

# tolerance (degrees) to find polygon vertices at a pole
POLE_TOLERANCE = 1e-6
# tolerances (meters) to close seams between, and to simplify, the parts of
# polygons re-formed around a pole (see `display_polygons`)
POLAR_SEAM_TOLERANCE = 10
POLAR_SIMPLIFY_TOLERANCE = 1000
# maximum length (degrees) of the edges of polygons drawn with rhumb lines
# (see `display_polygons`)
RHUMB_SEGMENT_LENGTH = 2.0


def _touches_pole(polygon: Polygon, sign: int) -> bool:
    """
    Checks whether a polygon has a vertex at the north (`sign` 1) or south
    (`sign` -1) pole.
    """
    return any(sign * y >= 90 - POLE_TOLERANCE for _, y, *_ in polygon.exterior.coords)


@functools.cache
def _polar_transformers(sign: int) -> Tuple[Transformer, Transformer]:
    """
    Gets the transformers to and from an azimuthal equidistant projection
    centered on the north (`sign` 1) or south (`sign` -1) pole.
    """
    crs = f"+proj=aeqd +lat_0={90 * sign} +lon_0=0 +datum=WGS84 +units=m"
    return (
        Transformer.from_crs("EPSG:4326", crs, always_xy=True),
        Transformer.from_crs(crs, "EPSG:4326", always_xy=True),
    )


def _reproject(geometry: BaseGeometry, transformer: Transformer) -> BaseGeometry:
    return shapely.transform(
        geometry,
        lambda c: np.column_stack(transformer.transform(c[:, 0], c[:, 1])),
    )


def _touches_antimeridian(polygon: Polygon, sign: int) -> bool:
    """
    Checks whether a polygon has a vertex at the antimeridian, at longitude
    180 (`sign` 1) or -180 (`sign` -1).
    """
    return any(sign * x >= 180 - POLE_TOLERANCE for x, *_ in polygon.exterior.coords)


def _join_antimeridian(polygons: Sequence[Polygon]) -> List[Polygon]:
    """
    Joins polygons (parts of one geometry) that TAT-C split at the
    antimeridian, shifting those at longitude 180 by -360 degrees (so that
    longitudes continue past -180), as edges along the antimeridian would
    no longer coincide when drawn with geodesics. The vertices TAT-C added
    at the antimeridian (on straight longitude/latitude lines, which kink
    geodesics) are removed.
    """
    if not (
        any(_touches_antimeridian(p, 1) for p in polygons)
        and any(_touches_antimeridian(p, -1) for p in polygons)
    ):
        return list(polygons)
    joined = unary_union(
        [translate(p, -360) if _touches_antimeridian(p, 1) else p for p in polygons]
    )

    def ring(coordinates) -> list:
        return [(x, y) for x, y, *_ in coordinates if abs(x + 180) > POLE_TOLERANCE]

    results = []
    for polygon in polygon_parts(joined):
        cleaned = Polygon(
            ring(polygon.exterior.coords),
            [ring(interior.coords) for interior in polygon.interiors],
        )
        results.append(cleaned if cleaned.is_valid else polygon)
    return results


def display_polygons(
    polygons: Sequence[Polygon], geodesic: bool = False
) -> List[Tuple[Polygon, str]]:
    """
    Prepares polygons in longitude/latitude (as TAT-C's footprints and
    swaths) to draw in Cesium, with the arc type of their edges.

    Polygons are drawn with rhumb lines (`RHUMB`), which follow their
    longitude/latitude edges, or, if `geodesic`, with geodesics
    (`GEODESIC`) between their vertices, except those that touch a pole.
    Geodesics follow the boundary of a large footprint, whose vertices are
    sampled on its curved boundary, more closely than rhumb lines, which
    sag toward the equator far from it. Rhumb lines are divided into
    segments of at most `RHUMB_SEGMENT_LENGTH`: Cesium triangulates a
    polygon between its vertices as if its edges were geodesics, which, for
    long rhumb lines far from the equator, fills the wrong area between
    them.

    Polygons drawn with geodesics that TAT-C split at the antimeridian are
    joined (see `_join_antimeridian`).

    TAT-C splits a geometry that covers a pole at the antimeridian, with
    edges along the
    pole (or, as one ring, with a zero-width spike out to the pole and back),
    which Cesium cannot draw: rhumb lines to a pole are undefined, and such
    rings do not triangulate. Polygons that touch a pole are merged in an
    azimuthal equidistant projection centered on the pole, where the
    antimeridian and the pole are not edges, simplified (removing slivers
    Cesium cannot triangulate), and re-formed as polygons around the pole,
    drawn with geodesics (`GEODESIC`).

    Args:
        polygons (Sequence[shapely.geometry.Polygon]): The polygons (parts
            of one geometry).
        geodesic (bool): `True`, to draw polygons with geodesics.

    Returns:
        List[Tuple[shapely.geometry.Polygon, str]]: The polygons to draw and
            the arc type of their edges.
    """
    results = []
    polar: Dict[int, List[Polygon]] = {1: [], -1: []}
    others = []
    for polygon in polygons:
        if polygon.is_empty:
            continue
        if _touches_pole(polygon, 1):
            polar[1].append(polygon)
        elif _touches_pole(polygon, -1):
            polar[-1].append(polygon)
        else:
            others.append(polygon)
    if geodesic:
        results.extend((polygon, "GEODESIC") for polygon in _join_antimeridian(others))
    else:
        results.extend(
            (shapely.segmentize(polygon, RHUMB_SEGMENT_LENGTH), "RHUMB")
            for polygon in others
        )
    for sign, parts in polar.items():
        if not parts:
            continue
        to_polar, from_polar = _polar_transformers(sign)
        merged = (
            unary_union([shapely.make_valid(_reproject(p, to_polar)) for p in parts])
            .buffer(POLAR_SEAM_TOLERANCE)
            .buffer(-POLAR_SEAM_TOLERANCE)
            .simplify(POLAR_SIMPLIFY_TOLERANCE)
        )
        for geometry in getattr(merged, "geoms", [merged]):
            if isinstance(geometry, Polygon) and not geometry.is_empty:
                results.append((_reproject(geometry, from_polar), "GEODESIC"))
    return results
