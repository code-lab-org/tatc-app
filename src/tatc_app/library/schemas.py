"""
Schema specifications of saved designs and analysis runs.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

import json
from enum import Enum
from typing import Annotated, Any, Dict, Optional
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints, model_validator

from .. import limits
from ..utils.schemas import CamelModel

# the name of a saved design or run
Name = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]


class AnalysisType(str, Enum):
    """
    Type of a saved analysis run (as the GUI names its analyses).
    """

    coverage = "coverage"
    coincidence = "coincidence"
    swaths = "swaths"
    latency = "latency"
    access = "access"
    region = "region"


def check_size(*values: Any) -> None:
    """
    Checks values (as JSON) are within the maximum size of a saved record.

    Raises:
        ValueError: if the values are too large.
    """
    size = sum(len(json.dumps(value)) for value in values)
    if size > limits.MAX_SAVED_BYTES:
        raise ValueError(
            f"Too large to save: {size:,} bytes (at most {limits.MAX_SAVED_BYTES:,})."
        )


class DesignInput(CamelModel):
    """
    A design to save: satellites and constellations (and their display
    colors), ground stations, and target points, as the GUI exports them.
    """

    name: Name = Field(..., description="Name of the design.")
    design: Dict[str, Any] = Field(..., description="The design (as exported).")

    @model_validator(mode="after")
    def validate_size(self) -> "DesignInput":
        """
        Validates the design is within the maximum size.
        """
        check_size(self.design)
        return self


class DesignInfo(BaseModel):
    """
    A saved design, without its data.
    """

    id: UUID = Field(..., description="Identifier of the saved design.")
    name: str = Field(..., description="Name of the design.")
    created: str = Field(..., description="Time (ISO 8601) it was first saved.")
    updated: str = Field(..., description="Time (ISO 8601) it was last saved.")
    satellites: int = Field(
        ..., description="Number of satellites and constellations of the design."
    )


class SavedDesign(DesignInfo):
    """
    A saved design, with its data.
    """

    design: Dict[str, Any] = Field(..., description="The design (as exported).")


class RunInput(CamelModel):
    """
    An analysis run to save: its request (to run it again) and the design it
    analyzed (to show it again), with the summary of the results of its task.
    """

    name: Name = Field(..., description="Name of the run.")
    analysis: AnalysisType = Field(..., description="Type of the analysis.")
    task_id: UUID = Field(
        ...,
        description="Identifier of the completed analysis task, whose results "
        "summarize the run (for coverage and latency analyses).",
    )
    request: Dict[str, Any] = Field(..., description="The analysis request.")
    design: Dict[str, Any] = Field(..., description="The design (as exported).")

    @model_validator(mode="after")
    def validate_size(self) -> "RunInput":
        """
        Validates the run is within the maximum size.
        """
        check_size(self.request, self.design)
        return self


class RunRename(CamelModel):
    """
    A new name of a saved run.
    """

    name: Name = Field(..., description="Name of the run.")


class RunInfo(BaseModel):
    """
    A saved analysis run, with its summary but without its inputs.
    """

    id: UUID = Field(..., description="Identifier of the saved run.")
    name: str = Field(..., description="Name of the run.")
    analysis: AnalysisType = Field(..., description="Type of the analysis.")
    created: str = Field(..., description="Time (ISO 8601) it was saved.")
    summary: Optional[Dict[str, Any]] = Field(
        None,
        description="Summary of the results (`CoverageSummary` or "
        "`LatencySummary`), or null for analyses without one.",
    )


class SavedRun(RunInfo):
    """
    A saved analysis run, with its inputs.
    """

    request: Dict[str, Any] = Field(..., description="The analysis request.")
    design: Dict[str, Any] = Field(..., description="The design (as exported).")
