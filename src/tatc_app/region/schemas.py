"""
Schema specifications for analyses of the swath coverage of a region.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

from datetime import timedelta
from enum import Enum
from typing import Dict, List, Optional, Union

import pandas as pd
from geojson_pydantic import FeatureCollection
from pydantic import BaseModel, Field, PrivateAttr, field_validator, model_validator
from shapely.geometry import MultiPolygon, Polygon, box

from ..analysis.schemas import MAX_DISPLAY_STEPS, AnalysisRequest, AnimatedResult
from ..analysis.summary import RegionSummary
from ..coincidence.schemas import CoincidencePlatforms
from ..generation.masks import resolve_mask
from ..generation.schemas import Mask, TimeGenerator
from ..satellites import validate_instrument_index
from ..utils.schemas import CamelModel

# the region of a request without one: the globe
GLOBE = box(-180, -90, 180, 90)


def mask_spec(mask: Optional[Mask]) -> Optional[Union[dict, str]]:
    """
    Gets the specification of a mask that `resolve_mask` resolves: a GeoJSON
    geometry, a known shape or country code, or `None`.
    """
    if mask is None:
        return None
    if isinstance(mask, BaseModel):
        return mask.model_dump(mode="json")
    if isinstance(mask, Enum):
        return mask.value
    return str(mask)


class SwathCoincidenceOptions(CamelModel):
    """
    Options to find the coincident swaths of a region: the areas that the
    footprints of two platforms observe in common, within a time difference.
    """

    max_time_difference: timedelta = Field(
        timedelta(0),
        description="Maximum time (seconds, or an ISO 8601 duration) between "
        "footprints that coincide.",
        examples=[600],
    )
    platforms: CoincidencePlatforms = Field(
        CoincidencePlatforms.members,
        description="Distinct platforms: each member satellite (`members`), or "
        "each satellite or constellation of the request (`systems`).",
    )

    @field_validator("max_time_difference")
    @classmethod
    def validate_max_time_difference(cls, value: timedelta) -> timedelta:
        """
        Validates the maximum time difference is not negative.
        """
        if value < timedelta(0):
            raise ValueError("The maximum time difference must not be negative.")
        return value


class RegionAnalysisRequest(AnalysisRequest):
    """
    User request to analyze the swath coverage of a region: the footprints
    of instruments sampled every `step` over the analysis period (so
    `display` does not apply), clipped to the region, with the share of its
    area observed over time, its observations (when any part of it is
    observed), and optionally the areas that platforms observe in common.
    """

    region: Optional[Mask] = Field(
        None,
        description="The region: a polygon, a known shape, or a country code "
        "(`null` for the globe).",
    )
    instrument_index: Optional[int] = Field(
        None, ge=0, description="Instrument index, or `null` for all instruments."
    )
    step: timedelta = Field(
        timedelta(seconds=60),
        gt=timedelta(0),
        description="Time step to sample orbit tracks and footprints.",
    )
    segment: timedelta = Field(
        timedelta(minutes=10),
        gt=timedelta(0),
        description="Duration of each displayed swath segment.",
    )
    coincidence: Optional[SwathCoincidenceOptions] = Field(
        None,
        description="Options to also find coincident swaths (`null` to skip " "it).",
    )
    # the region's geometry
    _region: Optional[Union[Polygon, MultiPolygon]] = PrivateAttr(None)

    @model_validator(mode="after")
    def validate_region(self) -> "RegionAnalysisRequest":
        """
        Validates the region resolves to a polygon with an area.
        """
        try:
            region = resolve_mask(mask_spec(self.region))
        except (ValueError, KeyError) as exc:
            raise ValueError(f"Invalid region: {exc}") from exc
        region = GLOBE if region is None else region
        if region.is_empty or region.area <= 0:
            raise ValueError("Invalid region: it has no area.")
        self._region = region
        return self

    @model_validator(mode="after")
    def validate_options(self) -> "RegionAnalysisRequest":
        """
        Validates the instrument index, that `display` is not set (footprints
        are sampled every `step`), and that coincident swaths have at least
        two platforms.
        """
        validate_instrument_index(self.satellites, self.instrument_index)
        if self.display is not None:
            raise ValueError(
                "Invalid display: region analyses sample the whole analysis "
                "period every `step`."
            )
        if self.coincidence is not None:
            systems = self.get_platform_systems()
            count = (
                len(self.get_members())
                if systems is None
                else len(set(systems.values()))
            )
            if count < 2:
                raise ValueError(
                    "Too few platforms: coincident swaths need at least two "
                    + (
                        "member satellites."
                        if systems is None
                        else "satellites or constellations."
                    )
                )
        return self

    def get_region(self) -> Union[Polygon, MultiPolygon]:
        """
        Gets the region's geometry (the globe, without a region).
        """
        return self._region

    def get_display_times(self) -> pd.DatetimeIndex:
        """
        Gets the times at which to sample orbit tracks and footprints.

        Returns:
            pandas.DatetimeIndex: The times.
        """
        return TimeGenerator(start=self.start, end=self.end, delta=self.step).to_index(
            MAX_DISPLAY_STEPS
        )

    def get_platform_systems(self) -> Optional[Dict[str, str]]:
        """
        Gets the platform of each member satellite, if coincident swaths are
        between systems.

        Returns:
            Optional[Dict[str, str]]: The satellite or constellation (its
                index in `satellites`, as a string) of each analyzed member,
                by name, or `None` if each member is a platform.
        """
        if (
            self.coincidence is None
            or self.coincidence.platforms != CoincidencePlatforms.systems
        ):
            return None
        systems = self.get_member_systems()
        return {member.name: str(systems[member.name]) for member in self.get_members()}


class RegionObservation(BaseModel):
    """
    An observation of a region: a period when any part of it is observed
    (overlapping observations by several satellites merged).
    """

    satellite: str = Field(..., description="Observing satellites, comma-separated.")
    instrument: str = Field(..., description="Observing instruments, comma-separated.")
    start: float = Field(..., description="Start (seconds since the analysis start).")
    end: float = Field(..., description="End (seconds since the analysis start).")


class RegionAnalysisResult(AnimatedResult):
    """
    Results of an analysis of the swath coverage of a region.
    """

    region: FeatureCollection = Field(..., description="The region.")
    swaths: FeatureCollection = Field(
        ...,
        description="Swath segments clipped to the region, with properties "
        "`satellite`, `instrument`, `start`, and `end`.",
    )
    coincident: Optional[FeatureCollection] = Field(
        None,
        description="Areas of the region observed in common by two platforms "
        "(dissolved by pair and segment), with properties `satellite_1`, "
        "`satellite_2`, `start` (the earlier time), and `end` (the later), if "
        "coincident swaths were found.",
    )
    observations: List[RegionObservation] = Field(
        [], description="Observations of the region, in order of time."
    )
    systems: Dict[str, int] = Field(
        {},
        description="Index of the requested satellite or constellation of "
        "each member satellite, by name.",
    )
    summary: RegionSummary = Field(..., description="Summary of the region's coverage.")
