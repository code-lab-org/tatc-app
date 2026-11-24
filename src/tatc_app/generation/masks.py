"""
Masks to limit the extent of generated points and cells: a GeoJSON polygon,
a known shape, or a country.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import io
from enum import Enum
from functools import lru_cache
from importlib import resources
from typing import FrozenSet, Optional, Union

import geopandas as gpd
from shapely.geometry import MultiPolygon, Polygon, shape


class KnownShape(str, Enum):
    """
    Known shapes to use as masks.
    """

    conus = "conus"


@lru_cache(maxsize=None)
def _load_resource(filename: str) -> gpd.GeoDataFrame:
    """
    Loads a zipped shapefile bundled in the `tatc_app` package's `resources`
    directory (declared as package data in `pyproject.toml`), independent of
    the process's current working directory. Cached since parsing a bundled
    shapefile takes tens of milliseconds and its contents never change
    within a process's lifetime.
    """
    data = (resources.files("tatc_app") / "resources" / filename).read_bytes()
    return gpd.read_file(io.BytesIO(data))


def _load_countries() -> gpd.GeoDataFrame:
    """
    Loads the countries (Natural Earth 110m admin-0 countries), bundled with
    the application since `geopandas.datasets` was removed in geopandas 1.0.
    """
    return _load_resource("ne_110m_admin_0_countries.zip")


@lru_cache(maxsize=None)
def country_codes() -> FrozenSet[str]:
    """
    Gets the ISO 3166-1 alpha-3 codes of the countries available as masks.
    """
    # `ISO_A3_EH` (rather than `ISO_A3`) is used because several countries
    # (e.g. France, Norway) have a placeholder `-99` in `ISO_A3` due to a
    # long-standing Natural Earth data issue.
    return frozenset(_load_countries().ISO_A3_EH) - {"-99"}


def load_country_mask(iso_3166_1_alpha3: str) -> Union[Polygon, MultiPolygon]:
    """
    Loads a country geometry from its ISO 3166-1 alpha-3 code.

    Args:
        iso_3166_1_alpha3 (str): The ISO 3166-1 alpha-3 country code
            (case insensitive).

    Raises:
        ValueError: If no country has the code.

    Returns:
        Union[Polygon, MultiPolygon]: The country's border geometry.
    """
    code = iso_3166_1_alpha3.upper()
    if code not in country_codes():
        raise ValueError(f"Unknown country code: {iso_3166_1_alpha3}")
    world = _load_countries()
    return world[world.ISO_A3_EH == code].to_crs("EPSG:4326").geometry.union_all()


def load_known_shape(known_shape: KnownShape) -> Union[Polygon, MultiPolygon]:
    """
    Loads a known shape.

    Args:
        known_shape (KnownShape): A known shape.

    Returns:
        Union[Polygon, MultiPolygon]: The known shape's geometry.
    """
    if known_shape == KnownShape.conus:
        usa = _load_resource("cb_2020_us_state_20m.zip")
        return (
            usa[~usa.STUSPS.isin(["AK", "HI", "PR"])]
            .to_crs("EPSG:4326")
            .geometry.union_all()
        )
    raise ValueError(f"Unknown shape: {known_shape}")


def resolve_mask(
    mask: Optional[Union[dict, str]],
) -> Optional[Union[Polygon, MultiPolygon]]:
    """
    Resolves a mask specification to a geometry.

    Args:
        mask (Optional[Union[dict, str]]): A GeoJSON geometry, a known shape
            name (see `KnownShape`), an ISO 3166-1 alpha-3 country code, or
            `None`.

    Raises:
        ValueError: If the mask is an unknown name.

    Returns:
        Optional[Union[Polygon, MultiPolygon]]: The mask.
    """
    if isinstance(mask, str):
        if mask in KnownShape.__members__:
            return load_known_shape(KnownShape(mask))
        return load_country_mask(mask)
    return shape(mask) if mask is not None else None
