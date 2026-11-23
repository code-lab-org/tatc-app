"""
Schema specifications for tracking analysis endpoints.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Union

import pandas as pd
from geojson_pydantic import FeatureCollection, Polygon
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel
from shapely.geometry import box, mapping

from ..generation.schemas import TimeGenerator
from ..satellites import SpaceSystemInput, validate_instrument_index
from ..utils.analysis import MAX_DISPLAY_STEPS, AnalysisRequest
from ..utils.timeline import OrbitTracks


class OrbitTrackAnalysisRequest(BaseModel):
    """
    User request to perform orbit track analysis.
    """

    model_config = ConfigDict(
        from_attributes=True, populate_by_name=True, alias_generator=to_camel
    )
    satellite: SpaceSystemInput = Field(
        ..., description="Satellite or constellation from which to observe."
    )
    instrument_index: Optional[int] = Field(
        0, ge=0, description="Instrument index, or `null` for all instruments."
    )
    times: Union[List[datetime], TimeGenerator] = Field(
        ...,
        description="Times at which to compute the track.",
        examples=[
            TimeGenerator(
                start=datetime.fromisoformat("2021-01-01T00:00:00+00:00"),
                end=datetime.fromisoformat("2021-01-01T01:00:00+00:00"),
                delta=timedelta(seconds=30),
            )
        ],
    )
    elevation: float = Field(
        0,
        description="Elevation (meters) above datum in the WGS 84 coordinate system.",
    )
    mask: Optional[Polygon] = Field(
        None,
        description="Mask to limit the extent of results.",
        examples=[Polygon(**mapping(box(-180, -90, 180, 90)))],
    )

    @model_validator(mode="after")
    def valid_instrument_index(self) -> "OrbitTrackAnalysisRequest":
        """
        Validates the instrument index is in bounds.
        """
        validate_instrument_index([self.satellite], self.instrument_index)
        return self

    @model_validator(mode="after")
    def valid_times(self) -> "OrbitTrackAnalysisRequest":
        """
        Validates the times are timezone-aware and within limits.
        """
        self.get_times()
        return self

    def get_times(self) -> pd.DatetimeIndex:
        """
        Gets the times at which to compute the track (in UTC).

        Returns:
            pandas.DatetimeIndex: The times.
        """
        if isinstance(self.times, TimeGenerator):
            return self.times.to_index(MAX_DISPLAY_STEPS)
        if any(time.tzinfo is None for time in self.times):
            raise ValueError("Times must be timezone-aware.")
        return pd.DatetimeIndex(self.times).tz_convert("UTC")


class GroundTrackAnalysisRequest(OrbitTrackAnalysisRequest):
    """
    User request to perform ground track analysis.
    """

    elevation: Optional[float] = Field(
        None,
        description="Elevation (meters) above datum in the WGS 84 coordinate "
        "system, or `null` for the mean elevation of the footprint.",
    )


class SwathAnalysisRequest(AnalysisRequest):
    """
    User request to analyze the swaths of instruments as they accumulate
    over time.
    """

    instrument_index: Optional[int] = Field(
        0, ge=0, description="Instrument index, or `null` for all instruments."
    )
    step: timedelta = Field(
        timedelta(seconds=60),
        gt=timedelta(0),
        description="Time step to sample orbit tracks and footprints.",
    )
    segment: Optional[timedelta] = Field(
        timedelta(minutes=10),
        gt=timedelta(0),
        description="Duration of each swath segment (displayed once it ends), "
        "or `null` to only compute orbit tracks.",
    )

    @model_validator(mode="after")
    def valid_instrument_index(self) -> "SwathAnalysisRequest":
        """
        Validates the instrument index is in bounds.
        """
        validate_instrument_index(self.satellites, self.instrument_index)
        return self

    def get_display_times(self) -> pd.DatetimeIndex:
        """
        Gets the times at which to sample orbit tracks and footprints.

        Returns:
            pandas.DatetimeIndex: The times.
        """
        return TimeGenerator(start=self.start, end=self.end, delta=self.step).to_index(
            MAX_DISPLAY_STEPS
        )


class SwathAnalysisResult(BaseModel):
    """
    Results of a swath analysis.
    """

    swaths: FeatureCollection = Field(
        ...,
        description="Swath segments with properties `satellite`, `instrument`, "
        "`start`, and `end`.",
    )
    tracks: OrbitTracks = Field(..., description="Orbit tracks of satellites.")
    colors: Dict[str, str] = Field({}, description="Display color of satellites.")
