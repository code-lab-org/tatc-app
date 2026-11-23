"""
Cached catalog of general perturbations (GP) elements from CelesTrak.

CelesTrak updates its GP data once every two hours and asks clients not to
download the same data more often (see
https://celestrak.org/NORAD/documentation/gp-data-formats.php). Rather than
forwarding each user query to CelesTrak, the server downloads one group of
objects (by default, active satellites) in the orbit mean-elements message
(OMM) JSON format at most once every two hours, keeps it in memory and on disk
(so restarting the server does not download it again), and searches it
locally.

Unlike two line elements (TLE), the OMM format is not limited to 5-character
catalog numbers. Objects with catalog numbers up to 339999 are converted to
TLE (using the Alpha-5 encoding above 99999); objects with larger catalog
numbers are converted to GP orbits.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

from __future__ import annotations

import asyncio
import functools
import json
import logging
import os
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Awaitable, Callable

import aiohttp
from pydantic import AwareDatetime, BaseModel, Field
from tatc.schemas import GeneralPerturbationsOrbit, TwoLineElements
from tatc.schemas.orbit.gp_elements import GeneralPerturbationsElements

from tatc_app import __version__

logger = logging.getLogger(__name__)

CELESTRAK_GP_URL = "https://celestrak.org/NORAD/elements/gp.php"
"""CelesTrak endpoint for general perturbations (GP) data."""

MIN_REFRESH_INTERVAL = timedelta(hours=2)
"""Minimum interval between downloads, per CelesTrak's usage policy."""

RETRY_INTERVAL = timedelta(minutes=15)
"""Minimum interval between attempts after a failed download."""

MAX_ALPHA5_CATALOG_NUMBER = 339999
"""Largest catalog number that TLE (with the Alpha-5 encoding) can represent."""


class CelestrakObject(BaseModel):
    """An object found in the CelesTrak catalog."""

    name: str = Field(..., description="Object name.")
    norad_cat_id: int = Field(..., description="NORAD catalog number.")
    object_id: str | None = Field(None, description="International designator.")
    epoch: str = Field(..., description="Epoch (UTC) of the elements.")
    orbit: TwoLineElements | GeneralPerturbationsOrbit = Field(
        ...,
        description="Orbit: two line elements for catalog numbers up to "
        + f"{MAX_ALPHA5_CATALOG_NUMBER}, otherwise general perturbations.",
    )


class CelestrakSearchResult(BaseModel):
    """Result of a search of the CelesTrak catalog."""

    group: str = Field(..., description="CelesTrak group searched.")
    downloaded: AwareDatetime | None = Field(
        None, description="Time the catalog was downloaded from CelesTrak."
    )
    total: int = Field(..., description="Number of matching objects.")
    objects: list[CelestrakObject] = Field(
        ..., description="Matching objects (up to the requested limit)."
    )


def to_celestrak_object(record: dict) -> CelestrakObject:
    """
    Converts a CelesTrak OMM record to an object with a TAT-C orbit.

    Args:
        record (dict): the OMM record

    Returns:
        CelestrakObject: the object
    """
    catalog_number = int(record["NORAD_CAT_ID"])
    if catalog_number <= MAX_ALPHA5_CATALOG_NUMBER:
        elements = GeneralPerturbationsElements.from_omm_dict(record)
        orbit = TwoLineElements(type="tle", tle=elements.to_tle())
    else:
        # SGP4 (and hence TAT-C) cannot initialize a satellite with a catalog
        # number beyond the Alpha-5 range; since the catalog number does not
        # affect propagation, the elements use catalog number 0 instead.
        elements = GeneralPerturbationsElements.from_omm_dict(
            dict(record, NORAD_CAT_ID=0)
        )
        orbit = GeneralPerturbationsOrbit(type="gp", elements=[elements])
    return CelestrakObject(
        name=str(record.get("OBJECT_NAME") or catalog_number).strip(),
        norad_cat_id=catalog_number,
        object_id=record.get("OBJECT_ID"),
        epoch=record["EPOCH"],
        orbit=orbit,
    )


def _match_rank(record: dict, query: str) -> int | None:
    """
    Ranks how well a record matches a query (lower is better).

    Args:
        record (dict): the OMM record
        query (str): the query (upper case)

    Returns:
        int | None: the rank, or None if the record does not match
    """
    name = str(record.get("OBJECT_NAME") or "").upper()
    if query.isdigit() and int(query) == int(record.get("NORAD_CAT_ID", -1)):
        return 0
    if name == query:
        return 1
    if name.startswith(query):
        return 2
    if query in name:
        return 3
    if str(record.get("OBJECT_ID") or "").upper().startswith(query):
        return 4
    return None


async def download_omm_json(group: str) -> list[dict]:
    """
    Downloads a group of objects from CelesTrak in the OMM JSON format.

    Args:
        group (str): the CelesTrak group (e.g., "active")

    Returns:
        list[dict]: the OMM records
    """
    async with aiohttp.ClientSession(
        headers={"User-Agent": f"tatc-app/{__version__}"},
        timeout=aiohttp.ClientTimeout(total=120),
    ) as session:
        async with session.get(
            CELESTRAK_GP_URL, params={"GROUP": group, "FORMAT": "JSON"}
        ) as response:
            # CelesTrak reports errors (including requests made too soon
            # after a previous download) as plain text
            text = await response.text()
            if response.status != 200:
                raise RuntimeError(
                    f"CelesTrak responded {response.status}: {text[:200]}"
                )
    try:
        records = json.loads(text)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"CelesTrak responded: {text[:200]}") from error
    if not isinstance(records, list):
        raise RuntimeError("CelesTrak response is not a list of OMM records.")
    return records


class CelestrakCatalog:  # pylint: disable=too-many-instance-attributes
    """
    Catalog of a CelesTrak group, downloaded at most once every two hours.
    """

    def __init__(
        self,
        group: str = "active",
        cache_dir: str | os.PathLike | None = None,
        refresh_interval: timedelta = MIN_REFRESH_INTERVAL,
        retry_interval: timedelta = RETRY_INTERVAL,
        download: Callable[[str], Awaitable[list[dict]]] = download_omm_json,
    ):
        """
        Initializes a catalog.

        Args:
            group (str): the CelesTrak group
            cache_dir (str | os.PathLike | None): the directory in which the
                catalog is cached (None, for no cache on disk)
            refresh_interval (timedelta): the interval between downloads
                (no less than two hours)
            retry_interval (timedelta): the interval between attempts after
                a failed download
            download (Callable): the function to download a group
        """
        self.group = group
        self.cache_path = (
            Path(cache_dir) / f"celestrak-{group}.json" if cache_dir else None
        )
        self.refresh_interval = max(refresh_interval, MIN_REFRESH_INTERVAL)
        self.retry_interval = retry_interval
        self._download = download
        self._records: list[dict] | None = None
        self._downloaded: datetime | None = None
        self._last_failure: float | None = None
        self._lock = asyncio.Lock()

    @property
    def downloaded(self) -> datetime | None:
        """Time the catalog was downloaded from CelesTrak, if any."""
        return self._downloaded

    def _is_fresh(self) -> bool:
        return (
            self._downloaded is not None
            and datetime.now(timezone.utc) - self._downloaded < self.refresh_interval
        )

    def _read_cache(self) -> None:
        if self.cache_path is None or not self.cache_path.is_file():
            return
        try:
            cache = json.loads(self.cache_path.read_text(encoding="utf-8"))
            self._records = cache["records"]
            self._downloaded = datetime.fromisoformat(cache["downloaded"])
        except (OSError, ValueError, KeyError, TypeError) as error:
            logger.warning("Ignoring CelesTrak cache %s: %s", self.cache_path, error)

    def _write_cache(self) -> None:
        if self.cache_path is None:
            return
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            # write to a temporary file, then replace, so the cache is
            # never left partially written
            temporary_path = self.cache_path.with_suffix(".tmp")
            temporary_path.write_text(
                json.dumps(
                    {
                        "downloaded": self._downloaded.isoformat(),
                        "records": self._records,
                    }
                ),
                encoding="utf-8",
            )
            os.replace(temporary_path, self.cache_path)
        except OSError as error:
            logger.warning("Cannot cache CelesTrak data: %s", error)

    async def get_records(self) -> list[dict]:
        """
        Gets the catalog records, downloading them from CelesTrak only if
        the cached records are older than the refresh interval (and no
        download has failed within the retry interval). If a download fails,
        the stale records are used.

        Returns:
            list[dict]: the OMM records

        Raises:
            RuntimeError: if no records have been downloaded
        """
        async with self._lock:
            if self._records is None:
                await asyncio.to_thread(self._read_cache)
            if not self._is_fresh() and (
                self._last_failure is None
                or time.monotonic() - self._last_failure
                >= self.retry_interval.total_seconds()
            ):
                try:
                    records = await self._download(self.group)
                except (
                    aiohttp.ClientError,
                    asyncio.TimeoutError,
                    RuntimeError,
                ) as error:
                    self._last_failure = time.monotonic()
                    logger.warning("Cannot download CelesTrak data: %s", error)
                else:
                    self._records = records
                    self._downloaded = datetime.now(timezone.utc)
                    self._last_failure = None
                    await asyncio.to_thread(self._write_cache)
            if self._records is None:
                raise RuntimeError("CelesTrak data is not available.")
            return self._records

    async def search(self, query: str, limit: int = 100) -> CelestrakSearchResult:
        """
        Searches the catalog by name, catalog number, or international
        designator.

        Args:
            query (str): the query
            limit (int): the maximum number of objects to return

        Returns:
            CelestrakSearchResult: the search result
        """
        records = await self.get_records()
        query = query.strip().upper()
        matches = []
        for record in records:
            rank = _match_rank(record, query) if query else None
            if rank is not None:
                matches.append((rank, str(record.get("OBJECT_NAME") or ""), record))
        matches.sort(key=lambda match: match[:2])
        objects = []
        for _, _, record in matches:
            if len(objects) >= limit:
                break
            try:
                objects.append(to_celestrak_object(record))
            except (KeyError, TypeError, ValueError) as error:
                logger.warning("Skipping invalid CelesTrak record: %s", error)
        return CelestrakSearchResult(
            group=self.group,
            downloaded=self._downloaded,
            total=len(matches),
            objects=objects,
        )


@functools.cache
def get_catalog() -> CelestrakCatalog:
    """
    Gets the server's catalog, configured (on first use, after environment
    variables are loaded) by the `TATC_CELESTRAK_GROUP` (default: active) and
    `TATC_CELESTRAK_CACHE_DIR` (default: a `tatc-app` directory in the
    system's temporary directory) environment variables.

    Returns:
        CelestrakCatalog: the catalog
    """
    return CelestrakCatalog(
        group=os.getenv("TATC_CELESTRAK_GROUP", "active"),
        cache_dir=os.getenv(
            "TATC_CELESTRAK_CACHE_DIR",
            os.path.join(tempfile.gettempdir(), "tatc-app"),
        ),
    )
