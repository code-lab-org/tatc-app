from datetime import datetime, timedelta, timezone

from tatc.analysis import collect_orbit_track
from tatc.schemas import GeneralPerturbationsOrbit, Instrument, Satellite

from tatc_app.generation.schemas import TimeGenerator
from tatc_app.tracking.schemas import OrbitTrackAnalysisRequest
from tatc_app.utils.serialization import from_geojson

from .base import TatcTestCase

TLE = [
    "1 25544U 98067A   22171.11255782  .00008307  00000+0  15444-3 0  9992",
    "2 25544  51.6448 322.0970 0003980 282.3738 231.6559 15.49798078345636",
]


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
        task = self.run_analysis(
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
        result = self.get_json(f"/analyze/orbit-track/{task['task_id']}")
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
