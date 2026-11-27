import json
import time
import unittest

from fastapi.testclient import TestClient

from tatc_app.auth import Authenticator, current_user
from tatc_app.main import app

# two-line elements of the International Space Station (June 20, 2022)
TLE = [
    "1 25544U 98067A   22171.11255782  .00008307  00000+0  15444-3 0  9992",
    "2 25544  51.6448 322.0970 0003980 282.3738 231.6559 15.49798078345636",
]

# provider metadata of a (fictitious) OpenID Connect provider
OIDC_METADATA = {
    "issuer": "https://auth.example.com/dex",
    "authorization_endpoint": "https://auth.example.com/dex/auth",
    "token_endpoint": "https://auth.example.com/dex/token",
    "jwks_uri": "https://auth.example.com/dex/keys",
}


def create_oidc_authenticator(**kwargs) -> Authenticator:
    """
    Creates an authenticator for a (fictitious) OpenID Connect provider.
    """
    kwargs.setdefault("client_secret", "secret")
    return Authenticator(
        mode="oidc",
        issuer=OIDC_METADATA["issuer"],
        client_id="tatc-app",
        metadata=dict(OIDC_METADATA, **kwargs.pop("metadata", {})),
        **kwargs,
    )


class TatcTestCase(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides = {}

    def require_authentication(self):
        """
        Requires requests to authenticate with an OpenID Connect provider.
        """
        app.dependency_overrides[current_user] = (
            create_oidc_authenticator().current_user
        )

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

    def analysis_result(self, path: str, request, model=None, timeout: float = 600):
        """
        Runs an analysis, and gets its result (keeping its task id as
        `self.task_id`, to get its other outputs).

        Args:
            path (str): The path of the analysis, such as `/analyze/coverage`.
            request: The analysis request (a model, or serialized JSON).
            model: The model to validate the result with, if any.

        Returns:
            The result: a model instance, or its JSON if no model is given.
        """
        self.task_id = self.run_analysis(path, request, timeout)["task_id"]
        result = self.get_json(f"{path}/{self.task_id}")
        return model.model_validate(result) if model else result

    def get_json(self, path: str) -> dict:
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200, response.text)
        return json.loads(response.content)
