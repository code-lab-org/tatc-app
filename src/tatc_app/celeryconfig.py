"""
Celery configuration file.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

# Celery reads lowercase setting names
# pylint: disable=invalid-name

from tatc_app import limits

broker_connection_retry_on_startup = True
task_compression = "gzip"

# keep results for a known time (Celery's default is one day) so clients
# and the per-user limit of running analyses can rely on it
result_expires = limits.RESULT_EXPIRES

# stop tasks that run too long (enforced by workers using the prefork pool,
# not the solo pool), recording them as failed
task_time_limit = limits.TASK_TIME_LIMIT or None
