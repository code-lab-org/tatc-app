"""
Limits on the work that requests may enqueue, so a shared deployment stays
responsive for all users. Each limit is configured by an environment
variable (see the README).

Limits are read through this module (for example, `limits.MAX_POINTS`)
rather than imported by name, so tests can change them.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import os
from datetime import timedelta

from dotenv import load_dotenv

load_dotenv()


def _env_number(name: str, default: float) -> float:
    """
    Gets a non-negative number from an environment variable.

    Raises:
        ValueError: if the variable is set but not a non-negative number.
    """
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    number = float(value)
    if not number >= 0:
        raise ValueError(f"{name} must be a non-negative number, got {value!r}.")
    return number


# maximum number of points (generated or listed) of an analysis or request
# to generate points
MAX_POINTS = int(_env_number("TATC_MAX_POINTS", 100_000))

# maximum number of cells (generated or listed) of an analysis or request to
# generate cells
MAX_CELLS = int(_env_number("TATC_MAX_CELLS", 100_000))

# maximum number of candidate points or cells generated before clipping them
# to a mask (a Fibonacci lattice always covers the globe, and an equally
# spaced grid covers the bounds of the mask), which bounds the memory and
# time of generation even when few candidates fall within the mask
MAX_GRID_CANDIDATES = 5_000_000

# maximum duration of the analysis period
MAX_ANALYSIS_DURATION = timedelta(days=_env_number("TATC_MAX_ANALYSIS_DAYS", 366))

# maximum number of analyses each user may have running at once (0 for no limit)
MAX_ACTIVE_ANALYSES = int(_env_number("TATC_MAX_ACTIVE_ANALYSES", 3))

# time (seconds) after which workers stop a task that has not finished (0
# for no limit)
TASK_TIME_LIMIT = int(_env_number("TATC_TASK_TIME_LIMIT", 3600))

# time (seconds) for which the backend keeps task results
RESULT_EXPIRES = int(_env_number("TATC_RESULT_EXPIRES", 86400))
