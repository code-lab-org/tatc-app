"""
Limit on the number of analyses each user may have running at once, so one
user cannot fill the task queue for everyone.

The server tracks the analyses each user enqueues (in memory, so the limit
applies per server process) until their results are ready, they are
revoked, or their results would have expired from the backend.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import threading
import time
from typing import Callable, Dict, Iterator, Optional
from uuid import uuid4

from fastapi import Depends, HTTPException

from .. import limits
from ..auth import User, current_user
from ..worker import app as celery_app

# prefix of the keys of reservations not (yet) bound to an enqueued task
_RESERVATION = "reservation:"


class TaskQuota:
    """
    Tracks the running tasks of each user, limiting how many may run at once.
    """

    def __init__(
        self,
        limit: Callable[[], int],
        max_age: Callable[[], float],
        is_ready: Optional[Callable[[str], bool]] = None,
    ):
        """
        Args:
            limit (Callable[[], int]): Gets the maximum number of running
                tasks per user (0 for no limit).
            max_age (Callable[[], float]): Gets the time (seconds) after which
                a task no longer counts as running (such as the time for
                which the backend keeps results, after which a task is no
                longer known).
            is_ready (Optional[Callable[[str], bool]]): Tests whether the
                result of a task (by identifier) is ready (default: from the
                Celery result backend).
        """
        self._limit = limit
        self._max_age = max_age
        self._is_ready = is_ready or (
            lambda task_id: celery_app.AsyncResult(task_id).ready()
        )
        self._lock = threading.Lock()
        # the start time of each running task (or reservation), by user
        self._running: Dict[str, Dict[str, float]] = {}

    def _prune(self, user_id: str, now: float) -> Dict[str, float]:
        """
        Forgets tasks that are too old (of all users), or ready (of a user),
        and gets the remaining tasks of the user.
        """
        max_age = self._max_age()
        for user in list(self._running):
            tasks = self._running[user]
            for key in [k for k, start in tasks.items() if now - start > max_age]:
                del tasks[key]
            if not tasks:
                del self._running[user]
        tasks = self._running.get(user_id, {})
        for key in list(tasks):
            if not key.startswith(_RESERVATION) and self._is_ready(key):
                del tasks[key]
        return tasks

    def reserve(self, user_id: str) -> "TaskSlot":
        """
        Reserves a slot for a user's task.

        Args:
            user_id (str): The user identifier.

        Raises:
            HTTPException: (429) if the user has too many running tasks.

        Returns:
            TaskSlot: The reserved slot, to bind to the enqueued task (or
                release).
        """
        with self._lock:
            now = time.time()
            tasks = self._prune(user_id, now)
            limit = self._limit()
            if limit and len(tasks) >= limit:
                raise HTTPException(
                    status_code=429,
                    detail=f"Too many running analyses ({len(tasks)} of at most "
                    f"{limit}). Wait for an analysis to finish, or cancel one, "
                    "and try again.",
                )
            key = f"{_RESERVATION}{uuid4()}"
            self._running.setdefault(user_id, {})[key] = now
            return TaskSlot(self, user_id, key)

    def _bind(self, user_id: str, key: str, task_id: str) -> None:
        with self._lock:
            tasks = self._running.setdefault(user_id, {})
            tasks[task_id] = tasks.pop(key, time.time())

    def _release(self, user_id: str, key: str) -> None:
        with self._lock:
            tasks = self._running.get(user_id, {})
            tasks.pop(key, None)
            if not tasks:
                self._running.pop(user_id, None)

    def release_task(self, task_id: str) -> None:
        """
        Stops counting a task (for example, once revoked) as running.

        Args:
            task_id (str): The task identifier.
        """
        with self._lock:
            for user in list(self._running):
                self._running[user].pop(task_id, None)
                if not self._running[user]:
                    del self._running[user]

    def running(self, user_id: str) -> int:
        """
        Counts the running tasks (and reservations) of a user.

        Args:
            user_id (str): The user identifier.

        Returns:
            int: The number of running tasks.
        """
        with self._lock:
            return len(self._prune(user_id, time.time()))


class TaskSlot:
    """
    A slot reserved for a user's task.
    """

    def __init__(self, quota: TaskQuota, user_id: str, key: str):
        self._quota = quota
        self._user_id = user_id
        self._key = key
        self._bound = False

    def track(self, task: dict) -> dict:
        """
        Binds the slot to an enqueued task, counted as running until its
        (final) result is ready.

        Args:
            task (dict): The enqueued task, with its `task_id` (see
                `celery.utils.enqueue`).

        Returns:
            dict: The enqueued task.
        """
        self._quota._bind(  # pylint: disable=protected-access
            self._user_id, self._key, task["task_id"]
        )
        self._bound = True
        return task

    def close(self) -> None:
        """
        Releases the slot if no task was bound to it (for example, if the
        request failed before enqueuing a task).
        """
        if not self._bound:
            self._quota._release(  # pylint: disable=protected-access
                self._user_id, self._key
            )


# the running analyses of users
analysis_quota = TaskQuota(
    lambda: limits.MAX_ACTIVE_ANALYSES, lambda: limits.RESULT_EXPIRES
)


def analysis_slot(user: User = Depends(current_user)) -> Iterator[TaskSlot]:
    """
    Dependency to reserve a slot for the analysis a user enqueues.

    Raises:
        HTTPException: (429) if the user has too many running analyses.

    Yields:
        TaskSlot: The reserved slot, to bind to the enqueued analysis.
    """
    slot = analysis_quota.reserve(user.id)
    try:
        yield slot
    finally:
        slot.close()
