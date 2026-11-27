from datetime import datetime, timedelta, timezone

from tatc.analysis import collect_ground_track
from tatc.schemas import GeneralPerturbationsOrbit, Instrument, Satellite

from tatc_app.tracking.schemas import GroundTrackAnalysisRequest

from .base import TLE, TatcTestCase


class AnalyzeGroundTrackTestCase(TatcTestCase):
    def test_analyze_ground_track(self):
        satellite = Satellite(
            name="Test",
            orbit=GeneralPerturbationsOrbit.from_tle(TLE),
            instruments=[Instrument(name="Test", field_of_regard=100.0)],
        )
        times = [
            datetime(2022, 6, 1, tzinfo=timezone.utc) + timedelta(minutes=i)
            for i in range(10)
        ]
        result = self.analysis_result(
            "/analyze/ground-track",
            GroundTrackAnalysisRequest(satellite=satellite, times=times),
        )
        expected = collect_ground_track(satellite, times)
        self.assertEqual(len(result["features"]), len(expected))
        self.assertEqual(
            {f["geometry"]["type"] for f in result["features"]},
            set(expected.geometry.geom_type),
        )
