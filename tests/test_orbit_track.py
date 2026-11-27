from datetime import datetime, timedelta, timezone
from unittest import mock

from tatc.analysis import collect_orbit_track
from tatc.schemas import (
    GeneralPerturbationsOrbit,
    Instrument,
    Satellite,
    SunSynchronousOrbit,
    WalkerConstellation,
)

from tatc_app import limits
from tatc_app.generation.schemas import TimeGenerator
from tatc_app.tracking.schemas import OrbitTrackAnalysisRequest
from tatc_app.tracking.tasks import collect_track_task
from tatc_app.utils.serialization import from_geojson

from .base import TLE, TatcTestCase


class AnalyzeTrackTestCase(TatcTestCase):
    def setUp(self):
        super().setUp()
        self.satellite = Satellite(
            name="Test",
            orbit=GeneralPerturbationsOrbit.from_tle(TLE),
            instruments=[Instrument(name="Test", field_of_regard=100.0)],
        )
        self.times = [
            datetime(2022, 6, 1, tzinfo=timezone.utc) + timedelta(minutes=i)
            for i in range(10)
        ]

    def test_analyze_orbit_track(self):
        task = self.run_analysis(
            "/analyze/orbit-track",
            OrbitTrackAnalysisRequest(satellite=self.satellite, times=self.times),
        )
        gdf = from_geojson(
            self.client.get(f"/analyze/orbit-track/{task['task_id']}").text,
            datetimes=["time"],
        ).sort_values("time", ignore_index=True)
        expected = collect_orbit_track(self.satellite, self.times)
        self.assertEqual(len(gdf), len(expected))
        self.assertTrue(
            (
                gdf.geometry.distance(expected.geometry.reset_index(drop=True)) < 1e-6
            ).all()
        )

    def test_analyze_orbit_track_time_generator(self):
        result = self.analysis_result(
            "/analyze/orbit-track",
            OrbitTrackAnalysisRequest(
                satellite=self.satellite,
                times=TimeGenerator(
                    start=self.times[0],
                    end=self.times[-1],
                    delta=timedelta(minutes=1),
                ),
            ),
        )
        self.assertEqual(len(result["features"]), len(self.times))

    def test_instrument_index_out_of_bounds(self):
        response = self.client.post(
            "/analyze/orbit-track",
            json={
                "satellite": self.satellite.model_dump(mode="json"),
                "instrument_index": 1,
                "times": [t.isoformat() for t in self.times],
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_invalid_times(self):
        satellite = self.satellite.model_dump(mode="json")
        # naive times
        response = self.client.post(
            "/analyze/orbit-track",
            json={"satellite": satellite, "times": ["2022-06-01T00:00:00"]},
        )
        self.assertEqual(response.status_code, 422)
        # too many times
        response = self.client.post(
            "/analyze/orbit-track",
            json={
                "satellite": satellite,
                "times": [self.times[0].isoformat()] * 20001,
            },
        )
        self.assertEqual(response.status_code, 422)


class ConstellationTrackTestCase(TatcTestCase):
    def setUp(self):
        super().setUp()
        self.constellation = WalkerConstellation(
            name="W",
            orbit=SunSynchronousOrbit(altitude=705e3, equator_crossing_time="13:30"),
            instruments=[Instrument(name="I", field_of_regard=100.0)],
            number_satellites=4,
            number_planes=2,
        )
        self.times = [
            datetime(2022, 6, 1, tzinfo=timezone.utc) + timedelta(minutes=i)
            for i in range(10)
        ]

    def post(self, path="/analyze/orbit-track"):
        return self.client.post(
            path,
            json={
                "satellite": self.constellation.model_dump(mode="json"),
                "times": [time.isoformat() for time in self.times],
            },
        )

    def test_too_many_positions(self):
        # 4 members at 10 times
        for path in ("/analyze/orbit-track", "/analyze/ground-track"):
            with self.subTest(path=path):
                with mock.patch.object(limits, "MAX_TRACK_POSITIONS", 39):
                    response = self.post(path)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertIn("Too many positions", response.text)
                with mock.patch.object(limits, "MAX_TRACK_POSITIONS", 40):
                    response = self.post(path)
                self.assertEqual(response.status_code, 200, response.text)

    def test_members_grouped_by_positions(self):
        # 2 members (20 positions) of each task, as their 10 times fit
        with (
            mock.patch("tatc_app.tracking.router.TRACK_CHUNK_SIZE", 20),
            mock.patch.object(
                collect_track_task, "s", wraps=collect_track_task.s
            ) as signature,
        ):
            response = self.post()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([len(c.args[1]) for c in signature.call_args_list], [2, 2])
        result = from_geojson(
            self.client.get(f"/analyze/orbit-track/{response.json()['task_id']}").text,
            datetimes=["time"],
        )
        for member in self.constellation.generate_members():
            expected = collect_orbit_track(member, self.times)
            actual = result[result["satellite"] == member.name]
            self.assertEqual(len(actual), len(expected))
