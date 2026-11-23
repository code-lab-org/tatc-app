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

import colorsys
import math
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import geopandas as gpd
from shapely.geometry import MultiPolygon, Polygon
from tatc.constants import EARTH_MEAN_RADIUS, EARTH_MU

from .utils.timeline import MemberTrack, OrbitTracks, Timeline

# categorical colors (Tableau 10) assigned to satellites without a color
PALETTE = [
    "#4e79a7",
    "#f28e2b",
    "#e15759",
    "#76b7b2",
    "#59a14f",
    "#edc948",
    "#b07aa1",
    "#ff9da7",
    "#9c755f",
    "#bab0ac",
]


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
    color = color.lstrip("#")
    return [int(color[i : i + 2], 16) for i in (0, 2, 4)] + [alpha]


def assign_colors(
    members: Sequence[str], colors: Optional[Dict[str, str]] = None
) -> Dict[str, str]:
    """
    Assigns a color to each member, defaulting to a categorical palette.

    Args:
        members (Sequence[str]): The member names.
        colors (Optional[Dict[str, str]]): Requested colors by member name.

    Returns:
        Dict[str, str]: The color (`#rrggbb`) of each member.
    """
    colors = colors or {}
    return {
        member: colors.get(member) or PALETTE[i % len(PALETTE)]
        for i, member in enumerate(members)
    }


def instrument_color(color: str, index: int, count: int) -> str:
    """
    Derives a distinct color for each instrument of a satellite: the first
    instrument keeps the satellite color, and others rotate its hue evenly
    (with a minimum saturation, so variants of gray colors stay distinct).

    Args:
        color (str): The satellite color (`#rrggbb`).
        index (int): The instrument index.
        count (int): The number of instruments of the satellite.

    Returns:
        str: The instrument color (`#rrggbb`).
    """
    if index <= 0 or count <= 1:
        return color
    red, green, blue = (c / 255 for c in rgba(color)[:3])
    hue, lightness, saturation = colorsys.rgb_to_hls(red, green, blue)
    red, green, blue = colorsys.hls_to_rgb(
        (hue + index / count) % 1, lightness, max(saturation, 0.5)
    )
    return "#" + "".join(f"{round(c * 255):02x}" for c in (red, green, blue))


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
            "label": {
                "text": track.name,
                "font": "11px sans-serif",
                "fillColor": {"rgba": [255, 255, 255, 255]},
                "outlineColor": {"rgba": [0, 0, 0, 255]},
                "outlineWidth": 2,
                "style": "FILL_AND_OUTLINE",
                "horizontalOrigin": "LEFT",
                "pixelOffset": {"cartesian2": [8, 0]},
                "distanceDisplayCondition": {"distanceDisplayCondition": [0, 3e7]},
            },
        }
        if path:
            period = _orbit_period(track.positions)
            packet["path"] = {
                "leadTime": 0,
                "trailTime": period,
                "resolution": 60,
                "width": 1.5,
                "material": {"solidColor": {"color": {"rgba": rgba(color, 160)}}},
            }
        packets.append(packet)
        if footprint:
            packets.extend(_footprint_packets(track, color, epoch, start, end))
    return packets


def _footprint_packets(
    track: MemberTrack, color: str, epoch: str, start: datetime, end: datetime
) -> List[dict]:
    """
    Builds packets for the footprint of each instrument of a satellite,
    following the position of the satellite packet.
    """
    packets = []
    for index, instrument in enumerate(track.instruments):
        widths = instrument.swath_widths
        if not any(w > 0 for w in widths[1::2]):
            continue
        radii = []
        for t, width in zip(widths[0::2], widths[1::2]):
            radii.extend([t, max(width / 2, 1.0)])
        axis = {"epoch": epoch, "number": radii}
        fill = instrument_color(color, index, len(track.instruments))
        packets.append(
            {
                "id": f"fp/{track.name}/{index}",
                "name": f"{track.name} {instrument.name}",
                "availability": interval(start, end),
                "position": {"reference": f"sat/{track.name}#position"},
                "ellipse": {
                    "semiMajorAxis": axis,
                    "semiMinorAxis": axis,
                    "material": {"solidColor": {"color": {"rgba": rgba(fill, 70)}}},
                },
            }
        )
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
            packet["label"] = {
                "text": name,
                "font": "11px sans-serif",
                "fillColor": {"rgba": rgba(color)},
                "outlineColor": {"rgba": [0, 0, 0, 255]},
                "outlineWidth": 2,
                "style": "FILL_AND_OUTLINE",
                "horizontalOrigin": "LEFT",
                "pixelOffset": {"cartesian2": [8, 0]},
                "heightReference": "CLAMP_TO_GROUND",
                "disableDepthTestDistance": 1e12,
            }
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
            "cartographicDegrees": [
                v for x, y, *_ in polygon.exterior.coords[:-1] for v in (x, y, 0)
            ]
        }
    }
    if len(polygon.interiors) > 0:
        graphics["holes"] = {
            "cartographicDegrees": [
                [v for x, y, *_ in ring.coords[:-1] for v in (x, y, 0)]
                for ring in polygon.interiors
            ]
        }
    return graphics


def _swath_color(color: str, instrument: Optional[str], names: Sequence[str]) -> str:
    """
    Gets the color of a swath segment of an instrument (by name) among the
    instruments of a satellite, or the satellite color if not found.
    """
    names = list(names)
    if instrument in names:
        return instrument_color(color, names.index(instrument), len(names))
    return color


def swath_packets(
    swaths: gpd.GeoDataFrame,
    end: datetime,
    colors: Optional[Dict[str, str]] = None,
    *,
    instruments: Optional[Dict[str, Sequence[str]]] = None,
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
        tolerance (float): The tolerance (degrees) to simplify geometries.
        alpha (int): The fill opacity (0-255).
        instruments (Optional[Dict[str, Sequence[str]]]): The instrument
            names of each satellite (in order), to color the segments of each
            instrument distinctly (see `instrument_color`).

    Returns:
        List[dict]: The CZML packets.
    """
    colors = assign_colors(list(dict.fromkeys(swaths["satellite"])), colors)
    instruments = instruments or {}
    packets = []
    for i, row in enumerate(swaths.itertuples()):
        instrument = getattr(row, "instrument", None)
        color = _swath_color(
            colors[row.satellite], instrument, instruments.get(row.satellite, [])
        )
        geometry = row.geometry.simplify(tolerance, preserve_topology=True)
        polygons = (
            list(geometry.geoms)
            if isinstance(geometry, MultiPolygon)
            else [geometry] if isinstance(geometry, Polygon) else []
        )
        for j, polygon in enumerate(polygons):
            if polygon.is_empty:
                continue
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
                        "arcType": "RHUMB",
                        "material": {
                            "solidColor": {"color": {"rgba": rgba(color, alpha)}}
                        },
                    },
                }
            )
    return packets
