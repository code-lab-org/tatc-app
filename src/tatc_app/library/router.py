"""
Router specifications of the designs and analysis runs that users save.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import json
import logging
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import ValidationError

from .. import limits
from ..analysis.summary import CoverageSummary, LatencySummary, RegionSummary
from ..auth import User, current_user
from ..celery.utils import get_task_result
from ..coincidence.schemas import CoincidenceAnalysisRequest
from ..coverage.schemas import CoverageAnalysisRequest
from ..latency.schemas import LatencyAnalysisRequest
from ..overflight.schemas import OverflightAnalysisRequest
from ..swaths.schemas import SwathAnalysisRequest
from .database import library
from .schemas import (
    AnalysisType,
    DesignInfo,
    DesignInput,
    RunInfo,
    RunInput,
    RunRename,
    SavedDesign,
    SavedRun,
)

logger = logging.getLogger(__name__)

designs_router = APIRouter()
runs_router = APIRouter()

# the request schema of each type of analysis
REQUEST_MODELS = {
    AnalysisType.coverage: CoverageAnalysisRequest,
    AnalysisType.coincidence: CoincidenceAnalysisRequest,
    AnalysisType.swaths: SwathAnalysisRequest,
    AnalysisType.latency: LatencyAnalysisRequest,
    AnalysisType.access: OverflightAnalysisRequest,
}

# the summary schema of each type of analysis with a summary
SUMMARY_MODELS = {
    AnalysisType.coverage: CoverageSummary,
    AnalysisType.coincidence: CoverageSummary,
    AnalysisType.latency: LatencySummary,
    AnalysisType.swaths: RegionSummary,
}

# the types of analysis whose results have a summary only for some requests
# (swaths, only over a region)
OPTIONAL_SUMMARIES = {AnalysisType.swaths}


def check_capacity(table: str, user: User) -> None:
    """
    Checks a user may save another design or run.

    Raises:
        HTTPException: (409) if the user has saved the most allowed.
    """
    if library.count(table, user.id) >= limits.MAX_SAVED_ITEMS:
        raise HTTPException(
            status_code=409,
            detail=f"Too many saved {table} (at most {limits.MAX_SAVED_ITEMS}). "
            "Delete some and try again.",
        )


def not_found(kind: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"{kind} not found.")


# --- Designs ---


@designs_router.get("", response_model=List[DesignInfo])
def list_designs(user: User = Depends(current_user)):
    """
    Endpoint to list the saved designs of the user, latest first.
    """
    return library.list_designs(user.id)


@designs_router.post("", response_model=SavedDesign)
def save_design(design: DesignInput, user: User = Depends(current_user)):
    """
    Endpoint to save a new design of the user.
    """
    check_capacity("designs", user)
    return library.create_design(user.id, design.name, design.design)


@designs_router.get("/{design_id}", response_model=SavedDesign)
def get_design(design_id: UUID, user: User = Depends(current_user)):
    """
    Endpoint to get a saved design of the user.
    """
    design = library.get_design(user.id, str(design_id))
    if design is None:
        raise not_found("Design")
    return design


@designs_router.put("/{design_id}", response_model=SavedDesign)
def update_design(
    design_id: UUID, design: DesignInput, user: User = Depends(current_user)
):
    """
    Endpoint to replace a saved design of the user.
    """
    saved = library.update_design(user.id, str(design_id), design.name, design.design)
    if saved is None:
        raise not_found("Design")
    return saved


@designs_router.delete("/{design_id}", status_code=204)
def delete_design(design_id: UUID, user: User = Depends(current_user)):
    """
    Endpoint to delete a saved design of the user.
    """
    if not library.delete_design(user.id, str(design_id)):
        raise not_found("Design")
    return Response(status_code=204)


# --- Runs ---


def get_run_summary(analysis: AnalysisType, task_id: UUID) -> Optional[dict]:
    """
    Gets the summary of the results of a completed analysis task (`None`
    for analyses without a summary).

    Raises:
        HTTPException: (409) if the results are not available, or (422) if
            they are not the results of the analysis.
    """
    model = SUMMARY_MODELS.get(analysis)
    if model is None:
        return None
    try:
        result = json.loads(get_task_result(task_id, f"{analysis.value} run", logger))
    except HTTPException as exc:
        if exc.status_code == 409:
            raise HTTPException(
                status_code=409,
                detail="The results of the run are not available (not finished, "
                "or expired). Run the analysis again to save it.",
            ) from exc
        raise
    summary = result.get("summary") if isinstance(result, dict) else None
    # swath analyses summarize only the coverage of a region
    if summary is None and analysis in OPTIONAL_SUMMARIES and "swaths" in result:
        return None
    try:
        return model.model_validate(summary).model_dump(mode="json")
    except (AttributeError, ValidationError) as exc:
        raise HTTPException(
            status_code=422,
            detail=f"The task's results are not of a {analysis.value} analysis.",
        ) from exc


@runs_router.get("", response_model=List[RunInfo])
def list_runs(
    analysis: Optional[AnalysisType] = None, user: User = Depends(current_user)
):
    """
    Endpoint to list the saved runs of the user (with their summaries),
    latest first, optionally of one type of analysis.
    """
    return library.list_runs(user.id, None if analysis is None else analysis.value)


@runs_router.post("", response_model=SavedRun)
def save_run(run: RunInput, user: User = Depends(current_user)):
    """
    Endpoint to save a completed analysis run of the user: its request (to
    run it again), its design, and the summary of its results.
    """
    check_capacity("runs", user)
    try:
        REQUEST_MODELS[run.analysis].model_validate(run.request)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=[
                {"loc": ["body", "request", *error["loc"]], "msg": error["msg"]}
                for error in exc.errors(include_url=False)
            ],
        ) from exc
    summary = get_run_summary(run.analysis, run.task_id)
    return library.create_run(
        user.id, run.name, run.analysis.value, run.request, run.design, summary
    )


@runs_router.get("/{run_id}", response_model=SavedRun)
def get_run(run_id: UUID, user: User = Depends(current_user)):
    """
    Endpoint to get a saved run of the user, with its inputs.
    """
    run = library.get_run(user.id, str(run_id))
    if run is None:
        raise not_found("Run")
    return run


@runs_router.patch("/{run_id}", response_model=SavedRun)
def rename_run(run_id: UUID, rename: RunRename, user: User = Depends(current_user)):
    """
    Endpoint to rename a saved run of the user.
    """
    run = library.rename_run(user.id, str(run_id), rename.name)
    if run is None:
        raise not_found("Run")
    return run


@runs_router.delete("/{run_id}", status_code=204)
def delete_run(run_id: UUID, user: User = Depends(current_user)):
    """
    Endpoint to delete a saved run of the user.
    """
    if not library.delete_run(user.id, str(run_id)):
        raise not_found("Run")
    return Response(status_code=204)
