from datetime import datetime, timezone
from unittest import mock
from uuid import uuid4

from celery.result import AsyncResult, GroupResult
from tatc.schemas import GeneralPerturbationsOrbit, Instrument, WalkerConstellation

from tatc_app.coverage.schemas import CoverageAnalysisRequest
from tatc_app.generation.schemas import CellGenerator, PointGenerator
from tatc_app.worker import app as celery_app

from .base import TLE, TatcTestCase


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


class TaskStatusTestCase(TatcTestCase):
    def test_progress(self):
        # (eager tasks do not link a workflow to its group: save one)
        children = [AsyncResult(str(uuid4()), app=celery_app) for _ in range(3)]
        for child in children[:2]:
            celery_app.backend.mark_as_done(child.id, {})
        group = GroupResult(str(uuid4()), children, app=celery_app)
        group.save()
        response = self.client.get(f"/tasks/{group.id}/progress")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"task_count": 3, "completed_count": 2})

    def test_progress_unknown_group(self):
        response = self.client.get(f"/tasks/{uuid4()}/progress")
        self.assertEqual(response.status_code, 404, response.text)

    def test_pending_task(self):
        # the result backend does not distinguish unknown tasks from pending
        task_id = str(uuid4())
        status = self.get_json(f"/tasks/{task_id}/status")
        self.assertEqual(status, {"ready": False, "successful": False})
        response = self.client.get(f"/analyze/coverage/{task_id}")
        self.assertEqual(response.status_code, 409, response.text)

    def test_failed_task(self):
        task_id = str(uuid4())
        celery_app.backend.mark_as_failure(task_id, RuntimeError("Out of memory"))
        status = self.get_json(f"/tasks/{task_id}/status")
        self.assertEqual(status, {"ready": True, "successful": False})
        with self.assertLogs("tatc_app", level="ERROR"):
            response = self.client.get(f"/analyze/coverage/{task_id}")
        self.assertEqual(response.status_code, 500, response.text)
        self.assertIn("Task failed: Out of memory", response.json()["detail"])
