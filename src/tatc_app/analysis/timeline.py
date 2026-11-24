"""
Compact, columnar timelines of events (observations, contacts, data
latencies) between targets and satellites, used to animate results in a
client (see also `tracks` for the orbit tracks of satellites).

Times are seconds since a common `epoch` to keep payloads small, compared to
one GeoJSON feature per event.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

from datetime import datetime
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


def seconds_since(times: pd.Series, epoch: datetime) -> List[Optional[float]]:
    """
    Converts times to seconds since an epoch (rounded to milliseconds, with
    `None` for missing times).
    """
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
        start=seconds_since(frame.start, epoch),
        end=seconds_since(frame.end, epoch),
    )
