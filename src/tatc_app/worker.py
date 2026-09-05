"""
TAT-C worker configuration.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import os
import ssl

from celery import Celery
from dotenv import load_dotenv

# Load environment variables from the .env file
load_dotenv()

# parse the broker connection
broker_string = os.getenv("TATC_BROKER", "amqp://localhost:5672//")
if broker_string.startswith("amqps://"):
    broker_ssl_option = os.getenv(
        "TATC_BROKER_SSL_CERT_REQS",
        "REQUIRED",
    ).upper()
    broker_ssl_config = {
        "server_hostname": None,
        "cert_reqs": {
            "REQUIRED": ssl.CERT_REQUIRED,
            "OPTIONAL": ssl.CERT_OPTIONAL,
            "NONE": ssl.CERT_NONE,
        }[broker_ssl_option],
    }
    # Optional custom CA/client certificates
    if value := os.getenv("TATC_BROKER_SSL_KEYFILE"):
        broker_ssl_config["keyfile"] = value
    if value := os.getenv("TATC_BROKER_SSL_CERTFILE"):
        broker_ssl_config["certfile"] = value
    if value := os.getenv("TATC_BROKER_SSL_CA_CERTS"):
        broker_ssl_config["ca_certs"] = value
else:
    broker_ssl_config = False

# parse the backend connection
backend_string = os.getenv("TATC_BACKEND", "redis://localhost:6379/")
if backend_string.startswith("rediss://"):
    backend_ssl_option = os.getenv(
        "TATC_BACKEND_SSL_CERT_REQS",
        "REQUIRED",
    ).upper()
    backend_ssl_config = {
        "ssl_cert_reqs": {
            "REQUIRED": ssl.CERT_REQUIRED,
            "OPTIONAL": ssl.CERT_OPTIONAL,
            "NONE": ssl.CERT_NONE,
        }[backend_ssl_option],
    }
    if value := os.getenv("TATC_BACKEND_SSL_KEYFILE"):
        backend_ssl_config["ssl_keyfile"] = value
    if value := os.getenv("TATC_BACKEND_SSL_CERTFILE"):
        backend_ssl_config["ssl_certfile"] = value
    if value := os.getenv("TATC_BACKEND_SSL_CA_CERTS"):
        backend_ssl_config["ssl_ca_certs"] = value
else:
    backend_ssl_config = False

# Create the Celery app
app = Celery(
    "tatc_app",
    broker=broker_string,
    broker_use_ssl=broker_ssl_config,
    backend=backend_string,
    redis_backend_use_ssl=backend_ssl_config,
    include=[
        "tatc_app.coverage.tasks",
        "tatc_app.generation.tasks",
        "tatc_app.overflight.tasks",
        "tatc_app.tracking.tasks",
        "tatc_app.utils.tasks",
        "tatc_app.latency.tasks",
    ],
)

app.config_from_object("tatc_app.celeryconfig")

app.conf.update(
    broker_use_ssl=broker_ssl_config,
    redis_backend_use_ssl=backend_ssl_config,
)
