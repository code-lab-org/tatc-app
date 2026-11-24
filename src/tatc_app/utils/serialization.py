"""
Utilities to (de)serialize geospatial data frames exchanged between tasks
and returned to clients.

Date times are serialized as ISO 8601 strings (UTC, millisecond precision)
and durations as seconds; missing values (`NaT`, `NaN`) as `null`.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import json
from typing import Iterable, Optional

import geopandas as gpd
import pandas as pd


def to_geojson(gdf: gpd.GeoDataFrame) -> str:
    """
    Serializes a geospatial data frame to a GeoJSON feature collection.

    Args:
        gdf (geopandas.GeoDataFrame): The data frame.

    Returns:
        str: The GeoJSON serialized feature collection.
    """
    out = gdf.copy()
    for column in out.columns:
        if column == out.geometry.name:
            continue
        series = out[column]
        if pd.api.types.is_datetime64_any_dtype(series):
            out[column] = [
                None if pd.isna(t) else t.isoformat(timespec="milliseconds")
                for t in series.dt.tz_convert("UTC").dt.round("ms")
            ]
        elif pd.api.types.is_timedelta64_dtype(series):
            out[column] = series.dt.total_seconds()
    return out.to_json(show_bbox=False, drop_id=True, na="null")


def from_geojson(
    data: str,
    datetimes: Iterable[str] = (),
    timedeltas: Iterable[str] = (),
    columns: Optional[Iterable[str]] = None,
) -> gpd.GeoDataFrame:
    """
    Deserializes a GeoJSON feature collection to a geospatial data frame.

    Args:
        data (str): The GeoJSON serialized feature collection.
        datetimes (Iterable[str]): Columns to parse as date times (UTC).
        timedeltas (Iterable[str]): Columns to parse as durations (seconds).
        columns (Optional[Iterable[str]]): Columns of an empty result.

    Returns:
        geopandas.GeoDataFrame: The data frame.
    """
    features = json.loads(data).get("features", [])
    if len(features) == 0:
        gdf = gpd.GeoDataFrame(
            {c: [] for c in (columns or []) if c != "geometry"},
            geometry=gpd.GeoSeries([], crs="EPSG:4326"),
        )
    else:
        gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
    for column in datetimes:
        if column in gdf.columns:
            gdf[column] = pd.to_datetime(gdf[column], utc=True, format="ISO8601")
    for column in timedeltas:
        if column in gdf.columns:
            gdf[column] = pd.to_timedelta(gdf[column].astype("float64"), unit="s")
    return gdf


def concat(frames: Iterable[gpd.GeoDataFrame]) -> gpd.GeoDataFrame:
    """
    Concatenates geospatial data frames, ignoring empty ones.

    Args:
        frames (Iterable[geopandas.GeoDataFrame]): The data frames.

    Returns:
        geopandas.GeoDataFrame: The concatenated data frame (possibly empty).
    """
    frames = list(frames)
    non_empty = [frame for frame in frames if not frame.empty]
    if len(non_empty) == 0:
        return frames[0] if frames else gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    return gpd.GeoDataFrame(pd.concat(non_empty, ignore_index=True), crs="EPSG:4326")
