import unittest

from pydantic import ValidationError
from tatc.schemas import CircularOrbit, GeneralPerturbationsOrbit, Instrument, Satellite

from tatc_app.satellites import SatelliteInput, generate_members, to_tatc_satellite

TLE = [
    "1 25544U 98067A   22171.11255782  .00008307  00000+0  15444-3 0  9992",
    "2 25544  51.6448 322.0970 0003980 282.3738 231.6559 15.49798078345636",
]


class TwoLineElementsInputTestCase(unittest.TestCase):
    def test_tle_orbit_resolves_to_general_perturbations_orbit(self):
        satellite = SatelliteInput.model_validate(
            {
                "name": "Test",
                "orbit": {"type": "tle", "tle": TLE},
                "instruments": [{"name": "Test"}],
            }
        )
        resolved = to_tatc_satellite(satellite)
        self.assertIsInstance(resolved, Satellite)
        self.assertIsInstance(resolved.orbit, GeneralPerturbationsOrbit)

    def test_generate_members_treats_a_satellite_as_its_own_sole_member(self):
        satellite = SatelliteInput.model_validate(
            {
                "name": "Test",
                "orbit": {"type": "tle", "tle": TLE},
                "instruments": [{"name": "Test"}],
            }
        )
        members = generate_members(satellite)
        self.assertEqual(len(members), 1)
        self.assertIsInstance(members[0], Satellite)
        self.assertIsInstance(members[0].orbit, GeneralPerturbationsOrbit)

    def test_native_orbit_passes_through_unchanged(self):
        satellite = SatelliteInput.model_validate(
            {
                "name": "Test",
                "orbit": CircularOrbit(mean_altitude=500e3),
                "instruments": [Instrument(name="Test")],
            }
        )
        resolved = to_tatc_satellite(satellite)
        self.assertIsInstance(resolved.orbit, CircularOrbit)

    def test_native_satellite_instance_validates_directly(self):
        # mirrors how requests are constructed from native tatc objects
        # elsewhere in the test suite, not only from JSON payloads
        orbit = GeneralPerturbationsOrbit.from_tle(TLE)
        satellite = Satellite(
            name="Test", orbit=orbit, instruments=[Instrument(name="Test")]
        )
        parsed = SatelliteInput.model_validate(satellite)
        self.assertIsInstance(parsed.orbit, GeneralPerturbationsOrbit)

    def test_malformed_tle_is_rejected(self):
        with self.assertRaises(ValidationError):
            SatelliteInput.model_validate(
                {
                    "name": "Test",
                    "orbit": {"type": "tle", "tle": ["not", "a tle"]},
                    "instruments": [{"name": "Test"}],
                }
            )
