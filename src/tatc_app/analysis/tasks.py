"""
Shared tasks and utilities of analyses.

Analyses are enqueued as a Celery chord: a group of parallel tasks (each
returning a result tagged by `kind`, for example a chunk of observations or
the orbit track of one satellite) followed by one task that combines them.
Every analysis also collects the orbit track of each member satellite
(`collect_member_track_task`) to animate its results.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import json
from datetime import datetime
from typing import Dict, List, NamedTuple, Optional

import geopandas as gpd
import pandas as pd
from tatc.analysis import collect_ground_track, collect_orbit_track
from tatc.schemas import Instrument, Satellite

from ..worker import app
from .colors import assign_colors
from .tracks import MemberTrack, OrbitTracks, build_member_track

# maximum swath width (meters) of a footprint drawn as a circle: Cesium
# tessellates wider circles on the ground with gaps (and breaks up circles
# spanning about a quarter of the Earth, as the full disk of a geostationary
# imager), so wider footprints are drawn with polygons computed by TAT-C
MAX_CIRCULAR_SWATH_WIDTH = 6000e3


def tag(kind: str, data) -> dict:
    """
    Tags the result of a parallel task by kind.
    """
    return {"kind": kind, "data": data}


def untag(results: list, kind: str) -> list:
    """
    Gets the results of parallel tasks of a kind.
    """
    return [r["data"] for r in results if r["kind"] == kind]


def deserialize_members(members: List[str]) -> List[Satellite]:
    """
    Deserializes member satellites passed to tasks (see
    `endpoints.serialize_members`).
    """
    return [Satellite.model_validate_json(member) for member in members]


def parse_times(times: List[str]) -> pd.DatetimeIndex:
    """
    Parses ISO 8601 serialized times passed to tasks (in UTC).
    """
    return pd.DatetimeIndex([datetime.fromisoformat(t) for t in times]).tz_convert(
        "UTC"
    )


def has_circular_footprint(
    instrument, orbit_track: Optional[pd.DataFrame] = None
) -> bool:
    """
    Checks whether an instrument's footprint is the circle spanned by its
    swath width: a (simple) instrument, whose view is a cone centered on
    nadir spanning its field of regard, with a swath width (in its orbit
    track, if given) of at most `MAX_CIRCULAR_SWATH_WIDTH`. Footprints of
    other instruments (pointed, conical, or in situ), and wider circles,
    are computed by TAT-C to animate results.
    """
    if not (isinstance(instrument, Instrument) and instrument.type == "instrument"):
        return False
    if orbit_track is None or orbit_track.empty:
        return True
    return not (orbit_track["swath_width"] > MAX_CIRCULAR_SWATH_WIDTH).any()


def compute_member_track(
    satellite: Satellite, times: pd.DatetimeIndex, epoch: datetime
) -> MemberTrack:
    """
    Computes the orbit track (and instrument footprints) of a member
    satellite to animate results.

    Args:
        satellite (tatc.schemas.Satellite): The satellite.
        times (pandas.DatetimeIndex): The times.
        epoch (datetime.datetime): The reference time.

    Returns:
        MemberTrack: The member track.
    """
    indices = range(len(satellite.instruments))
    orbit_tracks = [collect_orbit_track(satellite, times, index) for index in indices]
    return build_member_track(
        orbit_tracks,
        epoch,
        [
            (
                None
                if has_circular_footprint(
                    satellite.instruments[index], orbit_tracks[index]
                )
                else collect_ground_track(satellite, times, index)
            )
            for index in indices
        ],
    )


@app.task
def collect_member_track_task(
    satellite: str, times: list, epoch: str, colors: Optional[list] = None
) -> dict:
    """
    Task to collect the orbit track of a member satellite to animate results.

    Args:
        satellite (str): JSON serialized :class:`tatc.schemas.Satellite` object.
        times (list): List of ISO 8601 serialized times.
        epoch (str): ISO 8601 serialized reference time.
        colors (Optional[list]): Display colors of the instruments (in
            order, `None` to derive one from the satellite color).

    Returns:
        dict: Tagged (`track`) JSON serialized `MemberTrack`.
    """
    track = compute_member_track(
        Satellite.model_validate_json(satellite),
        parse_times(times),
        datetime.fromisoformat(epoch),
    )
    for instrument, color in zip(track.instruments, colors or []):
        instrument.color = color
    return tag("track", track.model_dump_json())


class Animation(NamedTuple):
    """
    The orbit tracks (and colors) of member satellites that animate the
    results of an analysis.
    """

    epoch: datetime
    tracks: OrbitTracks
    members: List[str]
    colors: Dict[str, str]


def combine_animation(
    results: list, start: str, colors: Optional[Dict[str, str]]
) -> Animation:
    """
    Combines the tagged member tracks of parallel tasks, assigning a color
    to each member satellite.

    Args:
        results (list): The tagged results of parallel tasks.
        start (str): ISO 8601 serialized start time (reference time).
        colors (Optional[Dict[str, str]]): Requested colors by member name.

    Returns:
        Animation: The epoch, orbit tracks, member names, and colors.
    """
    epoch = datetime.fromisoformat(start)
    tracks = OrbitTracks.model_validate(
        {
            "epoch": epoch,
            "tracks": [json.loads(track) for track in untag(results, "track")],
        }
    )
    members = [track.name for track in tracks.tracks]
    return Animation(epoch, tracks, members, assign_colors(members, colors))


def get_cell_targets(
    points: gpd.GeoDataFrame, cells: gpd.GeoDataFrame
) -> Dict[str, List[int]]:
    """
    Gets the indices of points within each cell.

    Args:
        points (geopandas.GeoDataFrame): The points.
        cells (geopandas.GeoDataFrame): The cells (with a `cell_id` column).

    Returns:
        Dict[str, List[int]]: The point indices by `cell_id`.
    """
    if points.empty or cells.empty:
        return {}
    joined = gpd.sjoin(
        gpd.GeoDataFrame(geometry=points.geometry.values, crs="EPSG:4326"),
        cells[["cell_id", "geometry"]],
        predicate="intersects",
    )
    return {
        str(cell_id): sorted(int(i) for i in group.index)
        for cell_id, group in joined.groupby("cell_id")
    }
