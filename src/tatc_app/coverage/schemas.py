"""
Schema specifications for coverage analysis endpoints.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

from typing import Dict, List, Union

from geojson_pydantic import FeatureCollection
from pydantic import BaseModel, Field
from tatc.schemas import Point

from ..generation.schemas import Cell, CellGenerator, PointGenerator
from ..utils.analysis import AnalysisRequest
from ..utils.timeline import OrbitTracks, Timeline


class CoverageAnalysisRequest(AnalysisRequest):
    """
    User request to perform coverage analysis.
    """

    points: Union[List[Point], PointGenerator] = Field(
        ..., description="Points from which to collect observations."
    )
    cells: Union[List[Cell], CellGenerator] = Field(
        ..., description="Cells from which to aggregate observations."
    )


class CoverageAnalysisResult(BaseModel):
    """
    Response to provide coverage analysis results.
    """

    points: FeatureCollection = Field(
        ...,
        description="Point-level coverage statistics (`target_hash`, `samples`, "
        "mean `access` and `revisit` in seconds), for every point.",
    )
    cells: FeatureCollection = Field(
        ...,
        description="Cell-level coverage statistics (`cell_id`, `samples`, "
        "mean `access` and `revisit` in seconds), for every cell.",
    )
    timeline: Timeline = Field(
        ..., description="Observations of points (in the order of `points`)."
    )
    cell_targets: Dict[str, List[int]] = Field(
        {}, description="Indices of the points within each cell, by `cell_id`."
    )
    tracks: OrbitTracks = Field(..., description="Orbit tracks of satellites.")
    colors: Dict[str, str] = Field({}, description="Display color of satellites.")
