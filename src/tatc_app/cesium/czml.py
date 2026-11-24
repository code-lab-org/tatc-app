"""
Builders for CZML documents to animate analysis results in Cesium.

Each function returns a list of CZML packets (plain dictionaries). Entity
identifiers follow the pattern `<kind>/<name>`: `sat/<satellite>` for
satellites, `fp/<satellite>/<instrument index>` for instrument footprints,
`tgt/<target_hash>` for target points, `gs/<station>` for ground stations,
`link/...` for access and contact lines, and `swath/...` for swath segments,
so clients can look up entities by identifier.

See https://github.com/AnalyticalGraphicsInc/czml-writer/wiki/CZML-Guide

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import functools
import math
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import geopandas as gpd
import numpy as np
import shapely
from pyproj import Transformer
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from tatc.constants import EARTH_MEAN_RADIUS, EARTH_MU

from ..analysis.colors import assign_colors, hex_to_rgb, instrument_color
from ..analysis.schemas import AnimatedResult
from ..analysis.timeline import Timeline
from ..analysis.tracks import MemberTrack, OrbitTracks, decode_polygons, polygon_parts

# tolerance (degrees) to find polygon vertices at a pole
POLE_TOLERANCE = 1e-6
# tolerances (meters) to close seams between, and to simplify, the parts of
# polygons re-formed around a pole (see `display_polygons`)
POLAR_SEAM_TOLERANCE = 10
POLAR_SIMPLIFY_TOLERANCE = 1000
# maximum length (degrees) of the edges of polygons drawn with rhumb lines
# (see `display_polygons`)
RHUMB_SEGMENT_LENGTH = 2.0
# area (square degrees) of footprint polygons drawn as static entities, as
# Cesium takes too long to rebuild larger time-varying polygons every frame
# (about 2 seconds for the full disk of a geostationary imager), and the
# tolerance (degrees) within which their shape is unchanged over time (see
# `_footprint_polygon_packets`), as a fraction of their size
STATIC_FOOTPRINT_AREA = 1000
FOOTPRINT_MOTION_TOLERANCE = 0.01


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


def _solid(color: str, alpha: int = 255) -> dict:
    """
    Builds a CZML solid color material.
    """
    return {"solidColor": {"color": {"rgba": rgba(color, alpha)}}}


def _label(text: str, color: str = "#ffffff", **options) -> dict:
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


def document_packet(
    name: str, start: datetime, end: datetime, multiplier: float = 60
) -> dict:
    """
    Builds the document packet, which sets the clock of the animation.

    Args:
        name (str): The document name.
        start (datetime.datetime): The animation start.
        end (datetime.datetime): The animation end.
        multiplier (float): The animation speed (simulated seconds per second).

    Returns:
        dict: The CZML packet.
    """
    return {
        "id": "document",
        "name": name,
        "version": "1.0",
        "clock": {
            "interval": interval(start, end),
            "currentTime": iso(start),
            "multiplier": multiplier,
            "range": "LOOP_STOP",
            "step": "SYSTEM_CLOCK_MULTIPLIER",
        },
    }


def animation_packets(name: str, result: AnimatedResult) -> List[dict]:
    """
    Builds the document packet and satellite packets that animate the
    results of an analysis.

    Args:
        name (str): The document name.
        result (AnimatedResult): The analysis result.

    Returns:
        List[dict]: The CZML packets.
    """
    return [
        document_packet(name, result.tracks.epoch, result.tracks.get_end())
    ] + satellite_packets(result.tracks, result.colors)


def _orbit_period(positions: Sequence[float]) -> float:
    """
    Estimates the orbital period (seconds) from the mean altitude of a track.
    """
    altitudes = positions[3::4]
    if len(altitudes) == 0:
        return 0
    semimajor_axis = EARTH_MEAN_RADIUS + sum(altitudes) / len(altitudes)
    return 2 * math.pi * math.sqrt(semimajor_axis**3 / EARTH_MU)


def satellite_packets(
    tracks: OrbitTracks,
    colors: Optional[Dict[str, str]] = None,
    path: bool = True,
    footprint: bool = True,
) -> List[dict]:
    """
    Builds packets for satellites moving along their orbit tracks, with an
    optional trailing path and optional footprints (for each instrument, the
    circle spanned by the swath width of its field of regard, in a distinct
    translucent color so overlapping footprints remain visible).

    Args:
        tracks (OrbitTracks): The orbit tracks.
        colors (Optional[Dict[str, str]]): The color of each satellite.
        path (bool): `True`, to draw a path trailing one orbital period.
        footprint (bool): `True`, to draw the field of regard footprints.

    Returns:
        List[dict]: The CZML packets.
    """
    colors = assign_colors([track.name for track in tracks.tracks], colors)
    epoch = iso(tracks.epoch)
    packets = []
    for track in tracks.tracks:
        if len(track.positions) < 4:
            continue
        color = colors[track.name]
        start = tracks.epoch + timedelta(seconds=track.positions[0])
        end = tracks.epoch + timedelta(seconds=track.positions[-4])
        packet = {
            "id": f"sat/{track.name}",
            "name": track.name,
            "availability": interval(start, end),
            "position": {
                "epoch": epoch,
                "cartographicDegrees": track.positions,
                "interpolationAlgorithm": "LAGRANGE",
                "interpolationDegree": 5,
            },
            "point": {
                "pixelSize": 8,
                "color": {"rgba": rgba(color)},
                "outlineColor": {"rgba": [255, 255, 255, 255]},
                "outlineWidth": 1,
            },
            "label": _label(
                track.name,
                distanceDisplayCondition={"distanceDisplayCondition": [0, 3e7]},
            ),
        }
        if path:
            period = _orbit_period(track.positions)
            packet["path"] = {
                "leadTime": 0,
                "trailTime": period,
                "resolution": 60,
                "width": 1.5,
                "material": _solid(color, 160),
            }
        packets.append(packet)
        if footprint:
            packets.extend(_footprint_packets(track, color, tracks.epoch, start, end))
    return packets


def _instrument_fill(track: MemberTrack, index: int, color: str) -> str:
    """
    Gets the color of an instrument of a satellite: its chosen color, if any,
    or else one derived from the satellite color (see `instrument_color`).
    """
    chosen = track.instruments[index].color
    return chosen or instrument_color(color, index, len(track.instruments))


def _footprint_packets(
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
        fill = _instrument_fill(track, index, color)
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
                    "material": _solid(fill, 70),
                },
            }
        )
    return packets


def _ring_degrees(coordinates: Iterable[Sequence[float]]) -> List[float]:
    """
    Converts ring coordinates (longitude, latitude in degrees; not closed)
    to CZML cartographic degrees on the surface.
    """
    return [v for x, y, *_ in coordinates for v in (x, y, 0)]


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


def display_polygons(polygons: Sequence[Polygon]) -> List[Tuple[Polygon, str]]:
    """
    Prepares polygons in longitude/latitude (as TAT-C's footprints and
    swaths) to draw in Cesium, with the arc type of their edges.

    Polygons are drawn with rhumb lines (`RHUMB`), which follow their
    longitude/latitude edges, except those that touch a pole. Their edges
    are divided into segments of at most `RHUMB_SEGMENT_LENGTH`: Cesium
    triangulates a polygon between its vertices as if its edges were
    geodesics, which, for long rhumb lines far from the equator (as edges
    of the full disk of a geostationary imager), fills the wrong area
    between them. TAT-C splits
    a geometry that covers a pole at the antimeridian, with edges along the
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

    Returns:
        List[Tuple[shapely.geometry.Polygon, str]]: The polygons to draw and
            the arc type of their edges.
    """
    results = []
    polar: Dict[int, List[Polygon]] = {1: [], -1: []}
    for polygon in polygons:
        if polygon.is_empty:
            continue
        if _touches_pole(polygon, 1):
            polar[1].append(polygon)
        elif _touches_pole(polygon, -1):
            polar[-1].append(polygon)
        else:
            results.append((shapely.segmentize(polygon, RHUMB_SEGMENT_LENGTH), "RHUMB"))
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
    drawn = [display_polygons(decode_polygons(polygons)) for _, polygons in footprints]
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
            "polygon": {**polygon, "material": _solid(fill, alpha)},
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
                        {**_polygon_positions(shape), "arcType": arc_type},
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
                "cartographicDegrees": _ring_degrees(shape.exterior.coords[:-1]),
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
                    _ring_degrees(ring.coords[:-1]) for ring in shape.interiors
                ],
            }
            for lower, upper, shape, _ in samples
        ]
    return polygon


def site_packets(
    prefix: str,
    sites: Iterable[Tuple[str, str, float, float]],
    color: str = "#ffffff",
    pixel_size: int = 6,
    label: bool = False,
) -> List[dict]:
    """
    Builds packets for fixed sites on the surface (targets or stations).

    Args:
        prefix (str): The identifier prefix (for example, `tgt` or `gs`).
        sites (Iterable[Tuple[str, str, float, float]]): The identifier,
            name, longitude (degrees), and latitude (degrees) of each site.
        color (str): The point color.
        pixel_size (int): The point size (pixels).
        label (bool): `True`, to label each site with its name.

    Returns:
        List[dict]: The CZML packets.
    """
    packets = []
    for identifier, name, longitude, latitude in sites:
        packet = {
            "id": f"{prefix}/{identifier}",
            "name": name,
            "position": {"cartographicDegrees": [longitude, latitude, 0]},
            "point": {
                "pixelSize": pixel_size,
                "color": {"rgba": rgba(color)},
                "outlineColor": {"rgba": [0, 0, 0, 255]},
                "outlineWidth": 1,
                "heightReference": "CLAMP_TO_GROUND",
                "disableDepthTestDistance": 1e12,
            },
        }
        if label:
            packet["label"] = _label(
                name,
                color,
                heightReference="CLAMP_TO_GROUND",
                disableDepthTestDistance=1e12,
            )
        packets.append(packet)
    return packets


def link_packets(
    timeline: Timeline,
    target_prefix: str,
    colors: Optional[Dict[str, str]] = None,
    min_duration: float = 1,
    width: float = 2,
) -> List[dict]:
    """
    Builds packets for lines between targets and satellites (for example,
    accesses to target points or contacts with ground stations), each
    available only during its events.

    Args:
        timeline (Timeline): The events between targets and satellites.
        target_prefix (str): The identifier prefix of targets (for example,
            `tgt` or `gs`).
        colors (Optional[Dict[str, str]]): The color of each satellite.
        min_duration (float): The minimum duration (seconds) to display an
            instantaneous event.
        width (float): The line width (pixels).

    Returns:
        List[dict]: The CZML packets.
    """
    colors = assign_colors(timeline.members, colors)
    intervals = {}
    for target, member, start, end in zip(
        timeline.target, timeline.member, timeline.start, timeline.end
    ):
        end = start + min_duration if end is None or end - start < min_duration else end
        intervals.setdefault((target, member), []).append(
            interval(
                timeline.epoch + timedelta(seconds=start),
                timeline.epoch + timedelta(seconds=end),
            )
        )
    packets = []
    for (target, member), availability in intervals.items():
        target_id = f"{target_prefix}/{timeline.targets[target]}"
        member_name = timeline.members[member]
        packets.append(
            {
                "id": f"link/{target_id}/{member_name}",
                "name": f"{member_name} - {timeline.targets[target]}",
                "availability": availability,
                "polyline": {
                    "positions": {
                        "references": [
                            f"{target_id}#position",
                            f"sat/{member_name}#position",
                        ]
                    },
                    "arcType": "NONE",
                    "width": width,
                    "material": {
                        "polylineGlow": {
                            "color": {"rgba": rgba(colors[member_name])},
                            "glowPower": 0.2,
                        }
                    },
                },
            }
        )
    return packets


def _polygon_positions(polygon: Polygon) -> dict:
    """
    Builds the positions and holes of a CZML polygon.
    """
    graphics = {
        "positions": {
            "cartographicDegrees": _ring_degrees(polygon.exterior.coords[:-1])
        }
    }
    if len(polygon.interiors) > 0:
        graphics["holes"] = {
            "cartographicDegrees": [
                _ring_degrees(ring.coords[:-1]) for ring in polygon.interiors
            ]
        }
    return graphics


def _swath_color(
    color: str, instrument: Optional[str], track: Optional[MemberTrack]
) -> str:
    """
    Gets the color of a swath segment of an instrument (by name) of a
    satellite: the color of the instrument of its track, or the satellite
    color if not found.
    """
    names = [i.name for i in track.instruments] if track else []
    if instrument in names:
        return _instrument_fill(track, names.index(instrument), color)
    return color


def swath_packets(
    swaths: gpd.GeoDataFrame,
    end: datetime,
    colors: Optional[Dict[str, str]] = None,
    *,
    tracks: Optional[OrbitTracks] = None,
    tolerance: float = 0.01,
    alpha: int = 150,
) -> List[dict]:
    """
    Builds packets for swath segments that accumulate over time: each
    segment appears at its end time and remains until the end of the
    analysis.

    Args:
        swaths (geopandas.GeoDataFrame): The swath segments, with columns
            `satellite`, `start`, `end`, and `geometry` (and, optionally,
            `instrument`).
        end (datetime.datetime): The end of the analysis.
        colors (Optional[Dict[str, str]]): The color of each satellite.
        tracks (Optional[OrbitTracks]): The orbit tracks of the satellites,
            whose instruments (and their colors) color the segments of each
            instrument distinctly.
        tolerance (float): The tolerance (degrees) to simplify geometries.
        alpha (int): The fill opacity (0-255).

    Returns:
        List[dict]: The CZML packets.
    """
    colors = assign_colors(list(dict.fromkeys(swaths["satellite"])), colors)
    member_tracks = {track.name: track for track in tracks.tracks} if tracks else {}
    packets = []
    for i, row in enumerate(swaths.itertuples()):
        instrument = getattr(row, "instrument", None)
        color = _swath_color(
            colors[row.satellite], instrument, member_tracks.get(row.satellite)
        )
        polygons = polygon_parts(
            row.geometry.simplify(tolerance, preserve_topology=True)
        )
        for j, (polygon, arc_type) in enumerate(display_polygons(polygons)):
            packets.append(
                {
                    "id": f"swath/{row.satellite}/{i}/{j}",
                    "name": " ".join(
                        str(part)
                        for part in (row.satellite, instrument, "swath")
                        if part
                    ),
                    "availability": interval(row.end.to_pydatetime(), end),
                    "polygon": {
                        **_polygon_positions(polygon),
                        "arcType": arc_type,
                        "material": _solid(color, alpha),
                    },
                }
            )
    return packets
