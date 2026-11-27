from datetime import datetime, timedelta, timezone

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point as GeoPoint
from tatc.schemas import (
    GeneralPerturbationsOrbit,
    GroundStation,
    Instrument,
    Point,
    WalkerConstellation,
)

from tatc_app.analysis.summary import (
    HISTOGRAM_BINS,
    Weighting,
    coverage_curve,
    get_weighting,
    point_weights,
    summarize_coverage,
    summarize_latency,
    summarize_values,
    weighted_quantile,
)
from tatc_app.coverage.schemas import CoverageAnalysisRequest, CoverageAnalysisResult
from tatc_app.generation.schemas import CellGenerator, PointGenerator
from tatc_app.latency.schemas import LatencyAnalysisRequest, LatencyAnalysisResult

from .base import TLE, TatcTestCase

START = datetime(2022, 6, 1, tzinfo=timezone.utc)
END = datetime(2022, 6, 2, tzinfo=timezone.utc)


def frame(latitudes, **columns) -> gpd.GeoDataFrame:
    """
    Creates points at latitudes (and longitude 0) with columns.
    """
    return gpd.GeoDataFrame(
        {
            "target_hash": [f"p{i}" for i in range(len(latitudes))],
            **columns,
        },
        geometry=[GeoPoint(0, latitude) for latitude in latitudes],
        crs="EPSG:4326",
    )


class SummaryFunctionsTestCase(TatcTestCase):
    def test_weighting(self):
        self.assertEqual(
            get_weighting(PointGenerator(method="equally_spaced")), Weighting.area
        )
        self.assertEqual(
            get_weighting(PointGenerator(method="fibonacci_lattice")),
            Weighting.uniform,
        )
        self.assertEqual(
            get_weighting([Point(id=0, latitude=0, longitude=0)]), Weighting.uniform
        )

    def test_point_weights(self):
        points = frame([0, 60, 90])
        np.testing.assert_allclose(
            point_weights(points, Weighting.area), [1, 0.5, 1e-6], atol=1e-9
        )
        np.testing.assert_array_equal(point_weights(points, Weighting.uniform), 1)

    def test_weighted_quantile(self):
        values = np.array([4.0, 1.0, 3.0, 2.0])
        equal = np.ones(4)
        # equal weights give ordinary (linear) quantiles
        for q in (0, 0.25, 0.5, 0.9, 1):
            self.assertAlmostEqual(
                weighted_quantile(values, equal, q), np.quantile(values, q)
            )
        # a heavier value pulls the median toward it
        self.assertGreater(
            weighted_quantile(values, np.array([10.0, 1, 1, 1]), 0.5), 2.5
        )
        self.assertEqual(weighted_quantile(np.array([7.0]), np.ones(1), 0.9), 7)

    def test_summarize_values(self):
        values = np.array([np.nan, 3600.0, 7200.0, 10800.0])
        distribution, histogram = summarize_values(values, np.ones(4))
        self.assertEqual(distribution.count, 3)
        self.assertAlmostEqual(distribution.mean, 7200)
        self.assertAlmostEqual(distribution.median, 7200)
        self.assertEqual(distribution.max, 10800)
        self.assertEqual(len(histogram.edges), HISTOGRAM_BINS + 1)
        self.assertEqual(histogram.edges[0], 0)
        self.assertEqual(histogram.edges[-1], 10800)
        self.assertAlmostEqual(sum(histogram.shares), 1)
        self.assertEqual(summarize_values(np.array([np.nan]), np.ones(1)), (None, None))

    def test_coverage_curve(self):
        curve = coverage_curve(
            np.array([0.0, 50.0, np.nan, 100.0]), np.array([1.0, 1, 1, 1]), 100
        )
        self.assertEqual(curve.times[0], 0)
        self.assertEqual(curve.times[-1], 100)
        self.assertEqual(curve.shares[0], 0.25)
        self.assertEqual(curve.shares[-1], 0.75)
        self.assertTrue(np.all(np.diff(curve.shares) >= 0))

    def test_summarize_coverage(self):
        hour = pd.Timedelta(hours=1)
        points = frame(
            [0, 0, 60, 60],
            samples=[0, 1, 2, 3],
            access=[
                pd.NaT,
                pd.Timedelta(seconds=60),
                pd.Timedelta(seconds=60),
                pd.Timedelta(seconds=60),
            ],
            revisit=[pd.NaT, pd.NaT, 2 * hour, 4 * hour],
        )
        observations = pd.DataFrame(
            {
                "target_hash": ["p1", "p2", "p2", "p3"],
                "start": [START + timedelta(hours=h) for h in (12, 1, 6, 0)],
            }
        )
        uniform = summarize_coverage(
            points, observations, Weighting.uniform, START, END
        )
        self.assertEqual(uniform.points, 4)
        self.assertAlmostEqual(uniform.observed, 0.75)
        self.assertAlmostEqual(uniform.revisited, 0.5)
        self.assertEqual(uniform.revisit.count, 2)
        self.assertAlmostEqual(uniform.revisit.mean, 3 * 3600)
        self.assertAlmostEqual(uniform.coverage.shares[-1], 0.75)
        # by area, points at 60 degrees count half as much as at the equator
        area = summarize_coverage(points, observations, Weighting.area, START, END)
        self.assertAlmostEqual(area.observed, 2 / 3)
        self.assertAlmostEqual(area.revisited, 1 / 3)
        # no observations
        empty = summarize_coverage(
            frame([0], samples=[0], access=[pd.NaT], revisit=[pd.NaT]),
            pd.DataFrame(),
            Weighting.uniform,
            START,
            END,
        )
        self.assertEqual(empty.observed, 0)
        self.assertIsNone(empty.revisit)
        self.assertIsNone(empty.revisit_histogram)
        self.assertEqual(max(empty.coverage.shares), 0)

    def test_summarize_latency(self):
        points = frame(
            [0, 0, 0], latency=[pd.NaT, pd.Timedelta(hours=1), pd.Timedelta(hours=3)]
        )
        contacts = pd.DataFrame(
            {
                "start": [START, START + timedelta(hours=1)],
                "end": [START + timedelta(minutes=10), pd.NaT],
            }
        )
        summary = summarize_latency(points, contacts, Weighting.uniform)
        self.assertAlmostEqual(summary.downlinked, 2 / 3)
        self.assertAlmostEqual(summary.latency.mean, 2 * 3600)
        self.assertEqual(summary.contacts, 2)
        self.assertAlmostEqual(summary.contact_duration, 600)
        empty = summarize_latency(points.iloc[:1], pd.DataFrame(), Weighting.uniform)
        self.assertEqual(empty.contacts, 0)
        self.assertIsNone(empty.contact_duration)
        self.assertIsNone(empty.latency)


class SummaryEndpointsTestCase(TatcTestCase):
    def setUp(self):
        super().setUp()
        self.satellite = WalkerConstellation(
            name="Test",
            orbit=GeneralPerturbationsOrbit.from_tle(TLE),
            instruments=[Instrument(name="Test", field_of_regard=60.0)],
            number_satellites=4,
            number_planes=2,
        )

    def test_coverage_summary(self):
        result = self.analysis_result(
            "/analyze/coverage",
            CoverageAnalysisRequest(
                satellites=[self.satellite],
                start=START,
                end=END,
                points=PointGenerator(method="equally_spaced", distance=2000e3),
                cells=CellGenerator(method="equally_spaced", distance=5000e3),
            ),
            CoverageAnalysisResult,
        )
        summary = result.summary
        samples = [
            f["properties"]["samples"] for f in result.points.model_dump()["features"]
        ]
        self.assertEqual(summary.points, len(samples))
        self.assertEqual(summary.weighting, Weighting.area)
        self.assertGreater(summary.observed, 0)
        self.assertLessEqual(summary.revisited, summary.observed)
        self.assertEqual(summary.revisit.count, sum(s >= 2 for s in samples))
        self.assertEqual(summary.coverage.times[-1], (END - START).total_seconds())
        # by the end, the share observed so far is the share observed
        self.assertAlmostEqual(summary.coverage.shares[-1], summary.observed)

    def test_latency_summary(self):
        result = self.analysis_result(
            "/analyze/latency",
            LatencyAnalysisRequest(
                satellites=[self.satellite],
                stations=[
                    GroundStation(name="Wallops", latitude=37.94, longitude=-75.46)
                ],
                start=START,
                end=END,
                points=PointGenerator(method="fibonacci_lattice", distance=3000e3),
                cells=CellGenerator(method="equally_spaced", distance=5000e3),
            ),
            LatencyAnalysisResult,
        )
        summary = result.summary
        self.assertEqual(summary.weighting, Weighting.uniform)
        self.assertEqual(summary.contacts, len(result.contacts.start))
        self.assertGreater(summary.downlinked, 0)
        self.assertIsNotNone(summary.latency)
        self.assertGreater(summary.latency.p90, summary.latency.median)
