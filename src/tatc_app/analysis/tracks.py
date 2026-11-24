"""
Compact, columnar orbit tracks of satellites (positions, swath widths, and
instrument footprints) used to animate results in a client.

Times are seconds since a common `epoch` to keep payloads small, compared to
one GeoJSON feature per position.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

from datetime import datetime, timedelta
from typing import List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from pydantic import AwareDatetime, BaseModel, Field
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

from .timeline import seconds_since

# tolerance (degrees) to simplify footprints, and decimals to round coordinates
FOOTPRINT_TOLERANCE = 0.01
FOOTPRINT_DECIMALS = 4


class InstrumentTrack(BaseModel):
    """
    Swath widths (and, optionally, footprints) of one instrument of a member
    satellite.
    """

    name: str = Field(..., description="Instrument name.")
    swath_widths: List[float] = Field(
        ...,
        description="Interleaved samples [t, swath width (m), ...] of the "
        "instrument field of regard, with t in seconds since epoch.",
    )
    footprints: Optional[List[Tuple[float, List[List[List[float]]]]]] = Field(
        None,
        description="Samples [t, polygons] of the instrument footprint "
        "computed by TAT-C (`tatc.analysis.collect_ground_track`), with t in "
        "seconds since epoch and each polygon a list of rings (the exterior, "
        "then any holes) of interleaved [longitude (deg), latitude (deg), ...] "
        "coordinates (not closed); no polygons if the instrument does not "
        "observe. If `null`, the footprint is the circle spanned by the swath "
        "width.",
    )
    color: Optional[str] = Field(
        None,
        description="Display color (`#rrggbb`) of the instrument, or `null` "
        "to derive it from the satellite color.",
    )


class MemberTrack(BaseModel):
    """
    Orbit track of a member satellite.
    """

    name: str = Field(..., description="Member satellite name.")
    positions: List[float] = Field(
        ...,
        description="Interleaved samples [t, longitude (deg), latitude (deg), "
        "altitude (m), ...] with t in seconds since epoch.",
    )
    instruments: List[InstrumentTrack] = Field(
        [], description="Swath widths of each instrument (in order)."
    )


class OrbitTracks(BaseModel):
    """
    Orbit tracks of member satellites.
    """

    epoch: AwareDatetime = Field(..., description="Reference time (t=0).")
    tracks: List[MemberTrack] = Field([], description="Member satellite tracks.")

    def get_end(self) -> datetime:
        """
        Gets the latest time of any track (or the epoch, if none).

        Returns:
            datetime.datetime: The end time.
        """
        return self.epoch + timedelta(
            seconds=max(
                (track.positions[-4] for track in self.tracks if track.positions),
                default=0,
            )
        )


def polygon_parts(geometry: Optional[BaseGeometry]) -> List[Polygon]:
    """
    Gets the (non-empty) polygons of a geometry: a polygon, or the polygons
    of a multi-polygon or geometry collection.
    """
    if geometry is None:
        return []
    parts = (
        [geometry] if isinstance(geometry, Polygon) else getattr(geometry, "geoms", [])
    )
    return [part for part in parts if isinstance(part, Polygon) and not part.is_empty]


def encode_polygons(polygons: Sequence[Polygon]) -> List[List[List[float]]]:
    """
    Encodes polygons as lists of rings (the exterior, then any holes) of
    interleaved [longitude, latitude, ...] coordinates, not closed and
    rounded to keep payloads small (see `InstrumentTrack.footprints`).
    """
    return [
        [
            [
                round(float(v), FOOTPRINT_DECIMALS)
                for x, y, *_ in ring.coords[:-1]
                for v in (x, y)
            ]
            for ring in [polygon.exterior, *polygon.interiors]
        ]
        for polygon in polygons
    ]


def decode_polygons(polygons: Sequence[Sequence[Sequence[float]]]) -> List[Polygon]:
    """
    Decodes polygons encoded by `encode_polygons`.
    """
    return [
        Polygon(
            list(zip(rings[0][0::2], rings[0][1::2])),
            [list(zip(ring[0::2], ring[1::2])) for ring in rings[1:]],
        )
        for rings in polygons
    ]


def _footprint_polygons(geometry: Optional[BaseGeometry]) -> List[List[List[float]]]:
    """
    Encodes a footprint (see `InstrumentTrack.footprints`), simplified to
    keep payloads small.
    """
    if geometry is None or geometry.is_empty:
        return []
    return encode_polygons(
        polygon_parts(geometry.simplify(FOOTPRINT_TOLERANCE, preserve_topology=True))
    )


def build_footprints(
    ground_track: pd.DataFrame, epoch: datetime
) -> List[Tuple[float, List[List[List[float]]]]]:
    """
    Builds the footprint samples of one instrument from its ground track
    results (`tatc.analysis.collect_ground_track`), with no polygons when
    the instrument does not observe (`valid_obs` is false).

    Args:
        ground_track (geopandas.GeoDataFrame): The ground track, with columns
            `time`, `geometry`, and (optionally) `valid_obs`.
        epoch (datetime.datetime): The reference time.

    Returns:
        List[Tuple[float, List[List[List[float]]]]]: The footprint samples
            (see `InstrumentTrack.footprints`).
    """
    times = seconds_since(ground_track["time"], epoch)
    valid = (
        ground_track["valid_obs"]
        if "valid_obs" in ground_track
        else pd.Series(True, index=ground_track.index)
    )
    return [
        (t, _footprint_polygons(geometry) if bool(ok) else [])
        for t, geometry, ok in zip(times, ground_track.geometry, valid)
        if t is not None
    ]


def build_member_track(
    orbit_tracks: Sequence[pd.DataFrame],
    epoch: datetime,
    ground_tracks: Optional[Sequence[Optional[pd.DataFrame]]] = None,
) -> MemberTrack:
    """
    Builds the track of one member satellite from its orbit track results
    (`tatc.analysis.collect_orbit_track`, for one satellite and each of its
    instruments, in order). Positions are taken from the first instrument.

    Args:
        orbit_tracks (Sequence[geopandas.GeoDataFrame]): The orbit track of
            each instrument.
        epoch (datetime.datetime): The reference time.
        ground_tracks (Optional[Sequence[Optional[geopandas.GeoDataFrame]]]):
            The ground track (`tatc.analysis.collect_ground_track`) of each
            instrument, or `None` for an instrument (or all) whose footprint
            is the circle spanned by its swath width.

    Returns:
        MemberTrack: The member track.
    """
    positions = []
    instruments = []
    ground_tracks = list(ground_tracks or [])
    for i, orbit_track in enumerate(orbit_tracks):
        times = seconds_since(orbit_track["time"], epoch)
        if i == 0:
            for t, geometry in zip(times, orbit_track.geometry):
                positions.extend(
                    [
                        t,
                        round(geometry.x, 6),
                        round(geometry.y, 6),
                        round(geometry.z, 1),
                    ]
                )
        swath_widths = []
        for t, width in zip(times, orbit_track["swath_width"]):
            swath_widths.extend([t, 0.0 if np.isnan(width) else round(float(width), 1)])
        ground_track = ground_tracks[i] if i < len(ground_tracks) else None
        instruments.append(
            InstrumentTrack(
                name=str(orbit_track["instrument"].iloc[0]) if len(orbit_track) else "",
                swath_widths=swath_widths,
                footprints=(
                    build_footprints(ground_track, epoch)
                    if ground_track is not None
                    else None
                ),
            )
        )
    first = orbit_tracks[0] if len(orbit_tracks) else None
    return MemberTrack(
        name=(
            str(first["satellite"].iloc[0]) if first is not None and len(first) else ""
        ),
        positions=positions,
        instruments=instruments,
    )
