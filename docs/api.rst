Schema Reference
================

The request and response bodies of the API endpoints. Fields are listed by
their Python names: requests also accept the camel case aliases
(for example, ``instrumentColors`` for ``instrument_colors``) of models
derived from ``CamelModel``. A running server also documents every endpoint
interactively at ``/docs``.

Satellites, constellations, instruments, and orbits are the schemas of the
`TAT-C library <https://tatc.readthedocs.io>`_ (``tatc.schemas``).

Tasks
-----

Analyses and tracks run as tasks: an endpoint enqueues a task and responds
with its identifiers, and the results are retrieved once it completes.

.. autopydantic_model:: tatc_app.celery.schemas.CeleryTask

.. autopydantic_model:: tatc_app.celery.schemas.CeleryResultStatus

.. autopydantic_model:: tatc_app.celery.schemas.CeleryResultProgress

Analyses
--------

Requests of all analyses share the satellites, analysis period, and display
options of ``AnalysisRequest``, and results with animations share the
member tracks of ``AnimatedResult``.

.. autopydantic_model:: tatc_app.analysis.schemas.AnalysisRequest

.. autopydantic_model:: tatc_app.analysis.schemas.PointsCellsAnalysisRequest

.. autopydantic_model:: tatc_app.analysis.schemas.AnimatedResult

Results of coverage and latency analyses include a summary over their points:
shares of the region, and distributions of the points' statistics, weighted
by the area each point represents for points equally spaced in latitude and
longitude (see ``Weighting``).

.. autopydantic_model:: tatc_app.analysis.summary.Distribution

.. autopydantic_model:: tatc_app.analysis.summary.Histogram

.. autopydantic_model:: tatc_app.analysis.summary.CoverageCurve

Coverage and Revisit
^^^^^^^^^^^^^^^^^^^^

.. autopydantic_model:: tatc_app.coverage.schemas.CoverageAnalysisRequest

.. autopydantic_model:: tatc_app.coverage.schemas.CoverageAnalysisResult

.. autopydantic_model:: tatc_app.analysis.summary.CoverageSummary

A coverage analysis may also assess sampling sufficiency (``sufficiency`` of
its request): how well the observations of each point estimate the mean of a
field over the analysis period, for a field with a decorrelation time, and how
they spread in time and local time of day.

.. autopydantic_model:: tatc_app.coverage.schemas.SufficiencyOptions

.. autopydantic_model:: tatc_app.analysis.summary.SufficiencySummary

A coverage (or coincidence) analysis may also size the ground samples of
observations (``sample_size`` of its request): the larger of each
observation's pixel and pixel spacing, along and across track, for
instruments with pixels. Coverage results summarize the sizes of each point's
observations; a maximum sample size drops coarser observations before
coverage (or coincidence) is computed.

.. autopydantic_model:: tatc_app.coverage.schemas.SampleSizeOptions

.. autopydantic_model:: tatc_app.analysis.summary.SampleSizeSummary

Coincident Observations
^^^^^^^^^^^^^^^^^^^^^^^

A coincidence analysis finds the periods when at least ``min_platforms``
distinct platforms (member satellites, or satellites and constellations)
observe each point at once, within ``max_time_difference``, and gives the
statistics of coverage of those periods: its results and summary are those
of a coverage analysis, of coincidences rather than observations.

.. autopydantic_model:: tatc_app.coincidence.schemas.CoincidenceAnalysisRequest

.. autopydantic_model:: tatc_app.coincidence.schemas.CoincidenceAnalysisResult

Ground Track Swaths
^^^^^^^^^^^^^^^^^^^

A swath analysis samples the footprints of instruments every ``step``,
dissolved into segments that accumulate over the animation (``display``, by
default every ``step`` over the analysis period): swath segments are given
only over it.

With a ``region``, footprints are clipped to it and sampled over the whole
analysis period, to summarize the share of its area observed over time
(measured in an equal-area projection of the WGS 84 ellipsoid), its
observations (when any part of it is observed), and, with ``coincidence``,
the areas that two platforms observe in common within
``max_time_difference``. Without one, footprints are sampled only over the
animation.

.. autopydantic_model:: tatc_app.swaths.schemas.SwathAnalysisRequest

.. autopydantic_model:: tatc_app.swaths.schemas.SwathCoincidenceOptions

.. autopydantic_model:: tatc_app.swaths.schemas.SwathAnalysisResult

.. autopydantic_model:: tatc_app.analysis.summary.RegionSummary

.. autopydantic_model:: tatc_app.analysis.summary.SwathCoincidenceSummary

Data Latency
^^^^^^^^^^^^

.. autopydantic_model:: tatc_app.latency.schemas.LatencyAnalysisRequest

.. autopydantic_model:: tatc_app.latency.schemas.LatencyAnalysisResult

.. autopydantic_model:: tatc_app.analysis.summary.LatencySummary

Point Access (Overflight)
^^^^^^^^^^^^^^^^^^^^^^^^^

.. autopydantic_model:: tatc_app.overflight.schemas.OverflightAnalysisRequest

.. autopydantic_model:: tatc_app.overflight.schemas.OverflightAnalysisResult

Orbit and Ground Tracks
^^^^^^^^^^^^^^^^^^^^^^^

.. autopydantic_model:: tatc_app.tracking.schemas.OrbitTrackAnalysisRequest

.. autopydantic_model:: tatc_app.tracking.schemas.GroundTrackAnalysisRequest

Points, Cells, and Times
------------------------

Analyses of a region take points and cells as lists, or as specifications to
generate them.

.. autopydantic_model:: tatc_app.generation.schemas.PointGenerator

.. autopydantic_model:: tatc_app.generation.schemas.CellGenerator

.. autopydantic_model:: tatc_app.generation.schemas.TimeGenerator

The outline of a region (a polygon, known shape, or country) displays it.

.. autopydantic_model:: tatc_app.generation.schemas.RegionOutlineRequest

.. autoclass:: tatc_app.generation.schemas.PointGeneratorMethod
   :members:
   :undoc-members:

.. autoclass:: tatc_app.generation.schemas.CellStrips
   :members:
   :undoc-members:

.. autoclass:: tatc_app.generation.masks.KnownShape
   :members:
   :undoc-members:

Validation
----------

.. autopydantic_model:: tatc_app.validation.router.SpaceSystemValidation

.. autopydantic_model:: tatc_app.validation.router.MemberSummary

System and Instrument Catalogs
------------------------------

.. autopydantic_model:: tatc_app.system_catalog.systems.CatalogSatelliteSystem

.. autopydantic_model:: tatc_app.system_catalog.systems.CatalogSpacecraft

.. autopydantic_model:: tatc_app.system_catalog.systems.CatalogInstrument

.. autopydantic_model:: tatc_app.system_catalog.systems.CatalogBuildRequest

.. autopydantic_model:: tatc_app.system_catalog.systems.CatalogBuildResult

.. autopydantic_model:: tatc_app.system_catalog.systems.CatalogMember

.. autopydantic_model:: tatc_app.system_catalog.instruments.CatalogInstrumentEntry

.. autopydantic_model:: tatc_app.system_catalog.instruments.CatalogConfiguration

.. autopydantic_model:: tatc_app.system_catalog.instruments.CatalogInstrumentRequest

.. autopydantic_model:: tatc_app.system_catalog.instruments.CatalogInstrumentResult

CelesTrak
---------

.. autopydantic_model:: tatc_app.celestrak.catalog.CelestrakSearchResult

.. autopydantic_model:: tatc_app.celestrak.catalog.CelestrakObject

Authentication
--------------

.. autopydantic_model:: tatc_app.auth.AuthInfo

.. autopydantic_model:: tatc_app.auth.User

Saved Designs and Runs
----------------------

Signed-in users save designs (as the GUI exports them) and analysis runs to
their account. A saved run keeps its request (to run it again), its design,
and the summary of its results (for coverage and latency analyses), not the
full results.

.. autopydantic_model:: tatc_app.library.schemas.DesignInput

.. autopydantic_model:: tatc_app.library.schemas.DesignInfo

.. autopydantic_model:: tatc_app.library.schemas.SavedDesign

.. autopydantic_model:: tatc_app.library.schemas.RunInput

.. autopydantic_model:: tatc_app.library.schemas.RunRename

.. autopydantic_model:: tatc_app.library.schemas.RunInfo

.. autopydantic_model:: tatc_app.library.schemas.SavedRun
