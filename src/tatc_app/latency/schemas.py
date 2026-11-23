"""
Schema specifications for latency analysis endpoints.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

from typing import Dict, List, Literal, Union

from geojson_pydantic import FeatureCollection
from pydantic import BaseModel, Field, field_validator
from tatc.schemas import GroundStation, Point

from ..generation.schemas import Cell, CellGenerator, PointGenerator
from ..utils.analysis import AnalysisRequest
from ..utils.timeline import OrbitTracks, Timeline


class LatencyAnalysisRequest(AnalysisRequest):
    """
    User request to perform latency analysis.
    """

    points: Union[List[Point], PointGenerator] = Field(
        ..., description="Points from which to collect observations."
    )
    cells: Union[List[Cell], CellGenerator] = Field(
        ..., description="Cells from which to aggregate observations."
    )
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
    def unique_station_names(cls, stations: List[GroundStation]) -> List[GroundStation]:
        """
        Validates ground station names are unique.
        """
        names = [station.name for station in stations]
        if len(set(names)) < len(names):
            raise ValueError("Ground station names must be unique.")
        return stations


class LatencyAnalysisResult(BaseModel):
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
    tracks: OrbitTracks = Field(..., description="Orbit tracks of satellites.")
    colors: Dict[str, str] = Field({}, description="Display color of satellites.")
