# Changelog

All notable changes to the TAT-C web application are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). The version is set
by `__version__` in `src/tatc_app/__init__.py`.

## [Unreleased]

### Added

- `TATC_GENERATION_TIMEOUT`: time that a request waits for a worker to
  generate its points or cells before failing (HTTP 503), 300 seconds by
  default.
- `TATC_MAX_TRACK_POSITIONS`: maximum number of positions (member satellites
  times sample times) of an orbit or ground track request, 200,000 by
  default (HTTP 422 beyond it).

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

### Fixed

- Polling task status and progress no longer blocks other requests to the
  server.
- Result layers that finish loading after being replaced or cleared no longer
  stay on the globe, and layers hidden while loading stay hidden.

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

[Unreleased]: https://github.com/code-lab-org/tatc-app/compare/v2.1.0...HEAD
[2.1.0]: https://github.com/code-lab-org/tatc-app/compare/ae1ad0e...v2.1.0
[2.0.0]: https://github.com/code-lab-org/tatc-app/commit/ae1ad0e
[1.1.0]: https://github.com/code-lab-org/tatc-app/commit/40868a2
[1.0]: https://github.com/code-lab-org/tatc-app/commit/e1e4b4e
