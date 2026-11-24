import unittest

from pydantic import TypeAdapter, ValidationError
from tatc.schemas import (
    GeneralPerturbationsOrbit,
    MOGConstellation,
    Satellite,
    SOCConstellation,
    TrainConstellation,
    WalkerConstellation,
)

from tatc_app.satellites import SpaceSystemInput, expand_members, generate_members

from .base import TatcTestCase

TLE = [
    "1 25544U 98067A   21156.30527927  .00003432  00000-0  70541-4 0  9993",
    "2 25544  51.6455  41.4969 0003508  68.0432  78.3395 15.48957534286754",
]
EPOCH = "2022-01-01T00:00:00Z"

ORBITS = {
    "tle": {"type": "tle", "tle": TLE},
    "circular": {
        "type": "circular",
        "altitude": 500e3,
        "inclination": 45,
        "epoch": EPOCH,
    },
    "sso": {
        "type": "sso",
        "altitude": 705e3,
        "equator_crossing_time": "10:30",
        "equator_crossing_ascending": False,
        "epoch": EPOCH,
    },
    "keplerian": {
        "type": "keplerian",
        "semimajor_axis": 7000e3,
        "eccentricity": 0.01,
        "inclination": 60,
        "epoch": EPOCH,
    },
    "geosynchronous": {"type": "geosynchronous", "longitude": -75, "epoch": EPOCH},
    "molniya": {"type": "molniya", "perigee_altitude": 600e3, "epoch": EPOCH},
    "tundra": {"type": "tundra", "perigee_altitude": 25000e3, "epoch": EPOCH},
    "repeat": {
        "type": "repeat",
        "revolutions": 233,
        "days": 16,
        "ascending_node": {"time": EPOCH, "longitude": 0},
    },
    "gp": GeneralPerturbationsOrbit.from_tle(TLE).model_dump(mode="json"),
}

INSTRUMENTS = [
    {"type": "instrument", "name": "Simple", "field_of_regard": 100},
    {
        "type": "pointed",
        "name": "Pointed",
        "cross_track_field_of_view": 30,
        "along_track_field_of_view": 2,
        "roll_angle": 5,
    },
    {
        "type": "conical",
        "name": "Conical",
        "cone_angle": 45,
        "along_track_field_of_view": 2,
    },
]

adapter = TypeAdapter(SpaceSystemInput)


class SpaceSystemSchemaTestCase(unittest.TestCase):
    def test_satellite_every_orbit_type(self):
        for orbit_type, orbit in ORBITS.items():
            with self.subTest(orbit_type=orbit_type):
                system = adapter.validate_python(
                    {"type": "satellite", "name": "Sat", "orbit": orbit}
                )
                self.assertIsInstance(system, Satellite)
                self.assertEqual(system.orbit.type, orbit_type)
                self.assertEqual(len(generate_members(system)), 1)

    def test_missing_type_defaults_to_satellite(self):
        system = adapter.validate_python({"name": "Sat", "orbit": ORBITS["tle"]})
        self.assertIsInstance(system, Satellite)

    def test_every_instrument_type(self):
        system = adapter.validate_python(
            {"name": "Sat", "orbit": ORBITS["circular"], "instruments": INSTRUMENTS}
        )
        self.assertEqual(
            [type(i).__name__ for i in system.instruments],
            ["Instrument", "PointedInstrument", "ConicalInstrument"],
        )
        # instrument types survive serialization to tasks
        copy = Satellite.model_validate_json(system.model_dump_json())
        self.assertEqual(
            [i.type for i in copy.instruments], ["instrument", "pointed", "conical"]
        )

    def test_attitude(self):
        system = adapter.validate_python(
            {
                "name": "Sat",
                "orbit": ORBITS["sso"],
                "attitude": {"type": "attitude", "roll_angle": 10},
                "instruments": [INSTRUMENTS[1]],
            }
        )
        self.assertEqual(system.attitude.roll_angle, 10)

    def test_unknown_instrument_field_rejected(self):
        with self.assertRaises(ValidationError):
            adapter.validate_python(
                {
                    "name": "Sat",
                    "orbit": ORBITS["circular"],
                    "instruments": [{"type": "instrument", "unknown": 1}],
                }
            )

    def test_naive_epoch_rejected(self):
        with self.assertRaises(ValidationError):
            adapter.validate_python(
                {
                    "name": "Sat",
                    "orbit": {**ORBITS["circular"], "epoch": "2022-01-01T00:00:00"},
                }
            )

    def test_walker(self):
        system = adapter.validate_python(
            {
                "type": "walker",
                "name": "W",
                "orbit": ORBITS["circular"],
                "configuration": "star",
                "number_satellites": 6,
                "number_planes": 3,
                "relative_spacing": 1,
                "seam_spacing": 30,
            }
        )
        self.assertIsInstance(system, WalkerConstellation)
        self.assertEqual(len(generate_members(system)), 6)

    def test_train(self):
        system = adapter.validate_python(
            {
                "type": "train",
                "name": "T",
                "orbit": ORBITS["sso"],
                "number_satellites": 3,
                "interval": "PT5M",
            }
        )
        self.assertIsInstance(system, TrainConstellation)
        self.assertEqual(len(generate_members(system)), 3)

    def test_mog(self):
        system = adapter.validate_python(
            {
                "type": "mog",
                "name": "M",
                "orbit": ORBITS["circular"],
                "parallel_axis": 50e3,
                "transverse_axis": 25e3,
                "number_satellites": 4,
            }
        )
        self.assertIsInstance(system, MOGConstellation)
        self.assertEqual(len(generate_members(system)), 4)

    def test_mog_requires_circular_orbit(self):
        with self.assertRaises(ValidationError):
            adapter.validate_python(
                {
                    "type": "mog",
                    "name": "M",
                    "orbit": ORBITS["sso"],
                    "parallel_axis": 50e3,
                    "transverse_axis": 25e3,
                }
            )

    def test_soc(self):
        for inclination, polar in ((60, None), (98, True)):
            with self.subTest(inclination=inclination):
                system = adapter.validate_python(
                    {
                        "type": "soc",
                        "name": "S",
                        "orbit": {**ORBITS["circular"], "inclination": inclination},
                        "swath_width": 2000e3,
                        "packing_distance": 1,
                        "polar": polar,
                    }
                )
                self.assertIsInstance(system, SOCConstellation)
                self.assertGreater(len(generate_members(system)), 1)

    def test_duplicate_member_names_rejected(self):
        satellite = adapter.validate_python({"name": "Sat", "orbit": ORBITS["tle"]})
        with self.assertRaisesRegex(ValueError, "Duplicate satellite name"):
            expand_members([satellite, satellite])


class ValidateSpaceSystemTestCase(TatcTestCase):
    def test_validate_walker(self):
        response = self.client.post(
            "/validate/space-system",
            json={
                "type": "walker",
                "name": "W",
                "orbit": ORBITS["circular"],
                "number_satellites": 4,
                "number_planes": 2,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        members = response.json()["members"]
        self.assertEqual(len(members), 4)
        self.assertAlmostEqual(members[0]["altitude"], 500e3, delta=20e3)
        self.assertAlmostEqual(members[0]["inclination"], 45, delta=0.5)

    def test_validate_every_orbit_type(self):
        for orbit_type, orbit in ORBITS.items():
            with self.subTest(orbit_type=orbit_type):
                response = self.client.post(
                    "/validate/space-system", json={"name": "Sat", "orbit": orbit}
                )
                self.assertEqual(response.status_code, 200, response.text)
                member = response.json()["members"][0]
                self.assertEqual(member["orbit_type"], orbit_type)
                self.assertIsNotNone(member["period"])

    def test_validate_invalid(self):
        response = self.client.post(
            "/validate/space-system",
            json={
                "name": "Sat",
                "orbit": {**ORBITS["circular"], "altitude": -7000e3},
            },
        )
        self.assertEqual(response.status_code, 422)
