from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
from tatc.analysis import (
    aggregate_observations,
    collect_observations,
    estimate_sampling_error,
    grid_observations,
    reduce_observations,
)
from tatc.generation import (
    generate_cells_uniform_spacing,
    generate_points_uniform_spacing,
)
from tatc.schemas import (
    GeneralPerturbationsOrbit,
    Instrument,
    Point,
    WalkerConstellation,
)

from tatc_app.coverage.schemas import (
    CoverageAnalysisRequest,
    CoverageAnalysisResult,
    SufficiencyOptions,
)
from tatc_app.generation.schemas import CellGenerator, PointGenerator
from tatc_app.utils.serialization import from_geojson

from .base import TLE, TatcTestCase


class CoverageAnalysisTestCase(TatcTestCase):
    def setUp(self):
        super().setUp()
        self.satellite = WalkerConstellation(
            name="Test",
            orbit=GeneralPerturbationsOrbit.from_tle(TLE),
            instruments=[Instrument(name="Test", field_of_regard=180.0)],
            number_satellites=4,
            number_planes=2,
        )
        self.start = datetime(2022, 6, 1, tzinfo=timezone.utc)
        self.end = datetime(2022, 6, 2, tzinfo=timezone.utc)

    def test_analyze_coverage(self):
        result = self.analysis_result(
            "/analyze/coverage",
            CoverageAnalysisRequest(
                satellites=[self.satellite],
                colors=["#ff0000"],
                start=self.start,
                end=self.end,
                points=PointGenerator(method="equally_spaced", distance=5000e3),
                cells=CellGenerator(method="equally_spaced", distance=5000e3),
            ),
            CoverageAnalysisResult,
        )
        points = generate_points_uniform_spacing(5000e3)
        cells = generate_cells_uniform_spacing(5000e3)
        members = self.satellite.generate_members()
        expected = reduce_observations(
            aggregate_observations(
                collect_observations(
                    points, members, self.start, self.end, instrument_index=None
                )
            ),
            targets=points,
        )
        # every point is reported, including unobserved ones
        actual = from_geojson(
            result.points.model_dump_json(), timedeltas=["access", "revisit"]
        )
        self.assertEqual(len(actual), len(points))
        merged = actual.merge(
            expected, on="target_hash", suffixes=("", "_expected"), how="outer"
        )
        self.assertEqual(len(merged), len(points))
        self.assertTrue((merged["samples"] == merged["samples_expected"]).all())
        self.assertTrue(
            (
                (merged["revisit"] - merged["revisit_expected"])
                .abs()
                .fillna(pd.Timedelta(0))
                < timedelta(seconds=1)
            ).all()
        )
        # every cell is reported
        self.assertEqual(len(result.cells.features), len(cells))
        expected_cells = grid_observations(expected, cells)
        self.assertEqual(
            sorted(f.properties["samples"] for f in result.cells.features),
            sorted(expected_cells["samples"].tolist()),
        )
        # timeline has one event per aggregated observation
        self.assertEqual(len(result.timeline.targets), len(points))
        self.assertEqual(
            sorted(result.timeline.members), sorted(m.name for m in members)
        )
        self.assertEqual(len(result.timeline.start), int(expected["samples"].sum()))
        self.assertTrue(all(s >= 0 for s in result.timeline.start))
        # cells map to points
        self.assertTrue(len(result.cell_targets) > 0)
        # sampling sufficiency is not assessed unless requested
        self.assertNotIn("relative_error", result.points.features[0].properties)
        self.assertNotIn("relative_error", result.cells.features[0].properties)
        self.assertIsNone(result.summary.sufficiency)
        # tracks for each member, colored by constellation
        self.assertEqual(len(result.tracks.tracks), len(members))
        self.assertTrue(all(c == "#ff0000" for c in result.colors.values()))
        # czml document
        czml = self.get_json(f"/analyze/coverage/{self.task_id}/czml")
        self.assertEqual(czml[0]["id"], "document")
        self.assertEqual(
            {p["id"] for p in czml[1:]},
            {f"sat/{m.name}" for m in members} | {f"fp/{m.name}/0" for m in members},
        )

    def test_analyze_coverage_sufficiency(self):
        result = self.analysis_result(
            "/analyze/coverage",
            CoverageAnalysisRequest(
                satellites=[self.satellite],
                start=self.start,
                end=self.end,
                points=PointGenerator(method="equally_spaced", distance=5000e3),
                cells=CellGenerator(method="equally_spaced", distance=5000e3),
                sufficiency=SufficiencyOptions(
                    decorrelation_time=timedelta(hours=3),
                    standard_deviation=2.0,
                    target_relative_error=0.3,
                    local_time_bins=6,
                ),
            ),
            CoverageAnalysisResult,
        )
        points = generate_points_uniform_spacing(5000e3)
        observations = aggregate_observations(
            collect_observations(
                points,
                self.satellite.generate_members(),
                self.start,
                self.end,
                instrument_index=None,
            )
        )
        expected = estimate_sampling_error(
            observations,
            self.start,
            self.end,
            timedelta(hours=3),
            2.0,
            targets=points.geometry,
        )
        actual = from_geojson(
            result.points.model_dump_json(),
            timedeltas=["revisit_p50", "revisit_p90", "max_gap"],
        )
        merged = actual.merge(
            expected.drop(columns="geometry"),
            on="target_hash",
            suffixes=("", "_expected"),
        )
        self.assertEqual(len(merged), len(points))
        np.testing.assert_allclose(
            merged["relative_error"].to_numpy(dtype=float),
            merged["relative_error_expected"].to_numpy(dtype=float),
            equal_nan=True,
        )
        np.testing.assert_allclose(
            merged["sampling_error"].to_numpy(dtype=float),
            2 * merged["relative_error"].to_numpy(dtype=float),
            equal_nan=True,
        )
        # every point has a longest gap within the period
        self.assertTrue((actual["max_gap"] <= self.end - self.start).all())
        self.assertTrue(actual["local_time_coverage"].between(0, 1).all())
        # cells have the sufficiency of their points
        properties = result.cells.features[0].properties
        for column in (
            "relative_error",
            "sampling_error",
            "effective_samples",
            "max_gap",
            "local_time_coverage",
        ):
            self.assertIn(column, properties)
        # the summary
        summary = result.summary.sufficiency
        self.assertEqual(summary.decorrelation_time, 3 * 3600)
        self.assertEqual(summary.standard_deviation, 2.0)
        self.assertEqual(len(summary.local_time_shares), 6)
        self.assertAlmostEqual(sum(summary.local_time_shares), 1)
        self.assertEqual(
            summary.relative_error.count, int(actual["relative_error"].notna().sum())
        )
        self.assertGreaterEqual(summary.sufficient, 0)
        self.assertLessEqual(summary.sufficient, result.summary.observed)

    def test_analyze_coverage_invalid_sufficiency(self):
        for sufficiency in (
            {"decorrelationTime": 0},
            {"decorrelation_time": -60},
            {"decorrelationTime": 3600, "localTimeBins": 0},
            {"decorrelationTime": 3600, "standardDeviation": 0},
        ):
            response = self.client.post(
                "/analyze/coverage",
                json={
                    "satellites": [self.satellite.model_dump(mode="json")],
                    "start": "2022-06-01T00:00:00Z",
                    "end": "2022-06-02T00:00:00Z",
                    "points": {"method": "equally_spaced", "distance": 5000e3},
                    "cells": {"method": "equally_spaced", "distance": 5000e3},
                    "sufficiency": sufficiency,
                },
            )
            self.assertEqual(response.status_code, 422, sufficiency)

    def test_analyze_coverage_points_list(self):
        points = [
            Point(id=0, latitude=0, longitude=0),
            Point(id=1, latitude=40, longitude=-100),
        ]
        result = self.analysis_result(
            "/analyze/coverage",
            CoverageAnalysisRequest(
                satellites=[self.satellite],
                start=self.start,
                end=self.end,
                points=points,
                cells=[
                    {
                        "type": "Polygon",
                        "coordinates": [
                            [[-10, -10], [10, -10], [10, 10], [-10, 10], [-10, -10]]
                        ],
                    }
                ],
            ),
            CoverageAnalysisResult,
        )
        self.assertEqual(len(result.points.features), 2)
        self.assertEqual(len(result.cells.features), 1)
        self.assertEqual(list(result.cell_targets.values()), [[0]])

    def test_analyze_coverage_naive_time(self):
        response = self.client.post(
            "/analyze/coverage",
            json={
                "satellites": [self.satellite.model_dump(mode="json")],
                "start": "2022-06-01T00:00:00",
                "end": "2022-06-02T00:00:00",
                "points": {"method": "equally_spaced", "distance": 5000e3},
                "cells": {"method": "equally_spaced", "distance": 5000e3},
            },
        )
        self.assertEqual(response.status_code, 422)
