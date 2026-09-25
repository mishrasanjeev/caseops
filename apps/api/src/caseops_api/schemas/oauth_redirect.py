"""Rules every OAuth redirect URI must satisfy before an identity provider calls it.

Google and Microsoft both match a registered redirect URI as an exact string, so
an address that is malformed, insecure, or on the wrong path is accepted by a
free-text form and only fails after a user has already been sent through
consent. Each connector keeps its own expected path; the structural rules are
the same for every provider and live here once.
"""

from __future__ import annotations

from urllib.parse import urlsplit

LOCAL_OAUTH_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
# urlsplit() tolerates whitespace and control characters inside an authority;
# identity providers do not, so reject them before they reach a stored row.
_FORBIDDEN_URI_CHARACTERS = tuple(chr(code) for code in range(33)) + (chr(127),)


def oauth_redirect_error(
    value: str,
    *,
    label: str,
    provider: str,
    expected_path: str | None,
) -> str | None:
    """Return an actionable message, or ``None`` when ``value`` is usable.

    ``expected_path`` pins the one callback CaseOps serves for a connector. Pass
    ``None`` only for a connector that has no callback route yet, so the
    structural rules still apply without inventing a path.
    """

    if expected_path is None:
        advice = (
            f"The {label} redirect URI must be the full https address "
            f"{provider} sends the user back to"
        )
    else:
        advice = (
            f"The {label} redirect URI must be the address {provider} sends the user back to, "
            f"ending in {expected_path}"
        )
    if any(character in value for character in _FORBIDDEN_URI_CHARACTERS):
        return f"{advice}. Remove spaces, tabs and line breaks from the address."
    try:
        # urlsplit() itself raises on some malformed authorities, such as an
        # unclosed IPv6 bracket. The read path calls this for rows saved before
        # validation existed, so a parse failure must report, not crash.
        parts = urlsplit(value)
        host = parts.hostname or ""
    except ValueError:
        return f"{advice}. The address is not a valid URL."
    if parts.scheme not in {"http", "https"} or not host:
        return f"{advice}. Enter a full https address including the host."
    try:
        # Reading .port is the only way to learn that the authority carries an
        # unusable port; urlsplit() itself accepts one. Out-of-range values
        # raise here, and port 0 parses but is not an address anyone can call.
        port = parts.port
    except ValueError:
        return f"{advice}. The port after the host is not a usable number."
    if port == 0:
        return f"{advice}. Port 0 is not an address {provider} can call back."
    if parts.scheme != "https" and host not in LOCAL_OAUTH_HOSTS:
        return f"{advice}. {provider} accepts https only, except on localhost."
    if parts.username or parts.password:
        return f"{advice}. Remove the username or password from the address."
    if parts.query or parts.fragment:
        return f"{advice}. Remove the query string or fragment."
    if expected_path is not None and parts.path != expected_path:
        return (
            f"{advice}. It currently ends in {parts.path or '/'}, which {provider} will "
            "reject as a redirect_uri mismatch. Check for a trailing slash, a typo, or "
            "another connector's address pasted into this field."
        )
    return None
