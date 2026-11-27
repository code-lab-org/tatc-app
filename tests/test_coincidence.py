from datetime import datetime, timedelta, timezone

from tatc.analysis import (
    aggregate_observations,
    collect_observations,
    find_coincident_observations,
    reduce_observations,
)
from tatc.generation import generate_points_uniform_spacing
from tatc.schemas import (
    GeneralPerturbationsOrbit,
    Instrument,
    Satellite,
    WalkerConstellation,
)

from tatc_app.coincidence.schemas import (
    CoincidenceAnalysisRequest,
    CoincidenceAnalysisResult,
)
from tatc_app.coincidence.tasks import collect_coincident_observations
from tatc_app.coverage.schemas import SufficiencyOptions
from tatc_app.generation.schemas import CellGenerator, PointGenerator
from tatc_app.utils.serialization import from_geojson

from .base import TLE, TatcTestCase

START = datetime(2022, 6, 1, tzinfo=timezone.utc)
END = datetime(2022, 6, 2, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)


def names(listed: str) -> list:
    """Gets the names of a comma-separated list."""
    return [name.strip() for name in listed.split(",")]


class CoincidenceTestCase(TatcTestCase):
    def setUp(self):
        super().setUp()
        orbit = GeneralPerturbationsOrbit.from_tle(TLE)
        self.constellation = WalkerConstellation(
            name="W",
            orbit=orbit,
            instruments=[Instrument(name="I", field_of_regard=120.0)],
            number_satellites=4,
            number_planes=2,
        )
        self.satellite = Satellite(
            name="S",
            orbit=orbit,
            instruments=[Instrument(name="J", field_of_regard=120.0)],
        )
        self.points = generate_points_uniform_spacing(2000e3)

    def request(self, **kwargs) -> CoincidenceAnalysisRequest:
        return CoincidenceAnalysisRequest(
            **{
                "satellites": [self.constellation, self.satellite],
                "start": START,
                "end": END,
                "points": PointGenerator(method="equally_spaced", distance=2000e3),
                "cells": CellGenerator(method="equally_spaced", distance=5000e3),
                "max_time_difference": HOUR,
                **kwargs,
            }
        )

    def test_collect_members(self):
        members = self.request().get_members()
        actual = collect_coincident_observations(
            self.points, members, START, END, max_time_difference=HOUR
        )
        expected = aggregate_observations(
            find_coincident_observations(
                collect_observations(
                    self.points, members, START, END, instrument_index=None
                ),
                max_time_difference=HOUR,
            )
        )
        self.assertGreater(len(actual), 0)
        self.assertEqual(len(actual), len(expected))
        # each names at least two satellites, paired with their instruments
        for satellites, instruments in zip(actual.satellite, actual.instrument):
            self.assertGreaterEqual(len(set(names(satellites))), 2)
            self.assertEqual(len(names(satellites)), len(names(instruments)))
        # members of one constellation coincide with each other
        within = actual.satellite.map(
            lambda s: all(n.startswith("W") for n in names(s))
        )
        self.assertTrue(within.any())

    def test_collect_systems(self):
        request = self.request(platforms="systems")
        systems = request.get_platform_systems()
        self.assertEqual(systems["W 1"], systems["W 4"])
        self.assertNotEqual(systems["W 1"], systems["S"])
        coincident = collect_coincident_observations(
            self.points,
            request.get_members(),
            START,
            END,
            max_time_difference=HOUR,
            systems=systems,
        )
        self.assertGreater(len(coincident), 0)
        for satellites, instruments in zip(coincident.satellite, coincident.instrument):
            satellites, instruments = names(satellites), names(instruments)
            # every coincidence is between the satellite and the constellation
            self.assertIn("S", satellites)
            self.assertTrue(any(name.startswith("W ") for name in satellites))
            # with the members and instruments restored, in pairs
            self.assertEqual(len(satellites), len(instruments))
            for satellite, instrument in zip(satellites, instruments):
                self.assertEqual(instrument, "J" if satellite == "S" else "I")
        # fewer than between any members
        members = collect_coincident_observations(
            self.points,
            request.get_members(),
            START,
            END,
            max_time_difference=HOUR,
        )
        self.assertLess(len(coincident), len(members))

    def test_collect_without_coincidences(self):
        # a single platform never coincides with itself
        coincident = collect_coincident_observations(
            self.points,
            self.request(platforms="systems").get_members(),
            START,
            END,
            min_platforms=3,
            systems={name: "0" for name in ["W 1", "W 2", "W 3", "W 4", "S"]},
        )
        self.assertTrue(coincident.empty)

    def test_analyze_coincidence(self):
        request = self.request(
            colors=["#ff0000", "#00ff00"],
            sufficiency=SufficiencyOptions(decorrelation_time=timedelta(hours=6)),
        )
        result = self.analysis_result(
            "/analyze/coincidence", request, CoincidenceAnalysisResult
        )
        points = generate_points_uniform_spacing(2000e3)
        expected = reduce_observations(
            collect_coincident_observations(
                points, request.get_members(), START, END, max_time_difference=HOUR
            ),
            targets=points,
        )
        actual = from_geojson(result.points.model_dump_json())
        self.assertEqual(len(actual), len(points))
        merged = actual.merge(
            expected, on="target_hash", suffixes=("", "_expected"), how="outer"
        )
        self.assertTrue((merged["samples"] == merged["samples_expected"]).all())
        # the timeline has one event per coincident observation
        self.assertEqual(len(result.timeline.start), int(expected["samples"].sum()))
        # the summary, with the sufficiency of coincident observations
        summary = result.summary
        self.assertGreater(summary.observed, 0)
        self.assertIsNotNone(summary.sufficiency)
        self.assertIn("relative_error", result.points.features[0].properties)
        # the czml document
        czml = self.get_json(f"/analyze/coincidence/{self.task_id}/czml")
        self.assertEqual(czml[0]["id"], "document")

    def test_invalid_requests(self):
        base = {
            "satellites": [self.satellite.model_dump(mode="json")],
            "start": "2022-06-01T00:00:00Z",
            "end": "2022-06-02T00:00:00Z",
            "points": {"method": "equally_spaced", "distance": 5000e3},
            "cells": {"method": "equally_spaced", "distance": 5000e3},
        }
        constellation = self.constellation.model_dump(mode="json")
        for options in (
            # one satellite cannot coincide with itself
            {},
            # four members, but not five at once
            {"satellites": [constellation], "minPlatforms": 5},
            # one constellation is one system
            {"satellites": [constellation], "platforms": "systems"},
            {"satellites": [constellation], "maxTimeDifference": -60},
            {"satellites": [constellation], "minPlatforms": 1},
            {"satellites": [constellation], "platforms": "planes"},
        ):
            response = self.client.post("/analyze/coincidence", json=base | options)
            self.assertEqual(response.status_code, 422, options)
        # two satellites or constellations are two systems
        valid = CoincidenceAnalysisRequest.model_validate(
            base
            | {
                "satellites": [constellation, self.satellite.model_dump(mode="json")],
                "platforms": "systems",
            }
        )
        self.assertEqual(len(set(valid.get_platform_systems().values())), 2)
