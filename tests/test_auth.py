import time
import unittest
from urllib.parse import parse_qs, urlparse

from authlib.jose import JsonWebKey, jwt
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from tatc_app.auth import User

from .base import OIDC_METADATA, TatcTestCase, create_oidc_authenticator

KEY = JsonWebKey.generate_key("RSA", 2048, is_private=True, options={"kid": "test"})
OTHER_KEY = JsonWebKey.generate_key(
    "RSA", 2048, is_private=True, options={"kid": "other"}
)


def create_token(key=KEY, **claims) -> str:
    """
    Creates an ID token signed by a key.
    """
    now = int(time.time())
    payload = {
        "iss": OIDC_METADATA["issuer"],
        "aud": "tatc-app",
        "sub": "user-1",
        "email": "user@example.com",
        "name": "Test User",
        "iat": now,
        "exp": now + 3600,
    }
    payload.update(claims)
    return jwt.encode({"alg": "RS256", "kid": key.kid}, payload, key).decode()


class OidcAuthenticationTestCase(unittest.TestCase):
    """
    Tests authentication with an OpenID Connect provider, using an app with
    the authentication routes and one protected route.
    """

    def setUp(self):
        self.authenticator = create_oidc_authenticator(
            public_url="https://tatc.example.com",
            metadata={"jwks": {"keys": [KEY.as_dict(is_private=False)]}},
        )
        app = FastAPI()
        app.add_middleware(SessionMiddleware, secret_key="test")
        app.include_router(self.authenticator.router, prefix="/auth")

        @app.get("/protected")
        def protected(user: User = Depends(self.authenticator.current_user)):
            return user

        self.client = TestClient(app, base_url="https://testserver")

    def test_unauthenticated(self):
        self.assertEqual(self.client.get("/protected").status_code, 401)
        self.assertEqual(self.client.get("/auth/me").status_code, 401)

    def test_bearer_token(self):
        response = self.client.get(
            "/protected", headers={"Authorization": f"Bearer {create_token()}"}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["email"], "user@example.com")

    def test_bearer_token_rejected(self):
        for name, token in {
            "audience": create_token(aud="another-app"),
            "issuer": create_token(iss="https://other.example.com"),
            "expired": create_token(exp=int(time.time()) - 3600),
            "signature": create_token(key=OTHER_KEY),
            "malformed": "not-a-token",
        }.items():
            with self.subTest(name):
                response = self.client.get(
                    "/protected", headers={"Authorization": f"Bearer {token}"}
                )
                self.assertEqual(response.status_code, 401)

    def test_login_redirects_to_provider(self):
        response = self.client.get("/auth/login?next=/analysis", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        location = urlparse(response.headers["location"])
        query = parse_qs(location.query)
        self.assertEqual(
            f"{location.scheme}://{location.netloc}{location.path}",
            OIDC_METADATA["authorization_endpoint"],
        )
        self.assertEqual(query["client_id"], ["tatc-app"])
        self.assertEqual(
            query["redirect_uri"], ["https://tatc.example.com/auth/callback"]
        )
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertIn("openid", query["scope"][0])

    def test_callback_starts_session(self):
        async def authorize_access_token(request):
            return {
                "id_token": "id-token",
                "userinfo": {
                    "sub": "user-1",
                    "email": "user@example.com",
                    "name": "Test User",
                    "exp": time.time() + 3600,
                },
            }

        self.authenticator.client.authorize_access_token = authorize_access_token
        self.client.get("/auth/login?next=/analysis", follow_redirects=False)
        response = self.client.get("/auth/callback", follow_redirects=False)
        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.headers["location"], "/analysis")
        me = self.client.get("/auth/me")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["mode"], "oidc")
        self.assertEqual(me.json()["user"]["id"], "user-1")
        self.assertEqual(self.client.get("/auth/token").text, "id-token")
        self.assertEqual(self.client.post("/auth/logout").status_code, 204)
        self.assertEqual(self.client.get("/protected").status_code, 401)

    def test_login_ignores_external_redirect(self):
        async def authorize_access_token(request):
            return {"userinfo": {"sub": "user-1"}}

        self.authenticator.client.authorize_access_token = authorize_access_token
        self.client.get("/auth/login?next=//evil.example.com", follow_redirects=False)
        response = self.client.get("/auth/callback", follow_redirects=False)
        self.assertEqual(response.headers["location"], "/")

    def test_requires_configuration(self):
        with self.assertRaises(ValueError):
            create_oidc_authenticator(client_secret=None)


class NoAuthenticationTestCase(TatcTestCase):
    def test_local_user(self):
        response = self.client.get("/auth/me")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["mode"], "none")
        self.assertEqual(response.json()["user"]["id"], "local")

    def test_login_redirects_home(self):
        response = self.client.get("/auth/login", follow_redirects=False)
        self.assertEqual(response.headers["location"], "/")

    def test_protected_routes_require_authentication(self):
        self.require_authentication()
        self.assertEqual(self.client.get("/tasks/0/status").status_code, 401)
