"""Numeric store-version compatibility; no authentication or token authority."""

from __future__ import annotations

import re

_VERSION = re.compile(r"(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})", re.ASCII)


def version_parts(value: object) -> tuple[int, int, int]:
    if type(value) is not str or len(value) > 29:
        raise ValueError("Client version must contain three numeric components.")
    match = _VERSION.fullmatch(value)
    if match is None:
        raise ValueError("Client version must contain three numeric components.")
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch)


def validated_version(value: str) -> str:
    version_parts(value)
    return value
