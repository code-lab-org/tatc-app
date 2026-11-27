"""
Summaries of the swath coverage of a region: the share of its area observed
over time, its observations, and the areas that pairs of platforms observe
in common (coincident swaths).

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

from datetime import datetime
from typing import Optional, Union

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from pydantic import BaseModel, Field
from pyproj import Transformer
from shapely.geometry import MultiPolygon, Polygon
from tatc.analysis import aggregate_observations

from ..analysis.summary import (
    CoverageCurve,
    Distribution,
    curve_times,
    sampled_curve,
    summarize_values,
)

# an equal-area projection (cylindrical, on the WGS 84 ellipsoid) to measure
# areas of geometries in longitude and latitude, including whole bands of
# latitude and the globe
_TO_EQUAL_AREA = Transformer.from_crs(
    "EPSG:4326",
    "+proj=cea +lon_0=0 +lat_ts=0 +datum=WGS84 +units=m",
    always_xy=True,
)


class SwathCoincidenceSummary(BaseModel):
    """
    Summary of the coincident swaths of a region: the areas that two
    platforms observe in common, within a time difference.
    """

    pairs: int = Field(..., description="Number of pairs of coincident footprints.")
    common: float = Field(
        ...,
        description="Share of the region's area observed in common by two "
        "platforms (at least once).",
    )
    coverage: CoverageCurve = Field(
        ...,
        description="Share of the region's area observed in common so far, over "
        "time (by the later footprint of each pair).",
    )
    time_difference: Optional[Distribution] = Field(
        None,
        description="Distribution of the time (seconds) between the footprints "
        "of each pair.",
    )


class RegionSummary(BaseModel):
    """
    Summary of the swath coverage of a region.
    """

    area: float = Field(..., description="Area of the region (square kilometers).")
    covered: float = Field(
        ..., description="Share of the region's area observed at least once."
    )
    coverage: CoverageCurve = Field(
        ..., description="Share of the region's area observed so far, over time."
    )
    observations: int = Field(
        ...,
        description="Number of observations of the region (periods when any "
        "part of it is observed, overlapping observations merged).",
    )
    access: Optional[Distribution] = Field(
        None, description="Distribution of the duration (seconds) of observations."
    )
    revisit: Optional[Distribution] = Field(
        None,
        description="Distribution of the time (seconds) from the end of one "
        "observation to the start of the next.",
    )
    max_gap: float = Field(
        ...,
        description="Longest time (seconds) without an observation, including "
        "from the start and to the end of the period.",
    )
    coincidence: Optional[SwathCoincidenceSummary] = Field(
        None, description="Summary of coincident swaths, if found."
    )


def area_km2(geometry) -> float:
    """
    Gets the area (square kilometers) of a geometry in longitude and
    latitude (zero if empty or `None`).
    """
    if geometry is None or geometry.is_empty:
        return 0.0
    projected = shapely.transform(
        geometry,
        lambda c: np.column_stack(_TO_EQUAL_AREA.transform(c[:, 0], c[:, 1])),
    )
    return projected.area / 1e6


def curve_seconds(start: datetime, end: datetime) -> np.ndarray:
    """
    Gets the times (seconds since the start) of a coverage curve.
    """
    return curve_times((end - start).total_seconds())


def seconds_since(times: pd.Series, start: datetime) -> np.ndarray:
    """
    Converts times to seconds since a start.
    """
    return (
        (pd.to_datetime(times, utc=True) - pd.Timestamp(start).tz_convert("UTC"))
        .dt.total_seconds()
        .to_numpy(dtype=float)
    )


def _cumulative_curve(
    pieces: gpd.GeoDataFrame,
    region: Union[Polygon, MultiPolygon],
    region_area: float,
    start: datetime,
    end: datetime,
) -> tuple:
    """
    Accumulates the pieces of area observed by each time of a coverage curve
    into the share of the region's area observed so far.

    Returns:
        tuple: the curve, and the share observed by the end
    """
    times = curve_seconds(start, end)
    shares = np.zeros(len(times))
    by_bin = {}
    for row in pieces.itertuples():
        by_bin.setdefault(int(row.bin), []).append(row.geometry)
    observed = None
    for k in range(len(times)):
        if k in by_bin:
            piece = shapely.union_all(by_bin[k])
            observed = piece if observed is None else shapely.union(observed, piece)
        if observed is not None and region_area > 0:
            shares[k] = min(
                1.0, area_km2(shapely.intersection(observed, region)) / region_area
            )
    return sampled_curve(times, shares), float(shares[-1])


def summarize_region(  # pylint: disable=too-many-arguments,too-many-locals
    region: Union[Polygon, MultiPolygon],
    area: gpd.GeoDataFrame,
    observations: gpd.GeoDataFrame,
    start: datetime,
    end: datetime,
    common: Optional[gpd.GeoDataFrame] = None,
    differences: Optional[np.ndarray] = None,
) -> tuple:
    """
    Summarizes the swath coverage of a region.

    Returns:
        tuple: the `RegionSummary`, and the aggregated observations
    """
    region_area = area_km2(region)
    curve, covered = _cumulative_curve(area, region, region_area, start, end)
    duration = (end - start).total_seconds()
    aggregated = (
        aggregate_observations(observations).sort_values("start", ignore_index=True)
        if not observations.empty
        else observations
    )
    starts = (
        seconds_since(aggregated["start"], start)
        if not aggregated.empty
        else np.array([])
    )
    ends = (
        seconds_since(aggregated["end"], start)
        if not aggregated.empty
        else np.array([])
    )
    gaps = starts[1:] - ends[:-1]
    edges = np.concatenate(
        [
            [starts[0] if len(starts) else duration],
            gaps,
            [duration - ends[-1]] if len(ends) else [],
        ]
    )
    access, _ = summarize_values(ends - starts, np.ones(len(starts)))
    revisit, _ = summarize_values(gaps, np.ones(len(gaps)))
    coincidence = None
    if common is not None:
        common_curve, common_share = _cumulative_curve(
            common, region, region_area, start, end
        )
        values = np.asarray(differences if differences is not None else [], dtype=float)
        time_difference, _ = summarize_values(values, np.ones(len(values)))
        coincidence = SwathCoincidenceSummary(
            pairs=len(values),
            common=common_share,
            coverage=common_curve,
            time_difference=time_difference,
        )
    summary = RegionSummary(
        area=region_area,
        covered=covered,
        coverage=curve,
        observations=len(aggregated),
        access=access,
        revisit=revisit,
        max_gap=float(np.max(edges)) if len(edges) else duration,
        coincidence=coincidence,
    )
    return summary, aggregated
