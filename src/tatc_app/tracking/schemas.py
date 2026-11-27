"""
Schema specifications for tracking analysis endpoints.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

from datetime import datetime, timedelta
from typing import List, Optional, Union

import pandas as pd
from geojson_pydantic import Polygon
from pydantic import AwareDatetime, Field, PrivateAttr, model_validator
from shapely.geometry import box, mapping
from tatc.schemas import Satellite

from .. import limits
from ..analysis.schemas import MAX_DISPLAY_STEPS
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
        description=f"Times at which to compute the track (at most "
        f"{MAX_DISPLAY_STEPS}, and at most `TATC_MAX_TRACK_POSITIONS` positions "
        "of all member satellites).",
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
        Validates the number of times, and of positions (of all member
        satellites at all times), are within limits.
        """
        if isinstance(self.times, list) and len(self.times) > MAX_DISPLAY_STEPS:
            raise ValueError(f"Too many times: at most {MAX_DISPLAY_STEPS}.")
        positions = len(self._members) * len(self.get_times())
        if positions > limits.MAX_TRACK_POSITIONS:
            raise ValueError(
                f"Too many positions: {len(self._members)} member satellites at "
                f"{positions // len(self._members)} times is {positions}, at most "
                f"{limits.MAX_TRACK_POSITIONS}. Request fewer satellites or times."
            )
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
