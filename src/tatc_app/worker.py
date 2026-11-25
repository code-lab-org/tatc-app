"""
TAT-C worker configuration.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import os
import ssl
from typing import Union

from celery import Celery
from dotenv import load_dotenv

# Load environment variables from the .env file
load_dotenv()

CERT_REQS = {
    "REQUIRED": ssl.CERT_REQUIRED,
    "OPTIONAL": ssl.CERT_OPTIONAL,
    "NONE": ssl.CERT_NONE,
}


def _ssl_config(env_prefix: str, key_prefix: str = "") -> dict:
    """
    Builds an SSL configuration from environment variables
    `<env_prefix>_SSL_CERT_REQS` (default `REQUIRED`) and optional custom
    CA/client certificates `<env_prefix>_SSL_KEYFILE`, `_SSL_CERTFILE`, and
    `_SSL_CA_CERTS`.

    Args:
        env_prefix (str): The environment variable prefix (e.g. `TATC_BROKER`).
        key_prefix (str): The prefix of configuration keys (e.g. `ssl_`).

    Returns:
        dict: The SSL configuration.
    """
    option = os.getenv(f"{env_prefix}_SSL_CERT_REQS", "REQUIRED").upper()
    config = {f"{key_prefix}cert_reqs": CERT_REQS[option]}
    for key in ("keyfile", "certfile", "ca_certs"):
        if value := os.getenv(f"{env_prefix}_SSL_{key.upper()}"):
            config[f"{key_prefix}{key}"] = value
    return config


# parse the broker connection
broker_string = os.getenv("TATC_BROKER", "amqp://localhost:5672//")
broker_ssl_config: Union[dict, bool] = (
    {"server_hostname": None, **_ssl_config("TATC_BROKER")}
    if broker_string.startswith("amqps://")
    else False
)

# parse the backend connection
backend_string = os.getenv("TATC_BACKEND", "redis://localhost:6379/")
backend_ssl_config: Union[dict, bool] = (
    _ssl_config("TATC_BACKEND", "ssl_")
    if backend_string.startswith("rediss://")
    else False
)

# Create the Celery app
app = Celery(
    "tatc_app",
    broker=broker_string,
    backend=backend_string,
    include=[
        "tatc_app.analysis.tasks",
        "tatc_app.coincidence.tasks",
        "tatc_app.coverage.tasks",
        "tatc_app.generation.tasks",
        "tatc_app.latency.tasks",
        "tatc_app.overflight.tasks",
        "tatc_app.region.tasks",
        "tatc_app.tracking.tasks",
    ],
)

app.config_from_object("tatc_app.celeryconfig")

# SSL options (set after loading the configuration file, to take precedence)
app.conf.update(
    broker_use_ssl=broker_ssl_config,
    redis_backend_use_ssl=backend_ssl_config,
)
