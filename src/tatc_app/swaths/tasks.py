"""
Task specifications for analyses of ground track swaths, optionally over a
region.

The sample times are split into windows, analyzed in parallel: each
collects the footprints of member satellites at its times, clipped to the
region if any (and those of the following `max_time_difference`, to pair
them with coincident footprints), and the observations of the region. The
combining task merges the swath segments of the windows (over the
animation), the areas observed by the times of a coverage curve, and the
observations.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Union

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from pyproj import Transformer
from shapely.geometry import MultiPolygon, Polygon, mapping, shape
from tatc.analysis import (
    aggregate_observations,
    collect_footprints,
    collect_region_observations,
    find_coincident_ground_track,
)

from ..analysis.summary import (
    COVERAGE_SAMPLES,
    CoverageCurve,
    RegionSummary,
    SwathCoincidenceSummary,
    summarize_values,
)
from ..analysis.tasks import (
    combine_animation,
    deserialize_members,
    parse_times,
    tag,
    untag,
)
from ..utils.serialization import concat, empty_frame, from_geojson, to_geojson
from ..worker import app
from .schemas import RegionObservation, SwathAnalysisResult

# number of time steps of each window analyzed in parallel
WINDOW_STEPS = int(os.getenv("TATC_SWATH_WINDOW_STEPS", "1440"))

# an equal-area projection (cylindrical, on the WGS 84 ellipsoid) to measure
# areas of geometries in longitude and latitude, including whole bands of
# latitude and the globe
_TO_EQUAL_AREA = Transformer.from_crs(
    "EPSG:4326",
    "+proj=cea +lon_0=0 +lat_ts=0 +datum=WGS84 +units=m",
    always_xy=True,
)

SWATH_COLUMNS = ["satellite", "instrument", "segment", "start", "end", "geometry"]
PAIR_COLUMNS = ["satellite_1", "satellite_2", "segment", "start", "end", "geometry"]
PIECE_COLUMNS = ["bin", "geometry"]
OBSERVATION_COLUMNS = [
    "target_hash",
    "satellite",
    "instrument",
    "start",
    "epoch",
    "end",
    "geometry",
]


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
    return np.linspace(0, (end - start).total_seconds(), COVERAGE_SAMPLES + 1)


def _seconds(times: pd.Series, start: datetime) -> np.ndarray:
    """
    Converts times to seconds since a start.
    """
    return (
        (pd.to_datetime(times, utc=True) - pd.Timestamp(start).tz_convert("UTC"))
        .dt.total_seconds()
        .to_numpy(dtype=float)
    )


def _dissolve_pieces(
    frame: gpd.GeoDataFrame, times: pd.Series, start: datetime, end: datetime
) -> gpd.GeoDataFrame:
    """
    Dissolves footprints (or overlaps) into one piece for each time of a
    coverage curve: the first curve time at or after its time.
    """
    if frame.empty:
        return empty_frame(PIECE_COLUMNS)
    bins = np.searchsorted(curve_seconds(start, end), _seconds(times, start), "left")
    pieces = gpd.GeoDataFrame(
        {"bin": np.minimum(bins, COVERAGE_SAMPLES)},
        geometry=frame.geometry.to_numpy(),
        crs="EPSG:4326",
    )
    return pieces.dissolve(by="bin", as_index=False)[PIECE_COLUMNS]


def _segment(times: pd.Series, start: datetime, segment: timedelta) -> np.ndarray:
    """
    Gets the display segment of times (samples on a boundary belong to the
    preceding segment).
    """
    elapsed = pd.to_datetime(times, utc=True) - pd.Timestamp(start).tz_convert("UTC")
    return (
        ((elapsed - pd.Timedelta(1, "ns")) // pd.Timedelta(segment))
        .clip(lower=0)
        .astype(int)
        .to_numpy()
    )


def analyze_window(  # pylint: disable=too-many-arguments,too-many-locals
    members: list,
    region: Optional[Union[Polygon, MultiPolygon]],
    times: pd.DatetimeIndex,
    window_end: datetime,
    start: datetime,
    end: datetime,
    display_end: datetime,
    step: timedelta,
    segment: Optional[timedelta],
    instrument_index: Optional[int] = None,
    max_time_difference: Optional[timedelta] = None,
    systems: Optional[Dict[str, str]] = None,
) -> Dict[str, pd.DataFrame]:
    """
    Analyzes a window of times: the footprints of the members at the times
    before the window's end (its own times), clipped to the region if any,
    as swath segments over the animation; with a region, the pieces of its
    area observed by each time of the coverage curve and its observations
    in the window; and, with a maximum time difference, the coincident
    footprints whose earlier time is the window's own (paired with
    footprints up to that difference after it).

    Args:
        members (list): The member satellites.
        region (Optional[Union[Polygon, MultiPolygon]]): The region, or
            `None` for unclipped swaths.
        times (pandas.DatetimeIndex): The times of the window: its own, and
            those of the following maximum time difference.
        window_end (datetime.datetime): The end of the window (exclusive).
        start (datetime.datetime): The start of the analysis period.
        end (datetime.datetime): The end of the analysis period.
        display_end (datetime.datetime): The end of the animation, after
            which swath segments (and coincident ones) are not given.
        step (datetime.timedelta): The time step (over which footprints sweep).
        segment (Optional[datetime.timedelta]): The duration of each swath
            segment, or `None` to give no swath segments.
        instrument_index (Optional[int]): The instrument index, or `None` for all.
        max_time_difference (Optional[datetime.timedelta]): The maximum time
            difference of coincident footprints, or `None` not to find them.
        systems (Optional[Dict[str, str]]): The platform of each member, by
            name, if coincident footprints are between systems.

    Returns:
        Dict[str, pandas.DataFrame]: the `swaths`; with a region, its `area`
            pieces and `observations`; and (with a maximum time difference)
            coincident `pairs` (dissolved), `common` area pieces, and
            `differences` of the window.
    """
    own_times = times[times < window_end]
    footprints = collect_footprints(
        members,
        list(times),
        instrument_index=instrument_index,
        mask=region,
        time_step=step,
    )
    if not footprints.empty:
        footprints = footprints[
            footprints.valid_obs & ~footprints.geometry.is_empty
        ].reset_index(drop=True)
    own = (
        footprints[footprints.time.isin(own_times)]
        if not footprints.empty
        else footprints
    )
    shown = own[own.time <= pd.Timestamp(display_end)] if not own.empty else own
    result = {
        "swaths": (
            _swath_segments(shown, start, display_end, step, segment)
            if segment is not None
            else empty_frame(SWATH_COLUMNS)
        )
    }
    if region is not None:
        result["area"] = _dissolve_pieces(own, own.get("time"), start, end)
        result["observations"] = _region_observations(
            region, members, own_times, step, end, instrument_index
        )
    if max_time_difference is not None:
        pairs = _coincident_pairs(footprints, own_times, max_time_difference, systems)
        # coincident segments over the animation (each shows at its later time)
        shown_pairs = (
            pairs[pd.to_datetime(pairs.time_2, utc=True) <= pd.Timestamp(display_end)]
            if not pairs.empty and segment is not None
            else pairs.iloc[0:0]
        )
        result["pairs"] = _pair_segments(shown_pairs, start, segment)
        result["common"] = _dissolve_pieces(pairs, pairs.get("time_2"), start, end)
        result["differences"] = pd.DataFrame(
            {
                "seconds": (
                    np.abs(pd.to_timedelta(pairs["time_difference"]).dt.total_seconds())
                    if not pairs.empty
                    else []
                )
            }
        )
    return result


def _swath_segments(
    footprints: gpd.GeoDataFrame,
    start: datetime,
    end: datetime,
    step: timedelta,
    segment: timedelta,
) -> gpd.GeoDataFrame:
    """
    Dissolves footprints into swath segments of each instrument of each
    satellite, from the start of the analysis to an end.
    """
    if footprints.empty:
        return empty_frame(SWATH_COLUMNS)
    track = footprints.assign(
        segment=_segment(footprints.time, start, segment),
        start=footprints.time - step / 2,
        end=footprints.time + step / 2,
    )
    swaths = track.dissolve(
        by=["satellite", "instrument", "segment"],
        aggfunc={"start": "min", "end": "max"},
        as_index=False,
    )
    swaths["start"] = swaths["start"].clip(lower=pd.Timestamp(start))
    swaths["end"] = swaths["end"].clip(upper=pd.Timestamp(end))
    return swaths[SWATH_COLUMNS]


def _region_observations(  # pylint: disable=too-many-arguments
    region: Union[Polygon, MultiPolygon],
    members: list,
    own_times: pd.DatetimeIndex,
    step: timedelta,
    end: datetime,
    instrument_index: Optional[int],
) -> gpd.GeoDataFrame:
    """
    Collects the observations of the region by members over the span of a
    window's own times, to the next window's first time (a step after its
    last, or the end of the analysis), with the region's representative
    point as geometry (its swaths are not needed, and observations split
    between windows are merged when aggregated).
    """
    if len(own_times) == 0:
        return empty_frame(OBSERVATION_COLUMNS)
    window_start = own_times[0].to_pydatetime()
    window_end = min(own_times[-1].to_pydatetime() + step, end)
    if window_end <= window_start:
        return empty_frame(OBSERVATION_COLUMNS)
    observations = collect_region_observations(
        region, members, window_start, window_end, instrument_index
    )
    if observations.empty:
        return empty_frame(OBSERVATION_COLUMNS)
    observations = observations.set_geometry(
        [region.representative_point()] * len(observations), crs="EPSG:4326"
    )
    return observations[OBSERVATION_COLUMNS]


def _coincident_pairs(
    footprints: gpd.GeoDataFrame,
    own_times: pd.DatetimeIndex,
    max_time_difference: timedelta,
    systems: Optional[Dict[str, str]],
) -> gpd.GeoDataFrame:
    """
    Finds the pairs of coincident footprints whose earlier time is one of a
    window's own times, between systems if given.
    """
    empty = gpd.GeoDataFrame(
        {
            "time_1": pd.Series([], dtype="datetime64[ns, UTC]"),
            "time_2": pd.Series([], dtype="datetime64[ns, UTC]"),
            "satellite_1": [],
            "satellite_2": [],
            "time_difference": pd.Series([], dtype="timedelta64[ns]"),
        },
        geometry=[],
        crs="EPSG:4326",
    )
    if footprints.empty:
        return empty
    pairs = find_coincident_ground_track(
        footprints, max_time_difference=max_time_difference
    )
    if pairs.empty:
        return empty
    pairs = pairs[pairs.time_1.isin(own_times)]
    if systems is not None:
        pairs = pairs[
            pairs.satellite_1.map(systems).to_numpy()
            != pairs.satellite_2.map(systems).to_numpy()
        ]
    return pairs.reset_index(drop=True)


def _pair_segments(
    pairs: gpd.GeoDataFrame, start: datetime, segment: timedelta
) -> gpd.GeoDataFrame:
    """
    Dissolves coincident footprints into segments of each pair of
    satellites (by the later time of each pair), from the earliest to the
    latest time of their footprints.
    """
    if pairs.empty:
        return empty_frame(PAIR_COLUMNS)
    names = np.sort(pairs[["satellite_1", "satellite_2"]].to_numpy(dtype=str), axis=1)
    frame = gpd.GeoDataFrame(
        {
            "satellite_1": names[:, 0],
            "satellite_2": names[:, 1],
            "segment": _segment(pairs.time_2, start, segment),
            "start": pd.to_datetime(pairs.time_1, utc=True),
            "end": pd.to_datetime(pairs.time_2, utc=True),
        },
        geometry=pairs.geometry.to_numpy(),
        crs="EPSG:4326",
    )
    return frame.dissolve(
        by=["satellite_1", "satellite_2", "segment"],
        aggfunc={"start": "min", "end": "max"},
        as_index=False,
    )[PAIR_COLUMNS]


@app.task
def collect_swath_window_task(  # pylint: disable=too-many-arguments
    members: List[str],
    region: Optional[str],
    times: List[str],
    window_end: str,
    start: str,
    end: str,
    display_end: str,
    step: float,
    segment: Optional[float],
    instrument_index: Optional[int] = None,
    max_time_difference: Optional[float] = None,
    systems: Optional[dict] = None,
) -> list:
    """
    Task to analyze a window of times of the swaths of member satellites
    (see `analyze_window`).

    Args:
        members (List[str]): JSON serialized member satellites.
        region (Optional[str]): GeoJSON serialized region geometry, or
            `None` for unclipped swaths.
        times (List[str]): ISO 8601 serialized times of the window.
        window_end (str): ISO 8601 serialized end of the window.
        start (str): ISO 8601 serialized start of the analysis period.
        end (str): ISO 8601 serialized end of the analysis period.
        display_end (str): ISO 8601 serialized end of the animation.
        step (float): Time step (seconds).
        segment (Optional[float]): Swath segment duration (seconds), or
            `None` to give no swath segments.
        instrument_index (Optional[int]): Instrument index, or `None` for all.
        max_time_difference (Optional[float]): Maximum time difference
            (seconds) of coincident footprints, or `None` not to find them.
        systems (Optional[dict]): Platform of each member, by name, if
            coincident footprints are between systems.

    Returns:
        list: Tagged GeoJSON (or JSON) serialized results of the window.
    """
    results = analyze_window(
        deserialize_members(members),
        None if region is None else shape(json.loads(region)),
        parse_times(times),
        datetime.fromisoformat(window_end),
        datetime.fromisoformat(start),
        datetime.fromisoformat(end),
        datetime.fromisoformat(display_end),
        timedelta(seconds=step),
        None if segment is None else timedelta(seconds=segment),
        instrument_index,
        None if max_time_difference is None else timedelta(seconds=max_time_difference),
        systems,
    )
    return [
        tag(
            f"swath-{kind}",
            (
                frame.to_json(orient="records")
                if kind == "differences"
                else to_geojson(frame)
            ),
        )
        for kind, frame in results.items()
    ]


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
    curve = CoverageCurve(
        times=[round(float(t), 3) for t in times],
        shares=[float(s) for s in shares],
    )
    return curve, float(shares[-1])


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
        _seconds(aggregated["start"], start) if not aggregated.empty else np.array([])
    )
    ends = _seconds(aggregated["end"], start) if not aggregated.empty else np.array([])
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


def _frames(results: list, kind: str, **kwargs) -> gpd.GeoDataFrame:
    """
    Concatenates the (GeoJSON serialized) frames of a kind of the windows.
    """
    return concat(
        from_geojson(data, **kwargs) for data in untag(results, f"swath-{kind}")
    )


@app.task
def combine_swaths_task(  # pylint: disable=too-many-arguments,too-many-locals
    results: list,
    region: Optional[str],
    start: str,
    end: str,
    colors: dict,
    systems: Optional[dict] = None,
    coincidence: bool = False,
) -> str:
    """
    Task to combine the windows of a swath analysis (and the orbit tracks of
    member satellites).

    Args:
        results (list): Tagged results of parallel tasks.
        region (Optional[str]): GeoJSON serialized region geometry, or
            `None` for unclipped swaths.
        start (str): ISO 8601 serialized start of the analysis period.
        end (str): ISO 8601 serialized end of the analysis period.
        colors (dict): Display colors by member satellite name.
        systems (Optional[dict]): Index of the satellite or constellation by
            member satellite name.
        coincidence (bool): Whether the windows found coincident footprints.

    Returns:
        str: JSON serialized `SwathAnalysisResult`.
    """
    animation = combine_animation(results, start, colors)
    start_time = datetime.fromisoformat(start)
    end_time = datetime.fromisoformat(end)

    swaths = _merge_segments(
        _frames(results, "swaths", datetimes=["start", "end"], columns=SWATH_COLUMNS),
        ["satellite", "instrument", "segment"],
        SWATH_COLUMNS,
    )
    result = {
        "swaths": json.loads(to_geojson(swaths.drop(columns="segment"))),
        "tracks": animation.tracks,
        "colors": animation.colors,
        "systems": systems or {},
    }
    if region is not None:
        result |= _region_results(
            results, shape(json.loads(region)), start_time, end_time, coincidence
        )
    return SwathAnalysisResult(**result).model_dump_json()


def _region_results(
    results: list,
    geometry: Union[Polygon, MultiPolygon],
    start_time: datetime,
    end_time: datetime,
    coincidence: bool,
) -> dict:
    """
    Combines the results of the windows over a region: the region, its
    coincident swath segments, its observations, and the summary of its
    coverage (fields of a `SwathAnalysisResult`).
    """

    observations = _frames(
        results,
        "observations",
        datetimes=["start", "epoch", "end"],
        columns=OBSERVATION_COLUMNS,
    )
    pairs = common = differences = None
    if coincidence:
        pairs = _merge_segments(
            _frames(results, "pairs", datetimes=["start", "end"], columns=PAIR_COLUMNS),
            ["satellite_1", "satellite_2", "segment"],
            PAIR_COLUMNS,
        )
        common = _frames(results, "common", columns=PIECE_COLUMNS)
        differences = np.array(
            [
                row["seconds"]
                for data in untag(results, "swath-differences")
                for row in json.loads(data)
            ],
            dtype=float,
        )
    summary, aggregated = summarize_region(
        geometry,
        _frames(results, "area", columns=PIECE_COLUMNS),
        observations,
        start_time,
        end_time,
        common,
        differences,
    )
    return {
        "region": {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "geometry": mapping(geometry), "properties": {}}
            ],
        },
        "coincident": (
            None
            if pairs is None
            else json.loads(to_geojson(pairs.drop(columns="segment")))
        ),
        "observations": [
            RegionObservation(
                satellite=str(row.satellite),
                instrument=str(row.instrument),
                start=float(s),
                end=float(e),
            )
            for row, s, e in zip(
                aggregated.itertuples(),
                (
                    _seconds(aggregated["start"], start_time)
                    if not aggregated.empty
                    else []
                ),
                _seconds(aggregated["end"], start_time) if not aggregated.empty else [],
            )
        ],
        "summary": summary,
    }


def _merge_segments(
    frame: gpd.GeoDataFrame, by: List[str], columns: List[str]
) -> gpd.GeoDataFrame:
    """
    Merges the segments of windows (a segment split between two windows is
    dissolved into one), sorted by start.
    """
    if frame.empty:
        return empty_frame(columns)
    merged = frame.dissolve(
        by=by, aggfunc={"start": "min", "end": "max"}, as_index=False
    )
    return merged[columns].sort_values("start", ignore_index=True)
