"""
TAT-C application configuration.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import os

from dotenv import load_dotenv
from fastapi import Depends, FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from msgpack_asgi import MessagePackMiddleware
from starlette.middleware.sessions import SessionMiddleware

from tatc_app import __version__
from tatc_app.auth import authenticator, current_user
from tatc_app.celery.router import router as celery_router
from tatc_app.celestrak.router import router as celestrak_router
from tatc_app.cesium.router import get_cesium_router
from tatc_app.coverage.router import router as coverage_router
from tatc_app.generation.router import router as generation_router
from tatc_app.latency.router import router as latency_router
from tatc_app.overflight.router import router as overflight_router
from tatc_app.tracking.router import router as tracking_router
from tatc_app.validation.router import router as validation_router

# Load environment variables from the .env file
load_dotenv()
CESIUM_TOKEN = os.getenv("TATC_CESIUM_TOKEN", "")
SECRET = os.getenv("TATC_SECRET", "change me")
if authenticator.mode == "oidc" and SECRET == "change me":
    raise ValueError("Set TATC_SECRET to a random secret to sign user sessions.")

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
# include the router for authentication
app.include_router(authenticator.router, prefix="/auth", tags=["auth"])
# Include the router for the /tasks route
app.include_router(
    celery_router,
    prefix="/tasks",
    dependencies=[Depends(current_user)],
)
# Include the router for the /celestrak route
app.include_router(
    celestrak_router,
    prefix="/celestrak",
    dependencies=[Depends(current_user)],
)
# Include the router for the /cesium route
app.include_router(
    get_cesium_router(CESIUM_TOKEN),
    prefix="/cesium",
    dependencies=[Depends(current_user)],
)
# Include the router for the /generate route
app.include_router(
    generation_router,
    prefix="/generate",
    dependencies=[Depends(current_user)],
)
# Include the router for the /validate route
app.include_router(
    validation_router,
    prefix="/validate",
    dependencies=[Depends(current_user)],
)
# Include the router for the /analyze route
app.include_router(
    overflight_router,
    prefix="/analyze",
    dependencies=[Depends(current_user)],
)
# Include the router for the /analyze route
app.include_router(
    tracking_router,
    prefix="/analyze",
    dependencies=[Depends(current_user)],
)
# Include the router for the /analyze route
app.include_router(
    coverage_router,
    prefix="/analyze",
    dependencies=[Depends(current_user)],
)
# Include the router for the /analyze route
app.include_router(
    latency_router,
    prefix="/analyze",
    dependencies=[Depends(current_user)],
)

# Mount a static directory to the root (/) route for any other requests
app.mount("/", StaticFiles(directory="src/static", html=True), name="frontend")
