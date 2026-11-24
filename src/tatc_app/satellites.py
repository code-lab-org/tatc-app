"""
Shared schemas and utilities for space-domain platforms (satellites and
constellations).

The accepted platform types mirror the space objects of the `tatc` library
(`tatc.schemas.AllSpaceObjects`): `Satellite`, `WalkerConstellation`,
`TrainConstellation`, `MOGConstellation`, and `SOCConstellation`, each of
which accepts every orbit type of `tatc.schemas.AllOrbits` (including two
line elements, `{"type": "tle", "tle": [line1, line2]}`), instrument type of
`tatc.schemas.AllInstruments`, and attitude, subject to the library's own
validation. A request without a `type` is treated as a `Satellite`.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

from typing import Annotated, Any, Iterable, List, Union

from pydantic import Discriminator, Tag
from tatc.schemas import (
    MOGConstellation,
    Satellite,
    SOCConstellation,
    TrainConstellation,
    WalkerConstellation,
)


def _get_space_system_type(value: Any) -> str:
    """
    Gets the type discriminator of a space system, defaulting to `satellite`.
    """
    if isinstance(value, dict):
        return value.get("type") or "satellite"
    return getattr(value, "type", None) or "satellite"


SpaceSystem = Union[
    Satellite,
    WalkerConstellation,
    TrainConstellation,
    MOGConstellation,
    SOCConstellation,
]

SpaceSystemInput = Annotated[
    Union[
        Annotated[Satellite, Tag("satellite")],
        Annotated[WalkerConstellation, Tag("walker")],
        Annotated[TrainConstellation, Tag("train")],
        Annotated[MOGConstellation, Tag("mog")],
        Annotated[SOCConstellation, Tag("soc")],
    ],
    Discriminator(_get_space_system_type),
]


def generate_members(system: SpaceSystem) -> List[Satellite]:
    """
    Expands a satellite or constellation into its member satellites. A plain
    satellite is its own sole member.

    Args:
        system (SpaceSystem): The satellite or constellation.

    Returns:
        List[Satellite]: The member satellites.
    """
    if isinstance(system, Satellite):
        return [system]
    return system.generate_members()


def expand_members(systems: Iterable[SpaceSystem]) -> List[Satellite]:
    """
    Expands satellites and constellations into the list of their member
    satellites, in a stable order, checking that member names are unique (as
    required by analyses that identify observations by satellite name).

    Args:
        systems (Iterable[SpaceSystem]): The satellites and constellations.

    Raises:
        HTTPException: (422) if two members share a name.

    Returns:
        List[Satellite]: The member satellites.
    """
    return check_unique_names(
        [member for system in systems for member in generate_members(system)]
    )


def check_unique_names(members: List[Satellite]) -> List[Satellite]:
    """
    Checks that member satellites have unique names (as required by analyses
    that identify observations by satellite name).

    Args:
        members (List[Satellite]): The member satellites.

    Raises:
        ValueError: If two members share a name.

    Returns:
        List[Satellite]: The member satellites.
    """
    names = set()
    for member in members:
        if member.name in names:
            raise ValueError(
                f"Duplicate satellite name '{member.name}': each satellite "
                "and constellation member must have a unique name."
            )
        names.add(member.name)
    return members


def validate_instrument_index(systems: Iterable[SpaceSystem], index: Any) -> None:
    """
    Validates an instrument index is in bounds for each satellite or
    constellation.

    Args:
        systems (Iterable[SpaceSystem]): The satellites and constellations.
        index (Optional[int]): The instrument index, or `None` for all.

    Raises:
        ValueError: if the index is out of bounds for any system.
    """
    if index is None:
        return
    for system in systems:
        if index >= len(system.instruments):
            raise ValueError(
                f"Instrument index {index} out of bounds for '{system.name}' "
                f"({len(system.instruments)} instrument(s))."
            )
