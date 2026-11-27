import os
from datetime import datetime, timedelta, timezone
from unittest import mock

import numpy as np
from celery.exceptions import TimeoutError as CeleryTimeoutError
from fastapi import HTTPException
from shapely.geometry import box
from tatc.constants import EARTH_MEAN_RADIUS
from tatc.generation._grid import generate_indices_uniform_spacing
from tatc.schemas import GeneralPerturbationsOrbit, Instrument, Point, Satellite

from tatc_app import limits
from tatc_app.celery.quota import TaskQuota, analysis_quota
from tatc_app.coverage.schemas import CoverageAnalysisRequest
from tatc_app.generation.schemas import CellGenerator, PointGenerator
from tatc_app.generation.tasks import count_uniform_candidates, generate_points_task
from tatc_app.worker import app as celery_app

from .base import TLE, TatcTestCase

START = datetime(2022, 6, 1, tzinfo=timezone.utc)


def coverage_request(**kwargs) -> CoverageAnalysisRequest:
    """
    Creates a (small) coverage analysis request.
    """
    return CoverageAnalysisRequest(
        **{
            "satellites": [
                Satellite(
                    name="Test",
                    orbit=GeneralPerturbationsOrbit.from_tle(TLE),
                    instruments=[Instrument(name="Test", field_of_regard=180.0)],
                )
            ],
            "start": START,
            "end": START + timedelta(hours=6),
            "points": PointGenerator(method="equally_spaced", distance=5000e3),
            "cells": CellGenerator(method="equally_spaced", distance=5000e3),
            **kwargs,
        }
    )


class GenerationLimitsTestCase(TatcTestCase):
    def test_distance_must_be_positive(self):
        for path in ("/generate/points", "/generate/cells"):
            for distance in (0, -1000):
                with self.subTest(path=path, distance=distance):
                    response = self.client.post(path, json={"distance": distance})
                    self.assertEqual(response.status_code, 422, response.text)

    def test_too_many_candidate_points(self):
        for method in ("fibonacci_lattice", "equally_spaced"):
            with self.subTest(method=method):
                response = self.client.post(
                    "/generate/points", json={"method": method, "distance": 1e3}
                )
                self.assertEqual(response.status_code, 422, response.text)
                self.assertIn("candidate points", response.json()["detail"])

    def test_too_many_candidate_cells(self):
        response = self.client.post("/generate/cells", json={"distance": 1e3})
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("candidate cells", response.json()["detail"])

    def test_fine_grid_in_small_mask(self):
        # equally spaced candidates cover only the bounds of the mask
        mask = {
            "type": "Polygon",
            "coordinates": [
                [[-112, 33], [-111, 33], [-111, 34], [-112, 34], [-112, 33]]
            ],
        }
        response = self.client.post(
            "/generate/points",
            json={"method": "equally_spaced", "distance": 5e3, "mask": mask},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertGreater(len(response.json()["features"]), 100)

    def test_too_many_points(self):
        with mock.patch.object(limits, "MAX_POINTS", 10):
            response = self.client.post("/generate/points", json={"distance": 2000e3})
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("Too many points", response.json()["detail"])

    def test_too_many_cells(self):
        with mock.patch.object(limits, "MAX_CELLS", 10):
            response = self.client.post("/generate/cells", json={"distance": 2000e3})
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("Too many cells", response.json()["detail"])

    def test_generation_timeout(self):
        # no worker generates the points in time
        result = mock.Mock()
        result.get.side_effect = CeleryTimeoutError()
        with (
            mock.patch.object(limits, "GENERATION_TIMEOUT", 5),
            mock.patch.object(generate_points_task, "delay", return_value=result),
        ):
            response = self.client.post("/generate/points", json={"distance": 2000e3})
        self.assertEqual(response.status_code, 503, response.text)
        result.get.assert_called_once_with(timeout=5)
        result.revoke.assert_called_once()

    def test_count_uniform_candidates(self):
        # the count must agree with the grid TAT-C generates
        masks = [None, box(-112, 33, -111, 34), box(100, -50, 179.5, 10)]
        for distance in (50e3, 333e3, 1000e3):
            for mask in masks:
                for strips in (None, "lat", "lon"):
                    with self.subTest(distance=distance, mask=mask, strips=strips):
                        theta = np.degrees(distance / EARTH_MEAN_RADIUS)
                        self.assertEqual(
                            count_uniform_candidates(distance, mask, strips),
                            len(
                                generate_indices_uniform_spacing(
                                    theta, theta, mask, strips
                                )
                            ),
                        )


class CoverageTestCase(TatcTestCase):
    def post_coverage(self, request: CoverageAnalysisRequest):
        return self.client.post(
            "/analyze/coverage",
            content=request.model_dump_json(),
            headers={"Content-Type": "application/json"},
        )


class AnalysisLimitsTestCase(CoverageTestCase):
    def test_analysis_period_too_long(self):
        request = coverage_request(end=START + timedelta(days=2))
        with mock.patch.object(limits, "MAX_ANALYSIS_DURATION", timedelta(days=1)):
            response = self.post_coverage(request)
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("must not exceed 1 days", response.text)

    def test_too_many_listed_points(self):
        request = coverage_request(
            points=[Point(id=i, latitude=0, longitude=i) for i in range(5)]
        )
        with mock.patch.object(limits, "MAX_POINTS", 4):
            response = self.post_coverage(request)
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("Too many points", response.text)

    def test_too_many_generated_points(self):
        with mock.patch.object(limits, "MAX_POINTS", 2):
            response = self.post_coverage(coverage_request())
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("Too many points", response.text)


class ActiveAnalysesTestCase(CoverageTestCase):
    def tearDown(self):
        super().tearDown()
        analysis_quota._running.clear()  # pylint: disable=protected-access

    def test_limit_running_analyses(self):
        request = coverage_request()
        with (
            mock.patch.object(limits, "MAX_ACTIVE_ANALYSES", 1),
            mock.patch.object(analysis_quota, "_is_ready", lambda task_id: False),
        ):
            first = self.post_coverage(request)
            self.assertEqual(first.status_code, 200, first.text)
            second = self.post_coverage(request)
            self.assertEqual(second.status_code, 429, second.text)
            # revoking the first analysis frees its slot
            with mock.patch.object(celery_app.control, "revoke"):
                self.client.post(f"/tasks/{first.json()['task_id']}/revoke")
            third = self.post_coverage(request)
            self.assertEqual(third.status_code, 200, third.text)

    def test_tracks_count_as_analyses(self):
        satellite = coverage_request().satellites[0].model_dump(mode="json")
        track = {
            "satellite": satellite,
            "times": [(START + timedelta(minutes=i)).isoformat() for i in range(3)],
        }
        with (
            mock.patch.object(limits, "MAX_ACTIVE_ANALYSES", 1),
            mock.patch.object(analysis_quota, "_is_ready", lambda task_id: False),
        ):
            first = self.client.post("/analyze/orbit-track", json=track)
            self.assertEqual(first.status_code, 200, first.text)
            for response in (
                self.client.post("/analyze/ground-track", json=track),
                self.post_coverage(coverage_request()),
            ):
                self.assertEqual(response.status_code, 429, response.text)

    def test_every_analysis_counts(self):
        body = coverage_request(end=START + timedelta(hours=1)).model_dump(mode="json")
        satellites = [
            body["satellites"][0],
            dict(body["satellites"][0], name="Other"),
        ]
        point = {"id": 0, "latitude": 0, "longitude": 0}
        station = {"name": "GS", "latitude": 40, "longitude": -105}
        requests = {
            "coverage": body,
            "coincidence": body | {"satellites": satellites},
            "latency": body | {"stations": [station]},
            "overflight": body | {"points": [point]},
            "swaths": {k: body[k] for k in ("satellites", "start", "end")},
        }
        with (
            mock.patch.object(limits, "MAX_ACTIVE_ANALYSES", 1),
            mock.patch.object(analysis_quota, "_is_ready", lambda task_id: False),
        ):
            for analysis, request in requests.items():
                with self.subTest(analysis):
                    first = self.client.post(f"/analyze/{analysis}", json=request)
                    self.assertEqual(first.status_code, 200, first.text)
                    second = self.client.post(f"/analyze/{analysis}", json=request)
                    self.assertEqual(second.status_code, 429, second.text)
                analysis_quota._running.clear()  # pylint: disable=protected-access

    def test_failed_request_releases_slot(self):
        request = coverage_request()
        with mock.patch.object(limits, "MAX_ACTIVE_ANALYSES", 1):
            with mock.patch.object(limits, "MAX_POINTS", 2):
                response = self.post_coverage(request)
            self.assertEqual(response.status_code, 422, response.text)
            self.assertEqual(analysis_quota.running("local"), 0)
            response = self.post_coverage(request)
            self.assertEqual(response.status_code, 200, response.text)


class TaskQuotaTestCase(TatcTestCase):
    def setUp(self):
        super().setUp()
        self.ready = set()
        self.max_age = 3600
        self.quota = TaskQuota(
            lambda: 2, lambda: self.max_age, lambda task_id: task_id in self.ready
        )

    def test_limit(self):
        self.quota.reserve("a").track({"task_id": "1"})
        self.quota.reserve("a").track({"task_id": "2"})
        with self.assertRaises(HTTPException) as context:
            self.quota.reserve("a")
        self.assertEqual(context.exception.status_code, 429)
        # other users have their own limit
        self.quota.reserve("b").track({"task_id": "3"})
        # a ready task no longer counts
        self.ready.add("1")
        self.quota.reserve("a").track({"task_id": "4"})
        self.assertEqual(self.quota.running("a"), 2)

    def test_unbound_reservation(self):
        slot = self.quota.reserve("a")
        self.assertEqual(self.quota.running("a"), 1)
        slot.close()
        self.assertEqual(self.quota.running("a"), 0)

    def test_bound_slot_stays_after_close(self):
        slot = self.quota.reserve("a")
        slot.track({"task_id": "1"})
        slot.close()
        self.assertEqual(self.quota.running("a"), 1)

    def test_release_task(self):
        self.quota.reserve("a").track({"task_id": "1"})
        self.quota.release_task("1")
        self.assertEqual(self.quota.running("a"), 0)

    def test_expired_tasks(self):
        self.quota.reserve("a").track({"task_id": "1"})
        self.max_age = -1
        self.assertEqual(self.quota.running("a"), 0)

    def test_no_limit(self):
        quota = TaskQuota(lambda: 0, lambda: 3600, lambda task_id: False)
        for i in range(10):
            quota.reserve("a").track({"task_id": str(i)})
        self.assertEqual(quota.running("a"), 10)


class CeleryLimitsTestCase(TatcTestCase):
    def test_celery_configuration(self):
        self.assertEqual(celery_app.conf.result_expires, limits.RESULT_EXPIRES)
        self.assertEqual(celery_app.conf.task_time_limit, limits.TASK_TIME_LIMIT)

    def test_invalid_environment(self):
        # pylint: disable=protected-access
        with mock.patch.dict(os.environ, {"TATC_TEST_LIMIT": "-1"}):
            with self.assertRaises(ValueError):
                limits._env_number("TATC_TEST_LIMIT", 1)
        with mock.patch.dict(os.environ, {"TATC_TEST_LIMIT": "2.5"}):
            self.assertEqual(limits._env_number("TATC_TEST_LIMIT", 1), 2.5)
        self.assertEqual(limits._env_number("TATC_TEST_UNSET", 7), 7)
