import unittest
from uuid import UUID

from fastapi.testclient import TestClient

from tatc_app.main import app
from tatc_app.utils.users import current_active_user
from tatc_app.utils.schemas import UserRead


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
