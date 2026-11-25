from datetime import datetime, timedelta, timezone

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point as GeoPoint
from shapely.geometry import box
from tatc.analysis import (
    aggregate_observations,
    collect_observations,
    compute_sample_sizes,
    reduce_observations,
)
from tatc.generation import generate_points_uniform_spacing
from tatc.schemas import (
    ConicalInstrument,
    Instrument,
    PointedInstrument,
    Satellite,
    SunSynchronousOrbit,
)

from tatc_app.analysis.sample_sizes import (
    POINT_COLUMNS,
    add_point_sizes,
    grid_sample_sizes,
    is_sized,
    meets_requirement,
    size_observations,
    summarize_point_sizes,
)
from tatc_app.analysis.summary import Weighting, summarize_sample_sizes
from tatc_app.coincidence.schemas import (
    CoincidenceAnalysisRequest,
    CoincidenceAnalysisResult,
)
from tatc_app.coverage.schemas import (
    CoverageAnalysisRequest,
    CoverageAnalysisResult,
    SampleSizeOptions,
)
from tatc_app.generation.schemas import CellGenerator, PointGenerator
from tatc_app.utils.serialization import from_geojson

from .base import TatcTestCase

START = datetime(2022, 6, 1, tzinfo=timezone.utc)
END = datetime(2022, 6, 2, tzinfo=timezone.utc)
ORBIT = SunSynchronousOrbit(
    altitude=705e3, equator_crossing_time="13:30", equator_crossing_ascending=True
)
# a 100-degree swath of 1000 pixels: about 1 km at nadir, growing off nadir
POINTED = PointedInstrument(
    name="P",
    cross_track_field_of_view=100,
    along_track_field_of_view=0.1,
    cross_track_pixels=1000,
)


def satellite(name="A", instruments=None) -> Satellite:
    return Satellite(name=name, orbit=ORBIT, instruments=instruments or [POINTED])


class SampleSizeFunctionsTestCase(TatcTestCase):
    def setUp(self):
        super().setUp()
        self.points = generate_points_uniform_spacing(1000e3)

    def test_is_sized(self):
        self.assertTrue(is_sized(POINTED))
        self.assertFalse(is_sized(Instrument(name="S")))
        conical = ConicalInstrument(
            name="C", cone_angle=45, along_track_field_of_view=1
        )
        self.assertFalse(is_sized(conical))
        self.assertTrue(
            is_sized(
                conical.model_copy(update={"beam_width": 1, "scan_sample_spacing": 1})
            )
        )

    def test_size_observations(self):
        sat = satellite(
            instruments=[POINTED, Instrument(name="S", field_of_regard=100)]
        )
        observations = collect_observations(
            self.points, [sat], START, END, instrument_index=None
        )
        sized = size_observations(observations, [sat])
        self.assertEqual(len(sized), len(observations))
        pointed = sized[sized.instrument == "P"]
        simple = sized[sized.instrument == "S"]
        self.assertTrue(pointed.sample_size.notna().all())
        self.assertTrue(simple.sample_size.isna().all())
        # the larger of the pixel and its spacing, along and across track
        expected = compute_sample_sizes(observations, [sat])[
            ["sample_along", "sample_cross", "spacing_along", "spacing_cross"]
        ].max(axis=1, skipna=False)
        np.testing.assert_allclose(sized.sample_size, expected, equal_nan=True)
        # about 1 km at nadir, larger off nadir
        self.assertGreater(pointed.sample_size.min(), 500)
        self.assertLess(pointed.sample_size.min(), 2000)
        self.assertGreater(pointed.sample_size.max(), 2 * pointed.sample_size.min())
        # nothing to size
        self.assertTrue(size_observations(observations.iloc[0:0], [sat]).empty)

    def test_requirement_and_point_sizes(self):
        sized = pd.DataFrame(
            {
                "target_hash": ["a", "a", "a", "b", "b"],
                "sample_size": [1000.0, 3000.0, np.nan, 500.0, 2500.0],
            }
        )
        np.testing.assert_array_equal(
            meets_requirement(sized, 2000), [True, False, False, True, False]
        )
        self.assertTrue(meets_requirement(sized, None).all())
        sizes = summarize_point_sizes(sized, 2000).set_index("target_hash")
        self.assertEqual(sizes.loc["a", "sample_size_median"], 2000)
        self.assertEqual(sizes.loc["a", "sample_size_min"], 1000)
        self.assertEqual(
            list(sizes.loc["a", ["observations", "observations_sized"]]), [3, 2]
        )
        self.assertEqual(sizes.loc["a", "observations_meeting"], 1)
        # without a requirement, the sized observations meet it
        sizes = summarize_point_sizes(sized).set_index("target_hash")
        self.assertEqual(sizes.loc["b", "observations_meeting"], 2)
        self.assertEqual(
            list(summarize_point_sizes(sized.iloc[0:0]).columns), POINT_COLUMNS
        )

    def test_add_grid_and_summarize(self):
        points = gpd.GeoDataFrame(
            {"target_hash": ["a", "b", "c"]},
            geometry=[GeoPoint(0, 0), GeoPoint(1, 0), GeoPoint(0, 60)],
            crs="EPSG:4326",
        )
        sizes = pd.DataFrame(
            {
                "target_hash": ["b", "a"],
                "sample_size_median": [2000.0, 1000.0],
                "sample_size_min": [1500.0, 800.0],
                "observations": [4, 2],
                "observations_sized": [4, 2],
                "observations_meeting": [1, 2],
            }
        )
        added = add_point_sizes(points, sizes)
        # in the order of the points, and none for the point not observed
        self.assertEqual(list(added.sample_size_median[:2]), [1000, 2000])
        self.assertTrue(np.isnan(added.sample_size_median[2]))
        self.assertEqual(list(added.observations), [2, 4, 0])
        cells = gpd.GeoDataFrame(
            {"cell_id": ["x", "y"]},
            geometry=[box(-1, -1, 2, 1), box(-1, 59, 1, 61)],
            crs="EPSG:4326",
        )
        gridded = grid_sample_sizes(added, cells, {"x": [0, 1], "y": [2]})
        self.assertEqual(gridded.sample_size_median[0], 1500)
        self.assertEqual(gridded.sample_size_min[0], 800)
        self.assertTrue(np.isnan(gridded.sample_size_median[1]))
        summary = summarize_sample_sizes(added, Weighting.uniform, 1200)
        self.assertEqual(summary.max_sample_size, 1200)
        self.assertEqual(
            (summary.observations, summary.sized, summary.meeting), (6, 6, 3)
        )
        self.assertEqual(summary.median.count, 2)
        self.assertEqual(summary.median.mean, 1500)
        self.assertEqual(summary.best.max, 1500)
        self.assertIsNone(summarize_sample_sizes(added, Weighting.uniform).meeting)


class SampleSizeEndpointsTestCase(TatcTestCase):
    def request(self, satellites=None, **kwargs) -> CoverageAnalysisRequest:
        return CoverageAnalysisRequest(
            satellites=satellites or [satellite()],
            start=START,
            end=END,
            points=PointGenerator(method="equally_spaced", distance=1000e3),
            cells=CellGenerator(method="equally_spaced", distance=5000e3),
            **kwargs,
        )

    def analyze(self, request) -> CoverageAnalysisResult:
        task = self.run_analysis("/analyze/coverage", request)
        return CoverageAnalysisResult.model_validate(
            self.get_json(f"/analyze/coverage/{task['task_id']}")
        )

    def test_coverage_sample_sizes(self):
        result = self.analyze(self.request(sample_size=SampleSizeOptions()))
        points = from_geojson(result.points.model_dump_json())
        observed = points[points.samples > 0]
        self.assertTrue(observed.sample_size_median.notna().all())
        self.assertTrue((observed.sample_size_min <= observed.sample_size_median).all())
        self.assertTrue(points[points.samples == 0].sample_size_median.isna().all())
        self.assertIn("sample_size_median", result.cells.features[0].properties)
        summary = result.summary.sample_size
        self.assertIsNone(summary.max_sample_size)
        self.assertEqual(summary.sized, summary.observations)
        self.assertGreater(summary.sized, 0)
        self.assertIsNone(summary.meeting)
        # without the option, no sizes
        plain = self.analyze(self.request())
        self.assertIsNone(plain.summary.sample_size)
        self.assertNotIn("sample_size_median", plain.points.features[0].properties)

    def test_coverage_max_sample_size(self):
        request = self.request(sample_size=SampleSizeOptions(max_sample_size=1500))
        result = self.analyze(request)
        # the observations at most 1.5 km, aggregated and reduced
        points = generate_points_uniform_spacing(1000e3)
        members = request.get_members()
        sized = size_observations(
            collect_observations(points, members, START, END, instrument_index=None),
            members,
        )
        kept = sized[sized.sample_size <= 1500].drop(columns="sample_size")
        expected = reduce_observations(aggregate_observations(kept), targets=points)
        actual = from_geojson(result.points.model_dump_json())
        merged = actual.merge(expected, on="target_hash", suffixes=("", "_expected"))
        self.assertEqual(len(merged), len(points))
        self.assertTrue((merged.samples == merged.samples_expected).all())
        summary = result.summary.sample_size
        self.assertEqual(summary.meeting, int((sized.sample_size <= 1500).sum()))
        self.assertLess(summary.meeting, summary.sized)
        self.assertEqual(int(actual.observations_meeting.sum()), summary.meeting)

    def test_coincidence_max_sample_size(self):
        satellites = [
            satellite("A"),
            satellite("B").model_copy(
                update={
                    "orbit": ORBIT.model_copy(update={"equator_crossing_time": "13:40"})
                }
            ),
        ]
        base = {
            "satellites": satellites,
            "start": START,
            "end": END,
            "points": PointGenerator(method="equally_spaced", distance=1000e3),
            "cells": CellGenerator(method="equally_spaced", distance=5000e3),
            "max_time_difference": timedelta(hours=1),
        }
        counts = []
        for sample_size in (None, SampleSizeOptions(max_sample_size=1500)):
            request = CoincidenceAnalysisRequest(**base, sample_size=sample_size)
            task = self.run_analysis("/analyze/coincidence", request)
            result = CoincidenceAnalysisResult.model_validate(
                self.get_json(f"/analyze/coincidence/{task['task_id']}")
            )
            counts.append(sum(f.properties["samples"] for f in result.points.features))
            # coincidences have no sample size statistics
            self.assertIsNone(result.summary.sample_size)
        self.assertGreater(counts[0], 0)
        self.assertLess(counts[1], counts[0])

    def test_requirement_needs_pixels(self):
        simple = satellite(instruments=[Instrument(name="S", field_of_regard=100)])
        body = self.request(satellites=[simple]).model_dump(mode="json")
        # sizes without a requirement are allowed (and undefined)
        self.assertEqual(
            self.client.post(
                "/analyze/coverage", json=body | {"sampleSize": {}}
            ).status_code,
            200,
        )
        for sample_size in ({"maxSampleSize": 1000}, {"maxSampleSize": 0}):
            response = self.client.post(
                "/analyze/coverage", json=body | {"sampleSize": sample_size}
            )
            self.assertEqual(response.status_code, 422, sample_size)
        self.assertIn(
            "instruments with pixels",
            self.client.post(
                "/analyze/coverage", json=body | {"sampleSize": {"maxSampleSize": 1000}}
            ).text,
        )
