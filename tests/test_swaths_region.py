from datetime import datetime, timedelta, timezone
from unittest import mock

import numpy as np
import pandas as pd
import shapely
from shapely.geometry import box
from tatc.analysis import (
    aggregate_observations,
    collect_footprints,
    collect_region_observations,
    find_coincident_ground_track,
)
from tatc.schemas import (
    PointedInstrument,
    Satellite,
    SunSynchronousOrbit,
    WalkerConstellation,
)

from tatc_app.swaths.schemas import SwathAnalysisRequest, SwathAnalysisResult
from tatc_app.swaths.tasks import area_km2

from .base import TatcTestCase

START = datetime(2022, 6, 1, tzinfo=timezone.utc)
END = datetime(2022, 6, 1, 12, tzinfo=timezone.utc)
STEP = timedelta(seconds=60)
DIFFERENCE = timedelta(hours=1)
REGION = box(-125, 24, -66, 50)
ORBIT = SunSynchronousOrbit(
    altitude=705e3, equator_crossing_time="13:30", equator_crossing_ascending=True
)
INSTRUMENT = PointedInstrument(
    name="P", cross_track_field_of_view=60, along_track_field_of_view=4
)


class RegionTestCase(TatcTestCase):
    def setUp(self):
        super().setUp()
        self.constellation = WalkerConstellation(
            name="W",
            orbit=ORBIT,
            instruments=[INSTRUMENT],
            number_satellites=4,
            number_planes=4,
        )
        self.satellite = Satellite(
            name="S",
            orbit=SunSynchronousOrbit(
                altitude=705e3,
                equator_crossing_time="13:00",
                equator_crossing_ascending=True,
            ),
            instruments=[INSTRUMENT],
        )

    def request(self, **kwargs) -> SwathAnalysisRequest:
        return SwathAnalysisRequest(
            **{
                "satellites": [self.constellation, self.satellite],
                "start": START,
                "end": END,
                "region": {
                    "type": "Polygon",
                    "coordinates": [list(REGION.exterior.coords)],
                },
                "step": STEP,
                "coincidence": {"max_time_difference": DIFFERENCE},
                **kwargs,
            }
        )

    def analyze(self, request, window_steps=None) -> SwathAnalysisResult:
        with mock.patch("tatc_app.swaths.router.WINDOW_STEPS", window_steps or 100000):
            task = self.run_analysis("/analyze/swaths", request)
        self.task_id = task["task_id"]
        return SwathAnalysisResult.model_validate(
            self.get_json(f"/analyze/swaths/{task['task_id']}")
        )

    def test_area(self):
        self.assertAlmostEqual(area_km2(box(-180, -90, 180, 90)) / 510065622, 1, 5)
        self.assertEqual(area_km2(None), 0)

    def test_region_analysis(self):
        request = self.request()
        members = request.get_members()
        result = self.analyze(request, window_steps=97)
        summary = result.summary
        self.assertAlmostEqual(summary.area, area_km2(REGION))
        # the share observed grows to the share covered
        shares = np.array(summary.coverage.shares)
        self.assertTrue((np.diff(shares) >= -1e-9).all())
        self.assertEqual(shares[0], 0)
        self.assertAlmostEqual(shares[-1], summary.covered)
        times = list(pd.date_range(START, END, freq=STEP))
        footprints = collect_footprints(
            members, times, instrument_index=None, mask=REGION, time_step=STEP
        )
        footprints = footprints[footprints.valid_obs]
        observed = shapely.intersection(shapely.union_all(footprints.geometry), REGION)
        self.assertAlmostEqual(summary.covered, area_km2(observed) / summary.area, 4)
        # the observations of the region, merged across windows
        expected = aggregate_observations(
            collect_region_observations(REGION, members, START, END, None)
        )
        self.assertEqual(summary.observations, len(expected))
        self.assertEqual(len(result.observations), len(expected))
        # coincident footprints, paired across windows
        pairs = find_coincident_ground_track(
            footprints.reset_index(drop=True), max_time_difference=DIFFERENCE
        )
        self.assertGreater(len(pairs), 0)
        self.assertEqual(summary.coincidence.pairs, len(pairs))
        self.assertLessEqual(summary.coincidence.time_difference.max, 3600)
        self.assertGreater(summary.coincidence.common, 0)
        self.assertLessEqual(summary.coincidence.common, summary.covered)
        # swaths and common areas to display
        self.assertGreater(len(result.swaths.features), 0)
        self.assertGreater(len(result.coincident.features), 0)
        czml = self.get_json(f"/analyze/swaths/{self.task_id}/czml")
        self.assertTrue(any(p["id"].startswith("coincident/") for p in czml))
        self.assertTrue(any(p["id"].startswith("swath/") for p in czml))

    def test_windows_agree(self):
        request = self.request()
        one = self.analyze(request).summary
        many = self.analyze(request, window_steps=50).summary
        self.assertAlmostEqual(one.covered, many.covered, 6)
        self.assertEqual(one.observations, many.observations)
        self.assertEqual(one.coincidence.pairs, many.coincidence.pairs)
        self.assertAlmostEqual(one.coincidence.common, many.coincidence.common, 6)

    def test_display(self):
        # the animation limits the swaths and coincident swaths given, but
        # not the summary of the whole analysis period
        display_end = START + timedelta(hours=4)
        full = self.analyze(self.request(), window_steps=200)
        shown = self.analyze(
            self.request(display={"start": START, "end": display_end, "delta": 60}),
            window_steps=200,
        )
        self.assertAlmostEqual(shown.summary.covered, full.summary.covered, 6)
        self.assertEqual(shown.summary.observations, full.summary.observations)
        self.assertEqual(
            shown.summary.coincidence.pairs, full.summary.coincidence.pairs
        )
        self.assertEqual(len(shown.observations), len(full.observations))
        for track in shown.tracks.tracks:
            self.assertEqual(len(track.positions), 4 * 241)
        for collection in (shown.swaths, shown.coincident):
            self.assertGreater(len(collection.features), 0)
            for feature in collection.features:
                self.assertLessEqual(
                    datetime.fromisoformat(feature.properties["end"]), display_end
                )
        self.assertLess(len(shown.swaths.features), len(full.swaths.features))
        self.assertLess(len(shown.coincident.features), len(full.coincident.features))

    def test_systems(self):
        result = self.analyze(
            self.request(
                coincidence={"max_time_difference": DIFFERENCE, "platforms": "systems"}
            ),
            window_steps=200,
        )
        names = [
            {f.properties["satellite_1"], f.properties["satellite_2"]}
            for f in result.coincident.features
        ]
        self.assertGreater(len(names), 0)
        # every common area is between the satellite and the constellation
        for pair in names:
            self.assertIn("S", pair)
        members = self.analyze(self.request(), window_steps=200)
        self.assertLess(
            result.summary.coincidence.pairs, members.summary.coincidence.pairs
        )

    def test_without_coincidence_and_known_region(self):
        result = self.analyze(
            self.request(
                coincidence=None, region="conus", end=START + timedelta(hours=3)
            )
        )
        self.assertIsNone(result.summary.coincidence)
        self.assertIsNone(result.coincident)
        self.assertGreater(result.summary.area, 7e6)

    def test_saved_run(self):
        request = self.request(coincidence=None, end=START + timedelta(hours=2))
        result = self.analyze(request)
        response = self.client.post(
            "/runs",
            json={
                "name": "Region",
                "analysis": "swaths",
                "taskId": self.task_id,
                "request": request.model_dump(mode="json"),
                "design": {
                    "version": 2,
                    "satellites": [],
                    "stations": [],
                    "targets": [],
                },
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json()["summary"], result.summary.model_dump(mode="json")
        )

    def test_invalid_requests(self):
        base = self.request().model_dump(mode="json", exclude_none=True)
        single = self.satellite.model_dump(mode="json")
        for changes in (
            {"region": "XYZ"},
            {"region": None},
            {"satellites": [single]},
            {
                "satellites": [base["satellites"][0]],
                "coincidence": {"platforms": "systems"},
            },
            {"coincidence": {"maxTimeDifference": -1}},
            {"step": 0},
        ):
            response = self.client.post("/analyze/swaths", json=base | changes)
            self.assertEqual(response.status_code, 422, changes)
        # one satellite, without coincident swaths, is valid
        valid = base | {"satellites": [single]}
        valid.pop("coincidence")
        SwathAnalysisRequest.model_validate(valid)
