from datetime import datetime, timedelta, timezone

import pandas as pd
from tatc.analysis import (
    aggregate_observations,
    collect_observations,
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

from tatc_app.coverage.schemas import CoverageAnalysisRequest, CoverageAnalysisResult
from tatc_app.generation.schemas import CellGenerator, PointGenerator
from tatc_app.utils.serialization import from_geojson

from .base import TatcTestCase

TLE = [
    "1 25544U 98067A   22171.11255782  .00008307  00000+0  15444-3 0  9992",
    "2 25544  51.6448 322.0970 0003980 282.3738 231.6559 15.49798078345636",
]


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
        task = self.run_analysis(
            "/analyze/coverage",
            CoverageAnalysisRequest(
                satellites=[self.satellite],
                colors=["#ff0000"],
                start=self.start,
                end=self.end,
                points=PointGenerator(method="equally_spaced", distance=5000e3),
                cells=CellGenerator(method="equally_spaced", distance=5000e3),
            ),
        )
        result = CoverageAnalysisResult.model_validate(
            self.get_json(f"/analyze/coverage/{task['task_id']}")
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
        # tracks for each member, colored by constellation
        self.assertEqual(len(result.tracks.tracks), len(members))
        self.assertTrue(all(c == "#ff0000" for c in result.colors.values()))
        # czml document
        czml = self.get_json(f"/analyze/coverage/{task['task_id']}/czml")
        self.assertEqual(czml[0]["id"], "document")
        self.assertEqual(
            {p["id"] for p in czml[1:]}, {f"sat/{m.name}" for m in members}
        )

    def test_analyze_coverage_points_list(self):
        points = [
            Point(id=0, latitude=0, longitude=0),
            Point(id=1, latitude=40, longitude=-100),
        ]
        task = self.run_analysis(
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
        )
        result = CoverageAnalysisResult.model_validate(
            self.get_json(f"/analyze/coverage/{task['task_id']}")
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
