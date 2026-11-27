"""
Shared utilities of analysis endpoints.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import logging
import math
import os
from typing import Callable, List, Optional, Type, TypeVar
from uuid import UUID

import numpy as np
from celery import chord, group
from celery.canvas import Signature
from fastapi import APIRouter, Response
from pydantic import BaseModel
from tatc.schemas import Satellite

from ..celery.quota import TaskSlot
from ..celery.utils import enqueue, get_task_result
from ..cesium.czml import animation_packets
from ..utils.serialization import MSGPACK_RESPONSES
from .schemas import AnalysisRequest, AnimatedResult
from .tasks import collect_member_track_task

ResultT = TypeVar("ResultT", bound=BaseModel)
AnimatedT = TypeVar("AnimatedT", bound=AnimatedResult)
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
    display = request.get_display().model_dump(mode="json")
    colors = request.get_member_instrument_colors()
    return [
        collect_member_track_task.s(
            member.model_dump_json(),
            display,
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
    Retrieves the (JSON serialized) result of a completed analysis task, as
    a model.

    Args:
        model (Type[pydantic.BaseModel]): The result schema.
        task_id (UUID): The task identifier.
        label (str): Human-readable task label, for logging.
        logger (logging.Logger): Logger to write failures to.

    Returns:
        pydantic.BaseModel: The result.
    """
    return model.model_validate_json(get_task_result(task_id, label, logger))


def add_result_routes(  # pylint: disable=too-many-arguments
    router: APIRouter,
    path: str,
    model: Type[AnimatedT],
    label: str,
    logger: logging.Logger,
    czml_description: str,
    czml_packets: Optional[Callable[[AnimatedT], List[dict]]] = None,
) -> None:
    """
    Adds the endpoints that retrieve the results of a completed analysis
    task, `GET /{path}/{task_id}`, and its animation as a CZML document,
    `GET /{path}/{task_id}/czml`: its member satellites (see
    `cesium.czml.animation_packets`), followed by any other packets of the
    result.

    Tasks store results as the endpoint responds with them (see
    `utils.serialization.to_response_json`), so it returns them as they are:
    its `response_model` only documents them.

    Args:
        router (fastapi.APIRouter): The router of the analysis.
        path (str): The path of the analysis (for example, `coverage`).
        model (Type[AnimatedResult]): The result schema.
        label (str): Human-readable analysis label (for example, "Coverage
            analysis"), which also names the endpoints and CZML document.
        logger (logging.Logger): Logger to write failures to.
        czml_description (str): What the CZML document animates.
        czml_packets (Optional[Callable]): Builds the other CZML packets of a
            result, if any.
    """
    key = label.lower().replace(" ", "_")

    def retrieve(task_id: UUID):
        return Response(
            get_task_result(task_id, label, logger), media_type="application/json"
        )

    def retrieve_czml(task_id: UUID):
        result = get_analysis_result(model, task_id, label, logger)
        packets = animation_packets(label, result)
        return packets if czml_packets is None else packets + czml_packets(result)

    router.add_api_route(
        f"/{path}/{{task_id}}",
        retrieve,
        methods=["GET"],
        name=f"retrieve_{key}",
        description=f"Retrieves the results of a completed {label.lower()} task.",
        response_model=model,
        response_model_exclude_none=True,
        responses=MSGPACK_RESPONSES,
    )
    router.add_api_route(
        f"/{path}/{{task_id}}/czml",
        retrieve_czml,
        methods=["GET"],
        name=f"retrieve_{key}_czml",
        description=f"Retrieves a completed {label.lower()} task as a CZML "
        f"document, animating {czml_description}.",
        response_model=List[dict],
    )
