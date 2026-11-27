"""
Runs the app for browser tests (see conftest.py): without sign in, with
tasks run eagerly (in the server process) and saved designs and runs in an
empty, temporary database.

Usage: python -m tests.browser.serve PORT
"""

import contextlib
import os
import sys
import tempfile

os.environ.update(
    TATC_AUTH="none",
    TATC_BROKER="memory://",
    TATC_BACKEND="cache+memory://",
    TATC_DATABASE=os.path.join(tempfile.mkdtemp(prefix="tatc-browser-"), "tatc.db"),
    # as in CI, which has no Cesium ion token
    TATC_CESIUM_TOKEN="",
)

# pylint: disable=wrong-import-position
import celery.app.task
import uvicorn

from tatc_app.worker import app as celery_app

celery_app.conf.update(
    task_always_eager=True,
    task_eager_propagates=False,
    task_store_eager_result=True,
)
# Eager tasks of concurrent requests (in the server's threadpool) race on
# Celery's process-wide flag that refuses to wait for results within a task
# (`denied_join_result`), which can leave it set: then point and cell
# generation, which waits for its task, fails. Workers never run tasks of
# concurrent requests in one process, so the tests disable the flag.
celery.app.task.denied_join_result = contextlib.nullcontext

if __name__ == "__main__":
    uvicorn.run(
        "tatc_app.main:app",
        host="127.0.0.1",
        port=int(sys.argv[1]),
        log_level="warning",
    )
