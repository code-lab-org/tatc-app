"""
Router specifications for celestrak endpoints.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from .catalog import CelestrakCatalog, CelestrakSearchResult, get_catalog

router = APIRouter()


# exclude unset fields, so orbits only include the fields set from CelesTrak
# (not library defaults, such as the unused epoch of two line elements)
@router.get(
    "/search", response_model=CelestrakSearchResult, response_model_exclude_unset=True
)
async def search_celestrak(
    query: str = Query(
        ...,
        min_length=1,
        description="Name, catalog number, or international designator.",
    ),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of objects."),
    catalog: CelestrakCatalog = Depends(get_catalog),
) -> CelestrakSearchResult:
    """
    Endpoint to search general perturbations (GP) elements from CelesTrak.
    Searches a catalog that the server downloads at most once every two hours
    (per CelesTrak's usage policy) rather than forwarding each query.

    Args:
        query (str): the name, catalog number, or international designator
        limit (int): the maximum number of objects
        catalog (CelestrakCatalog): the catalog

    Returns:
        CelestrakSearchResult: the matching objects
    """
    try:
        return await catalog.search(query, limit)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
