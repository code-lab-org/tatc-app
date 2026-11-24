from datetime import datetime, timezone
from unittest import mock
from uuid import uuid4

from celery.result import AsyncResult, GroupResult
from tatc.schemas import GeneralPerturbationsOrbit, Instrument, WalkerConstellation

from tatc_app.coverage.schemas import CoverageAnalysisRequest
from tatc_app.generation.schemas import CellGenerator, PointGenerator
from tatc_app.worker import app as celery_app

from .base import TatcTestCase

TLE = [
    "1 25544U 98067A   22171.11255782  .00008307  00000+0  15444-3 0  9992",
    "2 25544  51.6448 322.0970 0003980 282.3738 231.6559 15.49798078345636",
]


class TaskRevokeTestCase(TatcTestCase):
    def run_coverage(self) -> dict:
        return self.run_analysis(
            "/analyze/coverage",
            CoverageAnalysisRequest(
                satellites=[
                    WalkerConstellation(
                        name="Test",
                        orbit=GeneralPerturbationsOrbit.from_tle(TLE),
                        instruments=[Instrument(name="Test", field_of_regard=180.0)],
                        number_satellites=2,
                        number_planes=1,
                    )
                ],
                colors=["#ff0000"],
                start=datetime(2022, 6, 1, tzinfo=timezone.utc),
                end=datetime(2022, 6, 1, 6, tzinfo=timezone.utc),
                points=PointGenerator(method="equally_spaced", distance=5000e3),
                cells=CellGenerator(method="equally_spaced", distance=5000e3),
            ),
        )

    def test_revoke_task(self):
        task_id = str(uuid4())
        with mock.patch.object(celery_app.control, "revoke") as revoke:
            response = self.client.post(f"/tasks/{task_id}/revoke")
        self.assertEqual(response.status_code, 204, response.text)
        revoke.assert_called_once_with([task_id])

    def test_revoke_unknown_group(self):
        task_id = str(uuid4())
        with mock.patch.object(celery_app.control, "revoke") as revoke:
            response = self.client.post(
                f"/tasks/{task_id}/revoke", params={"group_id": str(uuid4())}
            )
        self.assertEqual(response.status_code, 204, response.text)
        revoke.assert_called_once_with([task_id])

    def test_revoke_group(self):
        task_id = str(uuid4())
        children = [str(uuid4()) for _ in range(3)]
        group = GroupResult(
            str(uuid4()),
            [AsyncResult(child, app=celery_app) for child in children],
            app=celery_app,
        )
        group.save()
        with mock.patch.object(celery_app.control, "revoke") as revoke:
            response = self.client.post(
                f"/tasks/{task_id}/revoke", params={"group_id": group.id}
            )
        self.assertEqual(response.status_code, 204, response.text)
        revoke.assert_called_once_with([task_id] + children)

    def test_revoke_completed_task(self):
        task = self.run_coverage()
        response = self.client.post(
            f"/tasks/{task['task_id']}/revoke",
            params={"group_id": task["group_id"]} if task.get("group_id") else {},
        )
        self.assertEqual(response.status_code, 204, response.text)
        # results of a completed task remain available
        response = self.client.get(f"/analyze/coverage/{task['task_id']}")
        self.assertEqual(response.status_code, 200, response.text)

    def test_revoke_invalid_id(self):
        response = self.client.post("/tasks/0/revoke")
        self.assertEqual(response.status_code, 422, response.text)
