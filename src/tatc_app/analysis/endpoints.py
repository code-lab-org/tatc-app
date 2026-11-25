"""
Shared utilities of analysis endpoints.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import logging
import math
import os
from typing import List, Optional, Type, TypeVar
from uuid import UUID

import numpy as np
from celery import chord, group
from celery.canvas import Signature
from pydantic import BaseModel
from tatc.schemas import Satellite

from ..celery.quota import TaskSlot
from ..celery.utils import enqueue, get_task_result
from .schemas import AnalysisRequest
from .tasks import collect_member_track_task

ResultT = TypeVar("ResultT", bound=BaseModel)
ItemsT = TypeVar("ItemsT")

# number of points analyzed by each parallel task
CHUNK_SIZE = int(os.getenv("TATC_CHUNK_SIZE", "250"))


def chunk(items: ItemsT, size: Optional[int] = None) -> List[ItemsT]:
    """
    Splits items (for example, a data frame or a time index) into chunks of
    (at most) a given size, to analyze in parallel tasks.

    Args:
        items: The items (a pandas object or a numpy array).
        size (Optional[int]): The maximum chunk size (default: `TATC_CHUNK_SIZE`).

    Returns:
        list: The (non-empty) chunks.
    """
    size = size or CHUNK_SIZE
    count = max(1, math.ceil(len(items) / size))
    positional = getattr(items, "iloc", items)
    return [
        positional[indices]
        for indices in np.array_split(np.arange(len(items)), count)
        if len(indices) > 0
    ]


def serialize_members(members: List[Satellite]) -> List[str]:
    """
    Serializes member satellites to pass to tasks (see
    `tasks.deserialize_members`).
    """
    return [member.model_dump_json() for member in members]


def member_track_signatures(
    request: AnalysisRequest, members: List[Satellite]
) -> List[Signature]:
    """
    Builds the signatures of tasks to collect the orbit tracks of member
    satellites over the display window of an analysis request.

    Args:
        request (AnalysisRequest): The analysis request.
        members (List[tatc.schemas.Satellite]): The member satellites.

    Returns:
        List[celery.canvas.Signature]: The task signatures.
    """
    times = [time.isoformat() for time in request.get_display_times()]
    colors = request.get_member_instrument_colors()
    return [
        collect_member_track_task.s(
            member.model_dump_json(),
            times,
            request.start.isoformat(),
            colors.get(member.name),
        )
        for member in members
    ]


def enqueue_analysis(
    request: AnalysisRequest,
    members: List[Satellite],
    tasks: List[Signature],
    combine: Signature,
    slot: TaskSlot,
) -> dict:
    """
    Enqueues an analysis: parallel tasks, plus tasks to collect the orbit
    track of each member satellite, followed by a task that combines their
    (tagged) results.

    Args:
        request (AnalysisRequest): The analysis request.
        members (List[tatc.schemas.Satellite]): The member satellites.
        tasks (List[celery.canvas.Signature]): The parallel analysis tasks.
        combine (celery.canvas.Signature): The task to combine results.
        slot (TaskSlot): The slot reserved for the user's analysis (see
            `celery.quota.analysis_slot`), counting it as running until its
            results are ready.

    Returns:
        dict: The enqueued task (see `celery.utils.enqueue`).
    """
    return slot.track(
        enqueue(
            chord(group(tasks + member_track_signatures(request, members)), combine)
        )
    )


def get_analysis_result(
    model: Type[ResultT], task_id: UUID, label: str, logger: logging.Logger
) -> ResultT:
    """
    Retrieves the (JSON serialized) result of a completed analysis task.

    Args:
        model (Type[pydantic.BaseModel]): The result schema.
        task_id (UUID): The task identifier.
        label (str): Human-readable task label, for logging.
        logger (logging.Logger): Logger to write failures to.

    Returns:
        pydantic.BaseModel: The result.
    """
    return model.model_validate_json(get_task_result(task_id, label, logger))
