"""
Shared schemas and utilities to accept satellite/constellation requests that
specify their orbit as two line elements (TLE), as commonly distributed by
sources such as Celestrak.

tatc's own schemas no longer accept raw TLE lines directly: orbits
propagated from TLEs are represented as a `GeneralPerturbationsOrbit`, whose
wire format is a structured list of orbital elements rather than the two raw
TLE lines a client would naturally have on hand. Since it isn't reasonable
to ask a client to perform that conversion itself, `TwoLineElements` is
accepted here as an additional orbit variant and converted into a
`GeneralPerturbationsOrbit` on the backend, via `generate_members`, before
any tatc analysis code sees it.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

from typing import List, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator
from tatc.schemas import (
    CircularOrbit,
    GeneralPerturbationsOrbit,
    GeosynchronousOrbit,
    KeplerianOrbit,
    MolniyaOrbit,
    Satellite,
    SunSynchronousOrbit,
    TrainConstellation,
    TundraOrbit,
    WalkerConstellation,
)


class TwoLineElements(BaseModel):
    """
    Orbit specified as two line elements (TLE).
    """

    type: Literal["tle"] = "tle"
    tle: List[str] = Field(
        ...,
        min_length=2,
        max_length=2,
        description="Two line element (TLE) lines.",
        examples=[
            [
                "1 25544U 98067A   21156.30527927  .00003432  00000-0  70541-4 0  9993",
                "2 25544  51.6455  41.4969 0003508  68.0432  78.3395 15.48957534286754",
            ]
        ],
    )

    @field_validator("tle")
    @classmethod
    def valid_tle(cls, tle: List[str]) -> List[str]:
        """
        Validates the TLE lines can be parsed into a `GeneralPerturbationsOrbit`.
        """
        GeneralPerturbationsOrbit.from_tle(tle)
        return tle


# orbit types accepted from a client, including tatc's native orbit types
# (passed through as-is) in addition to `TwoLineElements`.
OrbitInput = Union[
    CircularOrbit,
    GeneralPerturbationsOrbit,
    GeosynchronousOrbit,
    KeplerianOrbit,
    MolniyaOrbit,
    SunSynchronousOrbit,
    TundraOrbit,
    TwoLineElements,
]


class SatelliteInput(Satellite):
    """
    A `Satellite` request that may specify its orbit as two line elements.
    """

    # accepts a native tatc `Satellite` instance directly, not only a
    # dict/JSON payload, since it is otherwise a stricter (sub)type
    model_config = ConfigDict(from_attributes=True)

    orbit: OrbitInput


class TrainConstellationInput(TrainConstellation):
    """
    A `TrainConstellation` request that may specify its orbit as two line
    elements.
    """

    model_config = ConfigDict(from_attributes=True)

    orbit: OrbitInput


class WalkerConstellationInput(WalkerConstellation):
    """
    A `WalkerConstellation` request that may specify its orbit as two line
    elements.
    """

    model_config = ConfigDict(from_attributes=True)

    orbit: OrbitInput


SpaceSystemInput = Union[
    SatelliteInput, TrainConstellationInput, WalkerConstellationInput
]

_TATC_TYPES = {
    SatelliteInput: Satellite,
    TrainConstellationInput: TrainConstellation,
    WalkerConstellationInput: WalkerConstellation,
}


def to_tatc_satellite(
    satellite: SpaceSystemInput,
) -> Union[Satellite, TrainConstellation, WalkerConstellation]:
    """
    Converts a satellite/constellation request into the corresponding tatc
    schema, resolving a `TwoLineElements` orbit into a
    `GeneralPerturbationsOrbit` along the way.

    Args:
        satellite (SpaceSystemInput): the requested satellite or constellation.

    Returns:
        Union[Satellite, TrainConstellation, WalkerConstellation]: the
            equivalent tatc satellite or constellation.
    """
    orbit = (
        GeneralPerturbationsOrbit.from_tle(satellite.orbit.tle)
        if isinstance(satellite.orbit, TwoLineElements)
        else satellite.orbit
    )
    tatc_type = _TATC_TYPES[type(satellite)]
    return tatc_type(**satellite.model_dump(exclude={"orbit", "type"}), orbit=orbit)


def generate_members(satellite: SpaceSystemInput) -> List[Satellite]:
    """
    Expands a satellite/constellation request into its member satellites,
    resolving a `TwoLineElements` orbit into a `GeneralPerturbationsOrbit`
    along the way. A plain satellite (not a constellation) is treated as its
    own sole member.

    Args:
        satellite (SpaceSystemInput): the requested satellite or constellation.

    Returns:
        List[Satellite]: the member satellites.
    """
    converted = to_tatc_satellite(satellite)
    if isinstance(converted, Satellite):
        return [converted]
    return converted.generate_members()
