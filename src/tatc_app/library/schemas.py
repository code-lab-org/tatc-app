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
    runs: int = Field(..., description="Number of analysis runs saved under it.")


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
    design_id: Optional[UUID] = Field(
        None,
        description="Identifier of the saved design to save the run under (the "
        "design it analyzes may since differ), or null for none.",
    )
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


class RunUpdate(CamelModel):
    """
    Changes to a saved run: its name, or the saved design it is saved under
    (null for none). Fields left out do not change.
    """

    name: Optional[Name] = Field(None, description="Name of the run.")
    design_id: Optional[UUID] = Field(
        None, description="Identifier of the saved design, or null for none."
    )

    @model_validator(mode="after")
    def validate_fields(self) -> "RunUpdate":
        """
        Validates the update changes something, and does not clear the name.
        """
        if not self.model_fields_set:
            raise ValueError("Nothing to update.")
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("The name of a run cannot be null.")
        return self


class RunInfo(BaseModel):
    """
    A saved analysis run, with its summary but without its inputs.
    """

    id: UUID = Field(..., description="Identifier of the saved run.")
    name: str = Field(..., description="Name of the run.")
    analysis: AnalysisType = Field(..., description="Type of the analysis.")
    design_id: Optional[UUID] = Field(
        None, description="Identifier of the saved design it is saved under."
    )
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
