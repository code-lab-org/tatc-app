"""
Schema specifications for coverage analysis endpoints.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

from datetime import timedelta
from typing import Dict, List, Optional

from geojson_pydantic import FeatureCollection
from pydantic import Field, field_validator

from ..analysis.schemas import AnimatedResult, PointsCellsAnalysisRequest
from ..analysis.summary import CoverageSummary
from ..analysis.timeline import Timeline
from ..utils.schemas import CamelModel


class SufficiencyOptions(CamelModel):
    """
    Options to assess the sampling sufficiency of the observations of each
    point: how well they estimate the mean of a field over the analysis
    period, and how they are spread in time and in local time of day.
    """

    decorrelation_time: timedelta = Field(
        ...,
        description="Decorrelation time of the field (seconds, or an ISO 8601 "
        "duration): the time over which its values become nearly independent, "
        "such as hours for convective precipitation or days for synoptic "
        "temperature.",
        examples=[10800],
    )
    standard_deviation: Optional[float] = Field(
        None,
        gt=0,
        description="Standard deviation of the field, to give the sampling "
        "error in its units (otherwise only the error relative to it).",
    )
    target_relative_error: Optional[float] = Field(
        None,
        gt=0,
        description="Required sampling error relative to the field's standard "
        "deviation (such as 0.2), to report the share of the region that meets "
        "it.",
    )
    local_time_bins: int = Field(
        8,
        ge=1,
        le=24,
        description="Number of equal intervals of the (local solar) day in which "
        "to count samples.",
    )

    @field_validator("decorrelation_time")
    @classmethod
    def validate_decorrelation_time(cls, value: timedelta) -> timedelta:
        """
        Validates the decorrelation time is positive.
        """
        if value <= timedelta(0):
            raise ValueError("The decorrelation time must be positive.")
        return value


class CoverageAnalysisRequest(PointsCellsAnalysisRequest):
    """
    User request to perform coverage analysis.
    """

    sufficiency: Optional[SufficiencyOptions] = Field(
        None,
        description="Options to also assess sampling sufficiency (`null` to "
        "skip it).",
    )


class CoverageAnalysisResult(AnimatedResult):
    """
    Response to provide coverage analysis results.
    """

    points: FeatureCollection = Field(
        ...,
        description="Point-level coverage statistics (`target_hash`, `samples`, "
        "mean `access` and `revisit` in seconds), for every point. With "
        "sufficiency, also the `relative_error` (and `sampling_error`, given "
        "the field's standard deviation), `effective_samples`, `revisit_p50` "
        "and `revisit_p90` (seconds between consecutive samples), `max_gap` "
        "(seconds), and `local_time_coverage`.",
    )
    cells: FeatureCollection = Field(
        ...,
        description="Cell-level coverage statistics (`cell_id`, `samples`, "
        "mean `access` and `revisit` in seconds), for every cell. With "
        "sufficiency, also the root-mean-square `relative_error` (and "
        "`sampling_error`) and mean `effective_samples` of its observed "
        "points, and the mean `local_time_coverage` and longest `max_gap` of "
        "all its points.",
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
