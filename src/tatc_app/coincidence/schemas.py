"""
Schema specifications for coincident observation analysis endpoints.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

from datetime import timedelta
from enum import Enum

from pydantic import Field, field_validator, model_validator

from ..coverage.schemas import CoverageAnalysisRequest, CoverageAnalysisResult


class CoincidencePlatforms(str, Enum):
    """
    What counts as a distinct platform of coincident observations.
    """

    # each member satellite (two satellites of one constellation may coincide)
    members = "members"
    # each satellite or constellation of the request (members of one
    # constellation do not coincide with each other)
    systems = "systems"


class CoincidenceAnalysisRequest(CoverageAnalysisRequest):
    """
    User request to analyze coincident observations: the periods when at
    least `min_platforms` platforms observe a point at once (within
    `max_time_difference`), with the statistics of coverage of those
    periods (and, optionally, their sampling sufficiency).
    """

    min_platforms: int = Field(
        2,
        ge=2,
        le=20,
        description="Minimum number of distinct platforms observing a point at "
        "once.",
    )
    max_time_difference: timedelta = Field(
        timedelta(0),
        description="Maximum time (seconds, or an ISO 8601 duration) between "
        "observations that coincide: the gap between their periods, or between "
        "their epochs if `instantaneous`.",
        examples=[600],
    )
    instantaneous: bool = Field(
        False,
        description="Compare the observations' epochs (the times points are "
        "sampled) rather than their periods (the times points are in view).",
    )
    platforms: CoincidencePlatforms = Field(
        CoincidencePlatforms.members,
        description="Distinct platforms: each member satellite (`members`), or "
        "each satellite or constellation of the request (`systems`).",
    )

    @field_validator("max_time_difference")
    @classmethod
    def validate_max_time_difference(cls, value: timedelta) -> timedelta:
        """
        Validates the maximum time difference is not negative.
        """
        if value < timedelta(0):
            raise ValueError("The maximum time difference must not be negative.")
        return value

    @model_validator(mode="after")
    def validate_platforms(self) -> "CoincidenceAnalysisRequest":
        """
        Validates there are at least `min_platforms` distinct platforms.
        """
        systems = self.get_platform_systems()
        count = (
            len(self.get_members()) if systems is None else len(set(systems.values()))
        )
        if count < self.min_platforms:
            kind = (
                "member satellites"
                if self.platforms == CoincidencePlatforms.members
                else "satellites or constellations"
            )
            raise ValueError(
                f"Too few platforms: {self.min_platforms} must observe at once, "
                f"but there are {count} {kind} to analyze."
            )
        return self

    def get_platform_systems(self) -> dict | None:
        """
        Gets the platform of each member satellite, if platforms are systems.

        Returns:
            dict | None: The satellite or constellation (its index in
                `satellites`, as a string) of each analyzed member, by name,
                or `None` if each member is a platform.
        """
        if self.platforms != CoincidencePlatforms.systems:
            return None
        systems = self.get_member_systems()
        return {member.name: str(systems[member.name]) for member in self.get_members()}


class CoincidenceAnalysisResult(CoverageAnalysisResult):
    """
    Response to provide coincident observation analysis results: the
    statistics of coverage of the coincident periods (each an
    "observation", whose `samples`, `access`, and `revisit` are those of
    coincidences).
    """
