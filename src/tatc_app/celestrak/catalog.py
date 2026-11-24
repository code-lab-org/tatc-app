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

Objects are also looked up by catalog number (as for the satellites of the
system catalog). Those in the downloaded group need no further requests; each
other object is queried narrowly (by its catalog number) at most once every two
hours, and its result, including that CelesTrak has no data for it (as for
decayed objects), is cached in memory and on disk, as CelesTrak blocks clients
that repeat requests that fail.

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
from typing import Awaitable, Callable, Iterable

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


async def _get_omm_json(params: dict, timeout: float) -> tuple[int, str]:
    """
    Gets general perturbations data from CelesTrak.

    Args:
        params (dict): the query parameters
        timeout (float): the timeout (seconds)

    Returns:
        tuple[int, str]: the status and text of the response
    """
    async with aiohttp.ClientSession(
        headers={"User-Agent": f"tatc-app/{__version__}"},
        timeout=aiohttp.ClientTimeout(total=timeout),
    ) as session:
        async with session.get(
            CELESTRAK_GP_URL, params={**params, "FORMAT": "JSON"}
        ) as response:
            return response.status, await response.text()


def _parse_omm_json(status: int, text: str) -> list[dict]:
    """
    Parses a response of OMM records from CelesTrak.
    """
    # CelesTrak reports errors (including requests made too soon after a
    # previous download) as plain text
    if status != 200:
        raise RuntimeError(f"CelesTrak responded {status}: {text[:200]}")
    try:
        records = json.loads(text)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"CelesTrak responded: {text[:200]}") from error
    if not isinstance(records, list):
        raise RuntimeError("CelesTrak response is not a list of OMM records.")
    return records


async def download_omm_json(group: str) -> list[dict]:
    """
    Downloads a group of objects from CelesTrak in the OMM JSON format.

    Args:
        group (str): the CelesTrak group (e.g., "active")

    Returns:
        list[dict]: the OMM records
    """
    return _parse_omm_json(*await _get_omm_json({"GROUP": group}, timeout=120))


async def download_omm_object(catalog_number: int) -> dict | None:
    """
    Downloads one object from CelesTrak, by catalog number, in the OMM JSON
    format.

    Args:
        catalog_number (int): the NORAD catalog number

    Returns:
        dict | None: the OMM record, or None if CelesTrak has no data for the
        object (such as a decayed object)
    """
    status, text = await _get_omm_json({"CATNR": catalog_number}, timeout=30)
    # CelesTrak responds 404 ("No GP data found") for an object without data
    if status == 404:
        return None
    records = _parse_omm_json(status, text)
    for record in records:
        if int(record.get("NORAD_CAT_ID", -1)) == catalog_number:
            return record
    return None


# errors of a failed download from CelesTrak
DOWNLOAD_ERRORS = (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError)


def _write_json_atomic(path: Path | None, data, what: str) -> None:
    """
    Writes data to a JSON file (if any), via a temporary file that then
    replaces it, so the file is never left partially written.
    """
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_suffix(".tmp")
        temporary_path.write_text(json.dumps(data), encoding="utf-8")
        os.replace(temporary_path, path)
    except OSError as error:
        logger.warning("Cannot cache %s: %s", what, error)


def _try_convert(record: dict) -> CelestrakObject | None:
    """
    Converts an OMM record to an object, or logs and skips an invalid record.
    """
    try:
        return to_celestrak_object(record)
    except (KeyError, TypeError, ValueError) as error:
        logger.warning("Skipping invalid CelesTrak record: %s", error)
        return None


def _index_records(records: list[dict] | None) -> dict[int, dict]:
    """
    Indexes OMM records by catalog number (skipping invalid records).
    """
    index = {}
    for record in records or []:
        try:
            index[int(record["NORAD_CAT_ID"])] = record
        except (KeyError, TypeError, ValueError):
            continue
    return index


class CelestrakCatalog:  # pylint: disable=too-many-instance-attributes
    """
    Catalog of a CelesTrak group, downloaded at most once every two hours,
    and of other objects, each queried at most once every two hours.
    """

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        group: str = "active",
        cache_dir: str | os.PathLike | None = None,
        refresh_interval: timedelta = MIN_REFRESH_INTERVAL,
        retry_interval: timedelta = RETRY_INTERVAL,
        download: Callable[[str], Awaitable[list[dict]]] = download_omm_json,
        download_object: Callable[[int], Awaitable[dict | None]] = download_omm_object,
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
            download_object (Callable): the function to download an object
                by catalog number (returning None if there is no data)
        """
        self.group = group
        self.cache_path = (
            Path(cache_dir) / f"celestrak-{group}.json" if cache_dir else None
        )
        self.objects_cache_path = (
            Path(cache_dir) / "celestrak-objects.json" if cache_dir else None
        )
        self.refresh_interval = max(refresh_interval, MIN_REFRESH_INTERVAL)
        self.retry_interval = retry_interval
        self._download = download
        self._download_object = download_object
        self._records: list[dict] | None = None
        self._downloaded: datetime | None = None
        self._last_failure: float | None = None
        self._lock = asyncio.Lock()
        # the group's records by catalog number
        self._index: dict[int, dict] = {}
        # objects queried by catalog number: (time queried, record or None)
        self._objects: dict[int, tuple[datetime, dict | None]] | None = None
        self._last_object_failure: float | None = None
        self._objects_lock = asyncio.Lock()

    @property
    def downloaded(self) -> datetime | None:
        """Time the catalog was downloaded from CelesTrak, if any."""
        return self._downloaded

    def _set_records(self, records: list[dict], downloaded: datetime) -> None:
        self._records = records
        self._index = _index_records(records)
        self._downloaded = downloaded

    def _can_retry(self, last_failure: float | None) -> bool:
        """
        Checks whether no download has failed within the retry interval.
        """
        return (
            last_failure is None
            or time.monotonic() - last_failure >= self.retry_interval.total_seconds()
        )

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
            self._set_records(
                cache["records"], datetime.fromisoformat(cache["downloaded"])
            )
        except (OSError, ValueError, KeyError, TypeError) as error:
            logger.warning("Ignoring CelesTrak cache %s: %s", self.cache_path, error)

    def _write_cache(self) -> None:
        _write_json_atomic(
            self.cache_path,
            {"downloaded": self._downloaded.isoformat(), "records": self._records},
            "CelesTrak data",
        )

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
            if not self._is_fresh() and self._can_retry(self._last_failure):
                try:
                    records = await self._download(self.group)
                except DOWNLOAD_ERRORS as error:
                    self._last_failure = time.monotonic()
                    logger.warning("Cannot download CelesTrak data: %s", error)
                else:
                    self._set_records(records, datetime.now(timezone.utc))
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
            if (converted := _try_convert(record)) is not None:
                objects.append(converted)
        return CelestrakSearchResult(
            group=self.group,
            downloaded=self._downloaded,
            total=len(matches),
            objects=objects,
        )

    def _read_objects_cache(self) -> dict[int, tuple[datetime, dict | None]]:
        if self.objects_cache_path is None or not self.objects_cache_path.is_file():
            return {}
        try:
            cache = json.loads(self.objects_cache_path.read_text(encoding="utf-8"))
            return {
                int(number): (datetime.fromisoformat(entry["queried"]), entry["record"])
                for number, entry in cache.items()
            }
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            logger.warning(
                "Ignoring CelesTrak cache %s: %s", self.objects_cache_path, error
            )
            return {}

    def _write_objects_cache(self) -> None:
        _write_json_atomic(
            self.objects_cache_path,
            {
                str(number): {"queried": queried.isoformat(), "record": record}
                for number, (queried, record) in self._objects.items()
            },
            "CelesTrak objects",
        )

    async def _get_object_records(self, numbers: list[int]) -> dict[int, dict | None]:
        """
        Gets the records of objects by catalog number, querying CelesTrak for
        each object (one at a time) only if its cached result is older than the
        refresh interval and no query has failed within the retry interval.
        If a query fails, the stale result (if any) is used.

        Args:
            numbers (list[int]): the catalog numbers

        Returns:
            dict[int, dict | None]: the records (None, if there are none)
        """
        async with self._objects_lock:
            if self._objects is None:
                self._objects = await asyncio.to_thread(self._read_objects_cache)
            records = {}
            changed = False
            for number in numbers:
                cached = self._objects.get(number)
                records[number] = cached[1] if cached else None
                if cached and (
                    datetime.now(timezone.utc) - cached[0] < self.refresh_interval
                ):
                    continue
                if not self._can_retry(self._last_object_failure):
                    continue
                try:
                    record = await self._download_object(number)
                except DOWNLOAD_ERRORS as error:
                    # stop querying (for every object) until the retry interval
                    self._last_object_failure = time.monotonic()
                    logger.warning(
                        "Cannot download CelesTrak object %s: %s", number, error
                    )
                    continue
                self._objects[number] = (datetime.now(timezone.utc), record)
                records[number] = record
                changed = True
            if changed:
                await asyncio.to_thread(self._write_objects_cache)
            return records

    async def get_objects(
        self, catalog_numbers: Iterable[int]
    ) -> dict[int, CelestrakObject | None]:
        """
        Gets objects by catalog number: from the group, if it has them, or
        else by querying CelesTrak narrowly for each other object (at most
        once every two hours, per CelesTrak's usage policy).

        Args:
            catalog_numbers (Iterable[int]): the NORAD catalog numbers

        Returns:
            dict[int, CelestrakObject | None]: the objects, by catalog number
            (None, if CelesTrak has no data for an object or cannot be reached)
        """
        numbers = list(dict.fromkeys(int(number) for number in catalog_numbers))
        try:
            await self.get_records()
        except RuntimeError:
            pass  # no group records: query each object
        records = {number: self._index.get(number) for number in numbers}
        missing = [number for number, record in records.items() if record is None]
        if missing:
            records.update(await self._get_object_records(missing))
        return {
            number: None if record is None else _try_convert(record)
            for number, record in records.items()
        }


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
