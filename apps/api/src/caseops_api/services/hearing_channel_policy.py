"""Preserve an explicit hearing notification opt-out, including old queued work."""

from collections.abc import Mapping


def hearing_channels(policy: Mapping | None) -> tuple[str, ...]:
    # Historical hearings without a channel choice retain their existing email
    # default. An explicit empty list is a choice, not an absent value.
    if policy is not None and not isinstance(policy, Mapping):
        raise ValueError("Invalid hearing notification policy.")
    value = (policy or {}).get("channels")
    if value is None:
        return ("email",)
    if (
        not isinstance(value, list)
        or len(value) > 4
        or any(
            not isinstance(channel, str) or channel not in {"email", "in_app", "sms", "whatsapp"}
            for channel in value
        )
        or len(set(value)) != len(value)
    ):
        raise ValueError("Invalid hearing notification channels.")
    return tuple(value)


def explicit_hearing_channel_allowed(policy: Mapping | None, channel: str) -> bool:
    # Legacy fallback behavior is separate from a new explicit channel choice.
    # This is only a channel fence; the existing recipient/source/ACL fences
    # still decide whether an intent may be processed.
    if policy is None:
        return True
    if not isinstance(policy, Mapping):
        return False
    if policy.get("channels") is None:
        return True
    try:
        return channel in hearing_channels(policy)
    except (TypeError, ValueError):
        return False
