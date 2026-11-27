"""
Router specifications for cesium endpoints.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import os

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

# the Cesium ion access token of clients
CESIUM_TOKEN = os.getenv("TATC_CESIUM_TOKEN", "")

router = APIRouter()


@router.get("/token", response_class=PlainTextResponse)
async def get_cesium_token():
    """
    Endpoint to retrieve the Cesium access token.

    Returns:
        PlainTextResponse: the response containing the access token
    """
    return CESIUM_TOKEN
