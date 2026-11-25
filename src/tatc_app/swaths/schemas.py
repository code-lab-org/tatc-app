"""
Schema specifications for analyses of ground track swaths, optionally over a
region.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Union

import pandas as pd
from geojson_pydantic import FeatureCollection
from pydantic import BaseModel, Field, PrivateAttr, field_validator, model_validator
from shapely.geometry import MultiPolygon, Polygon, box

from ..analysis.schemas import MAX_DISPLAY_STEPS, AnalysisRequest, AnimatedResult
from ..analysis.summary import RegionSummary
from ..coincidence.schemas import CoincidencePlatforms
from ..generation.masks import resolve_mask
from ..generation.schemas import Mask, TimeGenerator, mask_spec
from ..satellites import validate_instrument_index
from ..utils.schemas import CamelModel

# the region of the known shape `global`
GLOBE = box(-180, -90, 180, 90)


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


class SwathAnalysisRequest(AnalysisRequest):
    """
    User request to analyze the swaths of instruments as they accumulate
    over time: footprints sampled every `step`, dissolved into segments.

    With a `region`, footprints are clipped to it and sampled over the whole
    analysis period, to give the share of its area observed over time, its
    observations (when any part of it is observed), and optionally the areas
    that platforms observe in common. Without one, footprints are sampled
    only over the animation.

    Orbit tracks animate results over the `display` times (by default,
    every `step` over the whole analysis period), and swath segments are
    given only over them, to limit the size of results.
    """

    instrument_index: Optional[int] = Field(
        0, ge=0, description="Instrument index, or `null` for all instruments."
    )
    step: timedelta = Field(
        timedelta(seconds=60),
        gt=timedelta(0),
        description="Time step to sample footprints.",
    )
    segment: Optional[timedelta] = Field(
        timedelta(minutes=10),
        gt=timedelta(0),
        description="Duration of each swath segment (displayed once it ends), "
        "or `null` to give no swath segments.",
    )
    region: Optional[Mask] = Field(
        None,
        description="The region to clip swaths to and whose coverage to "
        "summarize: a polygon, a known shape, or a country code (`null` for "
        "no region: unclipped swaths, without a summary).",
    )
    coincidence: Optional[SwathCoincidenceOptions] = Field(
        None,
        description="Options to also find coincident swaths over the region "
        "(`null` to skip it).",
    )
    # the region's geometry
    _region: Optional[Union[Polygon, MultiPolygon]] = PrivateAttr(None)

    @model_validator(mode="after")
    def validate_region(self) -> "SwathAnalysisRequest":
        """
        Validates the region (if any) resolves to a polygon with an area.
        """
        if self.region is None:
            self._region = None
            return self
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
    def validate_options(self) -> "SwathAnalysisRequest":
        """
        Validates the instrument index, the sample times, and that coincident
        swaths have a region and at least two platforms.
        """
        validate_instrument_index(self.satellites, self.instrument_index)
        self.get_sample_times()
        if self.coincidence is not None:
            if self._region is None:
                raise ValueError("Coincident swaths need a region.")
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

    def get_region(self) -> Optional[Union[Polygon, MultiPolygon]]:
        """
        Gets the region's geometry, or `None` without a region.
        """
        return self._region

    def get_display_times(self) -> pd.DatetimeIndex:
        """
        Gets the times at which to sample orbit tracks to animate results:
        the `display` times, or every `step` over the analysis period.

        Returns:
            pandas.DatetimeIndex: The times.
        """
        if self.display is not None:
            return self.display.to_index(MAX_DISPLAY_STEPS)
        return TimeGenerator(start=self.start, end=self.end, delta=self.step).to_index(
            MAX_DISPLAY_STEPS
        )

    def get_display_end(self) -> datetime:
        """
        Gets the end of the animation (at most the end of the analysis
        period), after which swath segments are not given.

        Returns:
            datetime.datetime: The end of the animation.
        """
        if self.display is None:
            return self.end
        return min(self.end, self.display.end)

    def get_sample_times(self) -> pd.DatetimeIndex:
        """
        Gets the times at which to sample footprints: every `step` over the
        analysis period with a region, or else over the animation.

        Returns:
            pandas.DatetimeIndex: The times.
        """
        end = self.end if self._region is not None else self.get_display_end()
        if end - self.start < self.step:
            return pd.DatetimeIndex([self.start, end]).tz_convert("UTC")
        return TimeGenerator(start=self.start, end=end, delta=self.step).to_index(
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


class SwathAnalysisResult(AnimatedResult):
    """
    Results of a swath analysis.
    """

    swaths: FeatureCollection = Field(
        ...,
        description="Swath segments (clipped to the region, if any) over the "
        "animation, with properties `satellite`, `instrument`, `start`, and "
        "`end`.",
    )
    region: Optional[FeatureCollection] = Field(None, description="The region, if any.")
    coincident: Optional[FeatureCollection] = Field(
        None,
        description="Areas of the region observed in common by two platforms "
        "over the animation (dissolved by pair and segment), with properties "
        "`satellite_1`, `satellite_2`, `start` (the earlier time), and `end` "
        "(the later), if coincident swaths were found.",
    )
    observations: List[RegionObservation] = Field(
        [],
        description="Observations of the region (if any), in order of time.",
    )
    systems: Dict[str, int] = Field(
        {},
        description="Index of the requested satellite or constellation of "
        "each member satellite, by name.",
    )
    summary: Optional[RegionSummary] = Field(
        None, description="Summary of the region's coverage (if any)."
    )
