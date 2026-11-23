from pydantic import TypeAdapter
from tatc.schemas import Satellite

from tatc_app.celestrak.catalog import CelestrakCatalog, get_catalog
from tatc_app.satellites import SpaceSystemInput
from tatc_app.system_catalog.systems import list_satellite_systems

from .base import TatcTestCase
from .test_celestrak import FakeDownload, FakeObjectDownload, omm_record

adapter = TypeAdapter(SpaceSystemInput)

# TRMM, which has decayed, so that CelesTrak has no data for it
DECAYED = 25063
START = "2026-11-21T00:00:00Z"
END = "2026-11-22T00:00:00Z"


def catalog_records(exclude=(DECAYED,)) -> list[dict]:
    """
    Creates OMM records for the spacecraft of the system catalog.
    """
    return [
        omm_record(spacecraft.name.upper(), spacecraft.norad_id, "2020-001A")
        for system in list_satellite_systems()
        for spacecraft in system.spacecraft
        if spacecraft.norad_id not in exclude
    ]


class SystemCatalogTestCase(TatcTestCase):
    def setUp(self):
        super().setUp()
        self.download = FakeDownload(catalog_records())
        self.download_object = FakeObjectDownload()
        catalog = CelestrakCatalog(
            download=self.download, download_object=self.download_object
        )
        self.client.app.dependency_overrides[get_catalog] = lambda: catalog

    def build(self, system_id: str, **request) -> dict:
        response = self.client.post(
            f"/catalog/systems/{system_id}/build",
            json={"start": START, "end": END, **request},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_list_systems(self):
        response = self.client.get("/catalog/systems")
        self.assertEqual(response.status_code, 200, response.text)
        systems = {system["id"]: system for system in response.json()}
        self.assertIn("landsat", systems)
        self.assertNotIn("nexrad", systems)  # networks are not satellites
        landsat = systems["landsat"]
        self.assertEqual(landsat["system_class"], "sun_synchronous")
        self.assertEqual(
            [(s["name"], s["norad_id"]) for s in landsat["spacecraft"]],
            [("Landsat 8", 39084), ("Landsat 9", 49260)],
        )
        self.assertEqual(
            landsat["spacecraft"][0]["instruments"], [{"id": "oli", "name": "OLI"}]
        )
        # navigation satellites carry no cataloged instruments
        self.assertEqual(systems["gps"]["spacecraft"][0]["instruments"], [])

    def test_build_with_gp_elements(self):
        result = self.build("landsat")
        self.assertEqual(result["name"], "Landsat")
        self.assertEqual(
            [m["orbit_source"] for m in result["members"]], ["celestrak"] * 2
        )
        self.assertEqual(result["members"][0]["epoch"], "2026-11-20T12:00:00.000000")
        for satellite, norad_id in zip(result["satellites"], [39084, 49260]):
            self.assertEqual(set(satellite["orbit"]), {"type", "tle"})
            system = adapter.validate_python(satellite)
            self.assertEqual(system.orbit.get_catalog_number(), norad_id)
            self.assertEqual([i.name for i in system.instruments], ["OLI"])
        self.assertEqual(self.download.calls, 1)
        self.assertEqual(self.download_object.calls, [])

    def test_build_every_system(self):
        response = self.client.get("/catalog/systems")
        for system in response.json():
            with self.subTest(system=system["id"]):
                members = [s["id"] for s in system["spacecraft"]]
                result = self.build(system["id"], members=members)
                self.assertEqual(len(result["satellites"]), len(members))
                for satellite, spacecraft in zip(
                    result["satellites"], system["spacecraft"]
                ):
                    # satellites round-trip through the schema of analyses
                    built = adapter.validate_python(satellite)
                    self.assertIsInstance(built, Satellite)
                    self.assertEqual(
                        adapter.validate_python(built.model_dump(mode="json")), built
                    )
                    if spacecraft["norad_id"] != DECAYED:
                        self.assertEqual(
                            built.orbit.get_catalog_number(), spacecraft["norad_id"]
                        )
        # only the object missing from the group is queried
        self.assertEqual(self.download_object.calls, [DECAYED])

    def test_build_default_members(self):
        result = self.build("jpss")
        # Suomi NPP is retired
        self.assertEqual([m["id"] for m in result["members"]], ["noaa-20", "noaa-21"])

    def test_build_without_gp_elements(self):
        result = self.build("trmm", members=["trmm"])
        self.assertEqual(result["members"][0]["orbit_source"], "catalog")
        self.assertIsNone(result["members"][0]["epoch"])
        self.assertNotEqual(result["satellites"][0]["orbit"]["type"], "tle")
        adapter.validate_python(result["satellites"][0])
        self.assertTrue(any("cataloged orbit" in w for w in result["warnings"]))
        self.assertEqual(self.download_object.calls, [DECAYED])
        # the absence of data is cached
        self.build("trmm", members=["trmm"])
        self.assertEqual(self.download_object.calls, [DECAYED])

    def test_build_selected_instruments(self):
        result = self.build("pace", instruments=["oci"])
        satellite = adapter.validate_python(result["satellites"][0])
        self.assertEqual([i.name for i in satellite.instruments], ["OCI"])
        # every instrument: those with other attitudes are omitted
        result = self.build("pace")
        satellite = adapter.validate_python(result["satellites"][0])
        self.assertNotIn("OCI", [i.name for i in satellite.instruments])
        self.assertTrue(any("omits OCI" in w for w in result["warnings"]))

    def test_build_without_instruments(self):
        result = self.build("landsat", instruments=False)
        satellite = adapter.validate_python(result["satellites"][0])
        self.assertEqual([i.name for i in satellite.instruments], ["Default"])
        self.assertEqual(result["warnings"], [])

    def test_build_old_elements(self):
        result = self.build("landsat", start="2025-01-01T00:00:00Z", end=None)
        self.assertTrue(any("GP elements of" in w for w in result["warnings"]))

    def test_build_validates(self):
        response = self.client.post(
            "/validate/space-system", json=self.build("goes")["satellites"][0]
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertAlmostEqual(response.json()["members"][0]["inclination"], 51.6)

    def test_build_unknown_system(self):
        response = self.client.post("/catalog/systems/unknown/build", json={})
        self.assertEqual(response.status_code, 404)

    def test_build_network(self):
        response = self.client.post("/catalog/systems/nexrad/build", json={})
        self.assertEqual(response.status_code, 404)

    def test_build_invalid_requests(self):
        for system_id, request in (
            ("landsat", {"members": ["noaa-20"]}),
            ("landsat", {"instruments": ["unknown"]}),
            ("landsat", {"instruments": ["viirs"]}),
            ("landsat", {"start": END, "end": START}),
            ("landsat", {"time_step": 0}),
            ("tropics", {}),  # every spacecraft is retired
        ):
            with self.subTest(system_id=system_id, request=request):
                response = self.client.post(
                    f"/catalog/systems/{system_id}/build", json=request
                )
                self.assertEqual(response.status_code, 422, response.text)

    def test_invalid_user(self):
        self.require_authentication()
        self.assertEqual(self.client.get("/catalog/systems").status_code, 401)
        response = self.client.post("/catalog/systems/landsat/build", json={})
        self.assertEqual(response.status_code, 401)
