import json
import time
import unittest
from uuid import UUID

from fastapi.testclient import TestClient

from tatc_app.main import app
from tatc_app.utils.schemas import UserRead
from tatc_app.utils.users import current_active_user


class TatcTestCase(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides[current_active_user] = lambda: UserRead(
            id=UUID("12345678123456781234567812345678"),
            email="user@example.com",
            is_active=True,
            is_verified=False,
            is_superuser=False,
        )
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides = {}

    def run_analysis(self, path: str, request, timeout: float = 600) -> dict:
        """
        Enqueues an analysis, waits for it to complete, and returns the
        response to retrieve its results (and the enqueued task).
        """
        response = self.client.post(
            path,
            content=(
                request
                if isinstance(request, str)
                else request.model_dump_json(by_alias=False)
            ),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        task = response.json()
        task_id = task.get("task_id")
        start = time.time()
        while True:
            status = self.client.get(f"/tasks/{task_id}/status").json()
            if status.get("ready"):
                break
            self.assertLess(time.time() - start, timeout, "Task timed out.")
            time.sleep(0.1)
        self.assertTrue(status.get("successful"), status)
        return task

    def get_json(self, path: str) -> dict:
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200, response.text)
        return json.loads(response.content)
