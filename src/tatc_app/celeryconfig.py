"""
Celery configuration file.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

# Celery reads lowercase setting names
# pylint: disable=invalid-name

from kombu import Queue

from tatc_app import limits

broker_connection_retry_on_startup = True

# Generating points or cells blocks the request that waits for it, so it has
# its own queue: it waits for the next free worker process rather than behind
# every queued chunk of other analyses. Workers consume all queues listed here
# (unless started with `-Q`).
task_default_queue = "celery"
task_queues = (Queue("celery"), Queue("generation"))
task_routes = {
    "tatc_app.generation.tasks.generate_points_task": {"queue": "generation"},
    "tatc_app.generation.tasks.generate_cells_task": {"queue": "generation"},
}
task_compression = "gzip"

# Results (several megabytes of JSON for large analyses) are stored gzipped,
# about a fifth of their size. Celery (>= 5.7) marks compressed results, so
# results stored before remain readable.
result_compression = "gzip"

# Each worker process reserves only the task it runs (and one more), rather
# than four: analysis tasks run for seconds, so reserving more would hold
# tasks (including generation tasks, which requests wait for) behind them
# while other processes are idle.
worker_prefetch_multiplier = 1

# keep results for a known time (Celery's default is one day) so clients
# and the per-user limit of running analyses can rely on it
result_expires = limits.RESULT_EXPIRES

# stop tasks that run too long (enforced by workers using the prefork pool,
# not the solo pool), recording them as failed
task_time_limit = limits.TASK_TIME_LIMIT or None
