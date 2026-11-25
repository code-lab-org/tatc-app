"""
Summaries of analysis results over a region: the shares of the region's
points with a property (such as observed at least once), distributions of
the points' statistics (such as mean revisit time), and the share of points
observed over time.

Points of a grid sample the region evenly by area, except points equally
spaced in latitude and longitude, which crowd toward the poles: each stands
for an area proportional to the cosine of its latitude, so summaries weight
them by it (`Weighting.area`).

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional, Union

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from ..generation.schemas import PointGenerator, PointGeneratorMethod

# number of bins of histograms
HISTOGRAM_BINS = 20

# number of times at which the share of points observed so far is sampled
COVERAGE_SAMPLES = 200


class Weighting(str, Enum):
    """
    Weighting of points in summaries.
    """

    # each point stands for an area proportional to the cosine of its latitude
    area = "area"
    # each point counts the same
    uniform = "uniform"


def get_weighting(points: Union[list, PointGenerator]) -> Weighting:
    """
    Gets the weighting of the points of a request: by area for points equally
    spaced in latitude and longitude, and uniform otherwise (a Fibonacci
    lattice samples evenly by area, and listed points count the same).

    Args:
        points (Union[list, PointGenerator]): The points of a request.

    Returns:
        Weighting: The weighting.
    """
    if (
        isinstance(points, PointGenerator)
        and points.method == PointGeneratorMethod.equally_spaced
    ):
        return Weighting.area
    return Weighting.uniform


class Distribution(BaseModel):
    """
    Weighted distribution of a statistic (in seconds) over the points with a
    value.
    """

    count: int = Field(..., description="Number of points with a value.")
    mean: float = Field(..., description="Weighted mean (seconds).")
    median: float = Field(..., description="Weighted median (seconds).")
    p90: float = Field(..., description="Weighted 90th percentile (seconds).")
    max: float = Field(..., description="Maximum (seconds).")


class Histogram(BaseModel):
    """
    Weighted histogram of a statistic (in seconds) over the points with a
    value.
    """

    edges: List[float] = Field(
        ..., description="Edges of equal-width bins (seconds), from zero."
    )
    shares: List[float] = Field(
        ..., description="Weighted share of the points with a value in each bin."
    )


class CoverageCurve(BaseModel):
    """
    Weighted share of points observed at least once, over time.
    """

    times: List[float] = Field(
        ..., description="Times (seconds since the start of the analysis)."
    )
    shares: List[float] = Field(
        ..., description="Weighted share of points observed by each time."
    )


class CoverageSummary(BaseModel):
    """
    Summary of coverage over the points of a region.
    """

    points: int = Field(..., description="Number of points.")
    weighting: Weighting = Field(..., description="Weighting of points.")
    observed: float = Field(
        ..., description="Weighted share of points observed at least once."
    )
    revisited: float = Field(
        ...,
        description="Weighted share of points observed at least twice (which "
        "have a revisit time).",
    )
    access: Optional[Distribution] = Field(
        None, description="Distribution of the mean access time of observed points."
    )
    revisit: Optional[Distribution] = Field(
        None,
        description="Distribution of the mean revisit time of points observed "
        "at least twice.",
    )
    revisit_histogram: Optional[Histogram] = Field(
        None, description="Histogram of the mean revisit time."
    )
    coverage: CoverageCurve = Field(
        ..., description="Share of points observed at least once, over time."
    )


class LatencySummary(BaseModel):
    """
    Summary of data latency over the points of a region.
    """

    points: int = Field(..., description="Number of points.")
    weighting: Weighting = Field(..., description="Weighting of points.")
    downlinked: float = Field(
        ...,
        description="Weighted share of points with an observation downlinked "
        "within the analysis period.",
    )
    latency: Optional[Distribution] = Field(
        None,
        description="Distribution of the mean latency of points with a "
        "downlinked observation.",
    )
    latency_histogram: Optional[Histogram] = Field(
        None, description="Histogram of the mean latency."
    )
    contacts: int = Field(..., description="Number of contacts with ground stations.")
    contact_duration: Optional[float] = Field(
        None,
        description="Mean duration (seconds) of contacts that end within the "
        "analysis period.",
    )


def point_weights(points: pd.DataFrame, weighting: Weighting) -> np.ndarray:
    """
    Gets the weights of points (with a point `geometry`).

    Args:
        points (pandas.DataFrame): The points.
        weighting (Weighting): The weighting.

    Returns:
        numpy.ndarray: The weights.
    """
    if weighting == Weighting.area and len(points) > 0:
        latitudes = np.array([geometry.y for geometry in points.geometry])
        # clip so a point at a pole still counts a little
        return np.clip(np.cos(np.radians(latitudes)), 1e-6, None)
    return np.ones(len(points))


def weighted_share(mask: np.ndarray, weights: np.ndarray) -> float:
    """
    Gets the weighted share of points in a mask (zero without points).
    """
    total = weights.sum()
    return float(weights[mask].sum() / total) if total > 0 else 0.0


def weighted_quantile(values: np.ndarray, weights: np.ndarray, q: float) -> float:
    """
    Gets a weighted quantile, interpolating between the midpoints of the
    cumulative weights of sorted values (the ordinary quantile for equal
    weights).

    Args:
        values (numpy.ndarray): The values.
        weights (numpy.ndarray): The weights of values.
        q (float): The quantile, between 0 and 1.

    Returns:
        float: The quantile.
    """
    order = np.argsort(values)
    values = values[order]
    weights = weights[order]
    if len(values) == 1:
        return float(values[0])
    cumulative = np.cumsum(weights) - weights / 2
    positions = (cumulative - cumulative[0]) / (cumulative[-1] - cumulative[0])
    return float(np.interp(q, positions, values))


def seconds(values: pd.Series) -> np.ndarray:
    """
    Converts durations (timedeltas, or seconds) to seconds, with NaN for
    missing values.
    """
    if pd.api.types.is_numeric_dtype(values) and not pd.api.types.is_bool_dtype(values):
        return values.to_numpy(dtype=float)
    # timedeltas (or missing values of any type, such as a column of only NaT)
    return (
        pd.to_timedelta(values.astype(object), errors="coerce")
        .dt.total_seconds()
        .to_numpy(dtype=float)
    )


def summarize_values(
    values: np.ndarray, weights: np.ndarray
) -> tuple[Optional[Distribution], Optional[Histogram]]:
    """
    Summarizes the (finite) values of a statistic of points as a distribution
    and a histogram.

    Args:
        values (numpy.ndarray): The values (seconds; NaN if none).
        weights (numpy.ndarray): The weights of points.

    Returns:
        tuple: The distribution and histogram, or `None` without values.
    """
    valid = np.isfinite(values)
    values = values[valid]
    weights = weights[valid]
    if len(values) == 0 or weights.sum() <= 0:
        return None, None
    distribution = Distribution(
        count=len(values),
        mean=float(np.average(values, weights=weights)),
        median=weighted_quantile(values, weights, 0.5),
        p90=weighted_quantile(values, weights, 0.9),
        max=float(values.max()),
    )
    # equal-width bins from zero to the maximum (or one second, if zero)
    edges = np.linspace(0, max(float(values.max()), 1.0), HISTOGRAM_BINS + 1)
    counts, _ = np.histogram(values, bins=edges, weights=weights)
    histogram = Histogram(
        edges=[round(float(e), 3) for e in edges],
        shares=[float(c) for c in counts / weights.sum()],
    )
    return distribution, histogram


def coverage_curve(
    first_observed: np.ndarray, weights: np.ndarray, duration: float
) -> CoverageCurve:
    """
    Gets the weighted share of points observed at least once over time.

    Args:
        first_observed (numpy.ndarray): The time (seconds since the start)
            each point is first observed (NaN if never).
        weights (numpy.ndarray): The weights of points.
        duration (float): The duration (seconds) of the analysis period.

    Returns:
        CoverageCurve: The curve, sampled at `COVERAGE_SAMPLES` times.
    """
    times = np.linspace(0, duration, COVERAGE_SAMPLES + 1)
    total = weights.sum()
    if total <= 0:
        return CoverageCurve(times=times.tolist(), shares=[0.0] * len(times))
    observed = np.isfinite(first_observed)
    order = np.argsort(first_observed[observed])
    sorted_times = first_observed[observed][order]
    cumulative = np.concatenate([[0], np.cumsum(weights[observed][order])])
    counts = np.searchsorted(sorted_times, times, side="right")
    return CoverageCurve(
        times=[round(float(t), 3) for t in times],
        shares=[float(s) for s in cumulative[counts] / total],
    )


def summarize_coverage(
    points: pd.DataFrame,
    observations: pd.DataFrame,
    weighting: Weighting,
    start: datetime,
    end: datetime,
) -> CoverageSummary:
    """
    Summarizes coverage statistics of points.

    Args:
        points (pandas.DataFrame): The reduced statistics of points
            (`target_hash`, `samples`, mean `access` and `revisit`, and
            point `geometry`).
        observations (pandas.DataFrame): The observations (`target_hash` and
            `start`).
        weighting (Weighting): The weighting of points.
        start (datetime.datetime): The start of the analysis period.
        end (datetime.datetime): The end of the analysis period.

    Returns:
        CoverageSummary: The summary.
    """
    weights = point_weights(points, weighting)
    samples = points["samples"].to_numpy()
    access, _ = summarize_values(seconds(points["access"]), weights)
    revisit, revisit_histogram = summarize_values(seconds(points["revisit"]), weights)
    first_observed = np.full(len(points), np.nan)
    if observations is not None and not observations.empty:
        first = (
            pd.to_datetime(observations["start"], utc=True)
            .groupby(observations["target_hash"])
            .min()
        )
        first_observed = (
            (
                pd.to_datetime(points["target_hash"].map(first), utc=True)
                - pd.Timestamp(start).tz_convert("UTC")
            )
            .dt.total_seconds()
            .to_numpy(dtype=float)
        )
    return CoverageSummary(
        points=len(points),
        weighting=weighting,
        observed=weighted_share(samples >= 1, weights),
        revisited=weighted_share(samples >= 2, weights),
        access=access,
        revisit=revisit,
        revisit_histogram=revisit_histogram,
        coverage=coverage_curve(first_observed, weights, (end - start).total_seconds()),
    )


def summarize_latency(
    points: pd.DataFrame,
    contacts: pd.DataFrame,
    weighting: Weighting,
) -> LatencySummary:
    """
    Summarizes latency statistics of points.

    Args:
        points (pandas.DataFrame): The reduced statistics of points (mean
            `latency`, and point `geometry`).
        contacts (pandas.DataFrame): The contacts (`start` and `end`).
        weighting (Weighting): The weighting of points.

    Returns:
        LatencySummary: The summary.
    """
    weights = point_weights(points, weighting)
    values = seconds(points["latency"])
    latency, latency_histogram = summarize_values(values, weights)
    contact_duration = None
    count = 0
    if contacts is not None and not contacts.empty:
        count = len(contacts)
        durations = (
            pd.to_datetime(contacts["end"], utc=True)
            - pd.to_datetime(contacts["start"], utc=True)
        ).dt.total_seconds()
        if durations.notna().any():
            contact_duration = float(durations.mean())
    return LatencySummary(
        points=len(points),
        weighting=weighting,
        downlinked=weighted_share(np.isfinite(values), weights),
        latency=latency,
        latency_histogram=latency_histogram,
        contacts=count,
        contact_duration=contact_duration,
    )
