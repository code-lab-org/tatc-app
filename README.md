# TAT-C Web Application

The web application is built on top of [TAT-C](https://github.com/code-lab-org/tatc) to expose
analysis functions as RESTful web services, distribute computational load over
multiple worker machines using a parallel task-worker architecture (Celery),
and provide a browser-based graphical user interface (GUI) with geospatial
visualization (Cesium) that allows users to run and visualize results for a
subset of TAT-C analysis functions without requiring Python knowledge.

The TAT-C web application contains four major components:
 * Server: hosts the TAT-C application programming interface (API) and graphical user interface (GUI)
 * Worker: executes low-level tasks
 * Broker: coordinates the list of tasks between server and worker(s)
 * Backend: stores completed task outputs

The web application is configured to support the RabbitMQ Broker and Redis Backend.

## Configuration

For the Manual Docker Containers and Python development methods (see
[Development](#development) below), the web application is configured with
environment variables, typically set in a `.env` file in the project root
directory. (The Docker Compose development method and the Deployment compose
files set these environment variables directly instead — see those sections
for details.)

### Cesium Access Token and Assets

The client-side Cesium geospatial visualization requires an access token
from <https://cesium.com/ion/tokens>. After creating an account, you *must*
add the Asset "Blue Marble Next Generation July, 2004" from the Asset Depot
(ID 3845) to the account assets to enable visualization.

Set `TATC_CESIUM_TOKEN` in the `.env` file to the access token:
```
TATC_CESIUM_TOKEN=your alphanumeric access token here
```

### Environment Variables

The web application references the following environment variables. Unless
installing via the "Docker Compose" method, you must set `TATC_BROKER` and
`TATC_BACKEND` to identify the protocol, credentials (if required), domain
name/URL, and port number of the broker and backend components.

 * `TATC_BROKER`: broker connection string (default: `amqp://guest:guest@broker:5672//`, assuming a local broker)
 * `TATC_BACKEND`: backend connection string (default: `redis://backend:6379/`, assuming a local backend)
 * `TATC_DATABASE_URL`: server user-account database connection string (default: `sqlite+aiosqlite:///data.db`,
   a SQLite file in the working directory); the Docker Compose methods below override this to store the
   file in the `tatc-data` volume so accounts persist across container restarts
 * `TATC_LOGIN_LIFETIME_SECONDS`: time until reauthentication required (default: `7200` seconds)
 * `TATC_SECRET`: cryptographic security secret phrase (default: `change me`)
 * `TATC_ADMIN_EMAIL`: administrator account email (default: `admin@example.com`)
 * `TATC_ADMIN_PASSWORD`: administrator account password (default: `admin`)
 * `TATC_CESIUM_TOKEN`: Cesium access token

## Development

This section covers running TAT-C locally from source, for development and
testing. For running a publicly-accessible instance, see
[Deployment](#deployment) below instead.

Due to the architectural complexity and dependencies for the parallel
task-queuing system (Celery), we strongly recommended using Docker containers
to install and run TAT-C, either via Docker Compose (recommended) or manually
built containers. A pure-Python setup is also available for tighter
edit/reload cycles on the server or worker code.

### Docker Compose (Recommended)

Docker Compose can build and operate all four application components (server,
worker, broker, and backend) locally from one command. It is suitable for
individual workstation use because it does not rely on network access between
components.

The `compose.dev.yml` file is intended for **local development only**: it
runs the broker and backend without authentication or TLS and exposes their
ports directly on the host. Do not use it to deploy a publicly-accessible
instance; see [Deployment](#deployment) below for that.

From the project root directory (`/`), build and run the Docker compose file
which provides the server, worker, broker, and backend components:
```shell
docker compose -f compose.dev.yml up
```
By default, the client-side GUI is available at <http://localhost:8000/>. The
server's user-account database is stored in the `tatc-data` Docker volume, so
accounts persist across `docker compose down` / `up` (though not the broker's
or backend's in-flight data, which are not persisted in this file — see
[Environment Variables](#environment-variables) above and
[Deployment](#deployment) below for the persisted production equivalents).

### Manual Docker Containers

Individual Docker containers can be built and run without Compose, for
example to test a single component in isolation or to run components across
multiple hosts by hand.

The broker and backend services can use the third-party Docker images
[rabbitmq](https://hub.docker.com/_/rabbitmq) and
[redis](https://hub.docker.com/_/redis), respectively. Specify the connection
strings for both in the `.env` file as described above.

For the server application, first build the `tatc_server` Docker image from the
project root (`/`).
```shell
docker build --target tatc_server --tag tatc_server .
```
Next, run a Docker container for the server application (this example maps host
port 8000 to container port 8000).
```shell
docker run -it -p 8000:8000 --env-file=.env tatc_server
```
The client-side GUI is available at <http://localhost:8000/>. Note that the
server needs at least one worker to process tasks.

For the worker application, first build the `tatc_worker` Docker image from the
project root (`/`).
```shell
docker build --target tatc_worker --tag tatc_worker .
```
Next, run a Docker container for the worker application.
```shell
docker run -it --env-file=.env tatc_worker
```
The worker will connect to the broker and wait for new tasks to process.

### Python

To use Python directly for the server and worker, the broker and backend
components must already be running (e.g., see Manual Docker Containers above).
Specify the connection strings for both in the `.env` file as described above.

This requires Python 3.11 or later. Install the web application and its
dependencies, including [TAT-C](https://github.com/code-lab-org/tatc), from
the project root:
```shell
pip install -e .
```

To start the TAT-C server application, run the command:
```shell
uvicorn tatc_app.main:app --reload --reload-dir tatc_app
```
The client-side GUI is available at <http://localhost:8000/>.

To start the TAT-C worker application, run the command:
```shell
celery -A tatc_app.worker worker --loglevel=INFO
```
The worker will connect to the broker and wait for new tasks to process. Note
that Celery does not currently support concurrency on Windows. Try using the
`solo` pool option (which does not perform parallel processing):
```shell
celery -A tatc_app.worker worker --loglevel=INFO --pool=solo
```

### Documentation

Generate documentation from the `docs` directory using the command:
```shell
make html
```

### Testing

Install the `dev` optional dependencies and run the test suite from the
project root:
```shell
pip install -e ".[dev]"
pytest
```

### Code Style

This project uses the black code style and isort import ordering, applied
from the project root:
```shell
black .
isort .
```

## Deployment

Production deployments should use `compose.server.yml` and `compose.worker.yml`
instead of `compose.dev.yml`. Unlike the development file, these:
 * terminate TLS at a [Traefik](https://traefik.io/traefik/) reverse proxy so the
   GUI, broker, and backend are only reachable over HTTPS/AMQPS/TLS-Redis;
 * require authenticated broker and backend connections (no `guest` account or
   unauthenticated Redis access); and
 * persist RabbitMQ, Redis, and the server's user-account database in named
   Docker volumes across restarts.

`compose.server.yml` runs the reverse proxy, server, worker, broker, and
backend on a single host and is suitable for most deployments.
`compose.worker.yml` runs an additional worker-only instance (for example,
on a separate machine) that connects to the broker and backend already
started by `compose.server.yml`.

Before running `compose.server.yml`, point the `TATC_DOMAIN` DNS record at
the server host and ensure ports 80, 443, 5671, and 6380 are reachable from
the Internet — Traefik uses the TLS-ALPN-01 challenge on port 443 to issue
Let's Encrypt certificates, and certificate issuance will fail otherwise.

Unlike `compose.dev.yml`, none of the environment variables below have
usable defaults — deployment will fail to start (or start insecurely) if
they are not set. Provide them via a `.env` file in the same directory as
the relevant compose file.

### Server Deployment

Run `docker compose -f compose.server.yml up` on the host that will serve
the GUI/API, broker, and backend. It requires:

 * `TATC_DOMAIN`: public domain name used to route and issue TLS certificates
   for the GUI/API (HTTPS), broker (AMQPS), and backend (TLS Redis)
 * `ACME_EMAIL`: contact email used when requesting Let's Encrypt TLS
   certificates
 * `BROKER_USER` / `BROKER_PASSWORD`: credentials for the RabbitMQ broker;
   `compose.server.yml` creates this account via `RABBITMQ_DEFAULT_USER` /
   `RABBITMQ_DEFAULT_PASS` and uses it to build the server's `TATC_BROKER`
   connection string
 * `BACKEND_USER` / `BACKEND_PASSWORD`: credentials for the Redis backend;
   these must match an enabled user in `redis.acl` (see below) and are used
   to build the server's `TATC_BACKEND` connection string
 * `TATC_SECRET`: cryptographic secret used to sign session/authentication
   tokens — set this to a long, random value
 * `TATC_ADMIN_EMAIL` / `TATC_ADMIN_PASSWORD`: initial administrator account
   credentials
 * `TATC_CESIUM_TOKEN`: Cesium access token (see
   [Cesium Access Token and Assets](#cesium-access-token-and-assets) above)

`compose.server.yml` and `compose.worker.yml` pull the `tatc-server` and
`tatc-worker` images from GHCR rather than building them locally. Set
`TATC_SERVER_IMAGE_TAG` / `TATC_WORKER_IMAGE_TAG` to a commit SHA (as pushed by the
[Build and push GHCR images](.github/workflows/ghcr-push-image.yml)
workflow on merge to `main`) to pin the deployed version; both default to
`latest` if unset.

The server's user-account database is stored in the `tatc-data` Docker
volume; `compose.server.yml` sets `TATC_DATABASE_URL` to place it there
automatically, so it persists across restarts without further configuration.

A `redis.acl` file must also exist alongside `compose.server.yml` — see
[Redis ACL File](#redis-acl-file) below.

### Worker Deployment

Run `docker compose -f compose.worker.yml up` on each additional host that
should process tasks for a broker/backend already started by
`compose.server.yml`. It requires only the connection credentials — not
`TATC_SECRET`, `TATC_ADMIN_EMAIL`/`TATC_ADMIN_PASSWORD`, `TATC_CESIUM_TOKEN`,
or `ACME_EMAIL`, none of which the worker uses:

 * `TATC_DOMAIN`: same public domain name as the server deployment, used to
   reach the broker (AMQPS) and backend (TLS Redis) through Traefik
 * `BROKER_USER` / `BROKER_PASSWORD`: same broker credentials as the server
   deployment
 * `BACKEND_USER` / `BACKEND_PASSWORD`: same backend credentials as the
   server deployment

### Redis ACL File

The Redis backend in `compose.server.yml` is started with `--aclfile` pointing
at a `redis.acl` file (mounted read-only from the project root), so a
`redis.acl` file must exist alongside `compose.server.yml` before deployment.
This file must define a user whose name and password match `BACKEND_USER`
and `BACKEND_PASSWORD` above. A placeholder `redis.acl` is included as a
template:
```
user default off
user username on >password ~* &* +@all -@admin -@dangerous
```
Replace `username` and `password` with the actual `BACKEND_USER` and
`BACKEND_PASSWORD` values before deploying. Treat `redis.acl` as a secret
once populated with real credentials — avoid committing a version containing
production passwords to version control.

## License

This project is distributed under the [BSD 3-Clause License](LICENSE).

## Contact

Paul T. Grogan <paul.grogan@asu.edu>

## Acknowledgements

This project was supported in part by the National Aeronautics and Space
Administration (NASA) Earth Science Division (ESD) Earth Science Technology
Office (ESTO) Advanced Information Systems Technology (AIST) program under
grant numbers: NNX17AE06G, 80NSSC17K0586, 80NSSC20K1118, 80NSSC21K1515, 
80NSSC22K1705 and 80NSSC24K0575 and NASA Jet Propulsion Laboratory 
contracts: 1074657, 1689594, 1686623, 1705655.