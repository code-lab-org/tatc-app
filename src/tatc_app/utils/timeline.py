"""
Compact, columnar representations of time-dynamic analysis results used to
animate results in a client: timelines of events (observations, contacts,
data latencies) between targets and satellites, and orbit tracks of
satellites.

Times are seconds since a common `epoch` to keep payloads small, compared to
one GeoJSON feature per event or position.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

from datetime import datetime, timedelta
from typing import List, Optional, Sequence

import numpy as np
import pandas as pd
from pydantic import AwareDatetime, BaseModel, Field


class Timeline(BaseModel):
    """
    Events between targets (for example, points or ground stations) and
    members (satellites), each spanning a `start` and (optional) `end` time.
    """

    epoch: AwareDatetime = Field(..., description="Reference time (t=0).")
    targets: List[str] = Field(
        ..., description="Target identifiers (for example, `target_hash`)."
    )
    members: List[str] = Field(..., description="Member satellite names.")
    target: List[int] = Field(..., description="Target index of each event.")
    member: List[int] = Field(..., description="Member index of each event.")
    start: List[float] = Field(..., description="Event start (seconds since epoch).")
    end: List[Optional[float]] = Field(
        ..., description="Event end (seconds since epoch), or null if none."
    )


def _seconds_since(times: pd.Series, epoch: datetime) -> List[Optional[float]]:
    seconds = (
        pd.to_datetime(times, utc=True) - pd.Timestamp(epoch).tz_convert("UTC")
    ).dt.total_seconds()
    return [None if np.isnan(s) else round(float(s), 3) for s in seconds]


def build_timeline(
    events: pd.DataFrame,
    epoch: datetime,
    targets: Sequence[str],
    members: Sequence[str],
    target_column: str = "target_hash",
    member_column: str = "satellite",
    start_column: str = "start",
    end_column: str = "end",
) -> Timeline:
    """
    Builds a timeline from a data frame of events, sorted by start time.
    Events with an unknown target or member are dropped; events attributed
    to several members (as by `tatc.analysis.aggregate_observations`, which
    merges overlapping observations) are attributed to the first.

    Args:
        events (pandas.DataFrame): The events.
        epoch (datetime.datetime): The reference time.
        targets (Sequence[str]): The target identifiers.
        members (Sequence[str]): The member names.
        target_column (str): The column identifying the target of an event.
        member_column (str): The column identifying the member of an event.
        start_column (str): The column of event start times.
        end_column (str): The column of event end times.

    Returns:
        Timeline: The timeline.
    """
    targets = list(targets)
    members = list(members)
    if events is None or events.empty:
        return Timeline(
            epoch=epoch,
            targets=targets,
            members=members,
            target=[],
            member=[],
            start=[],
            end=[],
        )
    target = pd.Categorical(events[target_column], categories=targets).codes
    # aggregated observations name all overlapping satellites ("a, b"):
    # attribute them to the first
    member = pd.Categorical(
        events[member_column].astype(str).str.split(", ").str[0],
        categories=members,
    ).codes
    frame = pd.DataFrame(
        {
            "target": target,
            "member": member,
            "start": pd.to_datetime(events[start_column], utc=True).values,
            "end": pd.to_datetime(events[end_column], utc=True).values,
        }
    )
    frame = frame[(frame.target >= 0) & (frame.member >= 0)].sort_values("start")
    return Timeline(
        epoch=epoch,
        targets=targets,
        members=members,
        target=frame.target.astype(int).tolist(),
        member=frame.member.astype(int).tolist(),
        start=_seconds_since(frame.start, epoch),
        end=_seconds_since(frame.end, epoch),
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
    swath_widths: List[float] = Field(
        ...,
        description="Interleaved samples [t, swath width (m), ...] of the "
        "instrument field of regard, with t in seconds since epoch.",
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


def build_member_track(orbit_track: pd.DataFrame, epoch: datetime) -> MemberTrack:
    """
    Builds the track of one member satellite from its orbit track results
    (`tatc.analysis.collect_orbit_track`, for one satellite and instrument).

    Args:
        orbit_track (geopandas.GeoDataFrame): The orbit track.
        epoch (datetime.datetime): The reference time.

    Returns:
        MemberTrack: The member track.
    """
    times = _seconds_since(orbit_track["time"], epoch)
    positions = []
    swath_widths = []
    for t, geometry, width in zip(
        times, orbit_track.geometry, orbit_track["swath_width"]
    ):
        positions.extend(
            [t, round(geometry.x, 6), round(geometry.y, 6), round(geometry.z, 1)]
        )
        swath_widths.extend([t, 0.0 if np.isnan(width) else round(float(width), 1)])
    return MemberTrack(
        name=str(orbit_track["satellite"].iloc[0]) if len(orbit_track) else "",
        positions=positions,
        swath_widths=swath_widths,
    )
