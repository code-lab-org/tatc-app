# Changelog

All notable changes to the TAT-C web application are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). The version is set
by `__version__` in `src/tatc_app/__init__.py`.

## [Unreleased]

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

[Unreleased]: https://github.com/code-lab-org/tatc-app/compare/ae1ad0e...main
[2.0.0]: https://github.com/code-lab-org/tatc-app/commit/ae1ad0e
[1.1.0]: https://github.com/code-lab-org/tatc-app/commit/40868a2
[1.0]: https://github.com/code-lab-org/tatc-app/commit/e1e4b4e
