"""Pydantic-compatible wrapper implemented with stdlib dataclasses."""

from jafta.pydantic_compat.core import (
    BaseModel,
    BaseSettings,
    canonical_input_key,
    field_for_input_key,
    lenient_literals,
)
from jafta.pydantic_compat.errors import ValidationError
from jafta.pydantic_compat.fields import (
    AliasChoices,
    ConfigDict,
    Field,
    FieldInfo,
    to_camel,
)
from jafta.pydantic_compat.validators import field_validator, model_validator

__all__ = [
    "AliasChoices",
    "BaseModel",
    "BaseSettings",
    "ConfigDict",
    "Field",
    "FieldInfo",
    "ValidationError",
    "canonical_input_key",
    "field_for_input_key",
    "field_validator",
    "lenient_literals",
    "model_validator",
    "to_camel",
]
