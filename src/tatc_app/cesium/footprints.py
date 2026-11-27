"""
Builders for the CZML packets of the footprints of the instruments of a
satellite: the polygons computed by TAT-C, if any, or else the circle
spanned by the swath width, centered below the satellite.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import math
from datetime import datetime, timedelta
from typing import List, Sequence, Tuple

from shapely.geometry import Polygon

from ..analysis.colors import instrument_color
from ..analysis.tracks import MemberTrack, decode_polygons
from .polygons import display_polygons
from .primitives import interval, iso, polygon_positions, ring_degrees, solid

# area (square degrees) of footprint polygons drawn as static entities, as
# Cesium takes too long to rebuild larger time-varying polygons every frame
# (about 2 seconds for the full disk of a geostationary imager), and of
# footprints drawn with geodesics (see `polygons.display_polygons`), and the
# tolerance (degrees) within which their shape is unchanged over time (see
# `_footprint_polygon_packets`), as a fraction of their size
STATIC_FOOTPRINT_AREA = 1000
FOOTPRINT_MOTION_TOLERANCE = 0.01


def instrument_fill(track: MemberTrack, index: int, color: str) -> str:
    """
    Gets the color of an instrument of a satellite: its chosen color, if any,
    or else one derived from the satellite color (see `instrument_color`).
    """
    chosen = track.instruments[index].color
    return chosen or instrument_color(color, index, len(track.instruments))


def footprint_packets(
    track: MemberTrack, color: str, epoch: datetime, start: datetime, end: datetime
) -> List[dict]:
    """
    Builds packets for the footprint of each instrument of a satellite: the
    polygons computed by TAT-C, if any, or else the circle spanned by the
    swath width, centered below the satellite.

    Circles are centered on the surface (the sub-satellite point), not at
    the satellite: Cesium sweeps the radius of an ellipse as an arc about
    its center's distance from the Earth's center, which shrinks circles
    centered at the satellite by its geocentric radius over the Earth's
    (about 10% for low Earth orbits, and 6.6 times for geostationary ones).
    """
    nadir = {
        "epoch": iso(epoch),
        "cartographicDegrees": [
            v
            for t, x, y in zip(
                track.positions[0::4], track.positions[1::4], track.positions[2::4]
            )
            for v in (t, x, y, 0)
        ],
        "interpolationAlgorithm": "LAGRANGE",
        "interpolationDegree": 5,
    }
    packets = []
    for index, instrument in enumerate(track.instruments):
        fill = instrument_fill(track, index, color)
        if instrument.footprints is not None:
            packets.extend(
                _footprint_polygon_packets(
                    f"fp/{track.name}/{index}",
                    f"{track.name} {instrument.name}",
                    instrument.footprints,
                    fill,
                    epoch,
                    start,
                    end,
                )
            )
            continue
        widths = instrument.swath_widths
        if not any(w > 0 for w in widths[1::2]):
            continue
        radii = []
        for t, width in zip(widths[0::2], widths[1::2]):
            radii.extend([t, max(width / 2, 1.0)])
        axis = {"epoch": iso(epoch), "number": radii}
        packets.append(
            {
                "id": f"fp/{track.name}/{index}",
                "name": f"{track.name} {instrument.name}",
                "availability": interval(start, end),
                "position": nadir,
                "ellipse": {
                    "semiMajorAxis": axis,
                    "semiMinorAxis": axis,
                    "material": solid(fill, 70),
                },
            }
        )
    return packets


def _merge_intervals(spans: Sequence[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """
    Merges sorted spans (seconds) that touch or overlap.
    """
    merged: List[Tuple[float, float]] = []
    for lower, upper in spans:
        if merged and lower <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], upper))
        else:
            merged.append((lower, upper))
    return merged


def _footprint_runs(
    samples: Sequence[Tuple[float, float, Polygon, str]],
) -> List[Tuple[float, float, Polygon, str]]:
    """
    Merges consecutive samples (lower and upper bounds, shape, and arc type)
    of a footprint polygon whose shape is unchanged, within a fraction
    `FOOTPRINT_MOTION_TOLERANCE` of the size (square root of the area) of
    the first shape of a run, into runs drawn with the first shape. The
    tolerance is relative as the edges of large footprints, near the limb
    of the Earth, move far for small changes of the satellite's position.
    """
    runs: List[Tuple[float, float, Polygon, str]] = []
    for lower, upper, shape, arc_type in samples:
        if runs:
            run_lower, run_upper, run_shape, run_arc_type = runs[-1]
            if (
                lower <= run_upper
                and arc_type == run_arc_type
                and shape.hausdorff_distance(run_shape)
                <= FOOTPRINT_MOTION_TOLERANCE * math.sqrt(run_shape.area)
            ):
                runs[-1] = (run_lower, max(run_upper, upper), run_shape, run_arc_type)
                continue
        runs.append((lower, upper, shape, arc_type))
    return runs


def _footprint_polygon_packets(  # pylint: disable=too-many-arguments,too-many-locals
    identifier: str,
    name: str,
    footprints: Sequence[Tuple[float, Sequence[Sequence[Sequence[float]]]]],
    fill: str,
    epoch: datetime,
    start: datetime,
    end: datetime,
    alpha: int = 70,
) -> List[dict]:
    """
    Builds packets for the time-sampled footprint polygons of an instrument
    (see `InstrumentTrack.footprints`): a parent entity (`identifier`, to
    show or hide the footprint) and child entities (`<identifier>/<n>`) for
    the polygons of a (multi-part) footprint, which change at the midpoints
    between samples.

    Each polygon of a footprint is one child entity whose positions change
    over time, which Cesium rebuilds every frame. Large polygons (of at
    least `STATIC_FOOTPRINT_AREA`), which take too long to rebuild, are
    instead one static child entity for each run of samples whose shape is
    unchanged (see `_footprint_runs`), shown only during its run: a few for
    a geostationary satellite.
    """
    times = [t for t, _ in footprints]
    if not any(polygons for _, polygons in footprints):
        return []
    # polygons (and arc types) to draw at each sample
    # (large footprints with geodesics)
    drawn = [
        display_polygons(
            parts, sum(part.area for part in parts) >= STATIC_FOOTPRINT_AREA
        )
        for parts in (decode_polygons(polygons) for _, polygons in footprints)
    ]
    # each sample spans from the midpoints with its neighbors
    bounds = (
        [times[0]] + [(a + b) / 2 for a, b in zip(times[:-1], times[1:])] + [times[-1]]
    )

    def when(lower: float, upper: float) -> str:
        return interval(
            max(start, epoch + timedelta(seconds=lower)),
            min(end, epoch + timedelta(seconds=upper)),
        )

    def child(polygon: dict, availability) -> dict:
        return {
            "id": f"{identifier}/{len(packets) - 1}",
            "name": name,
            "parent": identifier,
            "availability": availability,
            "polygon": {**polygon, "material": solid(fill, alpha)},
        }

    packets = [
        {
            "id": identifier,
            "name": name,
            "availability": interval(start, end),
        }
    ]
    parts = max(len(polygons) for polygons in drawn)
    for j in range(parts):
        samples = [
            (bounds[k], bounds[k + 1], *polygons[j])
            for k, polygons in enumerate(drawn)
            if j < len(polygons) and bounds[k] < bounds[k + 1]
        ]
        if not samples:
            continue
        if max(shape.area for _, _, shape, _ in samples) >= STATIC_FOOTPRINT_AREA:
            for lower, upper, shape, arc_type in _footprint_runs(samples):
                packets.append(
                    child(
                        {**polygon_positions(shape), "arcType": arc_type},
                        when(lower, upper),
                    )
                )
            continue
        packets.append(
            child(
                _dynamic_polygon(samples, when),
                [
                    when(lower, upper)
                    for lower, upper in _merge_intervals(
                        [(lower, upper) for lower, upper, *_ in samples]
                    )
                ],
            )
        )
    return packets


def _dynamic_polygon(
    samples: Sequence[Tuple[float, float, Polygon, str]],
    when,
) -> dict:
    """
    Builds the positions, holes, and arc types of a CZML polygon that change
    over the samples (lower and upper bounds, shape, and arc type) of a
    footprint polygon, with `when` formatting the interval between bounds.
    """
    arc_types = {arc_type for *_, arc_type in samples}
    polygon = {
        "positions": [
            {
                "interval": when(lower, upper),
                "cartographicDegrees": ring_degrees(shape.exterior.coords[:-1]),
            }
            for lower, upper, shape, _ in samples
        ],
        "arcType": (
            arc_types.pop()
            if len(arc_types) == 1
            else [
                {"interval": when(lower, upper), "arcType": arc_type}
                for lower, upper, _, arc_type in samples
            ]
        ),
    }
    if any(len(shape.interiors) > 0 for _, _, shape, _ in samples):
        polygon["holes"] = [
            {
                "interval": when(lower, upper),
                "cartographicDegrees": [
                    ring_degrees(ring.coords[:-1]) for ring in shape.interiors
                ],
            }
            for lower, upper, shape, _ in samples
        ]
    return polygon
