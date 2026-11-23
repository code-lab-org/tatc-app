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

The application requires TAT-C version 3.7 and accepts all of its space-domain
platforms: satellites and Walker, train, MOG, and streets-of-coverage (SOC)
constellations, with every orbit type (including two line elements and repeat
ground track orbits), instrument type (simple, pointed, and conical), and
attitude. It supports the following analyses, each split into parallel worker
tasks and visualized with animated results (CZML) in the GUI:
 * Coverage and revisit (`/analyze/coverage`): observations of a grid of points and cells.
 * Ground track swaths (`/analyze/swaths`): instrument swaths that accumulate over time.
 * Data latency (`/analyze/latency`): latency to downlink observations at ground stations.
 * Point access (`/analyze/overflight`): access windows of satellites to target points.

Each analysis has endpoints to enqueue it (`POST`), retrieve its results
(`GET .../{task_id}`), and retrieve an animated CZML document
(`GET .../{task_id}/czml`). `POST /validate/space-system` validates a satellite
or constellation and summarizes its members.

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
installing via the "Docker Compose" method, set `TATC_BROKER` and
`TATC_BACKEND` if the broker and backend do not run at their defaults, to
identify the protocol, credentials (if required), domain name/URL, and port
number of the broker and backend components.

 * `TATC_BROKER`: broker connection string (default: `amqp://localhost:5672//`
   when running with Python, assuming a broker on the same machine;
   `amqp://guest:guest@broker:5672//` in the Docker images, assuming a
   container named `broker`)
 * `TATC_BACKEND`: backend connection string (default: `redis://localhost:6379/`
   when running with Python, assuming a backend on the same machine;
   `redis://backend:6379/` in the Docker images, assuming a container named
   `backend`)
 * `TATC_AUTH`: authentication mode (default: `oidc`): `oidc` requires users to
   sign in with an OpenID Connect provider such as Dex (see
   [Authentication](#authentication)); `none` disables authentication for
   **local development only**
 * `TATC_OIDC_ISSUER`: OpenID Connect issuer URL (required for `oidc`), e.g. `https://example.com/dex`
 * `TATC_OIDC_CLIENT_ID`: OpenID Connect client identifier (default: `tatc-app`)
 * `TATC_OIDC_CLIENT_SECRET`: OpenID Connect client secret (required for `oidc`)
 * `TATC_PUBLIC_URL`: public base URL of the server, used to build the sign-in
   redirect URI `<TATC_PUBLIC_URL>/auth/callback` (default: inferred from requests)
 * `TATC_LOGIN_LIFETIME_SECONDS`: time until reauthentication required (default: `7200` seconds)
 * `TATC_SECRET`: secret used to sign session cookies (required for `oidc`)
 * `TATC_CESIUM_TOKEN`: Cesium access token
 * `TATC_CELESTRAK_GROUP`: CelesTrak group searched for orbital elements
   (default: `active`); the server downloads it at most once every two hours,
   per [CelesTrak's usage policy](https://celestrak.org/NORAD/documentation/gp-data-formats.php)
 * `TATC_CELESTRAK_CACHE_DIR`: directory in which the CelesTrak group is cached
   so restarts do not download it again (default: `tatc-app` in the system's
   temporary directory)

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
If they do not run on the same machine at their default ports, specify the
connection strings for both in the `.env` file as described above.

This requires Python 3.11 or later. Install the web application and its
dependencies, including [TAT-C](https://github.com/code-lab-org/tatc), from
the project root:
```shell
pip install -e .
```

For local development without sign in, set `TATC_AUTH=none` in the `.env`
file (`compose.dev.yml` does this for the Docker Compose method). To start the
TAT-C server application, run the command:
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

By default, tests run Celery tasks eagerly (in-process) with an in-memory
result backend, so they do not require a broker, backend, or worker (see
`tests/conftest.py`). To instead run tests against running components
configured by `TATC_BROKER` and `TATC_BACKEND`, set `TATC_TEST_LIVE=1`.

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
 * `TATC_SECRET`: secret used to sign session cookies — set this to a long,
   random value
 * `TATC_OIDC_CLIENT_SECRET`: secret shared by the server and Dex to
   authenticate the server as a Dex client — set this to a long, random value
 * `TATC_ADMIN_EMAIL` / `TATC_ADMIN_PASSWORD_HASH`: email and bcrypt password
   hash of a user who signs in with Dex (see [Authentication](#authentication))
 * `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET`: credentials of a GitHub OAuth
   app for users to sign in with GitHub (see [Authentication](#authentication))
 * `TATC_CESIUM_TOKEN`: Cesium access token (see
   [Cesium Access Token and Assets](#cesium-access-token-and-assets) above)

`compose.server.yml` and `compose.worker.yml` pull the `tatc-server` and
`tatc-worker` images from GHCR (built and pushed by
[Build and push GHCR images](.github/workflows/ghcr-push-image.yml) on every
merge to `main`) rather than building them locally. Leave
`TATC_SERVER_IMAGE_TAG` / `TATC_WORKER_IMAGE_TAG` unset (or `latest`) so
[Auto-deploy](#auto-deploy) picks up new images automatically, or pin them in
`.env` to a specific commit SHA for a reproducible, rollback-able deploy that
auto-deploy will then keep redeploying rather than moving off of.

### Authentication

The server deployment authenticates users with [Dex](https://dexidp.io), an
OpenID Connect provider that runs alongside the server (`compose.server.yml`)
at `https://<TATC_DOMAIN>/dex` and is configured by `dex.yaml`. Users sign in
through Dex with either:

 * **Email and password** of users listed under `staticPasswords` in
   `dex.yaml`. The template defines one user whose email and bcrypt password
   hash come from `TATC_ADMIN_EMAIL` and `TATC_ADMIN_PASSWORD_HASH`. Create a
   hash with, for example, `htpasswd -bnBC 10 "" 'your password' | tr -d ':\n'`
   or `python -c "import bcrypt; print(bcrypt.hashpw(b'your password', bcrypt.gensalt()).decode())"`,
   and wrap it in single quotes in `.env` (it contains `$` characters):
   `TATC_ADMIN_PASSWORD_HASH='$2b$10$...'`. Add more users to `dex.yaml` in
   the same way.
 * **GitHub**, using a GitHub OAuth app (GitHub settings, Developer settings,
   OAuth Apps) with the authorization callback URL
   `https://<TATC_DOMAIN>/dex/callback`; set its credentials as
   `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET`. To allow only members of
   GitHub organizations, uncomment `orgs` in `dex.yaml`; to disable GitHub
   sign in, remove its connector from `dex.yaml`.

Any user who signs in through Dex can use the application. See the
[Dex connectors](https://dexidp.io/docs/connectors/) to sign in with other
identity providers (for example, an institutional OpenID Connect, SAML, or
LDAP provider). Dex stores its state in the `tatc-dex-data` Docker volume.

Signed-in users can choose **Copy API token** in the user menu to copy an ID
token that authenticates programmatic API requests until it expires (8 hours),
for example:
```shell
curl -H "Authorization: Bearer <token>" https://<TATC_DOMAIN>/auth/me
```

Previous versions stored user accounts in a SQLite database in the `tatc-data`
Docker volume, which is no longer used and may be removed
(`docker volume rm tatc-data`).

A `redis.acl` file must also exist alongside `compose.server.yml` — see
[Redis ACL File](#redis-acl-file) below.

### Worker Deployment

Run `docker compose -f compose.worker.yml up` on each additional host that
should process tasks for a broker/backend already started by
`compose.server.yml`. It requires only the connection credentials — none of
the authentication settings, `TATC_CESIUM_TOKEN`, or `ACME_EMAIL`, which the
worker does not use:

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

### Auto-deploy

`.github/workflows/deploy.yml` redeploys the server host over SSH:
- on every push to `main` (picks up compose/config changes), and
- after `ghcr-push-image.yml` finishes pushing new images (picks up
  server/worker code changes, after the images are actually available in
  GHCR rather than racing them).

Both triggers run the same thing: `config/deploy/deploy.sh` on the instance,
which does `git merge --ff-only` then `docker compose -f
compose.server.yml pull && ... up -d`. It fails loudly rather than
overwriting anything if the checkout has diverged from `main`.

Because GitHub-hosted runners don't have a small, stable IP range, this means
opening inbound port 22 on the instance broadly rather than allowlisting
GitHub. To keep that safe, the deploy key is restricted with a forced
command so it can never be used for anything but running that one script,
even though the workflow only ever asks it to:

1. On the EC2 instance, in the deploy user's `~/.ssh/authorized_keys`
   (that user needs passwordless `docker`/`docker compose` access and a
   checkout of this repo with `.env` already in place):

   ```
   command="/path/to/repo/config/deploy/deploy.sh",no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-pty ssh-ed25519 AAAA...
   ```

2. Generate a dedicated deploy keypair (don't reuse a personal key) and add
   the public half as shown above:

   ```bash
   ssh-keygen -t ed25519 -f deploy_key -N "" -C "tatc-app-deploy"
   ```

3. Capture the instance's host key from a trusted channel (e.g. the EC2
   console's system log, or a `ssh-keyscan` run over a connection you already
   trust) - don't just accept whatever a first connection presents, since
   that defeats host verification entirely:

   ```bash
   ssh-keyscan -H <host> > known_hosts
   ```

4. In the repo's GitHub Actions settings, add:
   - Repository variables: `DEPLOY_SSH_HOST`, `DEPLOY_SSH_USER`
   - Repository secrets: `DEPLOY_SSH_KEY` (private half of `deploy_key`),
     `DEPLOY_SSH_KNOWN_HOSTS` (contents of `known_hosts`)

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