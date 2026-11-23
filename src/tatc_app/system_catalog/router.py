"""
Router specifications for system catalog endpoints.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import asyncio
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError

from ..celestrak.catalog import CelestrakCatalog, get_catalog
from .instruments import (
    CatalogInstrumentEntry,
    CatalogInstrumentRequest,
    CatalogInstrumentResult,
    add_instrument,
    get_instrument_entry,
    list_instrument_entries,
)
from .systems import (
    CatalogBuildRequest,
    CatalogBuildResult,
    CatalogSatelliteSystem,
    build_satellites,
    get_satellite_system,
    list_satellite_systems,
    select_spacecraft,
)

router = APIRouter()


@router.get("/systems", response_model=List[CatalogSatelliteSystem])
async def list_catalog_systems() -> List[CatalogSatelliteSystem]:
    """
    Endpoint to list the satellite systems of the TAT-C system catalog.

    Returns:
        List[CatalogSatelliteSystem]: The systems.
    """
    return await asyncio.to_thread(list_satellite_systems)


@router.post("/systems/{system_id}/build", response_model=CatalogBuildResult)
async def build_catalog_system(
    system_id: str,
    request: Optional[CatalogBuildRequest] = None,
    catalog: CelestrakCatalog = Depends(get_catalog),
) -> CatalogBuildResult:
    """
    Endpoint to build satellites of a system of the TAT-C system catalog.
    Each spacecraft's idealized cataloged orbit is replaced by its current
    general perturbations (GP) elements from CelesTrak, so that satellites are
    coordinated across systems. Elements come from the server's cached
    CelesTrak group or, for other spacecraft, narrow queries by catalog number,
    each cached for two hours (per CelesTrak's usage policy). Spacecraft
    without GP elements keep their cataloged orbits, with a warning.

    Args:
        system_id (str): The identifier of the system.
        request (CatalogBuildRequest): The members and options to build.
        catalog (CelestrakCatalog): The CelesTrak catalog.

    Returns:
        CatalogBuildResult: The satellites.
    """
    request = request or CatalogBuildRequest()
    try:
        system = await asyncio.to_thread(get_satellite_system, system_id)
    except KeyError as error:
        raise HTTPException(
            status_code=404, detail=f"No catalog satellite system '{system_id}'."
        ) from error
    try:
        spacecraft = select_spacecraft(system, request.members)
        objects = await catalog.get_objects(s.norad_id for s in spacecraft)
        return await asyncio.to_thread(
            build_satellites, system, spacecraft, objects, request
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/instruments", response_model=List[CatalogInstrumentEntry])
async def list_catalog_instruments() -> List[CatalogInstrumentEntry]:
    """
    Endpoint to list the instruments of the TAT-C instrument catalog whose
    views TAT-C analyzes (not limb sounders or radio occultation receivers).

    Returns:
        List[CatalogInstrumentEntry]: The instruments.
    """
    return await asyncio.to_thread(list_instrument_entries)


@router.post("/instruments/{entry_id}/add", response_model=CatalogInstrumentResult)
async def add_catalog_instrument(
    entry_id: str, request: CatalogInstrumentRequest
) -> CatalogInstrumentResult:
    """
    Endpoint to add an instrument of the TAT-C instrument catalog to a
    satellite or constellation. The instrument is built for the orbit of the
    satellite (or constellation), the analysis time step, and the analysis
    period, and sets the satellite's attitude to the validated one, which also
    orients any other instruments it carries (see `attitude_changed`).

    Args:
        entry_id (str): The identifier of the instrument entry.
        request (CatalogInstrumentRequest): The satellite and options.

    Returns:
        CatalogInstrumentResult: The satellite or constellation.
    """
    try:
        entry = await asyncio.to_thread(get_instrument_entry, entry_id)
    except KeyError as error:
        raise HTTPException(
            status_code=404, detail=f"No catalog instrument '{entry_id}'."
        ) from error
    try:
        return await asyncio.to_thread(add_instrument, entry, request)
    except ValidationError as error:
        raise HTTPException(
            status_code=422,
            detail=jsonable_encoder(
                error.errors(include_url=False, include_context=False)
            ),
        ) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
