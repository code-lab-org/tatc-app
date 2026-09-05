# This block defines the TAT-C runtime container using the appropriate
# base Python environment.

FROM python:3.12-slim-bookworm AS tatc_runtime

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /var/tatc-app

# Install dependencies first, in their own layer, so they stay cached
# across rebuilds that only change application source. pyproject.toml's
# dynamic version is read from tatc_app.__version__, so that one file has
# to be present for this install to resolve metadata; the rest of `src`
# (copied below) is not needed yet and is intentionally left out here.
COPY pyproject.toml pyproject.toml
COPY src/tatc_app/__init__.py src/tatc_app/__init__.py
RUN python -m pip install --no-cache-dir .

# Now install the application itself. Dependencies are already satisfied,
# so this only rebuilds and installs the local tatc-app package.
COPY src src
RUN python -m pip install --no-cache-dir .

# Run as a dedicated non-root user. The data directory is created (and
# owned by that user) here so its ownership is propagated to the
# `tatc-data` volume the first time it is mounted over that path.
RUN groupadd --system tatc \
    && useradd --system --gid tatc --no-create-home --shell /usr/sbin/nologin tatc \
    && mkdir -p /var/tatc-app/data \
    && chown -R tatc:tatc /var/tatc-app
USER tatc

# This block defines the TAT-C server container. Using the TAT-C runtime
# container, it installs and starts the server application.

FROM tatc_runtime AS tatc_server

WORKDIR /var/tatc-app
ENV TATC_BROKER=amqp://guest:guest@broker:5672//
ENV TATC_BACKEND=redis://backend:6379/

CMD ["uvicorn", "tatc_app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# This block defines the TAT-C worker container. Using the TAT-C runtime
# container, it starts the worker application.

FROM tatc_runtime AS tatc_worker

WORKDIR /var/tatc-app

ENV TATC_BROKER=amqp://guest:guest@broker:5672//
ENV TATC_BACKEND=redis://backend:6379/

CMD ["celery", "-A", "tatc_app.worker", "worker"]
