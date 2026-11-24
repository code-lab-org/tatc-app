"""
Satellite systems of the TAT-C system catalog (`tatc.catalog`), built with
current general perturbations (GP) elements from CelesTrak.

The catalog's orbits are idealized (the planes of orbits, with arbitrary or
relative phases, repeat ground tracks, and geostationary slots), so satellites
built from them are not coordinated across systems. Instead, each spacecraft's
cataloged orbit is replaced by the GP elements of its NORAD catalog number,
which the CelesTrak catalog (`tatc_app.celestrak.catalog`) obtains from its
cached group or, for other objects, by narrow queries cached for two hours.
Only a spacecraft for which CelesTrak has no data (such as a decayed one)
keeps its cataloged orbit, with a warning. Cataloged instruments are built
for the GP orbit, as some tailor their fields of view to the orbit.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

from __future__ import annotations

import functools
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field, model_validator
from tatc.catalog import (
    InstrumentPayload,
    SatelliteSystem,
    Spacecraft,
    build_payload,
    get_entry,
    get_system,
    list_systems,
)
from tatc.schemas import Satellite
from tatc.schemas.orbit import AllOrbits

from ..celestrak.catalog import CelestrakObject
from .capture import capture_catalog_warnings

MAX_ELEMENT_AGE = timedelta(days=14)
"""Difference between element epochs and the start beyond which to warn."""

MAX_DURATION = timedelta(days=366)
"""Longest period for which to build instruments (some schedule by day)."""


class CatalogInstrument(BaseModel):
    """An instrument a spacecraft carries: an entry of the instrument catalog."""

    id: str = Field(..., description="Instrument entry identifier.")
    name: str = Field(..., description="Instrument name.")


class CatalogSpacecraft(BaseModel):
    """A spacecraft of a satellite system of the catalog."""

    id: str = Field(..., description="Spacecraft identifier.")
    name: str = Field(..., description="Spacecraft name.")
    norad_id: int = Field(..., description="NORAD catalog number.")
    status: Literal["operational", "extended", "retired"] = Field(
        ..., description="Status on the date `as_of`."
    )
    as_of: date = Field(..., description="Date of the status.")
    instruments: list[CatalogInstrument] = Field(
        [],
        description="Cataloged instruments it carries (other than sounders, "
        + "which TAT-C analyzes with their own methods).",
    )


class CatalogSatelliteSystem(BaseModel):
    """A satellite system of the catalog."""

    id: str = Field(..., description="System identifier.")
    name: str = Field(..., description="System name.")
    aliases: list[str] = Field([], description="Other names.")
    system_class: str = Field(
        ..., description="System class (sun_synchronous, inclined, geostationary)."
    )
    role: str = Field(..., description="Role (observing or transmitting).")
    operator: str = Field(..., description="Organizations that operate it.")
    selection: str = Field(..., description="Why the system is cataloged.")
    tier: str = Field(..., description="Validation tier of the system.")
    limitations: list[str] = Field([], description="What it does not represent.")
    spacecraft: list[CatalogSpacecraft] = Field(..., description="Its spacecraft.")


class CatalogPeriod(BaseModel):
    """
    The analysis time step and period for which cataloged instruments are
    built (some tailor their fields of view to the time step, and some
    schedule their tilt by day).
    """

    time_step: float = Field(
        60,
        gt=0,
        le=3600,
        description="Analysis time step (seconds) to which instruments that scan "
        + "across track tailor their along-track fields of view.",
    )
    start: AwareDatetime | None = Field(
        None,
        description="Start of the analysis (default: now), for instruments that "
        + "schedule their tilt by day and spacecraft without GP elements.",
    )
    end: AwareDatetime | None = Field(
        None,
        description="End of the analysis (default: one day after the start), "
        + "for instruments that schedule their tilt by day.",
    )

    @model_validator(mode="after")
    def _check_period(self) -> CatalogPeriod:
        if self.start is None:
            self.start = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        if self.end is None:
            self.end = self.start + timedelta(days=1)
        if self.end <= self.start:
            raise ValueError("end must be after start")
        if self.end - self.start > MAX_DURATION:
            raise ValueError(f"the period must not exceed {MAX_DURATION.days} days")
        return self


class CatalogBuildRequest(CatalogPeriod):
    """Request to build satellites of a catalog system."""

    members: list[str] | None = Field(
        None,
        min_length=1,
        description="Identifiers (or names) of the spacecraft to build "
        + "(default: those not retired).",
    )
    instruments: bool | list[str] = Field(
        True,
        description="Whether satellites carry their cataloged instruments "
        + "(otherwise, TAT-C's default instrument), or the identifiers of the "
        + "cataloged instruments to carry (each on the satellites that carry it).",
    )


class CatalogMember(BaseModel):
    """A satellite built from a catalog system."""

    id: str = Field(..., description="Spacecraft identifier.")
    name: str = Field(..., description="Satellite name.")
    norad_id: int = Field(..., description="NORAD catalog number.")
    orbit_source: Literal["celestrak", "catalog"] = Field(
        ...,
        description="Source of the orbit: GP elements from CelesTrak, or the "
        + "cataloged (idealized) orbit, if CelesTrak has no data.",
    )
    epoch: str | None = Field(None, description="Epoch (UTC) of GP elements.")


class CatalogBuildResult(BaseModel):
    """Satellites built from a catalog system."""

    system: str = Field(..., description="System identifier.")
    name: str = Field(..., description="System name.")
    satellites: list[dict] = Field(
        ..., description="The satellites, in the schema of the TAT-C library."
    )
    members: list[CatalogMember] = Field(..., description="The satellites built.")
    warnings: list[str] = Field([], description="What the satellites do not model.")


def _get_references(system: SatelliteSystem, spacecraft: Spacecraft) -> list[str]:
    """
    Gets the identifiers of the cataloged instruments a spacecraft carries.
    """
    if system.role == "transmitting":
        return []
    return system.get_payload_references(spacecraft.id)


def _get_instruments(
    system: SatelliteSystem, spacecraft: Spacecraft
) -> list[CatalogInstrument]:
    """
    Gets the cataloged instruments a spacecraft carries.
    """
    return [
        CatalogInstrument(id=reference, name=get_entry(reference).name)
        for reference in _get_references(system, spacecraft)
    ]


@functools.cache
def _list_satellite_systems() -> tuple[CatalogSatelliteSystem, ...]:
    return tuple(
        CatalogSatelliteSystem(
            id=system.id,
            name=system.name,
            aliases=list(system.aliases),
            system_class=system.system_class.value,
            role=system.role,
            operator=system.operator,
            selection=system.selection,
            tier=system.validation.tier.value,
            limitations=list(system.limitations),
            spacecraft=[
                CatalogSpacecraft(
                    id=spacecraft.id,
                    name=spacecraft.name,
                    norad_id=spacecraft.norad_id,
                    status=spacecraft.status,
                    as_of=spacecraft.as_of,
                    instruments=_get_instruments(system, spacecraft),
                )
                for spacecraft in system.spacecraft
            ],
        )
        for system in list_systems(satellite=True)
    )


def list_satellite_systems() -> list[CatalogSatelliteSystem]:
    """
    Lists the satellite systems of the catalog (loaded once, as loading the
    catalog takes a few seconds).

    Returns:
        list[CatalogSatelliteSystem]: The systems, sorted by identifier.
    """
    return [system.model_copy(deep=True) for system in _list_satellite_systems()]


def get_satellite_system(system_id: str) -> SatelliteSystem:
    """
    Gets a satellite system of the catalog.

    Args:
        system_id (str): The identifier (or name or alias) of the system.

    Returns:
        SatelliteSystem: The system.

    Raises:
        KeyError: If there is no such satellite system.
    """
    system = get_system(system_id)
    if not isinstance(system, SatelliteSystem):
        raise KeyError(f"{system_id!r} is not a satellite system")
    return system


def select_spacecraft(
    system: SatelliteSystem, members: list[str] | None
) -> list[Spacecraft]:
    """
    Selects the spacecraft to build.

    Args:
        system (SatelliteSystem): The system.
        members (list[str] | None): The identifiers or names of the
            spacecraft, or None for those not retired.

    Returns:
        list[Spacecraft]: The spacecraft (without duplicates).

    Raises:
        ValueError: If a member is unknown, or (by default) every spacecraft
            is retired.
    """
    if members is None:
        selected = [s for s in system.spacecraft if s.status != "retired"]
        if not selected:
            raise ValueError(
                f"Every spacecraft of {system.name} is retired: select members."
            )
        return selected
    selected = []
    for member in members:
        try:
            spacecraft = system.get_spacecraft(member)
        except KeyError as error:
            raise ValueError(f"{system.name} has no spacecraft {member!r}.") from error
        if spacecraft not in selected:
            selected.append(spacecraft)
    return selected


def select_references(
    system: SatelliteSystem,
    spacecraft: list[Spacecraft],
    instruments: bool | list[str],
) -> dict[str, list[str]]:
    """
    Selects the cataloged instruments that each spacecraft carries.

    Args:
        system (SatelliteSystem): The system.
        spacecraft (list[Spacecraft]): The spacecraft to build.
        instruments (bool | list[str]): Whether to carry the cataloged
            instruments, or the identifiers (or names) of those to carry.

    Returns:
        dict[str, list[str]]: The identifiers of the instruments, by
        spacecraft identifier.

    Raises:
        ValueError: If an instrument is unknown or carried by no spacecraft.
    """
    available = {s.id: _get_references(system, s) for s in spacecraft}
    if instruments is True or instruments is False:
        return available if instruments else {s.id: [] for s in spacecraft}
    selected = []
    for instrument in instruments:
        try:
            reference = get_entry(instrument).id
        except KeyError as error:
            raise ValueError(f"No cataloged instrument {instrument!r}.") from error
        if not any(reference in references for references in available.values()):
            raise ValueError(
                f"No selected spacecraft of {system.name} carries {instrument!r}."
            )
        selected.append(reference)
    return {
        spacecraft_id: [r for r in references if r in selected]
        for spacecraft_id, references in available.items()
    }


def _build_payload(
    references: list[str],
    spacecraft: Spacecraft,
    orbit: AllOrbits,
    request: CatalogBuildRequest,
) -> InstrumentPayload:
    return build_payload(
        references,
        orbit=orbit,
        time_step=request.time_step,
        platform=spacecraft.id,
        start=request.start,
        end=request.end,
    )


def _try_build_payload(
    references: list[str],
    spacecraft: Spacecraft,
    orbit: AllOrbits,
    request: CatalogBuildRequest,
) -> InstrumentPayload | None:
    """
    Builds a payload, or returns `None` if its instruments have different
    attitudes (which a satellite cannot carry together).
    """
    try:
        return _build_payload(references, spacecraft, orbit, request)
    except ValueError as error:
        if "different attitudes" in str(error):
            return None
        raise


def _fit_payload(
    references: list[str],
    spacecraft: Spacecraft,
    orbit: AllOrbits,
    request: CatalogBuildRequest,
) -> tuple[InstrumentPayload, list[str]]:
    """
    Builds a payload of instruments, leaving out those whose attitudes differ
    from those of the instruments before them.

    Returns:
        tuple[InstrumentPayload, list[str]]: The payload and the references
            of the instruments left out.
    """
    payload = _try_build_payload(references, spacecraft, orbit, request)
    if payload is not None:
        return payload, []
    carried, omitted = [], []
    for reference in references:
        fits = _try_build_payload(carried + [reference], spacecraft, orbit, request)
        (carried if fits is not None else omitted).append(reference)
    return _build_payload(carried, spacecraft, orbit, request), omitted


def _build_satellite(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    system: SatelliteSystem,
    spacecraft: Spacecraft,
    orbit: AllOrbits,
    references: list[str],
    request: CatalogBuildRequest,
    notes: list[str],
) -> Satellite:
    """
    Builds a satellite with cataloged instruments for an orbit. Instruments
    whose attitudes differ from those of the instruments before them (which a
    satellite cannot carry together) are left out.
    """
    if not references:
        if request.instruments is not False and system.role != "transmitting":
            notes.append(
                f"{spacecraft.name} carries "
                + (
                    "no cataloged instrument other than sounders"
                    if request.instruments is True
                    else "none of the selected instruments"
                )
                + ", so it has TAT-C's default instrument (a field of regard of "
                "180 degrees)."
            )
        return Satellite(name=spacecraft.name, orbit=orbit)
    payload, omitted = _fit_payload(references, spacecraft, orbit, request)
    if omitted:
        notes.append(
            f"{spacecraft.name} omits "
            + ", ".join(get_entry(reference).name for reference in omitted)
            + ", as a satellite cannot carry instruments with different "
            "attitudes: select which instruments to carry, or load the "
            "spacecraft again with the others."
        )
    return payload.to_satellite(orbit, name=spacecraft.name)


def _serialize(satellite: Satellite, celestrak: CelestrakObject | None) -> dict:
    """
    Serializes a satellite in the schema of the TAT-C library, without unset
    values (and, for GP elements, without library defaults that they do not
    use, such as the epoch of two line elements).
    """
    data = satellite.model_dump(mode="json", exclude_none=True)
    if celestrak is not None:
        data["orbit"] = celestrak.orbit.model_dump(mode="json", exclude_unset=True)
    return data


def _parse_epoch(epoch: str) -> datetime:
    parsed = datetime.fromisoformat(epoch)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _cataloged_orbits(
    system: SatelliteSystem, uncoordinated: list[Spacecraft], start: datetime
) -> tuple[dict[str, AllOrbits], str | None]:
    """
    Builds the cataloged orbits of spacecraft without GP elements, at the
    start of the analysis (with phases spaced evenly among them).

    Returns:
        tuple[dict[str, AllOrbits], str | None]: The orbits by spacecraft
            identifier, and a note (if any spacecraft).
    """
    if not uncoordinated:
        return {}, None
    identifiers = [s.id for s in uncoordinated]
    configuration = system.configurations[system.default_configuration]
    orbits = dict(zip(identifiers, configuration.build_orbits(identifiers, start)))
    note = (
        "CelesTrak has no GP elements for "
        + ", ".join(f"{s.name} ({s.norad_id})" for s in uncoordinated)
        + ", so "
        + ("it has its" if len(uncoordinated) == 1 else "they have their")
        + " cataloged orbit, whose phase is not coordinated with other "
        "satellites."
    )
    return orbits, note


def _stale_elements_note(
    member: Spacecraft, celestrak: CelestrakObject | None, start: datetime
) -> str | None:
    """
    Notes GP elements whose epoch is far from the start, if any.
    """
    if (
        celestrak is None
        or abs(_parse_epoch(celestrak.epoch) - start) <= MAX_ELEMENT_AGE
    ):
        return None
    return (
        f"The GP elements of {member.name} are from "
        f"{celestrak.epoch[:10]}, more than {MAX_ELEMENT_AGE.days} "
        "days from the start, so its position is less accurate."
    )


def build_satellites(
    system: SatelliteSystem,
    spacecraft: list[Spacecraft],
    objects: dict[int, CelestrakObject | None],
    request: CatalogBuildRequest,
) -> CatalogBuildResult:
    """
    Builds satellites of a catalog system with GP elements from CelesTrak (or,
    for spacecraft without them, the cataloged orbits).

    Args:
        system (SatelliteSystem): The system.
        spacecraft (list[Spacecraft]): The spacecraft to build.
        objects (dict[int, CelestrakObject | None]): The CelesTrak objects, by
            NORAD catalog number.
        request (CatalogBuildRequest): The request.

    Returns:
        CatalogBuildResult: The satellites.

    Raises:
        ValueError: If a satellite cannot be built.
    """
    notes: list[str] = []
    references = select_references(system, spacecraft, request.instruments)
    with capture_catalog_warnings(notes):
        # spacecraft without GP elements keep their cataloged orbits
        cataloged, note = _cataloged_orbits(
            system,
            [s for s in spacecraft if objects.get(s.norad_id) is None],
            request.start,
        )
        if note:
            notes.append(note)
        satellites, members = [], []
        for member in spacecraft:
            celestrak = objects.get(member.norad_id)
            orbit = cataloged[member.id] if celestrak is None else celestrak.orbit
            satellite = _build_satellite(
                system, member, orbit, references[member.id], request, notes
            )
            satellites.append(_serialize(satellite, celestrak))
            members.append(
                CatalogMember(
                    id=member.id,
                    name=member.name,
                    norad_id=member.norad_id,
                    orbit_source="catalog" if celestrak is None else "celestrak",
                    epoch=None if celestrak is None else celestrak.epoch,
                )
            )
            note = _stale_elements_note(member, celestrak, request.start)
            if note:
                notes.append(note)
    return CatalogBuildResult(
        system=system.id,
        name=system.name,
        satellites=satellites,
        members=members,
        warnings=list(dict.fromkeys(notes)),
    )
