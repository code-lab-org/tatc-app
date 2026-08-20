"""
Task specifications for tracking analysis endpoints.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""


from datetime import datetime

from shapely.geometry import shape
from tatc.analysis.track import collect_ground_track, collect_orbit_track
from tatc.schemas import Instrument, Satellite

from ..worker import app


@app.task
def collect_orbit_track_task(
    satellite: str, instrument: str, times: list, elevation: float, mask: str
) -> str:
    """
    Task to collect orbit track.

    Args:
        satellites (str): JSON serialized :class:`tatc.schemas.Satellite` object.
        instrument (str): JSON serialized :class:`tatc.schemas.Instrument` object.
        times (str): List of ISO 8601 serialized times for which to compute orbit track.
        elevation (float): Elevation (meters) above datum in the WGS 84 coordinate system.
        mask (str): Optional GeoJSON serialized mask to constrain points.

    Returns:
        str: GeoJSON serialized orbit track.
    """
    sat = Satellite.model_validate_json(satellite)
    if instrument is not None:
        sat = sat.model_copy(
            update={"instruments": [Instrument.model_validate_json(instrument)]}
        )
    results = collect_orbit_track(
        sat,
        [datetime.fromisoformat(time) for time in times],
        0,
        elevation,
        shape(mask) if mask is not None else None,
    )
    # serialize Timestamp
    results["time"] = results["time"].apply(lambda t: t.isoformat())
    return results.to_json(show_bbox=False, drop_id=True)


@app.task
def collect_ground_track_task(
    satellite: str, instrument: str, times: list, elevation: float, mask: str
) -> str:
    """
    Task to collect ground track.

    Args:
        satellites (str): JSON serialized :class:`tatc.schemas.Satellite` object.
        instrument (str): JSON serialized :class:`tatc.schemas.Instrument` object.
        times (list): List of ISO 8601 serialized times for which to compute orbit track.
        elevation (float): Elevation (meters) above datum in the WGS 84 coordinate system.
        mask (str): Optional GeoJSON serialized mask to constrain points.

    Returns:
        str: GeoJSON serialized ground track.
    """
    sat = Satellite.model_validate_json(satellite)
    if instrument is not None:
        sat = sat.model_copy(
            update={"instruments": [Instrument.model_validate_json(instrument)]}
        )
    results = collect_ground_track(
        sat,
        [datetime.fromisoformat(time) for time in times],
        0,
        elevation,
        shape(mask) if mask is not None else None,
    )
    # serialize Timestamp
    results["time"] = results["time"].apply(lambda t: t.isoformat())
    return results.to_json(show_bbox=False, drop_id=True)
