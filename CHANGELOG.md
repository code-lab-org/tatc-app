# Changelog

All notable changes to the TAT-C web application are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). The version is set
by `__version__` in `src/tatc_app/__init__.py`.

## [Unreleased]

## [2.2.1] - 2026-11-27

### Fixed

- The animation of satellites and their footprints shows after running an
  analysis: it loaded hidden, as the analysis layer stayed hidden from
  before there were results to show.

## [2.2.0] - 2026-11-27

### Added

- `TATC_GENERATION_TIMEOUT`: time that a request waits for a worker to
  generate its points or cells before failing (HTTP 503), 300 seconds by
  default.
- `TATC_MAX_TRACK_POSITIONS`: maximum number of positions (member satellites
  times sample times) of an orbit or ground track request, 200,000 by
  default (HTTP 422 beyond it).
- Prompt to sign in again when a session expires, rather than show each
  request's error.

### Changed

- Workers generate points and cells from their own queue (`generation`), so
  a request waits for the next free worker process rather than behind queued
  analyses. Workers started without `-Q` consume both queues; update workers
  with (or before) the server.
- The frontend is part of the package (`src/tatc_app/static`), so the server
  no longer depends on starting from the project root.
- Listing saved designs and runs no longer reads their data and inputs.
- Simplify the backend: analyses share their result endpoints, the CZML
  builders are split into modules, swath summaries are in the swaths
  package, and the `.env` file is loaded once. The API and the results of
  analyses are unchanged.
- Orbit and ground track requests count toward `TATC_MAX_ACTIVE_ANALYSES`
  (HTTP 429 beyond it), and are analyzed in tasks of about 1,000 positions
  (several member satellites each, if they have few times) rather than one
  task for every 100 times of each member.
- The tasks that combine coverage and latency analyses and that collect
  tracks take new arguments: update workers with the server.
- Declare the libraries the app imports (geopandas, numpy, pandas, pyproj,
  and shapely), require authlib < 2, and drop unused aiofiles and tzlocal.
- Analyses are polled less often as they run (every second at first, up to
  every 4 seconds), and polls that fail with network or server errors are
  retried rather than ending the analysis.
- Simplify the frontend: each analysis type's inputs and data are in one
  place (`analysis-types.js`), and requests, number formatting, and summary
  charts share their helpers.
- The DataTables stylesheet and scripts are checked against integrity
  hashes, as every other CDN asset is.
- The frontend is ES modules, loaded from `main.js`, rather than scripts
  sharing global names in the order of `index.html`: each module imports
  what it uses, and `main.js` sets the modules up in order.
- CI runs the tests in a process per CPU and reports the code they cover
  (`pytest -n auto --cov=tatc_app`, with `pytest-xdist` and `pytest-cov` in
  the `dev` dependencies). Tests check that every endpoint requires a signed-in
  user, that every analysis counts toward `TATC_MAX_ACTIVE_ANALYSES`, and the
  progress and failure of tasks.
- Browser tests wait for the app's requests and dialogs rather than for fixed
  times or for the network to be idle (as the globe loads imagery), and run a
  server for each test process rather than each module, so that they may run
  in parallel (`pytest tests/browser -n 4`): about 120 s rather than 200 s in
  one process, and 55 to 65 s in 4, with CPUs to spare. CI runs them in one
  process, as its few CPUs are busy with one, and logs the time of each test
  (`--durations=0`).
- Browser tests have animation frames every 500 ms rather than 60 times a
  second, as without a GPU (as in CI) Cesium draws each frame of the globe in
  software, at seconds of CPU per frame: with software rendering, the tests
  take about 140 s rather than 570 s.
- Workers store analysis results as the endpoints respond with them, so the
  endpoints return them as stored rather than parse, validate, and serialize
  them again; and responses are gzipped at level 4 rather than 9 (4 to 5
  times faster, for responses 4 to 5% larger). A 3.3 MB coverage result is
  retrieved in about 50 ms rather than 240 ms. Update workers with the
  server.
- Workers store results gzipped (about a fifth of their size in Redis), which
  requires Celery >= 5.7, and each worker process reserves one task at a time
  rather than four, so tasks (and generation requests) don't wait behind a
  busy process while others are idle.
- The tasks that collect member tracks to animate an analysis receive its
  display period and step rather than every display time (up to 20,000 for
  each member). Update workers with the server.
- Gridding statistics of points to cells is vectorized: 0.1 s rather than
  1.4 s for 100,000 cells (means may differ in their last digit).
- Swath coverage curves of a region compute the area observed only at the
  times that observe more of it (for example, 43 ms rather than 376 ms for a
  region observed at 18 of the curve's 201 times).
- Deploy only after the images of a push to `main` are built (once its tests
  pass), rather than also as soon as it is pushed: a push that fails its tests
  no longer deploys its compose and config files with the previous images.

### Fixed

- Polling task status and progress no longer blocks other requests to the
  server.
- Result layers that finish loading after being replaced or cleared no longer
  stay on the globe, and layers hidden while loading stay hidden.
- Dialogs are labelled by their titles for screen readers, and close with
  Escape as soon as they show.
- Respond with MessagePack to requests with `Accept: application/x-msgpack`,
  as documented, rather than JSON (msgpack-asgi 2 changed its default type to
  `application/vnd.msgpack`).

## [2.1.0] - 2026-11-25

### Added

- Save analysis runs under saved designs: runs save under the saved design
  last opened or saved, list grouped by design, and move between designs.
  Saved designs count their runs. `GET /runs` filters runs by design, and
  `PATCH /runs/{id}` changes the design of a run.
- Compare the current analysis results with saved runs without saving them
  first, from the Analysis tab (Compare runs) or the Results dialog.
- Ground track swaths over a region, with the coverage of the region, and an
  animation duration (#17).
- Ground sample sizes of observations (#16).
- Coincident observations analysis (#14).
- Sampling sufficiency of coverage analyses (#15).
- Save designs and analysis runs to users' accounts, and compare saved runs
  (#13).
- Summaries of coverage and latency results over the region (#13).
- Limits on the work each request may enqueue (#13).
- CI tests before building images (#13).
- Display panel of view options and legends, and a dark theme (#12).
- Orbits from orbit mean-elements messages (OMM) as well as TLE (#12).
- API documentation (#11).
- Prompt users to sign in when they arrive (#10).

### Changed

- Require TAT-C 3.8 (>= 3.8.0, < 3.9), whose system catalog adds relaying
  systems (TDRS) and systems in storage (#18).
- Saved runs migrate to version 2 of the database schema on first use, with
  existing runs under no design.
- Deleting a saved design deletes the runs saved under it.
- Browsers revalidate frontend files before each use (#12).
- Refactor the backend around a shared analysis package, and the frontend
  (#11).

### Fixed

- Large and high-altitude footprints in Cesium (#12).
- The analysis animation is limited to the analysis duration (#12).
- Editing, analysis, and animation bugs (#11).

## [2.0.0] - 2026-11-23

### Added

- Authenticate users with Dex (OpenID Connect).
- Load satellites from the TAT-C system catalog with CelesTrak elements, and
  add instruments from the TAT-C instrument catalog.
- Expanded, animated analyses, with per-instrument footprints, colors, and
  filters.
- Editor panel embedded in the Cesium view as a collapsible drawer.

### Changed

- Require TAT-C 3.7.0.
- Cancel analysis runs when the analysis type changes, and drop results that
  include a removed satellite.

### Fixed

- Footprints and swaths that cover a pole, and footprints of non-simple
  instruments in animations.
- Overflight analysis of points with no observations.
- CelesTrak elements of large catalog numbers.

## [1.1.0] - 2026-09-04

### Added

- Automatic deployment with images from the GitHub Container Registry.
- Error handling and logging of failed Celery tasks.

### Changed

- Require TAT-C 3.5.0, with adapters to its interface and orbit schemas.
- Split development and production Docker Compose files.

## [1.0] - 2024-07-31

### Added

- Web application extracted from TAT-C into its own package.

[Unreleased]: https://github.com/code-lab-org/tatc-app/compare/v2.2.1...HEAD
[2.2.1]: https://github.com/code-lab-org/tatc-app/compare/v2.2.0...v2.2.1
[2.2.0]: https://github.com/code-lab-org/tatc-app/compare/v2.1.0...v2.2.0
[2.1.0]: https://github.com/code-lab-org/tatc-app/compare/ae1ad0e...v2.1.0
[2.0.0]: https://github.com/code-lab-org/tatc-app/commit/ae1ad0e
[1.1.0]: https://github.com/code-lab-org/tatc-app/commit/40868a2
[1.0]: https://github.com/code-lab-org/tatc-app/commit/e1e4b4e
