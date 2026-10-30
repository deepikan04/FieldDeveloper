"""Pydantic models for MCP tool arguments."""

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

from config import (
    CUSTOMER_ID_PATTERN,
    MIN_REASON_NON_WHITESPACE_CHARACTERS,
)


class ToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CustomerRecordArguments(ToolArguments):
    customer_id: str = Field(pattern=CUSTOMER_ID_PATTERN)

    @field_validator("customer_id")
    @classmethod
    def require_exact_customer_id(cls, value: str) -> str:
        if re.fullmatch(r"CUST-[A-Za-z0-9]{5}", value) is None:
            raise ValueError(
                "customer_id must match CUST- followed by 5 alphanumeric characters"
            )
        return value


class RefundArguments(CustomerRecordArguments):
    amount: float = Field(gt=0)
    reason: str

    @field_validator("reason")
    @classmethod
    def require_meaningful_reason(cls, value: str) -> str:
        non_whitespace_count = sum(not character.isspace() for character in value)
        if non_whitespace_count < MIN_REASON_NON_WHITESPACE_CHARACTERS:
            raise ValueError(
                "reason must contain at least "
                f"{MIN_REASON_NON_WHITESPACE_CHARACTERS} non-whitespace characters"
            )
        return value
