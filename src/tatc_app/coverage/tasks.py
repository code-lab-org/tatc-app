# -*- coding: utf-8 -*-
"""
Task specifications for coverage analysis endpoints.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

from datetime import datetime
import json

import geopandas as gpd

from tatc.schemas.point import Point
from tatc.schemas.satellite import Satellite
from tatc.analysis.coverage import (
    collect_multi_observations,
    aggregate_observations,
    reduce_observations,
    grid_observations,
)

from .schemas import CoverageAnalysisResult
from ..worker import app


@app.task
def run_coverage_analysis_task(
    point: str, satellites: list, start: str, end: str
) -> str:
    """
    Task to run coverage analysis.

    Args:
        point (str): JSON serialized :class:`tatc.schemas.Point` object.
        satellites (list): List of JSON serialized :class:`tatc.schemas.Satellite` objects.
        start (str): ISO 8601 serialized start time.
        end (str): ISO 8601 serialized end time.

    Returns:
        str: GeoJSON serialized `FeatureCollection` containing coverage analysis.
    """
    # call analysis function, parsing the serialized arguments
    results = reduce_observations(
        aggregate_observations(
            collect_multi_observations(
                Point.model_validate_json(point),
                [Satellite.model_validate_json(satellite) for satellite in satellites],
                datetime.fromisoformat(start),
                datetime.fromisoformat(end),
            )
        )
    )
    # re-serialize constituent data
    results["access"] = results["access"].apply(lambda t: t.value)
    results["revisit"] = results["revisit"].apply(lambda t: t.value)
    return results.to_json(show_bbox=False, drop_id=True)


@app.task
def grid_coverage_analysis_task(coverage_results: str, cells: str) -> str:
    """
    Task to grid coverage analysis over specified cells.

    Args:
        coverage_results (str): GeoJSON serialized `FeatureCollection` containing coverage analysis.
        cells (str): GeoJSON serialized `FeatureCollection` containing cell polygons.

    Returns:
        str: JSON serialized `CoverageAnalysisResult` containing coverage analysis results.
    """
    # deserialize the coverage statistics
    gdf = gpd.GeoDataFrame.from_features(json.loads(coverage_results), crs="EPSG:4326")
    # de-serialize constituent data
    gdf["access"] = gdf["access"].astype("timedelta64[ns]")
    gdf["revisit"] = gdf["revisit"].astype("timedelta64[ns]")
    # deserialize the cells
    grid_cells = gpd.GeoDataFrame.from_features(json.loads(cells), crs="EPSG:4326")
    # grid the results
    grid_data = grid_observations(gdf, grid_cells)
    # re-serialize constituent data
    grid_data["access"] = grid_data["access"].apply(lambda t: t.value)
    grid_data["revisit"] = grid_data["revisit"].apply(lambda t: t.value)
    # return the results object in json format
    return CoverageAnalysisResult(
        points=json.loads(coverage_results),
        cells=json.loads(grid_data.to_json(show_bbox=False, drop_id=True)),
    ).model_dump_json()
