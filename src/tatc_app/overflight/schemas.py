"""
Schema specifications for overflight (point access) analysis endpoints.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

from typing import List, Optional

from geojson_pydantic import FeatureCollection
from pydantic import Field, model_validator
from tatc.schemas import Point

from ..analysis.schemas import AnalysisRequest, AnimatedResult
from ..analysis.timeline import Timeline
from ..satellites import validate_instrument_index

# maximum number of points in an overflight analysis (to analyze more, use a
# coverage analysis)
MAX_POINTS = 1000


class OverflightAnalysisRequest(AnalysisRequest):
    """
    User request to collect overflights (accesses) of points.
    """

    points: List[Point] = Field(
        ...,
        min_length=1,
        max_length=MAX_POINTS,
        description="Points from which to collect observations.",
    )
    instrument_index: Optional[int] = Field(
        None, ge=0, description="Instrument index, or `null` for all instruments."
    )
    omit_solar: bool = Field(
        True,
        description="`True`, if solar angles can be omitted to improve computation speed.",
    )

    @model_validator(mode="after")
    def valid_instrument_index(self) -> "OverflightAnalysisRequest":
        """
        Validates the instrument index is in bounds.
        """
        validate_instrument_index(self.satellites, self.instrument_index)
        return self


class OverflightAnalysisResult(AnimatedResult):
    """
    Response to provide overflight analysis results.
    """

    points: FeatureCollection = Field(
        ...,
        description="Points (`point_id`, the hash of the geometry, and `id`) "
        "with statistics of observations by all satellites (`samples`, and mean "
        "`access` and `revisit` in seconds; overlapping observations by "
        "several satellites count once).",
    )
    observations: FeatureCollection = Field(
        ...,
        description="Observations by each satellite and instrument "
        "(`target_hash`, `satellite`, `instrument`, `start`, `epoch`, `end`, "
        "`platform_alt`, `platform_az`, and solar angles unless omitted), "
        "sorted by start time.",
    )
    timeline: Timeline = Field(
        ..., description="Observations of points (in the order of `points`)."
    )
