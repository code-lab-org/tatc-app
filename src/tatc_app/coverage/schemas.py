"""
Schema specifications for coverage analysis endpoints.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

from datetime import timedelta
from typing import Dict, List, Optional

from geojson_pydantic import FeatureCollection
from pydantic import Field, field_validator, model_validator

from ..analysis.sample_sizes import is_sized
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


class SampleSizeOptions(CamelModel):
    """
    Options to size the ground samples of observations (see
    `analysis.sample_sizes`): their statistics for each point (in coverage
    results), and an optional requirement that drops coarser observations
    before coverage (or coincidence) is computed.
    """

    max_sample_size: Optional[float] = Field(
        None,
        gt=0,
        description="Largest sample size (meters) of an observation that counts "
        "(`null` to count every observation): observations with a larger "
        "pixel or pixel spacing, along or across track, are dropped. Requires "
        "every analyzed instrument to be pointed, or conical with a beam width "
        "and a scan sample spacing.",
        examples=[1000],
    )


class CoverageAnalysisRequest(PointsCellsAnalysisRequest):
    """
    User request to perform coverage analysis.
    """

    sufficiency: Optional[SufficiencyOptions] = Field(
        None,
        description="Options to also assess sampling sufficiency (`null` to "
        "skip it).",
    )
    sample_size: Optional[SampleSizeOptions] = Field(
        None,
        description="Options to size the ground samples of observations (`null` "
        "to skip it).",
    )

    @model_validator(mode="after")
    def validate_sample_size(self) -> "CoverageAnalysisRequest":
        """
        Validates every analyzed instrument has sized samples if a maximum
        sample size is required (otherwise none of its observations would
        count).
        """
        if self.sample_size is None or self.sample_size.max_sample_size is None:
            return self
        unsized = sorted(
            {
                f"{member.name} ({instrument.name})"
                for member in self.get_members()
                for instrument in member.instruments
                if not is_sized(instrument)
            }
        )
        if unsized:
            listed = ", ".join(unsized[:5]) + (", ..." if len(unsized) > 5 else "")
            raise ValueError(
                "A maximum sample size requires instruments with pixels: pointed, "
                "or conical with a beam width and a scan sample spacing. Without "
                f"them: {listed}."
            )
        return self


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
        "(seconds), and `local_time_coverage`. With sample sizes, also the "
        "`sample_size_median` and `sample_size_min` (meters) of its "
        "observations, and the numbers of its `observations`, "
        "`observations_sized`, and `observations_meeting` the maximum sample "
        "size (before coarser observations are dropped).",
    )
    cells: FeatureCollection = Field(
        ...,
        description="Cell-level coverage statistics (`cell_id`, `samples`, "
        "mean `access` and `revisit` in seconds), for every cell. With "
        "sufficiency, also the root-mean-square `relative_error` (and "
        "`sampling_error`) and mean `effective_samples` of its observed "
        "points, and the mean `local_time_coverage` and longest `max_gap` of "
        "all its points. With sample sizes, also the mean `sample_size_median` "
        "and smallest `sample_size_min` of its points.",
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
