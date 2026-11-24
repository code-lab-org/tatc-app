"""
Shared base schemas.

@author: Paul T. Grogan <paul.grogan@asu.edu>
"""

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """
    Base class for request schemas that accept both snake_case field names
    and their camelCase aliases.
    """

    model_config = ConfigDict(
        from_attributes=True, populate_by_name=True, alias_generator=to_camel
    )
