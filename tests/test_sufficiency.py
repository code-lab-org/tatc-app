from datetime import datetime, timedelta, timezone

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point as GeoPoint
from shapely.geometry import box
from tatc.analysis import sampling_error_variance
from tatc.utils.geometry import hash_geometry

from tatc_app.analysis.sufficiency import compute_sufficiency, grid_sufficiency
from tatc_app.analysis.summary import Weighting, summarize_sufficiency

from .base import TatcTestCase

START = datetime(2022, 6, 1, tzinfo=timezone.utc)
END = datetime(2022, 6, 2, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)


def points_frame(longitudes) -> gpd.GeoDataFrame:
    """
    Creates points at longitudes (and latitude 0), as reduced statistics
    (identified by the hash of their geometry, as observations identify them).
    """
    geometries = [GeoPoint(longitude, 0) for longitude in longitudes]
    return gpd.GeoDataFrame(
        {"target_hash": [hash_geometry(g) for g in geometries]},
        geometry=geometries,
        crs="EPSG:4326",
    )


def observations_frame(points: gpd.GeoDataFrame, samples: dict) -> gpd.GeoDataFrame:
    """
    Creates aggregated observations of points at times (hours after the
    start), by the index of the point, each one minute long.
    """
    rows = []
    for index, hours in samples.items():
        target_hash = points["target_hash"][index]
        geometry = points.geometry[index]
        for h in hours:
            epoch = START + h * HOUR
            rows.append(
                {
                    "target_hash": target_hash,
                    "start": epoch - timedelta(seconds=30),
                    "epoch": epoch,
                    "end": epoch + timedelta(seconds=30),
                    "geometry": geometry,
                }
            )
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


class ComputeSufficiencyTestCase(TatcTestCase):
    def setUp(self):
        super().setUp()
        # p0 (at local noon at 12:00 UTC) sampled every 6 hours from 03:00,
        # p1 once, and p2 never
        self.points = points_frame([0, 90, -90])
        self.observations = observations_frame(
            self.points, {0: [3, 9, 15, 21], 1: [12]}
        )

    def test_compute_sufficiency(self):
        result = compute_sufficiency(
            self.observations,
            self.points,
            START,
            END,
            timedelta(hours=3),
            standard_deviation=2.0,
            local_time_bins=4,
        )
        points = result.points
        # the points keep their order
        self.assertEqual(
            points["target_hash"].tolist(), self.points["target_hash"].tolist()
        )
        # the error of the evenly spaced samples, as the library computes it
        expected = np.sqrt(
            sampling_error_variance([h * 3600 for h in (3, 9, 15, 21)], 86400, 3 * 3600)
        )
        self.assertAlmostEqual(points["relative_error"][0], expected, places=6)
        self.assertAlmostEqual(points["sampling_error"][0], 2 * expected, places=6)
        # samples 6 hours apart (twice the decorrelation time) repeat each
        # other a little (a correlation of exp(-2) between neighbors)
        self.assertGreater(points["effective_samples"][0], 3)
        self.assertLess(points["effective_samples"][0], 4)
        self.assertEqual(points["revisit_p50"][0], pd.Timedelta(hours=6))
        # the longest gap includes the ends of the period
        self.assertEqual(points["max_gap"][0], pd.Timedelta(hours=6))
        self.assertEqual(points["max_gap"][1], pd.Timedelta(hours=12))
        self.assertEqual(points["max_gap"][2], pd.Timedelta(hours=24))
        self.assertTrue(np.isnan(points["relative_error"][2]))
        # a point not observed has no effective samples
        self.assertEqual(points["effective_samples"][2], 0)
        # p0 is sampled once in each 6-hour interval of its local day
        self.assertEqual(points["local_time_coverage"][0], 1.0)
        self.assertEqual(points["local_time_coverage"][1], 0.25)
        self.assertEqual(points["local_time_coverage"][2], 0.0)
        np.testing.assert_array_equal(result.local_time_samples[0], [1, 1, 1, 1])
        self.assertEqual(result.local_time_samples[1].sum(), 1)
        np.testing.assert_array_equal(result.local_time_samples[2], [0, 0, 0, 0])

    def test_without_standard_deviation(self):
        result = compute_sufficiency(
            self.observations, self.points, START, END, timedelta(hours=3)
        )
        self.assertNotIn("sampling_error", result.points.columns)
        self.assertIn("relative_error", result.points.columns)

    def test_without_observations(self):
        result = compute_sufficiency(
            self.observations.iloc[0:0],
            self.points,
            START,
            END,
            timedelta(hours=3),
            standard_deviation=1.0,
        )
        points = result.points
        self.assertEqual(len(points), 3)
        self.assertTrue(points["relative_error"].isna().all())
        self.assertTrue(points["sampling_error"].isna().all())
        # as points not observed when others are (see test_compute_sufficiency)
        self.assertTrue((points["effective_samples"] == 0).all())
        self.assertTrue((points["max_gap"] == pd.Timedelta(days=1)).all())
        self.assertTrue((points["local_time_coverage"] == 0).all())
        self.assertEqual(result.local_time_samples.sum(), 0)

    def test_grid_sufficiency(self):
        points = compute_sufficiency(
            self.observations,
            self.points,
            START,
            END,
            timedelta(hours=3),
            standard_deviation=1.0,
        ).points
        cells = gpd.GeoDataFrame(
            {"cell_id": ["a", "b", "c"]},
            geometry=[box(-1, -1, 1, 1), box(-180, -1, 180, 1), box(0, 10, 1, 11)],
            crs="EPSG:4326",
        )
        gridded = grid_sufficiency(points, cells, {"a": [0], "b": [0, 1, 2]})
        errors = points["relative_error"].to_numpy(dtype=float)
        self.assertAlmostEqual(gridded["relative_error"][0], errors[0])
        # root-mean-square over the points with an error
        self.assertAlmostEqual(
            gridded["relative_error"][1], np.sqrt(np.mean(errors[:2] ** 2))
        )
        self.assertAlmostEqual(
            gridded["sampling_error"][1], gridded["relative_error"][1]
        )
        # the mean effective samples of the observed points (not p2's zero)
        effective = points["effective_samples"].to_numpy(dtype=float)
        self.assertAlmostEqual(gridded["effective_samples"][1], effective[:2].mean())
        # the longest gap of any point, and the mean local-time coverage (of 8
        # bins: 4 sampled by p0, 1 by p1)
        self.assertEqual(gridded["max_gap"][1], pd.Timedelta(hours=24))
        self.assertAlmostEqual(gridded["local_time_coverage"][1], (0.5 + 0.125) / 3)
        # a cell without points has no values
        self.assertTrue(np.isnan(gridded["relative_error"][2]))
        self.assertTrue(pd.isna(gridded["max_gap"][2]))


class SummarizeSufficiencyTestCase(TatcTestCase):
    def test_summarize_sufficiency(self):
        points = gpd.GeoDataFrame(
            {
                "target_hash": ["p0", "p1", "p2", "p3"],
                "relative_error": [0.1, 0.3, 0.5, np.nan],
                # (zero for p3, not observed, as tatc gives it)
                "effective_samples": [8.0, 4.0, 2.0, 0.0],
                "revisit_p50": [pd.Timedelta(hours=h) for h in (1, 2, 4)] + [pd.NaT],
                "revisit_p90": [pd.Timedelta(hours=h) for h in (2, 4, 8)] + [pd.NaT],
                "max_gap": [pd.Timedelta(hours=h) for h in (3, 6, 12, 24)],
                "local_time_coverage": [1.0, 0.5, 0.25, 0.0],
            },
            geometry=[GeoPoint(0, lat) for lat in (0, 0, 60, 60)],
            crs="EPSG:4326",
        )
        local = np.array([[2, 2], [2, 0], [1, 0], [0, 0]])
        uniform = summarize_sufficiency(
            points,
            local,
            Weighting.uniform,
            timedelta(hours=3),
            target_relative_error=0.3,
        )
        self.assertEqual(uniform.decorrelation_time, 3 * 3600)
        self.assertIsNone(uniform.standard_deviation)
        self.assertIsNone(uniform.sampling_error)
        # the point without samples falls short of the target
        self.assertAlmostEqual(uniform.sufficient, 0.5)
        self.assertEqual(uniform.relative_error.count, 3)
        self.assertAlmostEqual(uniform.relative_error.mean, 0.3)
        self.assertAlmostEqual(sum(uniform.relative_error_histogram.shares), 1)
        # of the observed points only
        self.assertEqual(uniform.effective_samples.count, 3)
        self.assertAlmostEqual(uniform.effective_samples.median, 4)
        self.assertAlmostEqual(uniform.effective_samples.mean, 14 / 3)
        self.assertEqual(uniform.revisit_p90.count, 3)
        # every point has a longest gap, the whole period if not observed
        self.assertEqual(uniform.max_gap.count, 4)
        self.assertEqual(uniform.max_gap.max, 24 * 3600)
        self.assertAlmostEqual(uniform.local_time_coverage, 1.75 / 4)
        np.testing.assert_allclose(uniform.local_time_shares, [5 / 7, 2 / 7])
        # by area, points at 60 degrees count half as much as at the equator
        area = summarize_sufficiency(
            points,
            local,
            Weighting.area,
            timedelta(hours=3),
            target_relative_error=0.3,
        )
        self.assertAlmostEqual(area.sufficient, 2 / 3)
        np.testing.assert_allclose(area.local_time_shares, [4.5 / 6.5, 2 / 6.5])
        # without a target, no share meets it
        self.assertIsNone(
            summarize_sufficiency(
                points, local, Weighting.uniform, timedelta(hours=3)
            ).sufficient
        )

    def test_summarize_sufficiency_without_samples(self):
        points = gpd.GeoDataFrame(
            {
                "target_hash": ["p0"],
                "relative_error": [np.nan],
                "sampling_error": [np.nan],
                "effective_samples": [np.nan],
                "revisit_p50": [pd.NaT],
                "revisit_p90": [pd.NaT],
                "max_gap": [pd.Timedelta(days=1)],
                "local_time_coverage": [0.0],
            },
            geometry=[GeoPoint(0, 0)],
            crs="EPSG:4326",
        )
        summary = summarize_sufficiency(
            points,
            np.zeros((1, 8)),
            Weighting.uniform,
            timedelta(hours=3),
            standard_deviation=1.0,
            target_relative_error=0.2,
        )
        self.assertEqual(summary.sufficient, 0)
        self.assertIsNone(summary.relative_error)
        self.assertIsNone(summary.relative_error_histogram)
        self.assertIsNone(summary.sampling_error)
        self.assertEqual(summary.max_gap.max, 86400)
        self.assertEqual(summary.local_time_shares, [0.0] * 8)
