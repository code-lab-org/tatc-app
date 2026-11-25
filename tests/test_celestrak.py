import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from tatc import constants
from tatc.schemas import GeneralPerturbationsOrbit, TwoLineElements

from tatc_app.celestrak.catalog import (
    MIN_REFRESH_INTERVAL,
    CelestrakCatalog,
    download_omm_object,
    get_catalog,
    to_celestrak_object,
)

from .base import TatcTestCase


def omm_record(name: str, catalog_number: int, object_id: str) -> dict:
    """
    Creates an OMM record, as in CelesTrak's JSON format.
    """
    return {
        "OBJECT_NAME": name,
        "OBJECT_ID": object_id,
        "EPOCH": "2026-11-20T12:00:00.000000",
        "MEAN_MOTION": 15.5,
        "ECCENTRICITY": 0.0003,
        "INCLINATION": 51.6,
        "RA_OF_ASC_NODE": 41.5,
        "ARG_OF_PERICENTER": 68.0,
        "MEAN_ANOMALY": 78.3,
        "EPHEMERIS_TYPE": 0,
        "CLASSIFICATION_TYPE": "U",
        "NORAD_CAT_ID": catalog_number,
        "ELEMENT_SET_NO": 999,
        "REV_AT_EPOCH": 100,
        "BSTAR": 0.0001,
        "MEAN_MOTION_DOT": 1e-5,
        "MEAN_MOTION_DDOT": 0,
    }


RECORDS = [
    omm_record("ISS (ZARYA)", 25544, "1998-067A"),
    omm_record("LANDSAT 8", 39084, "2013-008A"),
    omm_record("LANDSAT 9", 49260, "2021-088A"),
    omm_record("ALPHA FIVE SAT", 212345, "2026-001A"),
    omm_record("NINE DIGIT SAT", 812345678, "2026-002A"),
]


class FakeDownload:
    """
    Replaces downloads from CelesTrak, counting calls.
    """

    def __init__(self, records=RECORDS, error: Exception | None = None):
        self.records = records
        self.error = error
        self.calls = 0

    async def __call__(self, group: str) -> list[dict]:
        self.calls += 1
        if self.error:
            raise self.error
        return self.records


class FakeObjectDownload:
    """
    Replaces downloads of objects (by catalog number) from CelesTrak,
    recording the catalog numbers queried.
    """

    def __init__(self, records=(), error: Exception | None = None):
        self.records = {int(r["NORAD_CAT_ID"]): r for r in records}
        self.error = error
        self.calls = []

    async def __call__(self, catalog_number: int) -> dict | None:
        self.calls.append(catalog_number)
        if self.error:
            raise self.error
        return self.records.get(catalog_number)


# an object outside of the group
OTHER = omm_record("OTHER SAT", 43013, "2017-073A")


class CelestrakObjectsTestCase(unittest.TestCase):
    def setUp(self):
        self.cache_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.cache_dir.cleanup()

    def create_catalog(self, download_object, **kwargs):
        return CelestrakCatalog(
            cache_dir=self.cache_dir.name,
            download=FakeDownload(),
            download_object=download_object,
            **kwargs,
        )

    def test_objects_in_group_are_not_queried(self):
        download_object = FakeObjectDownload()
        catalog = self.create_catalog(download_object)
        objects = asyncio.run(catalog.get_objects([25544, 39084, 212345]))
        self.assertEqual(
            [o.name for o in objects.values()],
            ["ISS (ZARYA)", "LANDSAT 8", "ALPHA FIVE SAT"],
        )
        self.assertEqual(download_object.calls, [])

    def test_other_objects_are_queried_once(self):
        download_object = FakeObjectDownload([OTHER])
        catalog = self.create_catalog(download_object)
        for _ in range(3):
            objects = asyncio.run(catalog.get_objects([25544, 43013, 25063]))
            self.assertEqual(objects[43013].name, "OTHER SAT")
            self.assertEqual(objects[43013].orbit.get_catalog_number(), 43013)
            # CelesTrak has no data for the object
            self.assertIsNone(objects[25063])
        self.assertEqual(download_object.calls, [43013, 25063])

    def test_other_objects_are_queried_after_refresh_interval(self):
        download_object = FakeObjectDownload([OTHER])
        catalog = self.create_catalog(download_object)
        asyncio.run(catalog.get_objects([43013, 25063]))
        catalog._objects = {
            number: (queried - MIN_REFRESH_INTERVAL - timedelta(seconds=1), record)
            for number, (queried, record) in catalog._objects.items()
        }
        asyncio.run(catalog.get_objects([43013, 25063]))
        self.assertEqual(download_object.calls, [43013, 25063, 43013, 25063])

    def test_reuses_objects_cache_on_disk(self):
        asyncio.run(
            self.create_catalog(FakeObjectDownload([OTHER])).get_objects([43013, 25063])
        )
        download_object = FakeObjectDownload([OTHER])
        catalog = self.create_catalog(download_object)
        objects = asyncio.run(catalog.get_objects([43013, 25063]))
        self.assertEqual(objects[43013].name, "OTHER SAT")
        self.assertIsNone(objects[25063])
        self.assertEqual(download_object.calls, [])

    def test_failed_query_stops_queries_until_retry_interval(self):
        download_object = FakeObjectDownload(error=RuntimeError("CelesTrak 403"))
        catalog = self.create_catalog(download_object)
        objects = asyncio.run(catalog.get_objects([43013, 25063]))
        self.assertEqual(objects, {43013: None, 25063: None})
        asyncio.run(catalog.get_objects([43013, 25063]))
        self.assertEqual(download_object.calls, [43013])

    def test_failed_query_uses_stale_record(self):
        catalog = self.create_catalog(FakeObjectDownload([OTHER]))
        asyncio.run(catalog.get_objects([43013]))
        catalog._objects[43013] = (
            catalog._objects[43013][0] - MIN_REFRESH_INTERVAL - timedelta(seconds=1),
            catalog._objects[43013][1],
        )
        catalog._download_object = FakeObjectDownload(error=RuntimeError("down"))
        objects = asyncio.run(catalog.get_objects([43013]))
        self.assertEqual(objects[43013].name, "OTHER SAT")

    def test_objects_without_group(self):
        download_object = FakeObjectDownload([OTHER])
        catalog = CelestrakCatalog(
            download=FakeDownload(error=RuntimeError("down")),
            download_object=download_object,
        )
        objects = asyncio.run(catalog.get_objects([43013]))
        self.assertEqual(objects[43013].name, "OTHER SAT")

    def test_download_object(self):
        response = json.dumps([OTHER])
        with mock.patch(
            "tatc_app.celestrak.catalog._get_omm_json",
            mock.AsyncMock(return_value=(200, response)),
        ) as get:
            self.assertEqual(asyncio.run(download_omm_object(43013)), OTHER)
        get.assert_awaited_once_with({"CATNR": 43013}, timeout=30)

    def test_download_object_without_data(self):
        with mock.patch(
            "tatc_app.celestrak.catalog._get_omm_json",
            mock.AsyncMock(return_value=(404, "No GP data found")),
        ):
            self.assertIsNone(asyncio.run(download_omm_object(25063)))

    def test_download_object_error(self):
        with mock.patch(
            "tatc_app.celestrak.catalog._get_omm_json",
            mock.AsyncMock(return_value=(403, "Forbidden")),
        ):
            with self.assertRaises(RuntimeError):
                asyncio.run(download_omm_object(43013))


class CelestrakCatalogTestCase(unittest.TestCase):
    def setUp(self):
        self.cache_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.cache_dir.cleanup()

    def test_downloads_at_most_once_per_refresh_interval(self):
        download = FakeDownload()
        catalog = CelestrakCatalog(cache_dir=self.cache_dir.name, download=download)

        async def search():
            for query in ["LAN", "LANDSAT", "ZARYA", "25544", "1998-067"]:
                await catalog.search(query)
            # concurrent searches share one download
            await asyncio.gather(*[catalog.search("ISS") for _ in range(5)])

        asyncio.run(search())
        self.assertEqual(download.calls, 1)

    def test_refreshes_after_refresh_interval(self):
        download = FakeDownload()
        catalog = CelestrakCatalog(cache_dir=self.cache_dir.name, download=download)
        asyncio.run(catalog.get_records())
        catalog._downloaded -= MIN_REFRESH_INTERVAL + timedelta(seconds=1)
        asyncio.run(catalog.get_records())
        self.assertEqual(download.calls, 2)

    def test_refresh_interval_is_at_least_two_hours(self):
        catalog = CelestrakCatalog(refresh_interval=timedelta(minutes=1))
        self.assertEqual(catalog.refresh_interval, timedelta(hours=2))

    def test_reuses_cache_on_disk(self):
        asyncio.run(
            CelestrakCatalog(
                cache_dir=self.cache_dir.name, download=FakeDownload()
            ).get_records()
        )
        download = FakeDownload()
        catalog = CelestrakCatalog(cache_dir=self.cache_dir.name, download=download)
        self.assertEqual(len(asyncio.run(catalog.get_records())), len(RECORDS))
        self.assertEqual(download.calls, 0)

    def test_refreshes_stale_cache_on_disk(self):
        with open(f"{self.cache_dir.name}/celestrak-active.json", "w") as file:
            json.dump(
                {
                    "downloaded": (
                        datetime.now(timezone.utc) - timedelta(hours=3)
                    ).isoformat(),
                    "records": RECORDS[:1],
                },
                file,
            )
        download = FakeDownload()
        catalog = CelestrakCatalog(cache_dir=self.cache_dir.name, download=download)
        self.assertEqual(len(asyncio.run(catalog.get_records())), len(RECORDS))
        self.assertEqual(download.calls, 1)

    def test_failed_download_uses_stale_records_and_waits_to_retry(self):
        catalog = CelestrakCatalog(download=FakeDownload())
        asyncio.run(catalog.get_records())
        catalog._downloaded -= MIN_REFRESH_INTERVAL + timedelta(seconds=1)
        download = FakeDownload(error=RuntimeError("CelesTrak responded 403"))
        catalog._download = download
        self.assertEqual(len(asyncio.run(catalog.get_records())), len(RECORDS))
        self.assertEqual(len(asyncio.run(catalog.get_records())), len(RECORDS))
        self.assertEqual(download.calls, 1)

    def test_failed_download_without_records(self):
        catalog = CelestrakCatalog(download=FakeDownload(error=RuntimeError("down")))
        with self.assertRaises(RuntimeError):
            asyncio.run(catalog.get_records())

    def test_search(self):
        catalog = CelestrakCatalog(download=FakeDownload())
        result = asyncio.run(catalog.search("landsat"))
        self.assertEqual(result.total, 2)
        self.assertEqual([o.name for o in result.objects], ["LANDSAT 8", "LANDSAT 9"])
        result = asyncio.run(catalog.search("landsat", limit=1))
        self.assertEqual(result.total, 2)
        self.assertEqual(len(result.objects), 1)
        result = asyncio.run(catalog.search("812345678"))
        self.assertEqual([o.name for o in result.objects], ["NINE DIGIT SAT"])
        result = asyncio.run(catalog.search("2013-008"))
        self.assertEqual([o.name for o in result.objects], ["LANDSAT 8"])
        self.assertEqual(asyncio.run(catalog.search("doesnotexist")).total, 0)

    def test_five_digit_catalog_number(self):
        celestrak_object = to_celestrak_object(RECORDS[0])
        self.assertEqual(celestrak_object.orbit.type, "tle")
        self.assertEqual(celestrak_object.orbit.get_catalog_number(), 25544)

    def test_gp_orbit(self):
        for record in RECORDS:
            celestrak_object = to_celestrak_object(record)
            orbit = celestrak_object.gp_orbit
            self.assertEqual(orbit.type, "gp")
            self.assertEqual(orbit.elements[0].object_name, record["OBJECT_NAME"])
            self.assertAlmostEqual(orbit.get_inclination(), 51.6)
            self.assertAlmostEqual(
                orbit.get_mean_motion(), celestrak_object.orbit.get_mean_motion()
            )
            # catalog numbers beyond the Alpha-5 range are replaced by 0
            self.assertEqual(
                orbit.get_catalog_number(),
                record["NORAD_CAT_ID"] if record["NORAD_CAT_ID"] <= 339999 else 0,
            )

    def test_alpha5_catalog_number(self):
        celestrak_object = to_celestrak_object(RECORDS[3])
        self.assertEqual(celestrak_object.norad_cat_id, 212345)
        self.assertEqual(celestrak_object.orbit.type, "tle")
        self.assertEqual(celestrak_object.orbit.tle[0][2:7], "M2345")
        orbit = TwoLineElements.model_validate(celestrak_object.orbit.model_dump())
        self.assertEqual(orbit.get_catalog_number(), 212345)

    def test_nine_digit_catalog_number(self):
        celestrak_object = to_celestrak_object(RECORDS[4])
        self.assertEqual(celestrak_object.norad_cat_id, 812345678)
        self.assertEqual(celestrak_object.orbit.type, "gp")
        self.assertAlmostEqual(celestrak_object.orbit.get_inclination(), 51.6)
        # the elements can be propagated
        satellite = celestrak_object.orbit.elements[0].to_skyfield()
        time = constants.timescale.from_datetime(
            datetime(2026, 11, 21, tzinfo=timezone.utc)
        )
        self.assertGreater(sum(x**2 for x in satellite.at(time).position.km), 0)


class CelestrakRouterTestCase(TatcTestCase):
    def setUp(self):
        super().setUp()
        self.download = FakeDownload()
        catalog = CelestrakCatalog(download=self.download)
        self.client.app.dependency_overrides[get_catalog] = lambda: catalog

    def test_search_valid_user(self):
        response = self.client.get("/celestrak/search?query=zarya")
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result["total"], 1)
        self.assertIsNotNone(result["downloaded"])
        self.assertEqual(set(result["objects"][0]["orbit"].keys()), {"type", "tle"})
        orbit = TwoLineElements.model_validate(result["objects"][0]["orbit"])
        self.assertEqual(orbit.get_catalog_number(), 25544)
        gp_orbit = result["objects"][0]["gp_orbit"]
        self.assertEqual(gp_orbit["type"], "gp")
        gp_orbit = GeneralPerturbationsOrbit.model_validate(gp_orbit)
        self.assertEqual(gp_orbit.get_catalog_number(), 25544)

    def test_search_nine_digit_catalog_number(self):
        response = self.client.get("/celestrak/search?query=nine digit")
        self.assertEqual(response.status_code, 200, response.text)
        celestrak_object = response.json()["objects"][0]
        self.assertEqual(celestrak_object["norad_cat_id"], 812345678)
        self.assertEqual(celestrak_object["orbit"]["type"], "gp")
        orbit = GeneralPerturbationsOrbit.model_validate(celestrak_object["orbit"])
        self.assertEqual(orbit.elements[0].object_name, "NINE DIGIT SAT")
        self.assertAlmostEqual(orbit.get_inclination(), 51.6)

    def test_search_empty_response(self):
        response = self.client.get("/celestrak/search?query=doesnotexist")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["objects"], [])

    def test_search_downloads_once(self):
        for query in ["iss", "zarya", "landsat"]:
            self.client.get("/celestrak/search", params={"query": query})
        self.assertEqual(self.download.calls, 1)

    def test_search_unavailable(self):
        catalog = CelestrakCatalog(download=FakeDownload(error=RuntimeError("down")))
        self.client.app.dependency_overrides[get_catalog] = lambda: catalog
        response = self.client.get("/celestrak/search?query=zarya")
        self.assertEqual(response.status_code, 503)

    def test_search_invalid_user(self):
        self.require_authentication()
        response = self.client.get("/celestrak/search?query=zarya")
        self.assertEqual(response.status_code, 401)
