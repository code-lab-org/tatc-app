"""
Instruments of the TAT-C instrument catalog (`tatc.catalog`), added to
user-designed satellites and constellations.

A cataloged configuration models an instrument as it was validated against its
data products: its instruments (views) and the attitude of the body that
carries them. Configurations are built for the orbit of the satellite that
carries them, as most tailor their along-track fields of view to the orbit and
the analysis time step, and some schedule their tilt by day over the analysis
period. A satellite has one attitude, shared by its instruments, so adding a
configuration sets the satellite's attitude to the validated one, which also
orients any instruments it already carries. Limb sounders and radio occultation
receivers, whose soundings TAT-C analyzes with their own methods (not views of
instruments), are not listed.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

from __future__ import annotations

import copy
import functools
import re
import warnings
from typing import Any

from pydantic import BaseModel, Field, TypeAdapter
from tatc.catalog import InstrumentClass, InstrumentEntry, get_entry, list_entries
from tatc.schemas import Satellite

from ..satellites import SpaceSystemInput
from .systems import _BUILD_LOCK, CatalogPeriod

SOUNDERS = (InstrumentClass.LIMB, InstrumentClass.OCCULTATION)
"""Classes of instruments whose soundings TAT-C analyzes with other methods."""

_SPACE_SYSTEM = TypeAdapter(SpaceSystemInput)


class CatalogConfiguration(BaseModel):
    """A configuration of a cataloged instrument."""

    id: str = Field(..., description="Configuration identifier.")
    grade: str = Field(
        ..., description="Use it is validated for (coverage, timing, sample_size)."
    )
    tier: str = Field(..., description="Validation tier of the configuration.")
    description: str = Field(..., description="What the configuration represents.")
    instruments: int = Field(..., description="Number of instruments (views).")
    grouping: str | None = Field(
        None,
        description="How multiple instruments relate: union (parts of one view) "
        + "or alternatives (views analyzed one at a time).",
    )
    tilt_schedule: bool = Field(
        False, description="Whether its tilt is scheduled by day."
    )


class CatalogInstrumentEntry(BaseModel):
    """An instrument of the instrument catalog."""

    id: str = Field(..., description="Entry identifier.")
    name: str = Field(..., description="Instrument name.")
    aliases: list[str] = Field([], description="Other names.")
    instrument_class: str = Field(..., description="Instrument class.")
    selection: str = Field(..., description="Why the instrument is cataloged.")
    tier: str = Field(..., description="Validation tier of the instrument.")
    platforms: list[str] = Field(..., description="Spacecraft that carry it.")
    limitations: list[str] = Field([], description="What it does not represent.")
    default_configuration: str = Field(..., description="Default configuration.")
    configurations: list[CatalogConfiguration] = Field(
        ..., description="Ways of modeling it."
    )


class CatalogInstrumentRequest(CatalogPeriod):
    """Request to add a cataloged instrument to a satellite or constellation."""

    system: dict[str, Any] = Field(
        ...,
        description="The satellite or constellation, in the schema of the TAT-C "
        + "library, whose orbit the instrument is built for.",
    )
    configuration: str | None = Field(
        None, description="The configuration (default: the entry's default)."
    )
    replace: bool = Field(
        False,
        description="Whether the instrument replaces the existing instruments "
        + "(otherwise, it is added to them).",
    )


class CatalogInstrumentResult(BaseModel):
    """A satellite or constellation with a cataloged instrument added."""

    system: dict[str, Any] = Field(
        ..., description="The satellite or constellation, with the instrument."
    )
    entry: str = Field(..., description="Entry identifier.")
    configuration: str = Field(..., description="Configuration identifier.")
    added: list[str] = Field(..., description="Names of the instruments added.")
    attitude_changed: bool = Field(
        ...,
        description="Whether the attitude changed, which also orients the "
        + "instruments the satellite already carried.",
    )
    notes: list[str] = Field([], description="What the instrument does not model.")


def is_analyzable(entry: InstrumentEntry) -> bool:
    """
    Checks whether an entry has views of instruments to analyze (not
    soundings).
    """
    return entry.instrument_class not in SOUNDERS


@functools.cache
def _list_instrument_entries() -> tuple[CatalogInstrumentEntry, ...]:
    entries = []
    for entry in list_entries():
        if not is_analyzable(entry):
            continue
        validation = entry.validation
        entries.append(
            CatalogInstrumentEntry(
                id=entry.id,
                name=entry.name,
                aliases=list(entry.aliases),
                instrument_class=entry.instrument_class.value,
                selection=entry.selection,
                tier=validation.tier.value,
                platforms=[spacecraft.name for spacecraft in entry.get_spacecraft()],
                limitations=list(entry.limitations),
                default_configuration=entry.default_configuration,
                configurations=[
                    CatalogConfiguration(
                        id=key,
                        grade=configuration.grade.value,
                        tier=validation.configurations[key].tier.value,
                        description=configuration.description,
                        instruments=len(configuration.instruments),
                        grouping=configuration.grouping,
                        tilt_schedule=configuration.tilt_schedule is not None,
                    )
                    for key, configuration in entry.configurations.items()
                ],
            )
        )
    return tuple(entries)


def list_instrument_entries() -> list[CatalogInstrumentEntry]:
    """
    Lists the instruments of the catalog whose views TAT-C analyzes (loaded
    once, as loading the catalog takes a few seconds).

    Returns:
        list[CatalogInstrumentEntry]: The instruments, sorted by identifier.
    """
    return [entry.model_copy(deep=True) for entry in _list_instrument_entries()]


def get_instrument_entry(entry_id: str) -> InstrumentEntry:
    """
    Gets an instrument of the catalog whose views TAT-C analyzes.

    Args:
        entry_id (str): The identifier (or name or alias) of the entry.

    Returns:
        InstrumentEntry: The entry.

    Raises:
        KeyError: If there is no such entry, or it is a sounder.
    """
    entry = get_entry(entry_id)
    if not is_analyzable(entry):
        raise KeyError(f"{entry_id!r} is a sounder")
    return entry


def _unique_name(name: str, names: set[str]) -> str:
    """
    Gets a name that is not among others, as the design does (appending a
    number in parentheses).
    """
    if name not in names:
        return name
    base = re.sub(r" \(\d+\)$", "", name)
    number = 2
    while f"{base} ({number})" in names:
        number += 1
    return f"{base} ({number})"


def _describe_grouping(entry: InstrumentEntry, key: str, first: int) -> str | None:
    """
    Describes how to analyze the instruments of a configuration, by their
    indices in the satellite.
    """
    configuration = entry.configurations[key]
    count = len(configuration.instruments)
    indices = f"instruments {first} to {first + count - 1}"
    if configuration.grouping == "union":
        return (
            f"{entry.name}'s {indices} are parts of one view: analyze them "
            "together (with every instrument)."
        )
    if configuration.grouping == "alternatives":
        return (
            f"{entry.name}'s {indices} are alternative views, analyzed one at a "
            f"time (instrument {first + configuration.instrument_index} by "
            "default)."
        )
    return None


def add_instrument(  # pylint: disable=too-many-locals
    entry: InstrumentEntry, request: CatalogInstrumentRequest
) -> CatalogInstrumentResult:
    """
    Adds a cataloged instrument to a satellite or constellation, built for
    its orbit, the analysis time step, and the analysis period, with the
    validated attitude.

    Args:
        entry (InstrumentEntry): The entry.
        request (CatalogInstrumentRequest): The request.

    Returns:
        CatalogInstrumentResult: The satellite or constellation.

    Raises:
        pydantic.ValidationError: If the satellite or constellation (or the
            result) is not valid.
        ValueError: If the configuration is unknown.
    """
    system = _SPACE_SYSTEM.validate_python(request.system)
    notes: list[str] = []
    key = entry.select_configuration(request.configuration)
    with _BUILD_LOCK, warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        payload = entry.build(
            configuration=key,
            orbit=system.orbit,
            time_step=request.time_step,
            start=request.start,
            end=request.end,
        )
        # serialized as carried by a satellite, which omits the velocity
        # frames of instruments if the attitude sets the body's
        built = Satellite(
            name=system.name,
            orbit=system.orbit,
            instruments=payload.instruments,
            attitude=payload.attitude,
        ).model_dump(mode="json", exclude_none=True)
    notes.extend(str(warning.message) for warning in caught)

    result = copy.deepcopy(request.system)
    kept = [] if request.replace else list(result.get("instruments") or [])
    names = {instrument.get("name") or "Default" for instrument in kept}
    added = []
    for instrument in built["instruments"]:
        instrument["name"] = _unique_name(instrument["name"], names)
        names.add(instrument["name"])
        added.append(instrument)
    attitude = built.get("attitude")
    changed = (None if system.attitude is None else system.attitude.model_dump()) != (
        None if payload.attitude is None else payload.attitude.model_dump()
    )
    if attitude is not None:
        # the attitude sets the velocity frame of the body
        framed = [i for i in kept if i.pop("velocity_frame", None) is not None]
        if framed:
            notes.append(
                "The velocity frames of "
                + ", ".join(i.get("name") or "Default" for i in framed)
                + " are removed, as the attitude sets the body's."
            )
        result["attitude"] = attitude
    else:
        result.pop("attitude", None)
    result["instruments"] = kept + added
    if changed and kept:
        notes.append(
            f"The attitude is now {entry.name}'s validated attitude, which also "
            "orients the other instruments."
        )
    grouping = _describe_grouping(entry, key, len(kept))
    if grouping:
        notes.append(grouping)
    if entry.configurations[key].tilt_schedule is not None:
        notes.append(
            f"{entry.name}'s tilt is scheduled by day from "
            f"{request.start:%Y-%m-%d} to {request.end:%Y-%m-%d} (the analysis "
            "period): add it again to analyze another period."
        )
    notes.extend(payload.limitations)
    # checks that the result is valid
    _SPACE_SYSTEM.validate_python(result)
    return CatalogInstrumentResult(
        system=result,
        entry=entry.id,
        configuration=key,
        added=[instrument["name"] for instrument in added],
        attitude_changed=changed and bool(kept),
        notes=list(dict.fromkeys(notes)),
    )
