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
from ..utils.serialization import to_geojson
from ..worker import app

# functions that collect the tracks of a satellite, by kind of track
TRACKS = {"orbit": collect_orbit_track, "ground": collect_ground_track}


@app.task
def collect_track_task(  # pylint: disable=too-many-arguments
    kind: str,
    satellite: str,
    instrument_index: Optional[int],
    times: list,
    elevation: Optional[float],
    mask: Optional[dict],
) -> str:
    """
    Task to collect an orbit or ground track.

    Args:
        kind (str): The kind of track (`orbit` or `ground`, see `TRACKS`).
        satellite (str): JSON serialized :class:`tatc.schemas.Satellite` object.
        instrument_index (Optional[int]): Instrument index, or `None` for all.
        times (list): List of ISO 8601 serialized times.
        elevation (Optional[float]): Elevation (meters) above datum in the WGS 84 coordinate system.
        mask (Optional[dict]): Optional GeoJSON mask to constrain points.

    Returns:
        str: GeoJSON serialized track.
    """
    results = TRACKS[kind](
        Satellite.model_validate_json(satellite),
        parse_times(times),
        instrument_index,
        elevation,
        shape(mask) if mask is not None else None,
    )
    return to_geojson(results)


@app.task
def merge_feature_collections_task(collections: List[str]) -> str:
    """
    Task to merge feature collections into one feature collection.

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
        }
    )
