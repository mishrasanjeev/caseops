from __future__ import annotations

import re
import string

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 128

_DIGIT = re.compile(r"\d")
_UPPER = re.compile(r"[A-Z]")
_LOWER = re.compile(r"[a-z]")
_SPECIAL_CHARS = set(string.punctuation)


class WeakPasswordError(ValueError):
    """Raised when a password does not meet the CaseOps policy."""


def enforce_password_policy(password: str) -> None:
    if not isinstance(password, str):
        raise WeakPasswordError("Password must be a string.")

    length = len(password)
    if length < MIN_PASSWORD_LENGTH:
        raise WeakPasswordError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters.",
        )
    if length > MAX_PASSWORD_LENGTH:
        raise WeakPasswordError(
            f"Password must be at most {MAX_PASSWORD_LENGTH} characters.",
        )
    if not _UPPER.search(password):
        raise WeakPasswordError("Password must include an uppercase letter.")
    if not _LOWER.search(password):
        raise WeakPasswordError("Password must include a lowercase letter.")
    if not _DIGIT.search(password):
        raise WeakPasswordError("Password must include a digit.")
    if not any(ch in _SPECIAL_CHARS for ch in password):
        raise WeakPasswordError("Password must include a symbol.")
    if re.search(r"\s", password):
        raise WeakPasswordError("Password must not contain whitespace.")
