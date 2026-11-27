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
from pydantic import BaseModel

# OpenAPI metadata of endpoints that also respond with MessagePack (for
# requests with `Accept: application/x-msgpack`, see
# `msgpack_asgi.MessagePackMiddleware`)
MSGPACK_RESPONSES = {
    "200": {"content": {"application/json": {}, "application/x-msgpack": {}}}
}


def to_response_json(result: BaseModel) -> str:
    """
    Serializes the result of an analysis as its endpoint responds with it (by
    alias, without `None` values), so the endpoint returns the stored result
    as it is, without parsing and validating it again.

    Args:
        result (pydantic.BaseModel): The result.

    Returns:
        str: The JSON serialized result.
    """
    return result.model_dump_json(by_alias=True, exclude_none=True)


def empty_frame(columns: Iterable[str] = ()) -> gpd.GeoDataFrame:
    """
    Creates an empty geospatial data frame (in WGS 84), with columns.

    Args:
        columns (Iterable[str]): The columns (`geometry` is always last).

    Returns:
        geopandas.GeoDataFrame: The empty data frame.
    """
    return gpd.GeoDataFrame(
        {column: [] for column in columns if column != "geometry"},
        geometry=gpd.GeoSeries([], crs="EPSG:4326"),
    )


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
        gdf = empty_frame(columns or [])
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
        return frames[0] if frames else empty_frame()
    return gpd.GeoDataFrame(pd.concat(non_empty, ignore_index=True), crs="EPSG:4326")
