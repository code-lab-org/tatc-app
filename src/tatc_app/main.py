"""
TAT-C application configuration.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import os
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from msgpack_asgi import MessagePackMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import Response

from tatc_app import __version__
from tatc_app.auth import authenticator, current_user
from tatc_app.celery.router import router as celery_router
from tatc_app.celestrak.router import router as celestrak_router
from tatc_app.cesium.router import router as cesium_router
from tatc_app.coincidence.router import router as coincidence_router
from tatc_app.coverage.router import router as coverage_router
from tatc_app.generation.router import router as generation_router
from tatc_app.latency.router import router as latency_router
from tatc_app.library.router import designs_router, runs_router
from tatc_app.overflight.router import router as overflight_router
from tatc_app.swaths.router import router as swaths_router
from tatc_app.system_catalog.router import router as system_catalog_router
from tatc_app.tracking.router import router as tracking_router
from tatc_app.validation.router import router as validation_router

SECRET = os.getenv("TATC_SECRET", "change me")
if authenticator.mode == "oidc" and SECRET == "change me":
    raise ValueError("Set TATC_SECRET to a random secret to sign user sessions.")

# the files of the frontend, part of the package (so they do not depend on
# the working directory)
STATIC_DIR = Path(__file__).parent / "static"

# Create the FastAPI app
app = FastAPI(
    title="Tradespace Analysis Tool for Constellations (TAT-C)",
    description="Modeling tool for pre-Phase A architecture analysis for Earth science space missions.",
    version=__version__,
)
# Add MessagePack middleware to allow application/msgpack responses
app.add_middleware(MessagePackMiddleware)
# Add GZip middleware to allow compressed responses
app.add_middleware(GZipMiddleware)
# Add signed session cookies for users signed in with the OIDC provider
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET,
    session_cookie="tatc_session",
    max_age=authenticator.session_lifetime,
    same_site="lax",
    https_only=(authenticator.public_url or "").startswith("https://"),
)
# Include the router for authentication
app.include_router(authenticator.router, prefix="/auth", tags=["auth"])
# Include the routers of all other endpoints, which require a signed-in user
for router, prefix in [
    (celery_router, "/tasks"),
    (celestrak_router, "/celestrak"),
    (system_catalog_router, "/catalog"),
    (cesium_router, "/cesium"),
    (generation_router, "/generate"),
    (validation_router, "/validate"),
    (overflight_router, "/analyze"),
    (tracking_router, "/analyze"),
    (swaths_router, "/analyze"),
    (coverage_router, "/analyze"),
    (coincidence_router, "/analyze"),
    (latency_router, "/analyze"),
    (designs_router, "/designs"),
    (runs_router, "/runs"),
]:
    app.include_router(router, prefix=prefix, dependencies=[Depends(current_user)])


class FrontendFiles(StaticFiles):
    """
    Static files of the frontend that browsers revalidate before each use
    (`Cache-Control: no-cache`), so an update of the app never mixes new and
    stale files (for example, a new page with a stale stylesheet). Files not
    modified are not sent again (`304 Not Modified`, by their `ETag`).
    """

    def file_response(self, *args, **kwargs) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


# Mount the frontend (installed with the package) to the root (/) route for
# any other requests
app.mount("/", FrontendFiles(directory=STATIC_DIR, html=True), name="frontend")
