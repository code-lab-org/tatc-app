"""
Shared schemas and utilities for analysis requests and results.

Analyses are enqueued as a Celery chord: a group of parallel tasks (each
returning a result tagged by `kind`, for example a chunk of observations or
the orbit track of one satellite) followed by one task that combines them.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

from datetime import timedelta
from typing import Annotated, Dict, List, Optional

import pandas as pd
from fastapi import HTTPException
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)
from pydantic.alias_generators import to_camel
from tatc.schemas import Satellite

from ..generation.schemas import TimeGenerator
from ..satellites import SpaceSystemInput, expand_members, generate_members

# default and maximum durations of the display window of animated results
DEFAULT_DISPLAY_DURATION = timedelta(days=1)
DEFAULT_DISPLAY_STEP = timedelta(seconds=60)
MAX_DISPLAY_STEPS = 20000

# a display color (`#rrggbb`)
HexColor = Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")]


class AnalysisRequest(BaseModel):
    """
    Base class for requests to analyze satellites and constellations over a
    period of time.
    """

    model_config = ConfigDict(
        from_attributes=True, populate_by_name=True, alias_generator=to_camel
    )
    satellites: List[SpaceSystemInput] = Field(
        ..., min_length=1, description="Satellites and constellations to analyze."
    )
    colors: Optional[List[Optional[str]]] = Field(
        None,
        description="Display colors (`#rrggbb`) of each satellite or "
        "constellation (applied to its members) in animated results.",
    )
    instrument_colors: Optional[List[Optional[List[Optional[HexColor]]]]] = Field(
        None,
        description="Display colors (`#rrggbb`) of the instruments (in order) "
        "of each satellite or constellation (applied to its members) in "
        "animated results; `null` derives an instrument's color from the "
        "satellite color.",
    )
    exclude_members: Optional[List[str]] = Field(
        None,
        description="Names of member satellites (of the satellites and "
        "constellations) to leave out of the analysis.",
    )
    start: AwareDatetime = Field(
        ...,
        description="Start date time of the analysis period.",
        examples=["2021-01-01T00:00:00Z"],
    )
    end: AwareDatetime = Field(
        ...,
        description="End date time of the analysis period.",
        examples=["2021-01-02T00:00:00Z"],
    )
    display: Optional[TimeGenerator] = Field(
        None,
        description="Times at which to sample orbit tracks to animate results "
        "(default: 60 second steps over the first day of the analysis period).",
    )

    @model_validator(mode="after")
    def validate_period(self) -> "AnalysisRequest":
        """
        Validates the end follows the start.
        """
        if self.end <= self.start:
            raise ValueError("Invalid end: start must precede end.")
        return self

    @model_validator(mode="after")
    def validate_display(self) -> "AnalysisRequest":
        """
        Validates the number of display times is within limits.
        """
        self.get_display_times()
        return self

    def get_display_times(self) -> pd.DatetimeIndex:
        """
        Gets the times at which to sample orbit tracks to animate results.

        Returns:
            pandas.DatetimeIndex: The times.
        """
        display = self.display or TimeGenerator(
            start=self.start,
            end=min(self.end, self.start + DEFAULT_DISPLAY_DURATION),
            delta=DEFAULT_DISPLAY_STEP,
        )
        return display.to_index(MAX_DISPLAY_STEPS)

    def get_members(self) -> List[Satellite]:
        """
        Gets the member satellites to analyze: those of the satellites and
        constellations, less any excluded members.

        Raises:
            HTTPException: (422) if two members share a name, or if all
                members are excluded.

        Returns:
            List[Satellite]: The member satellites.
        """
        members = expand_members(self.satellites)
        if self.exclude_members:
            excluded = set(self.exclude_members)
            members = [member for member in members if member.name not in excluded]
            if not members:
                raise HTTPException(
                    status_code=422,
                    detail="All satellites are excluded from the analysis.",
                )
        return members

    def get_member_colors(self) -> Dict[str, str]:
        """
        Gets the display colors of member satellites, inherited from their
        satellite or constellation.

        Returns:
            Dict[str, str]: The color of each (colored) member, by name.
        """
        colors = {}
        for i, system in enumerate(self.satellites):
            color = self.colors[i] if self.colors and i < len(self.colors) else None
            if color:
                for member in generate_members(system):
                    colors[member.name] = color
        return colors

    def get_member_instrument_colors(self) -> Dict[str, List[Optional[str]]]:
        """
        Gets the display colors of the instruments of member satellites,
        inherited from their satellite or constellation.

        Returns:
            Dict[str, List[Optional[str]]]: The color of each instrument (in
                order, `None` to derive it from the satellite color) of each
                member with instrument colors, by name.
        """
        colors = {}
        for i, system in enumerate(self.satellites):
            instrument_colors = (
                self.instrument_colors[i]
                if self.instrument_colors and i < len(self.instrument_colors)
                else None
            )
            if instrument_colors and any(instrument_colors):
                for member in generate_members(system):
                    colors[member.name] = list(instrument_colors)
        return colors

    def get_member_systems(self) -> Dict[str, int]:
        """
        Gets the satellite or constellation of each member satellite.

        Returns:
            Dict[str, int]: The index (in `satellites`) of the satellite or
                constellation of each member, by name.
        """
        return {
            member.name: i
            for i, system in enumerate(self.satellites)
            for member in generate_members(system)
        }


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


def serialize_members(members: List[Satellite]) -> List[str]:
    """
    Serializes member satellites to pass to tasks.
    """
    return [member.model_dump_json() for member in members]


def deserialize_members(members: List[str]) -> List[Satellite]:
    """
    Deserializes member satellites passed to tasks.
    """
    return [Satellite.model_validate_json(member) for member in members]
