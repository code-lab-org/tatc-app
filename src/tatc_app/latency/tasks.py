"""
Task specifications for latency analysis endpoints.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import json
from datetime import datetime
from typing import List, Optional

import geopandas as gpd
from tatc.analysis import (
    collect_downlinks,
    collect_observations,
    compute_latencies,
    grid_latencies,
    reduce_latencies,
)
from tatc.schemas import GroundStation, Satellite

from ..analysis.summary import Weighting, summarize_latency
from ..analysis.tasks import combine_animation, get_cell_targets, tag, untag
from ..analysis.timeline import build_timeline
from ..utils.serialization import concat, empty_frame, from_geojson, to_geojson
from ..worker import app
from .schemas import LatencyAnalysisResult

LATENCY_COLUMNS = [
    "target_hash",
    "satellite",
    "instrument",
    "ground_station",
    "observed",
    "downlinked",
    "latency",
    "geometry",
]
CONTACT_COLUMNS = ["ground_station", "satellite", "start", "end", "geometry"]


def collect_latencies(
    points: gpd.GeoDataFrame,
    satellite: Satellite,
    stations: List[GroundStation],
    start: datetime,
    end: datetime,
    during_contact: str = "end",
) -> tuple:
    """
    Collects the latencies of observations of points by all instruments of a
    satellite, downlinked to ground stations.

    Args:
        points (geopandas.GeoDataFrame): The points.
        satellite (tatc.schemas.Satellite): The satellite.
        stations (List[tatc.schemas.GroundStation]): The ground stations.
        start (datetime.datetime): The start of the analysis period.
        end (datetime.datetime): The end of the analysis period.
        during_contact (str): The downlink of observations during a contact.

    Returns:
        tuple: The latencies of observations and the downlink contacts.
    """
    downlinks = collect_downlinks(stations, [satellite], start, end)
    contacts = (
        empty_frame(CONTACT_COLUMNS) if downlinks.empty else downlinks[CONTACT_COLUMNS]
    )
    observations = collect_observations(
        points, [satellite], start, end, instrument_index=None
    )
    if observations.empty:
        return empty_frame(LATENCY_COLUMNS), contacts
    latencies = compute_latencies(
        observations, downlinks, during_contact=during_contact
    )
    return latencies[LATENCY_COLUMNS], contacts


@app.task
def collect_latencies_task(
    points: str,
    satellite: str,
    stations: list,
    start: str,
    end: str,
    during_contact: str,
    include_contacts: bool,
) -> dict:
    """
    Task to collect latencies of observations of a chunk of points by one
    satellite.

    Args:
        points (str): GeoJSON serialized points.
        satellite (str): JSON serialized :class:`tatc.schemas.Satellite` object.
        stations (list): List of JSON serialized :class:`tatc.schemas.GroundStation` objects.
        start (str): ISO 8601 serialized start time.
        end (str): ISO 8601 serialized end time.
        during_contact (str): The downlink of observations during a contact.
        include_contacts (bool): `True`, to include downlink contacts.

    Returns:
        dict: Tagged (`lat`) GeoJSON serialized latencies and contacts.
    """
    latencies, contacts = collect_latencies(
        from_geojson(points),
        Satellite.model_validate_json(satellite),
        [GroundStation.model_validate_json(station) for station in stations],
        datetime.fromisoformat(start),
        datetime.fromisoformat(end),
        during_contact,
    )
    return tag(
        "lat",
        {
            "latencies": to_geojson(latencies),
            "contacts": to_geojson(contacts) if include_contacts else None,
        },
    )


def compute_latency(
    latencies: gpd.GeoDataFrame,
    contacts: gpd.GeoDataFrame,
    points: gpd.GeoDataFrame,
    cells: gpd.GeoDataFrame,
    stations: List[GroundStation],
    epoch: datetime,
    members: List[str],
    weighting: Optional[Weighting] = None,
) -> dict:
    """
    Reduces latencies of observations to statistics of points and cells,
    timelines of observations and contacts, and a summary over the points.

    Args:
        latencies (geopandas.GeoDataFrame): The latencies of observations.
        contacts (geopandas.GeoDataFrame): The downlink contacts.
        points (geopandas.GeoDataFrame): The points.
        cells (geopandas.GeoDataFrame): The cells.
        stations (List[tatc.schemas.GroundStation]): The ground stations.
        epoch (datetime.datetime): The reference time.
        members (List[str]): The member satellite names.
        weighting (Optional[Weighting]): The weighting of points in the
            summary (without it, no summary).

    Returns:
        dict: The `points`, `cells`, `timeline`, `contacts`, `stations`,
            `cell_targets`, and `summary`.
    """
    reduced = reduce_latencies(latencies, targets=points).reset_index(drop=True)
    gridded = grid_latencies(reduced, cells)
    return {
        "points": json.loads(to_geojson(reduced)),
        "cells": json.loads(to_geojson(gridded)),
        "timeline": build_timeline(
            latencies,
            epoch,
            reduced["target_hash"].tolist(),
            members,
            start_column="observed",
            end_column="downlinked",
        ),
        "contacts": build_timeline(
            contacts,
            epoch,
            [station.name for station in stations],
            members,
            target_column="ground_station",
        ),
        "stations": stations,
        "cell_targets": get_cell_targets(reduced, cells),
        "summary": (
            None
            if weighting is None
            else summarize_latency(reduced, contacts, weighting)
        ),
    }


@app.task
def combine_latency_task(
    results: list,
    points: str,
    cells: str,
    stations: list,
    start: str,
    colors: dict,
    weighting: Optional[str] = None,
) -> str:
    """
    Task to combine latencies of observations into latency statistics.

    Args:
        results (list): Tagged results of parallel tasks.
        points (str): GeoJSON serialized points.
        cells (str): GeoJSON serialized cells.
        stations (list): List of JSON serialized :class:`tatc.schemas.GroundStation` objects.
        start (str): ISO 8601 serialized start time (reference time).
        colors (dict): Display colors by member satellite name.
        weighting (Optional[str]): The weighting of points in the summary
            (see `Weighting`; without it, no summary).

    Returns:
        str: JSON serialized `LatencyAnalysisResult`.
    """
    animation = combine_animation(results, start, colors)
    data = untag(results, "lat")
    latencies = concat(
        from_geojson(
            d["latencies"],
            datetimes=["observed", "downlinked"],
            timedeltas=["latency"],
            columns=LATENCY_COLUMNS,
        )
        for d in data
    )
    contacts = concat(
        from_geojson(d["contacts"], datetimes=["start", "end"], columns=CONTACT_COLUMNS)
        for d in data
        if d["contacts"] is not None
    )
    return LatencyAnalysisResult(
        **compute_latency(
            latencies,
            contacts,
            from_geojson(points),
            from_geojson(cells, columns=["cell_id", "geometry"]),
            [GroundStation.model_validate_json(station) for station in stations],
            animation.epoch,
            animation.members,
            None if weighting is None else Weighting(weighting),
        ),
        tracks=animation.tracks,
        colors=animation.colors,
    ).model_dump_json()
