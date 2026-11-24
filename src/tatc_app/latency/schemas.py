"""
Schema specifications for latency analysis endpoints.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

from typing import Dict, List, Literal

from geojson_pydantic import FeatureCollection
from pydantic import Field, field_validator
from tatc.schemas import GroundStation

from ..analysis.schemas import AnimatedResult, PointsCellsAnalysisRequest
from ..analysis.timeline import Timeline


class LatencyAnalysisRequest(PointsCellsAnalysisRequest):
    """
    User request to perform latency analysis.
    """

    stations: List[GroundStation] = Field(
        ...,
        min_length=1,
        description="Ground stations to which observations can be downlinked.",
    )
    during_contact: Literal["next", "end", "immediate"] = Field(
        "end",
        description="Downlink of an observation made during a contact: at the "
        "`end` of that contact, at the `next` contact, or `immediate`.",
    )

    @field_validator("stations")
    @classmethod
    def validate_station_names(
        cls, stations: List[GroundStation]
    ) -> List[GroundStation]:
        """
        Validates ground station names are unique.
        """
        names = [station.name for station in stations]
        if len(set(names)) < len(names):
            raise ValueError("Ground station names must be unique.")
        return stations


class LatencyAnalysisResult(AnimatedResult):
    """
    Response to provide latency analysis results.
    """

    points: FeatureCollection = Field(
        ...,
        description="Point-level latency statistics (`target_hash`, `samples`, "
        "mean `latency` in seconds), for every point.",
    )
    cells: FeatureCollection = Field(
        ...,
        description="Cell-level latency statistics (`cell_id`, `samples`, mean "
        "`latency` in seconds), for every cell.",
    )
    timeline: Timeline = Field(
        ...,
        description="Observations of points (in the order of `points`) from "
        "the time `observed` (start) to the time `downlinked` (end).",
    )
    contacts: Timeline = Field(
        ..., description="Contacts between satellites and ground stations."
    )
    stations: List[GroundStation] = Field(..., description="Ground stations.")
    cell_targets: Dict[str, List[int]] = Field(
        {}, description="Indices of the points within each cell, by `cell_id`."
    )
