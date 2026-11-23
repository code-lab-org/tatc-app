from datetime import datetime, timedelta, timezone

from tatc.analysis import collect_ground_track
from tatc.schemas import GeneralPerturbationsOrbit, Instrument, Satellite

from tatc_app.tracking.schemas import GroundTrackAnalysisRequest

from .base import TatcTestCase


class AnalyzeGroundTrackTestCase(TatcTestCase):
    def test_analyze_ground_track(self):
        satellite = Satellite(
            name="Test",
            orbit=GeneralPerturbationsOrbit.from_tle(
                [
                    "1 25544U 98067A   22171.11255782  .00008307  00000+0  15444-3 0  9992",
                    "2 25544  51.6448 322.0970 0003980 282.3738 231.6559 15.49798078345636",
                ]
            ),
            instruments=[Instrument(name="Test", field_of_regard=100.0)],
        )
        times = [
            datetime(2022, 6, 1, tzinfo=timezone.utc) + timedelta(minutes=i)
            for i in range(10)
        ]
        task = self.run_analysis(
            "/analyze/ground-track",
            GroundTrackAnalysisRequest(satellite=satellite, times=times),
        )
        result = self.get_json(f"/analyze/ground-track/{task['task_id']}")
        expected = collect_ground_track(satellite, times)
        self.assertEqual(len(result["features"]), len(expected))
        self.assertEqual(
            {f["geometry"]["type"] for f in result["features"]},
            set(expected.geometry.geom_type),
        )
