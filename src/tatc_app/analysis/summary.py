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

from datetime import datetime, timedelta
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
    Weighted distribution of a statistic (in its units: seconds for times)
    over the points with a value.
    """

    count: int = Field(..., description="Number of points with a value.")
    mean: float = Field(..., description="Weighted mean.")
    median: float = Field(..., description="Weighted median.")
    p90: float = Field(..., description="Weighted 90th percentile.")
    max: float = Field(..., description="Maximum.")


class Histogram(BaseModel):
    """
    Weighted histogram of a statistic (in its units: seconds for times) over
    the points with a value.
    """

    edges: List[float] = Field(..., description="Edges of equal-width bins, from zero.")
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


class SufficiencySummary(BaseModel):
    """
    Summary of the sampling sufficiency of the points of a region.
    """

    decorrelation_time: float = Field(
        ..., description="Decorrelation time of the field (seconds)."
    )
    standard_deviation: Optional[float] = Field(
        None, description="Standard deviation of the field, if given."
    )
    target_relative_error: Optional[float] = Field(
        None, description="Required relative error, if given."
    )
    sufficient: Optional[float] = Field(
        None,
        description="Weighted share of points whose relative error is at most "
        "the target (points not observed have none, and fall short).",
    )
    relative_error: Optional[Distribution] = Field(
        None,
        description="Distribution of the sampling error relative to the field's "
        "standard deviation, of observed points.",
    )
    relative_error_histogram: Optional[Histogram] = Field(
        None, description="Histogram of the relative error."
    )
    sampling_error: Optional[Distribution] = Field(
        None,
        description="Distribution of the sampling error (in the units of the "
        "field), given its standard deviation.",
    )
    effective_samples: Optional[Distribution] = Field(
        None,
        description="Distribution of the effective number of independent "
        "samples of observed points.",
    )
    revisit_p90: Optional[Distribution] = Field(
        None,
        description="Distribution of the 90th percentile time (seconds) between "
        "consecutive samples, of points observed at least twice.",
    )
    max_gap: Optional[Distribution] = Field(
        None,
        description="Distribution of the longest time (seconds) without a "
        "sample, including from the start and to the end of the period (the "
        "whole period for points not observed).",
    )
    max_gap_histogram: Optional[Histogram] = Field(
        None, description="Histogram of the longest time without a sample."
    )
    local_time_coverage: float = Field(
        ...,
        description="Weighted mean share of the intervals of the day in which "
        "points are sampled.",
    )
    local_time_shares: List[float] = Field(
        ...,
        description="Weighted share of all samples in each equal interval of "
        "the (local solar) day, from midnight.",
    )


class SampleSizeSummary(BaseModel):
    """
    Summary of the ground sample sizes of the observations of the points of a
    region (in meters).
    """

    max_sample_size: Optional[float] = Field(
        None, description="Required maximum sample size (meters), if any."
    )
    observations: int = Field(
        ..., description="Number of observations of the points (by each satellite)."
    )
    sized: int = Field(
        ...,
        description="Number of observations with a sample size (by instruments "
        "with pixels).",
    )
    meeting: Optional[int] = Field(
        None,
        description="Number of observations at most the maximum sample size "
        "(which count toward coverage), if required.",
    )
    median: Optional[Distribution] = Field(
        None,
        description="Distribution of the median sample size (meters) of points "
        "with a sized observation.",
    )
    median_histogram: Optional[Histogram] = Field(
        None, description="Histogram of the median sample size (meters)."
    )
    best: Optional[Distribution] = Field(
        None,
        description="Distribution of the smallest sample size (meters) of "
        "points with a sized observation.",
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
    sufficiency: Optional[SufficiencySummary] = Field(
        None, description="Summary of sampling sufficiency, if assessed."
    )
    sample_size: Optional[SampleSizeSummary] = Field(
        None, description="Summary of ground sample sizes, if sized."
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
    values: np.ndarray,
    weights: np.ndarray,
    min_top: float = 1.0,
    digits: int = 3,
) -> tuple[Optional[Distribution], Optional[Histogram]]:
    """
    Summarizes the (finite) values of a statistic of points as a distribution
    and a histogram.

    Args:
        values (numpy.ndarray): The values (such as seconds; NaN if none).
        weights (numpy.ndarray): The weights of points.
        min_top (float): The least top edge of the histogram (as one second
            of times), if the values are smaller.
        digits (int): The decimal digits to which to round histogram edges.

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
    # equal-width bins from zero to the maximum (or the least top edge)
    edges = np.linspace(0, max(float(values.max()), min_top), HISTOGRAM_BINS + 1)
    counts, _ = np.histogram(values, bins=edges, weights=weights)
    histogram = Histogram(
        edges=[round(float(e), digits) for e in edges],
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


def summarize_sufficiency(  # pylint: disable=too-many-arguments,too-many-locals
    points: pd.DataFrame,
    local_time_samples: np.ndarray,
    weighting: Weighting,
    decorrelation_time: timedelta,
    standard_deviation: Optional[float] = None,
    target_relative_error: Optional[float] = None,
) -> SufficiencySummary:
    """
    Summarizes the sampling sufficiency of points.

    Args:
        points (pandas.DataFrame): The points, with their sufficiency (see
            `sufficiency.compute_sufficiency`) and point `geometry`.
        local_time_samples (numpy.ndarray): The number of samples of each
            point (rows) in each local-time bin.
        weighting (Weighting): The weighting of points.
        decorrelation_time (datetime.timedelta): The decorrelation time of
            the field.
        standard_deviation (Optional[float]): The standard deviation of the
            field, if given.
        target_relative_error (Optional[float]): The required relative error,
            if given.

    Returns:
        SufficiencySummary: The summary.
    """
    weights = point_weights(points, weighting)
    relative = points["relative_error"].to_numpy(dtype=float)
    # relative errors are shares of the field's standard deviation: bins of
    # at least 1% in all, with fine edges
    relative_error, relative_error_histogram = summarize_values(
        relative, weights, min_top=0.01, digits=6
    )
    sampling_error = None
    if "sampling_error" in points.columns:
        sampling_error, _ = summarize_values(
            points["sampling_error"].to_numpy(dtype=float), weights
        )
    # of observed points (those with an error): others have none
    effective_samples, _ = summarize_values(
        np.where(
            np.isfinite(relative),
            points["effective_samples"].to_numpy(dtype=float),
            np.nan,
        ),
        weights,
    )
    revisit_p90, _ = summarize_values(seconds(points["revisit_p90"]), weights)
    max_gap, max_gap_histogram = summarize_values(seconds(points["max_gap"]), weights)
    sufficient = None
    if target_relative_error is not None:
        # points without samples have no error, and fall short
        meets = np.nan_to_num(relative, nan=np.inf) <= target_relative_error
        sufficient = weighted_share(meets, weights)
    local_coverage = points["local_time_coverage"].to_numpy(dtype=float)
    local_coverage = np.nan_to_num(local_coverage, nan=0.0)
    totals = (np.asarray(local_time_samples, dtype=float) * weights[:, None]).sum(
        axis=0
    )
    return SufficiencySummary(
        decorrelation_time=decorrelation_time.total_seconds(),
        standard_deviation=standard_deviation,
        target_relative_error=target_relative_error,
        sufficient=sufficient,
        relative_error=relative_error,
        relative_error_histogram=relative_error_histogram,
        sampling_error=sampling_error,
        effective_samples=effective_samples,
        revisit_p90=revisit_p90,
        max_gap=max_gap,
        max_gap_histogram=max_gap_histogram,
        local_time_coverage=(
            float(np.average(local_coverage, weights=weights))
            if weights.sum() > 0
            else 0.0
        ),
        local_time_shares=[
            float(s) for s in (totals / totals.sum() if totals.sum() > 0 else totals)
        ],
    )


def summarize_sample_sizes(
    points: pd.DataFrame,
    weighting: Weighting,
    max_sample_size: Optional[float] = None,
) -> SampleSizeSummary:
    """
    Summarizes the ground sample sizes of points.

    Args:
        points (pandas.DataFrame): The points, with their sample sizes (see
            `sample_sizes.add_point_sizes`) and point `geometry`.
        weighting (Weighting): The weighting of points.
        max_sample_size (Optional[float]): The required maximum sample size
            (meters), if any.

    Returns:
        SampleSizeSummary: The summary.
    """
    weights = point_weights(points, weighting)
    median, median_histogram = summarize_values(
        points["sample_size_median"].to_numpy(dtype=float), weights
    )
    best, _ = summarize_values(points["sample_size_min"].to_numpy(dtype=float), weights)
    return SampleSizeSummary(
        max_sample_size=max_sample_size,
        observations=int(points["observations"].sum()),
        sized=int(points["observations_sized"].sum()),
        meeting=(
            None
            if max_sample_size is None
            else int(points["observations_meeting"].sum())
        ),
        median=median,
        median_histogram=median_histogram,
        best=best,
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
