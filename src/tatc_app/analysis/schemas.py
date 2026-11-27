"""
Shared schemas of analysis requests and results.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

from datetime import timedelta
from typing import Annotated, Dict, List, Optional, Sequence, Tuple, TypeVar, Union

import pandas as pd
from pydantic import (
    AwareDatetime,
    BaseModel,
    Field,
    PrivateAttr,
    StringConstraints,
    model_validator,
)
from tatc.schemas import Point, Satellite

from .. import limits
from ..generation.schemas import Cell, CellGenerator, PointGenerator, TimeGenerator
from ..satellites import SpaceSystemInput, check_unique_names, generate_members
from ..utils.schemas import CamelModel
from .tracks import OrbitTracks

# default and maximum durations of the display window of animated results
DEFAULT_DISPLAY_DURATION = timedelta(days=1)
DEFAULT_DISPLAY_STEP = timedelta(seconds=60)
MAX_DISPLAY_STEPS = 20000

# a display color (`#rrggbb`)
HexColor = Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")]

T = TypeVar("T")


def _item(values: Optional[Sequence[T]], index: int) -> Optional[T]:
    """
    Gets an item of an optional, possibly short, list (`None` if missing).
    """
    return values[index] if values and index < len(values) else None


def get_display_times(display: TimeGenerator) -> pd.DatetimeIndex:
    """
    Gets the times of a display (up to `MAX_DISPLAY_STEPS`).

    Args:
        display (TimeGenerator): The display.

    Raises:
        ValueError: if the display has more than `MAX_DISPLAY_STEPS` times.

    Returns:
        pandas.DatetimeIndex: The times.
    """
    return display.to_index(MAX_DISPLAY_STEPS)


class AnalysisRequest(CamelModel):
    """
    Base class for requests to analyze satellites and constellations over a
    period of time.
    """

    satellites: List[SpaceSystemInput] = Field(
        ..., min_length=1, description="Satellites and constellations to analyze."
    )
    colors: Optional[List[Optional[HexColor]]] = Field(
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
    # (index of the satellite or constellation, member) of each member
    _system_members: Optional[List[Tuple[int, Satellite]]] = PrivateAttr(None)
    # the member satellites to analyze
    _members: Optional[List[Satellite]] = PrivateAttr(None)

    @model_validator(mode="after")
    def validate_period(self) -> "AnalysisRequest":
        """
        Validates the end follows the start, within the maximum duration.
        """
        if self.end <= self.start:
            raise ValueError("Invalid end: start must precede end.")
        if self.end - self.start > limits.MAX_ANALYSIS_DURATION:
            days = limits.MAX_ANALYSIS_DURATION / timedelta(days=1)
            raise ValueError(
                f"Invalid end: the analysis period must not exceed {days:g} days."
            )
        return self

    @model_validator(mode="after")
    def validate_display(self) -> "AnalysisRequest":
        """
        Validates the number of display times is within limits.
        """
        self.get_display_times()
        return self

    @model_validator(mode="after")
    def validate_members(self) -> "AnalysisRequest":
        """
        Validates the members have unique names and are not all excluded.
        """
        members = check_unique_names(
            [member for _, member in self._get_system_members()]
        )
        if self.exclude_members:
            excluded = set(self.exclude_members)
            members = [member for member in members if member.name not in excluded]
            if not members:
                raise ValueError("All satellites are excluded from the analysis.")
        self._members = members
        return self

    def get_display(self) -> TimeGenerator:
        """
        Gets the times at which to sample orbit tracks to animate results:
        those requested, or the default display.

        Returns:
            TimeGenerator: The display times.
        """
        return self.display or TimeGenerator(
            start=self.start,
            end=min(self.end, self.start + DEFAULT_DISPLAY_DURATION),
            delta=DEFAULT_DISPLAY_STEP,
        )

    def get_display_times(self) -> pd.DatetimeIndex:
        """
        Gets the times at which to sample orbit tracks to animate results.

        Returns:
            pandas.DatetimeIndex: The times.
        """
        return get_display_times(self.get_display())

    def _get_system_members(self) -> List[Tuple[int, Satellite]]:
        """
        Expands the satellites and constellations (once) into their members.
        """
        if self._system_members is None:
            self._system_members = [
                (i, member)
                for i, system in enumerate(self.satellites)
                for member in generate_members(system)
            ]
        return self._system_members

    def get_members(self) -> List[Satellite]:
        """
        Gets the member satellites to analyze: those of the satellites and
        constellations, less any excluded members (see `validate_members`).

        Returns:
            List[Satellite]: The member satellites.
        """
        return self._members

    def get_member_colors(self) -> Dict[str, str]:
        """
        Gets the display colors of member satellites, inherited from their
        satellite or constellation.

        Returns:
            Dict[str, str]: The color of each (colored) member, by name.
        """
        return {
            member.name: _item(self.colors, i)
            for i, member in self._get_system_members()
            if _item(self.colors, i)
        }

    def get_member_instrument_colors(self) -> Dict[str, List[Optional[str]]]:
        """
        Gets the display colors of the instruments of member satellites,
        inherited from their satellite or constellation.

        Returns:
            Dict[str, List[Optional[str]]]: The color of each instrument (in
                order, `None` to derive it from the satellite color) of each
                member with instrument colors, by name.
        """
        return {
            member.name: list(_item(self.instrument_colors, i))
            for i, member in self._get_system_members()
            if any(_item(self.instrument_colors, i) or [])
        }

    def get_member_systems(self) -> Dict[str, int]:
        """
        Gets the satellite or constellation of each member satellite.

        Returns:
            Dict[str, int]: The index (in `satellites`) of the satellite or
                constellation of each member, by name.
        """
        return {member.name: i for i, member in self._get_system_members()}


class PointsCellsAnalysisRequest(AnalysisRequest):
    """
    Base class for requests to analyze observations of points, aggregated
    into cells (coverage and latency analyses).
    """

    points: Union[List[Point], PointGenerator] = Field(
        ..., description="Points from which to collect observations."
    )
    cells: Union[List[Cell], CellGenerator] = Field(
        ..., description="Cells from which to aggregate observations."
    )

    @model_validator(mode="after")
    def validate_counts(self) -> "PointsCellsAnalysisRequest":
        """
        Validates the numbers of listed points and cells are within limits
        (generated points and cells are checked as they are generated).
        """
        for kind, items, limit in (
            ("points", self.points, limits.MAX_POINTS),
            ("cells", self.cells, limits.MAX_CELLS),
        ):
            if isinstance(items, list) and len(items) > limit:
                raise ValueError(
                    f"Too many {kind}: {len(items):,} listed (at most {limit:,})."
                )
        return self


class AnimatedResult(BaseModel):
    """
    Base class for analysis results animated with the orbit tracks of
    satellites.
    """

    tracks: OrbitTracks = Field(..., description="Orbit tracks of satellites.")
    colors: Dict[str, str] = Field({}, description="Display color of satellites.")
