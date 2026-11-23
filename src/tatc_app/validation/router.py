"""
Router specifications for validation endpoints, which let clients check
inputs (and preview derived values, such as the members of a constellation)
before enqueuing analyses.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import math
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from tatc.constants import EARTH_MEAN_RADIUS, EARTH_MU
from tatc.schemas import Satellite

from ..satellites import SpaceSystemInput, expand_members

router = APIRouter()


class MemberSummary(BaseModel):
    """
    Summary of a member satellite.
    """

    name: str = Field(..., description="Satellite name.")
    orbit_type: str = Field(..., description="Orbit type.")
    altitude: Optional[float] = Field(
        None, description="Mean altitude (meters) above the mean Earth radius."
    )
    inclination: Optional[float] = Field(None, description="Inclination (degrees).")
    eccentricity: Optional[float] = Field(None, description="Eccentricity.")
    period: Optional[float] = Field(None, description="Orbital period (seconds).")
    instruments: List[str] = Field([], description="Instrument names.")


class SpaceSystemValidation(BaseModel):
    """
    Result of validating a satellite or constellation.
    """

    system: dict = Field(..., description="The normalized satellite or constellation.")
    members: List[MemberSummary] = Field(..., description="Member satellites.")


def summarize_member(member: Satellite) -> MemberSummary:
    """
    Summarizes a member satellite, from the mean elements of its orbit.

    Args:
        member (tatc.schemas.Satellite): The satellite.

    Returns:
        MemberSummary: The summary.
    """
    summary = MemberSummary(
        name=member.name,
        orbit_type=member.orbit.type,
        instruments=[instrument.name for instrument in member.instruments],
    )
    try:
        elements = member.orbit.to_gp_orbit().elements[0]
        mean_motion = math.radians(elements.mean_motion)  # rad/s
        semimajor_axis = (EARTH_MU / mean_motion**2) ** (1 / 3)
        summary.altitude = semimajor_axis - EARTH_MEAN_RADIUS
        summary.inclination = elements.inclination
        summary.eccentricity = elements.eccentricity
        summary.period = 2 * math.pi / mean_motion
    except Exception:  # pylint: disable=broad-except
        pass
    return summary


@router.post("/space-system", response_model=SpaceSystemValidation)
def validate_space_system(system: SpaceSystemInput):
    """
    Endpoint to validate a satellite or constellation and summarize its
    member satellites. Invalid inputs are rejected (422) with the validation
    errors of the `tatc` library.

    Args:
        system (SpaceSystemInput): The satellite or constellation.

    Returns:
        SpaceSystemValidation: The normalized system and member summaries.
    """
    try:
        members = expand_members([system])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return SpaceSystemValidation(
        system=system.model_dump(mode="json"),
        members=[summarize_member(member) for member in members],
    )
