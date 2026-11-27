from datetime import datetime, timezone

from shapely.geometry import Point as GeoPoint
from tatc.analysis import (
    aggregate_observations,
    collect_observations,
    reduce_observations,
)
from tatc.schemas import (
    GeneralPerturbationsOrbit,
    Instrument,
    Point,
    Satellite,
    TrainConstellation,
)

from tatc_app.overflight.schemas import (
    OverflightAnalysisRequest,
    OverflightAnalysisResult,
)

from .base import TLE, TatcTestCase


class OverflightAnalysisTestCase(TatcTestCase):
    def setUp(self):
        super().setUp()
        self.satellites = [
            Satellite(
                name="ISS",
                orbit=GeneralPerturbationsOrbit.from_tle(TLE),
                instruments=[Instrument(name="Test", field_of_regard=120.0)],
            ),
            TrainConstellation(
                name="Train",
                orbit=GeneralPerturbationsOrbit.from_tle(TLE),
                instruments=[Instrument(name="Test", field_of_regard=120.0)],
                number_satellites=2,
                interval="PT10M",
            ),
        ]
        self.points = [
            Point(id=1, latitude=33.4, longitude=-111.9),
            Point(id=2, latitude=0, longitude=0),
        ]
        self.start = datetime(2022, 6, 1, tzinfo=timezone.utc)
        self.end = datetime(2022, 6, 3, tzinfo=timezone.utc)

    def test_analyze_overflight(self):
        result = self.analysis_result(
            "/analyze/overflight",
            OverflightAnalysisRequest(
                satellites=self.satellites,
                points=self.points,
                start=self.start,
                end=self.end,
            ),
            OverflightAnalysisResult,
        )
        members = [
            self.satellites[0],
            *self.satellites[1].generate_members(),
        ]
        expected = collect_observations(
            [GeoPoint(p.longitude, p.latitude) for p in self.points],
            members,
            self.start,
            self.end,
            instrument_index=None,
        )
        statistics = reduce_observations(aggregate_observations(expected))
        self.assertEqual(len(result.observations.features), len(expected))
        self.assertEqual(
            sorted(f.properties["satellite"] for f in result.observations.features),
            sorted(expected["satellite"]),
        )
        starts = [f.properties["start"] for f in result.observations.features]
        self.assertEqual(starts, sorted(starts))
        self.assertIn("platform_alt", result.observations.features[0].properties)
        # points keep their identifiers, with statistics of observations
        self.assertEqual([f.properties["id"] for f in result.points.features], [1, 2])
        self.assertEqual(
            sum(f.properties["samples"] for f in result.points.features),
            statistics["samples"].sum(),
        )
        self.assertEqual(len(result.timeline.start), len(expected))
        self.assertEqual(len(result.tracks.tracks), 3)
        # czml document with targets and access links
        czml = self.get_json(f"/analyze/overflight/{self.task_id}/czml")
        ids = [packet["id"] for packet in czml]
        self.assertEqual(sum(i.startswith("tgt/") for i in ids), 2)
        self.assertEqual(sum(i.startswith("sat/") for i in ids), 3)
        links = [p for p in czml if p["id"].startswith("link/tgt/")]
        self.assertGreater(len(links), 0)
        self.assertEqual(
            sum(len(link["availability"]) for link in links), len(expected)
        )

    def test_analyze_overflight_no_observations(self):
        # the ISS (51.6 deg inclination) never observes a polar point
        result = self.analysis_result(
            "/analyze/overflight",
            OverflightAnalysisRequest(
                satellites=self.satellites[:1],
                points=[Point(id=1, latitude=89.0, longitude=0)],
                start=self.start,
                end=self.end,
            ),
        )
        self.assertEqual(len(result["observations"]["features"]), 0)
        properties = result["points"]["features"][0]["properties"]
        self.assertEqual(properties["samples"], 0)
        self.assertIsNone(properties["access"])
        self.assertIsNone(properties["revisit"])

    def test_analyze_overflight_solar(self):
        result = self.analysis_result(
            "/analyze/overflight",
            OverflightAnalysisRequest(
                satellites=self.satellites[:1],
                points=self.points[:1],
                start=self.start,
                end=self.end,
                omit_solar=False,
            ),
        )
        self.assertIn("solar_alt", result["observations"]["features"][0]["properties"])
