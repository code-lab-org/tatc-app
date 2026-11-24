"""
Schema specifications for generation endpoints.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

from datetime import datetime, timedelta
from enum import Enum
from typing import Annotated, Optional, Union

import pandas as pd
from geojson_pydantic import Polygon
from pydantic import AwareDatetime, Field, StringConstraints, model_validator
from shapely.geometry import box, mapping

from ..utils.schemas import CamelModel


class PointGeneratorMethod(str, Enum):
    """
    Method for point generation.
    """

    fibonacci_lattice = "fibonacci_lattice"
    equally_spaced = "equally_spaced"


class KnownShape(str, Enum):
    """
    Known shapes to use as masks.
    """

    conus = "conus"


# a mask to limit the extent of generated points or cells: a polygon, a known
# shape, or an ISO 3166-1 alpha-3 country code
Mask = Union[
    Polygon,
    KnownShape,
    Annotated[str, StringConstraints(min_length=3, max_length=3)],
]


class PointGenerator(CamelModel):
    """
    Specification to generate points.
    """

    method: PointGeneratorMethod = Field(
        PointGeneratorMethod.equally_spaced, description="Point generation method."
    )
    distance: float = Field(
        1e6, description="Characteristic distance (meters) between points."
    )
    elevation: float = Field(
        0,
        description="Elevation (meters) above datum in the WGS 84 coordinate system.",
    )
    mask: Optional[Mask] = Field(
        None,
        description="Mask to limit the extent of generated points. Allows ISO 3166-1 alpha-3 country codes.",
        examples=[Polygon(**mapping(box(-180, -90, 180, 90)))],
    )


class Cell(Polygon):
    """
    Cell represented as a polygon.
    """


class CellGeneratorMethod(str, Enum):
    """
    Method for cell generation.
    """

    equally_spaced = "equally_spaced"


class CellStrips(str, Enum):
    """
    Options for cells in strips.
    """

    latitude = "lat"
    longitude = "lon"


class CellGenerator(CamelModel):
    """
    Specification to generate cells.
    """

    method: CellGeneratorMethod = Field(
        CellGeneratorMethod.equally_spaced, description="Cell generation method."
    )
    distance: float = Field(
        1e6, description="Characteristic distance (meters) between cell centroids."
    )
    elevation: float = Field(
        0,
        description="Elevation (meters) above datum in the WGS 84 coordinate system.",
    )
    mask: Optional[Mask] = Field(
        None,
        description="Mask to limit the extent of generated cells. Allows ISO 3166-1 alpha-3 country codes.",
        examples=[Polygon(**mapping(box(-180, -90, 180, 90)))],
    )
    strips: Optional[CellStrips] = Field(
        None, description="Option for latitude or longitude strips for cells."
    )


class TimeGenerator(CamelModel):
    """
    Specification to generate time series.
    """

    start: AwareDatetime = Field(
        ...,
        description="Start date time of the observation period.",
        examples=[datetime.fromisoformat("2021-01-01T00:00:00+00:00")],
    )
    end: AwareDatetime = Field(
        ...,
        description="End date time of the observation period.",
        examples=[datetime.fromisoformat("2021-01-01T01:00:00+00:00")],
    )
    delta: timedelta = Field(
        ...,
        gt=timedelta(0),
        description="Time step duration.",
        examples=[timedelta(seconds=30)],
    )

    @model_validator(mode="after")
    def validate_period(self) -> "TimeGenerator":
        """
        Validates the start precedes the end by at least one time step.
        """
        if self.end <= self.start:
            raise ValueError("Invalid end: start must precede end.")
        if self.delta > self.end - self.start:
            raise ValueError("Invalid delta: must not exceed (end - start).")
        return self

    def to_index(self, max_count: int = 100000) -> "pd.DatetimeIndex":
        """
        Generates the time series (in UTC).

        Args:
            max_count (int): Maximum number of times allowed.

        Raises:
            ValueError: if the series would exceed `max_count` times.

        Returns:
            pandas.DatetimeIndex: The times.
        """
        if (self.end - self.start) / self.delta >= max_count:
            raise ValueError(
                f"Too many time steps: (end - start) / delta must be less than {max_count}."
            )
        return pd.date_range(self.start, self.end, freq=self.delta).tz_convert("UTC")
