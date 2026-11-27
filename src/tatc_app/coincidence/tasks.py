"""
Task specifications for coincident observation analysis endpoints.

Coincident observations are found for each chunk of points (the observations
of a point coincide only with others of the same point), and the coincident
periods are then combined as the observations of a coverage analysis (see
`coverage.tasks.combine_coverage_task`).

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional

import geopandas as gpd
import pandas as pd
from tatc.analysis import (
    aggregate_observations,
    collect_observations,
    find_coincident_observations,
)
from tatc.schemas import Satellite

from ..analysis.sample_sizes import drop_coarse, size_observations
from ..analysis.tasks import deserialize_members, tag
from ..coverage.tasks import OBSERVATION_COLUMNS
from ..utils.serialization import empty_frame, from_geojson, to_geojson
from ..worker import app

# joins a member's name to its instrument's while platforms are systems
# (a character not found in names)
MEMBER_SEPARATOR = "\x1f"
# separates the names of the contributors of a coincident observation
NAME_SEPARATOR = ", "


def _to_systems(observations: pd.DataFrame, systems: Dict[str, str]) -> pd.DataFrame:
    """
    Relabels observations to find coincidences between systems: the
    `satellite` of each is its system, and its `instrument` names its member
    too, so that the observations of members of one system do not coincide
    with each other, but each member's instrument still counts once.
    """
    relabeled = observations.copy()
    relabeled["instrument"] = (
        relabeled["satellite"].astype(str)
        + MEMBER_SEPARATOR
        + relabeled["instrument"].astype(str)
    )
    relabeled["satellite"] = relabeled["satellite"].map(systems)
    return relabeled


def _from_systems(coincident: pd.DataFrame) -> pd.DataFrame:
    """
    Restores the member satellites and instruments of coincident
    observations relabeled by `_to_systems` (from the instruments, which
    name each contributor in turn).
    """
    restored = coincident.copy()
    pairs = [
        [name.split(MEMBER_SEPARATOR, 1) for name in names.split(NAME_SEPARATOR)]
        for names in restored["instrument"].astype(str)
    ]
    restored["satellite"] = [
        NAME_SEPARATOR.join(member for member, _ in contributors)
        for contributors in pairs
    ]
    restored["instrument"] = [
        NAME_SEPARATOR.join(instrument for _, instrument in contributors)
        for contributors in pairs
    ]
    return restored


def collect_coincident_observations(  # pylint: disable=too-many-arguments
    points: gpd.GeoDataFrame,
    satellites: List[Satellite],
    start: datetime,
    end: datetime,
    min_platforms: int = 2,
    max_time_difference: timedelta = timedelta(0),
    instantaneous: bool = False,
    systems: Optional[Dict[str, str]] = None,
    max_sample_size: Optional[float] = None,
) -> gpd.GeoDataFrame:
    """
    Collects the coincident observations of points by all instruments of
    satellites, aggregated as observations (see
    `coverage.tasks.collect_sized_observations`).

    Args:
        points (geopandas.GeoDataFrame): The points.
        satellites (List[tatc.schemas.Satellite]): The satellites.
        start (datetime.datetime): The start of the analysis period.
        end (datetime.datetime): The end of the analysis period.
        min_platforms (int): The minimum number of platforms observing at
            once.
        max_time_difference (datetime.timedelta): The maximum time between
            coincident observations.
        instantaneous (bool): True to compare the observations' epochs
            rather than their periods.
        systems (Optional[Dict[str, str]]): The platform (system) of each
            member satellite, by name, or `None` if each member is a
            platform.
        max_sample_size (Optional[float]): The largest ground sample size
            (meters) of an observation that counts (see
            `analysis.sample_sizes`), or `None` for every observation.

    Returns:
        geopandas.GeoDataFrame: The aggregated coincident observations, with
            the contributing satellites and instruments of each.
    """
    observations = collect_observations(
        points, satellites, start, end, instrument_index=None
    )
    if max_sample_size is not None:
        observations = drop_coarse(
            size_observations(observations, satellites), max_sample_size
        )
    if observations.empty:
        return empty_frame(OBSERVATION_COLUMNS)
    if systems is not None:
        observations = _to_systems(observations, systems)
    coincident = find_coincident_observations(
        observations,
        min_platforms=min_platforms,
        max_time_difference=max_time_difference,
        instantaneous=instantaneous,
    )
    if coincident.empty:
        return empty_frame(OBSERVATION_COLUMNS)
    if systems is not None:
        coincident = _from_systems(coincident)
    return aggregate_observations(coincident)[OBSERVATION_COLUMNS]


@app.task
def collect_coincidence_task(  # pylint: disable=too-many-arguments
    points: str,
    satellites: list,
    start: str,
    end: str,
    min_platforms: int = 2,
    max_time_difference: float = 0,
    instantaneous: bool = False,
    systems: Optional[dict] = None,
    max_sample_size: Optional[float] = None,
) -> dict:
    """
    Task to collect the coincident observations of a chunk of points.

    Args:
        points (str): GeoJSON serialized points.
        satellites (list): List of JSON serialized :class:`tatc.schemas.Satellite` objects.
        start (str): ISO 8601 serialized start time.
        end (str): ISO 8601 serialized end time.
        min_platforms (int): The minimum number of platforms observing at
            once.
        max_time_difference (float): The maximum time (seconds) between
            coincident observations.
        instantaneous (bool): True to compare the observations' epochs.
        systems (Optional[dict]): The platform of each member satellite, by
            name, or `None` if each member is a platform.
        max_sample_size (Optional[float]): The largest ground sample size
            (meters) of an observation that counts, or `None`.

    Returns:
        dict: Tagged (`obs`) GeoJSON serialized aggregated coincident
            observations (combined by `coverage.tasks.combine_coverage_task`).
    """
    results = collect_coincident_observations(
        from_geojson(points),
        deserialize_members(satellites),
        datetime.fromisoformat(start),
        datetime.fromisoformat(end),
        min_platforms,
        timedelta(seconds=max_time_difference),
        instantaneous,
        systems,
        max_sample_size,
    )
    return tag("obs", to_geojson(results))
