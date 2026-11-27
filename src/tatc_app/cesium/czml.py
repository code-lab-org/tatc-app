"""
Builders for CZML documents to animate analysis results in Cesium.

Each function returns a list of CZML packets (plain dictionaries). Entity
identifiers follow the pattern `<kind>/<name>`: `sat/<satellite>` for
satellites, `fp/<satellite>/<instrument index>` for instrument footprints
(see `footprints`), `tgt/<target_hash>` for target points, `gs/<station>`
for ground stations, `link/...` for access and contact lines, and
`swath/...` for swath segments, so clients can look up entities by
identifier.

See https://github.com/AnalyticalGraphicsInc/czml-writer/wiki/CZML-Guide

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import math
from datetime import datetime, timedelta
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

import geopandas as gpd
from shapely.geometry import Polygon
from tatc.constants import EARTH_MEAN_RADIUS, EARTH_MU

from ..analysis.colors import assign_colors
from ..analysis.schemas import AnimatedResult
from ..analysis.timeline import Timeline
from ..analysis.tracks import MemberTrack, OrbitTracks, polygon_parts
from .footprints import footprint_packets, instrument_fill
from .polygons import display_polygons
from .primitives import (
    interval,
    iso,
    label_graphics,
    polygon_positions,
    rgba,
    solid,
)

# the color of the areas observed in common by coincident swaths
COINCIDENT_COLOR = "#ffd166"


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
            "label": label_graphics(
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
                "material": solid(color, 160),
            }
        packets.append(packet)
        if footprint:
            packets.extend(footprint_packets(track, color, tracks.epoch, start, end))
    return packets


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
            packet["label"] = label_graphics(
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
        return instrument_fill(track, names.index(instrument), color)
    return color


def _surface_polygons(
    areas: gpd.GeoDataFrame, tolerance: float
) -> Iterator[Tuple[int, tuple, int, Polygon, str]]:
    """
    Prepares the geometries of areas on the surface (such as swath segments)
    to draw: simplified (within a tolerance in degrees) and split into
    polygons to draw (see `polygons.display_polygons`).

    Yields:
        Tuple[int, tuple, int, shapely.geometry.Polygon, str]: The index and
            row of an area, and the index, shape, and arc type of each of
            its polygons.
    """
    simplified = areas.geometry.simplify(tolerance, preserve_topology=True)
    for i, (row, geometry) in enumerate(zip(areas.itertuples(), simplified)):
        for j, (polygon, arc_type) in enumerate(
            display_polygons(polygon_parts(geometry))
        ):
            yield i, row, j, polygon, arc_type


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
    for i, row, j, polygon, arc_type in _surface_polygons(swaths, tolerance):
        instrument = getattr(row, "instrument", None)
        color = _swath_color(
            colors[row.satellite], instrument, member_tracks.get(row.satellite)
        )
        packets.append(
            {
                "id": f"swath/{row.satellite}/{i}/{j}",
                "name": " ".join(
                    str(part) for part in (row.satellite, instrument, "swath") if part
                ),
                "availability": interval(row.end.to_pydatetime(), end),
                "polygon": {
                    **polygon_positions(polygon),
                    "arcType": arc_type,
                    "material": solid(color, alpha),
                },
            }
        )
    return packets


def coincident_packets(
    pairs: gpd.GeoDataFrame,
    end: datetime,
    *,
    tolerance: float = 0.01,
    alpha: int = 200,
) -> List[dict]:
    """
    Builds packets for the areas that pairs of satellites observe in common
    (coincident swaths), which accumulate over time: each appears at its end
    (the later footprint of its pairs) and remains until the end of the
    analysis, outlined in one highlight color over the swaths.

    Args:
        pairs (geopandas.GeoDataFrame): The common areas, with columns
            `satellite_1`, `satellite_2`, `end`, and `geometry`.
        end (datetime.datetime): The end of the analysis.
        tolerance (float): The tolerance (degrees) to simplify geometries.
        alpha (int): The fill opacity (0-255).

    Returns:
        List[dict]: The CZML packets.
    """
    return [
        {
            "id": f"coincident/{i}/{j}",
            "name": f"{row.satellite_1} and {row.satellite_2} in common",
            "availability": interval(row.end.to_pydatetime(), end),
            "polygon": {
                **polygon_positions(polygon),
                "arcType": arc_type,
                "material": solid(COINCIDENT_COLOR, alpha),
                "height": 0,
                "outline": True,
                "outlineColor": {"rgba": [0, 0, 0, 255]},
            },
        }
        for i, row, j, polygon, arc_type in _surface_polygons(pairs, tolerance)
    ]
