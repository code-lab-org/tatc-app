"""
Authentication of users with an OpenID Connect (OIDC) provider, such as Dex.

Two modes are supported, selected by the environment variable `TATC_AUTH`:

 * `oidc` (default): users sign in through the OIDC provider (authorization
   code flow with PKCE) and receive a signed session cookie; programmatic
   clients may instead send an ID token issued by the provider for this
   application as a bearer token (`Authorization: Bearer <token>`).
 * `none`: authentication is disabled and every request acts as a local
   user. Intended only for local development and testing.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import logging
import os
import time
from typing import Literal, Optional
from urllib.parse import urlparse

from authlib.integrations.starlette_client import OAuth, OAuthError
from authlib.jose import JsonWebKey, JsonWebToken
from authlib.jose.errors import JoseError
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class User(BaseModel):
    """
    An authenticated user.
    """

    id: str = Field(..., description="Unique user identifier (OIDC subject).")
    email: Optional[str] = Field(None, description="Email address.")
    name: Optional[str] = Field(None, description="Display name.")

    @classmethod
    def from_claims(cls, claims: dict) -> "User":
        """
        Gets the user identified by the claims of an ID token.
        """
        return cls(id=claims["sub"], email=claims.get("email"), name=claims.get("name"))


class AuthInfo(BaseModel):
    """
    The authentication mode and current user.
    """

    mode: Literal["oidc", "none"] = Field(..., description="Authentication mode.")
    user: User = Field(..., description="The current user.")


LOCAL_USER = User(id="local", email="local@localhost", name="Local user")
ID_TOKEN_ALGORITHMS = ["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"]

bearer_scheme = HTTPBearer(
    auto_error=False,
    description="An ID token issued by the OIDC provider for this application.",
)


class Authenticator:
    """
    Authenticates requests in the configured mode.

    Args:
        mode (str): `oidc` or `none`.
        issuer (str): The OIDC issuer URL (for example, `https://host/dex`).
        client_id (str): The OIDC client identifier of this application.
        client_secret (str): The OIDC client secret of this application.
        public_url (Optional[str]): The public base URL of this application,
            used to build the redirect URI (default: inferred from requests).
        session_lifetime (int): Maximum session lifetime (seconds).
        metadata (Optional[dict]): OIDC provider metadata (default: loaded
            from the issuer's discovery document).
    """

    def __init__(
        self,
        mode: str = "oidc",
        issuer: Optional[str] = None,
        client_id: str = "tatc-app",
        client_secret: Optional[str] = None,
        public_url: Optional[str] = None,
        session_lifetime: int = 7200,
        metadata: Optional[dict] = None,
    ):
        if mode not in ("oidc", "none"):
            raise ValueError(f"Invalid authentication mode: {mode}")
        self.mode = mode
        self.issuer = issuer.rstrip("/") if issuer else None
        self.client_id = client_id
        self.public_url = public_url.rstrip("/") if public_url else None
        self.session_lifetime = session_lifetime
        self.jwt = JsonWebToken(ID_TOKEN_ALGORITHMS)
        self.oauth = OAuth()
        if mode == "oidc":
            if not self.issuer or not client_secret:
                raise ValueError(
                    "OIDC authentication requires TATC_OIDC_ISSUER and "
                    "TATC_OIDC_CLIENT_SECRET (or set TATC_AUTH=none for local "
                    "development)."
                )
            # provider metadata is loaded from the discovery document unless
            # given (as keyword arguments, which the client keeps as metadata)
            kwargs = (
                {
                    "authorize_url": metadata["authorization_endpoint"],
                    "access_token_url": metadata["token_endpoint"],
                    **metadata,
                }
                if metadata
                else {
                    "server_metadata_url": f"{self.issuer}/.well-known/openid-configuration"
                }
            )
            self.oauth.register(
                "oidc",
                client_id=client_id,
                client_secret=client_secret,
                client_kwargs={
                    "scope": "openid email profile",
                    "code_challenge_method": "S256",
                },
                **kwargs,
            )
        self.router = self._create_router()

    @classmethod
    def from_env(cls) -> "Authenticator":
        """
        Creates an authenticator configured by environment variables.
        """
        mode = (os.getenv("TATC_AUTH") or "oidc").strip().lower()
        if mode == "none":
            logger.warning(
                "Authentication is disabled (TATC_AUTH=none): use only for "
                "local development."
            )
        return cls(
            mode=mode,
            issuer=os.getenv("TATC_OIDC_ISSUER"),
            client_id=os.getenv("TATC_OIDC_CLIENT_ID", "tatc-app"),
            client_secret=os.getenv("TATC_OIDC_CLIENT_SECRET"),
            public_url=os.getenv("TATC_PUBLIC_URL"),
            session_lifetime=int(os.getenv("TATC_LOGIN_LIFETIME_SECONDS", "7200")),
        )

    @property
    def client(self):
        """
        The OIDC client of this application.
        """
        return self.oauth.create_client("oidc")

    def _redirect_uri(self, request: Request) -> str:
        if self.public_url:
            return f"{self.public_url}/auth/callback"
        return str(request.url_for("auth_callback"))

    async def validate_id_token(self, token: str) -> User:
        """
        Validates an ID token issued by the provider for this application.

        Args:
            token (str): The ID token (JWT).

        Raises:
            HTTPException: (401) if the token is invalid.

        Returns:
            User: The user identified by the token.
        """
        options = {
            "iss": {"essential": True, "value": self.issuer},
            "aud": {"essential": True, "value": self.client_id},
            "exp": {"essential": True},
            "sub": {"essential": True},
        }
        claims = None
        error = None
        for refresh in (False, True):
            # retry once with fresh keys, in case the provider rotated its keys
            try:
                keys = JsonWebKey.import_key_set(
                    await self.client.fetch_jwk_set(force=refresh)
                )
                claims = self.jwt.decode(token, keys, claims_options=options)
                claims.validate(leeway=60)
                break
            except (JoseError, ValueError) as exc:
                claims, error = None, exc
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("Could not load the provider's signing keys: %s", exc)
                claims, error = None, exc
                break
        if claims is None:
            raise HTTPException(
                status_code=401,
                detail=f"Invalid token: {error}",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return User.from_claims(claims)

    async def current_user(
        self,
        request: Request,
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    ) -> User:
        """
        Dependency to get the authenticated user of a request.

        Raises:
            HTTPException: (401) if the request is not authenticated.

        Returns:
            User: The authenticated user.
        """
        if self.mode == "none":
            return LOCAL_USER
        if credentials is not None:
            return await self.validate_id_token(credentials.credentials)
        session = request.session.get("auth")
        if session and session.get("expires", 0) > time.time():
            return User(**session["user"])
        raise HTTPException(
            status_code=401,
            detail="Not authenticated.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    def _create_router(self) -> APIRouter:
        router = APIRouter()

        def safe_next(target: Optional[str]) -> str:
            # only allow redirects to local paths
            if target and target.startswith("/") and not target.startswith("//"):
                if not urlparse(target).netloc:
                    return target
            return "/"

        @router.get("/login", include_in_schema=False)
        async def auth_login(
            request: Request, next_path: Optional[str] = Query(None, alias="next")
        ):
            """
            Redirects the browser to sign in with the OIDC provider, then to
            the (local) path `next`.
            """
            if self.mode == "none":
                return RedirectResponse(safe_next(next_path))
            request.session["next"] = safe_next(next_path)
            return await self.client.authorize_redirect(
                request, self._redirect_uri(request)
            )

        @router.get("/callback", include_in_schema=False)
        async def auth_callback(request: Request):
            """
            Completes sign in with the OIDC provider.
            """
            if self.mode == "none":
                return RedirectResponse("/")
            try:
                token = await self.client.authorize_access_token(request)
            except OAuthError as exc:
                raise HTTPException(
                    status_code=401, detail=f"Sign in failed: {exc.description}"
                ) from exc
            claims = token.get("userinfo") or {}
            user = User.from_claims(claims)
            expires = min(
                time.time() + self.session_lifetime,
                float(claims.get("exp", time.time() + self.session_lifetime)),
            )
            request.session["auth"] = {
                "user": user.model_dump(),
                "id_token": token.get("id_token"),
                "expires": expires,
            }
            return RedirectResponse(request.session.pop("next", "/"))

        @router.post("/logout", status_code=204, include_in_schema=False)
        async def auth_logout(request: Request):
            """
            Signs out of this application (ends the session).
            """
            request.session.clear()

        @router.get("/me", response_model=AuthInfo)
        async def auth_me(user: User = Depends(self.current_user)):
            """
            Gets the authentication mode and the current user.
            """
            return AuthInfo(mode=self.mode, user=user)

        @router.get(
            "/token",
            response_class=PlainTextResponse,
            dependencies=[Depends(self.current_user)],
        )
        async def auth_token(request: Request):
            """
            Gets the ID token of the current session, to authenticate programmatic
            clients (`Authorization: Bearer <token>`) until it expires.
            """
            session = request.session.get("auth")
            if self.mode == "none" or not session or not session.get("id_token"):
                raise HTTPException(
                    status_code=404, detail="No token for this session."
                )
            return session["id_token"]

        return router


authenticator = Authenticator.from_env()
current_user = authenticator.current_user
