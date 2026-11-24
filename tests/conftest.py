"""
Test configuration.

By default, tests run Celery tasks eagerly (in-process) with an in-memory
result backend, so they do not require a broker, backend, or worker. Set the
environment variable `TATC_TEST_LIVE=1` to instead run tests against the
broker and backend configured by `TATC_BROKER` and `TATC_BACKEND` (with at
least one worker running).

Tests run with authentication disabled (`TATC_AUTH=none`); `test_auth.py`
tests authentication with an OpenID Connect provider.
"""

import os

# authentication is tested separately (see `test_auth.py`)
os.environ["TATC_AUTH"] = "none"

if os.getenv("TATC_TEST_LIVE", "0") != "1":
    os.environ["TATC_BROKER"] = "memory://"
    os.environ["TATC_BACKEND"] = "cache+memory://"

    from tatc_app.worker import app as celery_app

    celery_app.conf.update(
        task_always_eager=True,
        task_eager_propagates=False,
        task_store_eager_result=True,
    )
