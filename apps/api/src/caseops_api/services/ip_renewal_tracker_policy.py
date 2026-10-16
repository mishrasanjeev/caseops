"""Validate persisted policy without echoing corrupt private configuration."""

from zoneinfo import ZoneInfo

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

INVALID_POLICY = "ip_renewal_reminder_policy_invalid"


class RenewalPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timezone: str = Field(min_length=1, max_length=64, strict=True)
    cadence_days: int = Field(default=1, ge=1, le=31, strict=True)
    delivery_time: str = Field(
        default="09:00", pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$", strict=True
    )
    policy_version: int = Field(default=0, ge=0, strict=True)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (KeyError, ValueError) as error:
            raise ValueError("Invalid timezone") from error
        return value


def validated_policy(configuration, *, company):
    try:
        raw = configuration.renewal_reminder_policy_json if configuration else {}
        if not isinstance(raw, dict):
            raise ValueError("Policy must be an object")
        return RenewalPolicy.model_validate(
            {
                **raw,
                "timezone": configuration.timezone if configuration else company.timezone,
                "policy_version": configuration.version if configuration else 0,
            }
        ).model_dump()
    except (ValidationError, ValueError) as error:
        raise HTTPException(
            status_code=503,
            detail={
                "code": INVALID_POLICY,
                "message": "Correct the invalid workspace renewal cadence, time and timezone.",
            },
        ) from error
