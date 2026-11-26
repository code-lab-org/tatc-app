"""
Formatting of the values of CZML packets: times, intervals, colors,
materials, labels, and polygon positions.

See https://github.com/AnalyticalGraphicsInc/czml-writer/wiki/CZML-Guide

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

from datetime import datetime, timezone
from typing import Iterable, List, Sequence

from shapely.geometry import Polygon

from ..analysis.colors import hex_to_rgb


def iso(time: datetime) -> str:
    """
    Formats a date time as an ISO 8601 string (UTC).
    """
    return (
        time.astimezone(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def interval(start: datetime, end: datetime) -> str:
    """
    Formats an ISO 8601 time interval.
    """
    return f"{iso(start)}/{iso(end)}"


def rgba(color: str, alpha: int = 255) -> List[int]:
    """
    Converts a hex color (`#rrggbb`) to a CZML RGBA array.
    """
    return [*hex_to_rgb(color), alpha]


def solid(color: str, alpha: int = 255) -> dict:
    """
    Builds a CZML solid color material.
    """
    return {"solidColor": {"color": {"rgba": rgba(color, alpha)}}}


def label_graphics(text: str, color: str = "#ffffff", **options) -> dict:
    """
    Builds a CZML label to the right of a point.
    """
    return {
        "text": text,
        "font": "11px sans-serif",
        "fillColor": {"rgba": rgba(color)},
        "outlineColor": {"rgba": [0, 0, 0, 255]},
        "outlineWidth": 2,
        "style": "FILL_AND_OUTLINE",
        "horizontalOrigin": "LEFT",
        "pixelOffset": {"cartesian2": [8, 0]},
        **options,
    }


def ring_degrees(coordinates: Iterable[Sequence[float]]) -> List[float]:
    """
    Converts ring coordinates (longitude, latitude in degrees; not closed)
    to CZML cartographic degrees on the surface.
    """
    return [v for x, y, *_ in coordinates for v in (x, y, 0)]


def polygon_positions(polygon: Polygon) -> dict:
    """
    Builds the positions and holes of a CZML polygon.
    """
    graphics = {
        "positions": {"cartographicDegrees": ring_degrees(polygon.exterior.coords[:-1])}
    }
    if len(polygon.interiors) > 0:
        graphics["holes"] = {
            "cartographicDegrees": [
                ring_degrees(ring.coords[:-1]) for ring in polygon.interiors
            ]
        }
    return graphics
