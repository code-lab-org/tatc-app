"""
Schema specifications for coverage analysis endpoints.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

from typing import Dict, List, Optional

from geojson_pydantic import FeatureCollection
from pydantic import Field

from ..analysis.schemas import AnimatedResult, PointsCellsAnalysisRequest
from ..analysis.summary import CoverageSummary
from ..analysis.timeline import Timeline


class CoverageAnalysisRequest(PointsCellsAnalysisRequest):
    """
    User request to perform coverage analysis.
    """


class CoverageAnalysisResult(AnimatedResult):
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
    summary: Optional[CoverageSummary] = Field(
        None, description="Summary of coverage over the points."
    )
