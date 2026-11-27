"""
Task specifications for tracking analysis endpoints.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import json
from typing import List, Optional

from shapely.geometry import shape
from tatc.analysis import collect_ground_track, collect_orbit_track
from tatc.schemas import Satellite

from ..analysis.tasks import parse_times
from ..utils.serialization import concat, to_geojson
from ..worker import app

# functions that collect the tracks of a satellite, by kind of track
TRACKS = {"orbit": collect_orbit_track, "ground": collect_ground_track}


@app.task
def collect_track_task(  # pylint: disable=too-many-arguments
    kind: str,
    satellites: List[str],
    instrument_index: Optional[int],
    times: list,
    elevation: Optional[float],
    mask: Optional[dict],
) -> str:
    """
    Task to collect the orbit or ground tracks of satellites.

    Args:
        kind (str): The kind of track (`orbit` or `ground`, see `TRACKS`).
        satellites (List[str]): JSON serialized :class:`tatc.schemas.Satellite` objects.
        instrument_index (Optional[int]): Instrument index, or `None` for all.
        times (list): List of ISO 8601 serialized times.
        elevation (Optional[float]): Elevation (meters) above datum in the WGS 84 coordinate system.
        mask (Optional[dict]): Optional GeoJSON mask to constrain points.

    Returns:
        str: GeoJSON serialized tracks.
    """
    collect = TRACKS[kind]
    sample_times = parse_times(times)
    geometry = shape(mask) if mask is not None else None
    return to_geojson(
        concat(
            collect(
                Satellite.model_validate_json(satellite),
                sample_times,
                instrument_index,
                elevation,
                geometry,
            )
            for satellite in satellites
        )
    )


@app.task
def merge_feature_collections_task(collections: List[str]) -> str:
    """
    Task to merge feature collections into one (compact) feature collection,
    which the track endpoints return as it is.

    Args:
        collections (List[str]): GeoJSON serialized feature collections.

    Returns:
        str: GeoJSON serialized feature collection.
    """
    return json.dumps(
        {
            "type": "FeatureCollection",
            "features": [
                feature
                for collection in collections
                for feature in json.loads(collection)["features"]
            ],
        },
        separators=(",", ":"),
    )
