from typing import Literal, List
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class FieldRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=200)
    target: str = Field(min_length=1, max_length=80)
    kind: Literal["text", "email", "decimal", "date"] = "text"
    required: bool = False
    trim: bool = True
    collapse_spaces: bool = False
    casing: Literal["preserve", "lower", "upper"] = "preserve"
    date_format: Literal["%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"] = "%Y-%m-%d"

    @field_validator("source", "target")
    @classmethod
    def excel_safe_name(cls, value: str) -> str:
        if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]", value):
            raise ValueError("Field names contain characters Excel cannot store.")
        return value

    @field_validator("target")
    @classmethod
    def valid_target(cls, value: str) -> str:
        if not value.strip() or value != value.strip():
            raise ValueError("Destination names must be nonblank with no surrounding spaces.")
        if value.startswith("_"):
            raise ValueError("Destination names beginning with _ are reserved for audit metadata.")
        return value


class ProcessConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fields: List[FieldRule] = Field(min_length=1, max_length=100)
    duplicate_keys: List[str] = Field(default_factory=list, max_length=100)
    duplicate_policy: Literal["keep_all", "reject_later"] = "keep_all"
    null_markers: List[str] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def validate_fields(self) -> "ProcessConfig":
        targets = [field.target for field in self.fields]
        sources = [field.source for field in self.fields]
        if len(set(targets)) != len(targets):
            raise ValueError("Destination field names must be unique.")
        if len(set(sources)) != len(sources):
            raise ValueError("Each source column can only be mapped once.")
        if len(set(self.duplicate_keys)) != len(self.duplicate_keys):
            raise ValueError("Duplicate key fields must be unique.")
        if not set(self.duplicate_keys).issubset(targets):
            raise ValueError("Duplicate keys must be mapped destination fields.")
        if self.duplicate_policy == "reject_later" and not self.duplicate_keys:
            raise ValueError("Choose at least one duplicate key before rejecting duplicates.")
        if any(len(marker) > 100 for marker in self.null_markers):
            raise ValueError("Null markers must be at most 100 characters.")
        if any(re.search(r"[\ud800-\udfff]", marker) for marker in self.null_markers):
            raise ValueError("Null markers must contain valid Unicode text.")
        return self
