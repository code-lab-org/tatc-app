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

    def test_build_relay_satellites(self):
        tdrs = next(s for s in list_satellite_systems() if s.id == "tdrs")
        self.assertEqual(tdrs.role, "relaying")
        statuses = {s.id: s.status for s in tdrs.spacecraft}
        self.assertIn("storage", statuses.values())
        result = self.build("tdrs")
        # spares in storage are not built by default, as retired spacecraft
        self.assertEqual(
            [m["id"] for m in result["members"]],
            [
                i
                for i, status in statuses.items()
                if status not in ("retired", "storage")
            ],
        )
        # relay satellites carry no cataloged instruments, without a warning
        satellite = adapter.validate_python(result["satellites"][0])
        self.assertEqual([i.name for i in satellite.instruments], ["Default"])
        self.assertFalse(any("cataloged instrument" in w for w in result["warnings"]))

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


ORBIT = {
    "type": "circular",
    "epoch": START,
    "mean_altitude": 500e3,
    "inclination": 51.6,
}
# a satellite as the design creates it, with a default instrument
SATELLITE = {
    "type": "satellite",
    "name": "New Satellite",
    "orbit": ORBIT,
    "instruments": [{"type": "instrument", "name": "Default", "field_of_regard": 180}],
}


class InstrumentCatalogTestCase(TatcTestCase):
    def add(self, entry_id: str, system: dict = SATELLITE, **request) -> dict:
        response = self.client.post(
            f"/catalog/instruments/{entry_id}/add",
            json={"system": system, "start": START, "end": END, **request},
        )
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        # the result is valid for analyses
        adapter.validate_python(result["system"])
        return result

    def test_list_instruments(self):
        response = self.client.get("/catalog/instruments")
        self.assertEqual(response.status_code, 200, response.text)
        entries = {entry["id"]: entry for entry in response.json()}
        modis = entries["modis"]
        self.assertEqual(modis["platforms"], ["Terra", "Aqua"])
        self.assertEqual(modis["default_configuration"], "swath")
        swath = next(c for c in modis["configurations"] if c["id"] == "swath")
        self.assertEqual((swath["grade"], swath["instruments"]), ("timing", 1))
        self.assertTrue(entries["oci"]["configurations"][0]["tilt_schedule"])
        # sounders are analyzed with other methods
        for sounder in ("mls", "saber", "gras", "tgrs"):
            self.assertNotIn(sounder, entries)

    def test_add_every_configuration(self):
        entries = self.client.get("/catalog/instruments").json()
        for entry in entries:
            for configuration in entry["configurations"]:
                with self.subTest(entry=entry["id"], configuration=configuration["id"]):
                    result = self.add(
                        entry["id"], configuration=configuration["id"], replace=True
                    )
                    self.assertEqual(result["configuration"], configuration["id"])
                    self.assertEqual(
                        len(result["system"]["instruments"]),
                        configuration["instruments"],
                    )

    def test_replace(self):
        result = self.add("modis", replace=True)
        self.assertEqual(result["added"], ["MODIS"])
        self.assertEqual(
            [i["name"] for i in result["system"]["instruments"]], ["MODIS"]
        )
        self.assertEqual(result["system"]["attitude"]["velocity_frame"], "inertial")
        self.assertFalse(result["attitude_changed"])
        # other fields are kept as given
        self.assertEqual(result["system"]["orbit"], ORBIT)

    def test_add_to_instruments(self):
        result = self.add("modis")
        self.assertEqual(
            [i["name"] for i in result["system"]["instruments"]], ["Default", "MODIS"]
        )
        self.assertTrue(result["attitude_changed"])
        self.assertTrue(any("attitude is now" in n for n in result["notes"]))
        # the same attitude: names are unique, and the attitude is unchanged
        again = self.add("modis", system=result["system"])
        self.assertEqual(again["added"], ["MODIS (2)"])
        self.assertFalse(again["attitude_changed"])
        # an Earth-fixed body without other fields has no attitude
        other = self.add("oli", system=result["system"])
        self.assertTrue(other["attitude_changed"])
        self.assertNotIn("attitude", other["system"])

    def test_velocity_frames_removed(self):
        pointed = {
            "type": "pointed",
            "name": "Camera",
            "cross_track_field_of_view": 10,
            "along_track_field_of_view": 1,
            "velocity_frame": "inertial",
        }
        result = self.add("modis", system={**SATELLITE, "instruments": [pointed]})
        self.assertNotIn("velocity_frame", result["system"]["instruments"][0])
        self.assertTrue(any("velocity frames" in n for n in result["notes"]))

    def test_tilt_schedule(self):
        result = self.add("oci", replace=True)
        satellite = adapter.validate_python(result["system"])
        self.assertEqual(satellite.attitude.type, "schedule")
        self.assertTrue(any("scheduled by day" in n for n in result["notes"]))

    def test_groupings(self):
        walker = {
            "type": "walker",
            "name": "W",
            "orbit": ORBIT,
            "number_satellites": 4,
            "number_planes": 2,
        }
        result = self.add("ascat", system=walker, replace=True)
        self.assertEqual(len(result["system"]["instruments"]), 2)
        self.assertTrue(any("parts of one view" in n for n in result["notes"]))
        result = self.add("gedi")
        self.assertTrue(
            any(
                "instruments 1 to 8 are alternative views" in n for n in result["notes"]
            )
        )

    def test_add_tailored_to_orbit(self):
        low = self.add("modis", replace=True)["system"]["instruments"][0]
        high = self.add(
            "modis",
            system={**SATELLITE, "orbit": {**ORBIT, "mean_altitude": 800e3}},
            replace=True,
        )["system"]["instruments"][0]
        # the along-track field of view tiles the ground track in one time step
        self.assertNotAlmostEqual(
            low["along_track_field_of_view"], high["along_track_field_of_view"]
        )
        coarse = self.add("modis", replace=True, time_step=120)["system"]
        self.assertGreater(
            coarse["instruments"][0]["along_track_field_of_view"],
            low["along_track_field_of_view"],
        )

    def test_add_validates(self):
        response = self.client.post(
            "/validate/space-system", json=self.add("viirs")["system"]
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json()["members"][0]["instruments"], ["Default", "VIIRS"]
        )

    def test_add_unknown_instrument(self):
        for entry_id in ("unknown", "mls"):
            with self.subTest(entry_id=entry_id):
                response = self.client.post(
                    f"/catalog/instruments/{entry_id}/add", json={"system": SATELLITE}
                )
                self.assertEqual(response.status_code, 404)

    def test_add_invalid_requests(self):
        equatorial = {**SATELLITE, "orbit": {**ORBIT, "inclination": 0}}
        for entry_id, request in (
            ("modis", {"system": SATELLITE, "configuration": "unknown"}),
            ("modis", {"system": {**SATELLITE, "orbit": {"type": "unknown"}}}),
            ("modis", {"system": SATELLITE, "time_step": 0}),
            ("modis", {}),
            # its tilt switches at latitudes the orbit does not reach
            ("oci", {"system": equatorial}),
        ):
            with self.subTest(entry_id=entry_id, request=request):
                response = self.client.post(
                    f"/catalog/instruments/{entry_id}/add", json=request
                )
                self.assertEqual(response.status_code, 422, response.text)

    def test_invalid_user_instruments(self):
        self.require_authentication()
        self.assertEqual(self.client.get("/catalog/instruments").status_code, 401)
        response = self.client.post(
            "/catalog/instruments/modis/add", json={"system": SATELLITE}
        )
        self.assertEqual(response.status_code, 401)
