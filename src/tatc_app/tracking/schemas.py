"""
Schema specifications for tracking analysis endpoints.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Union

import pandas as pd
from geojson_pydantic import FeatureCollection, Polygon
from pydantic import AwareDatetime, Field, PrivateAttr, model_validator
from shapely.geometry import box, mapping
from tatc.schemas import Satellite

from ..analysis.schemas import MAX_DISPLAY_STEPS, AnalysisRequest, AnimatedResult
from ..generation.schemas import TimeGenerator
from ..satellites import SpaceSystemInput, expand_members, validate_instrument_index
from ..utils.schemas import CamelModel


class OrbitTrackAnalysisRequest(CamelModel):
    """
    User request to perform orbit track analysis.
    """

    satellite: SpaceSystemInput = Field(
        ..., description="Satellite or constellation from which to observe."
    )
    instrument_index: Optional[int] = Field(
        0, ge=0, description="Instrument index, or `null` for all instruments."
    )
    times: Union[List[AwareDatetime], TimeGenerator] = Field(
        ...,
        description=f"Times at which to compute the track (at most {MAX_DISPLAY_STEPS}).",
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
    # the member satellites
    _members: Optional[List[Satellite]] = PrivateAttr(None)

    @model_validator(mode="after")
    def validate_members(self) -> "OrbitTrackAnalysisRequest":
        """
        Validates the members have unique names.
        """
        self._members = expand_members([self.satellite])
        return self

    @model_validator(mode="after")
    def validate_instruments(self) -> "OrbitTrackAnalysisRequest":
        """
        Validates the instrument index is in bounds.
        """
        validate_instrument_index([self.satellite], self.instrument_index)
        return self

    @model_validator(mode="after")
    def validate_times(self) -> "OrbitTrackAnalysisRequest":
        """
        Validates the number of times is within limits.
        """
        if isinstance(self.times, list) and len(self.times) > MAX_DISPLAY_STEPS:
            raise ValueError(f"Too many times: at most {MAX_DISPLAY_STEPS}.")
        self.get_times()
        return self

    def get_members(self) -> List[Satellite]:
        """
        Gets the member satellites of the satellite or constellation.

        Returns:
            List[tatc.schemas.Satellite]: The member satellites.
        """
        return self._members

    def get_times(self) -> pd.DatetimeIndex:
        """
        Gets the times at which to compute the track (in UTC).

        Returns:
            pandas.DatetimeIndex: The times.
        """
        if isinstance(self.times, TimeGenerator):
            return self.times.to_index(MAX_DISPLAY_STEPS)
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
    over time. Orbit tracks and footprints are sampled every `step` over the
    whole analysis period (so `display` does not apply).
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
    def validate_instruments(self) -> "SwathAnalysisRequest":
        """
        Validates the instrument index is in bounds.
        """
        validate_instrument_index(self.satellites, self.instrument_index)
        return self

    @model_validator(mode="after")
    def validate_no_display(self) -> "SwathAnalysisRequest":
        """
        Validates `display` is not set (swaths are sampled every `step`).
        """
        if self.display is not None:
            raise ValueError(
                "Invalid display: swath analyses sample the whole analysis "
                "period every `step`."
            )
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


class SwathAnalysisResult(AnimatedResult):
    """
    Results of a swath analysis.
    """

    swaths: FeatureCollection = Field(
        ...,
        description="Swath segments with properties `satellite`, `instrument`, "
        "`start`, and `end`.",
    )
    systems: Dict[str, int] = Field(
        {},
        description="Index of the requested satellite or constellation of "
        "each member satellite, by name.",
    )
