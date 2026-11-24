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

Coverage and Revisit
^^^^^^^^^^^^^^^^^^^^

.. autopydantic_model:: tatc_app.coverage.schemas.CoverageAnalysisRequest

.. autopydantic_model:: tatc_app.coverage.schemas.CoverageAnalysisResult

Data Latency
^^^^^^^^^^^^

.. autopydantic_model:: tatc_app.latency.schemas.LatencyAnalysisRequest

.. autopydantic_model:: tatc_app.latency.schemas.LatencyAnalysisResult

Point Access (Overflight)
^^^^^^^^^^^^^^^^^^^^^^^^^

.. autopydantic_model:: tatc_app.overflight.schemas.OverflightAnalysisRequest

.. autopydantic_model:: tatc_app.overflight.schemas.OverflightAnalysisResult

Ground Track Swaths
^^^^^^^^^^^^^^^^^^^

.. autopydantic_model:: tatc_app.tracking.schemas.SwathAnalysisRequest

.. autopydantic_model:: tatc_app.tracking.schemas.SwathAnalysisResult

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
