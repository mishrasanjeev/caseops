"""Shared text redaction for anything that leaves the process.

DATA-GOV-15 requires that application, provider and audit logs, traces and
metrics minimise message bodies, document text, prompts, mark/client names,
email, phone, tokens and payment data.

This module exists because the redactor previously lived in
``services/notification_delivery.py`` and was applied only to text about to be
PERSISTED. The same exception was then written to the log unredacted - see the
``logger.exception`` immediately above the redacted ``job.error`` assignment in
``services/audit_exports.py``. One destination was sanitised and the other was
not, from the same object.

``core`` is the right home: ``services`` may import from ``core``, never the
reverse, so the log formatter can use this without a cycle.
"""
from __future__ import annotations

import re

# Any scheme, not just http(s). A driver failure quotes its DSN --
# postgresql://user:password@host:5432/db -- and matching only http(s) let
# connection strings through with the password intact. The scheme repetition is
# bounded: unbounded, CodeQL flags py/polynomial-redos.
_URL_RE = re.compile(r"[a-z][a-z0-9+.\-]{0,15}://[^\s]+", re.IGNORECASE)
_UUID_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\d\s().-]{8,}\d)(?!\d)")
_LONG_TOKEN_RE = re.compile(r"\b[A-Za-z0-9_.:-]{24,}\b")

MAX_REDACTED_ERROR_LENGTH = 200
MAX_REDACTED_LOG_LENGTH = 2_000
MAX_REDACTION_INPUT_LENGTH = 8_000

_SECRET_KEYS = {
    "apikey",
    "authorization",
    "authheader",
    "bearer",
    "clientsecret",
    "privatekey",
    # Present in the original set; dropped once during this refactor, which
    # silently unredacted "webhook-signature: signed-secret". Keep it.
    "webhooksignature",
    # Password keys were absent entirely, so "password=..." was never redacted;
    # the abbreviations are what people actually type in DSNs and debug lines.
    "password",
    "passwd",
    "pw",
    "pwd",
    "pass",
    "apisecret",
    "clientkey",
    "privatetoken",
    "secret",
    "token",
    "accesstoken",
    "refreshtoken",
    "sessionkey",
    "signature",
    "cardnumber",
    "cvv",
}
_TOKEN_EDGE_PUNCTUATION = "\"'<>[]{}(),;"


def _normalized_secret_key(value: str) -> str:
    return "".join(character for character in value.lower() if character.isalnum())


def _redact_secret_tokens(text: str) -> str:
    """Redact key/value secrets in linear time without regex backtracking."""
    tokens = text.split()
    redacted: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        candidate = token.strip(_TOKEN_EDGE_PUNCTUATION)
        separator_index = min(
            (position for position in (candidate.find("="), candidate.find(":")) if position >= 0),
            default=-1,
        )
        key_text = candidate[:separator_index] if separator_index >= 0 else candidate
        key = _normalized_secret_key(key_text)
        consumed_key_tokens = 1
        if key not in _SECRET_KEYS and index + 1 < len(tokens):
            paired_key = _normalized_secret_key(f"{candidate}{tokens[index + 1]}")
            if paired_key in _SECRET_KEYS:
                key = paired_key
                consumed_key_tokens = 2
        if key not in _SECRET_KEYS:
            redacted.append(token)
            index += 1
            continue

        redacted.append(f"{key_text or 'secret'}=[redacted]")
        index += consumed_key_tokens
        inline_value = separator_index >= 0 and separator_index < len(candidate) - 1
        inline_secret = (
            candidate[separator_index + 1 :].strip(_TOKEN_EDGE_PUNCTUATION)
            if inline_value
            else ""
        )
        if key == "authorization" and inline_secret.casefold() == "bearer":
            if index < len(tokens):
                index += 1
            continue
        if inline_value:
            continue
        if index < len(tokens) and tokens[index] in {"=", ":"}:
            index += 1
        if (
            key == "authorization"
            and index < len(tokens)
            and tokens[index].strip(_TOKEN_EDGE_PUNCTUATION).casefold() == "bearer"
        ):
            index += 1
        if index < len(tokens):
            index += 1
    return " ".join(redacted)


def _redact_email_tokens(text: str) -> str:
    """Redact email-like whitespace-delimited tokens in linear time."""
    redacted: list[str] = []
    for token in text.split():
        candidate = token.strip(f"{_TOKEN_EDGE_PUNCTUATION}.:")
        local, separator, domain = candidate.partition("@")
        suffix = domain.rpartition(".")[2]
        if separator and local and domain and suffix.isalpha() and len(suffix) >= 2:
            redacted.append(token.replace(candidate, "[email-redacted]", 1))
        else:
            redacted.append(token)
    return " ".join(redacted)


def redact_text(
    value: object,
    *,
    max_length: int = MAX_REDACTED_LOG_LENGTH,
    redact_identifiers: bool = True,
    redact_long_tokens: bool = True,
    redact_phone_numbers: bool = True,
) -> str:
    """Redact secrets and personal data from arbitrary text.

    ``max_length`` differs by destination on purpose. A persisted provider error
    is a short operator hint, so it is clipped hard; a log line clipped to the
    same length would destroy the diagnostic value that justifies logging.

    ``redact_identifiers`` controls UUID masking. Persisted provider errors mask
    them: an operator hint has no business carrying internal record ids. Logs do
    NOT, because tenant/request/matter ids are how an operator finds the incident
    at all, and DATA-GOV-15 enumerates message bodies, document text, prompts,
    names, email/phone, tokens and payment data - not internal identifiers.
    Masking them would degrade incident response while protecting nothing.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    text = " ".join(text[:MAX_REDACTION_INPUT_LENGTH].split())
    text = _redact_secret_tokens(text)
    text = _URL_RE.sub("[url-redacted]", text)
    text = _redact_email_tokens(text)
    if redact_identifiers:
        text = _UUID_RE.sub("[id-redacted]", text)
        text = _PHONE_RE.sub("[phone-redacted]", text)
        if redact_long_tokens:
            text = _LONG_TOKEN_RE.sub("[token-redacted]", text)
    else:
        # Preserving an identifier means protecting it from the LATER rules too.
        # A bare `if` around the UUID rule is not enough: the phone pattern
        # matches a UUID's digit-and-dash tail, so "7f3a1b2c-1111-...-4444" came
        # out as "7f3a1b2c-[phone-redacted]" - the correlation id destroyed and
        # nothing protected. Park them, redact, put them back.
        shielded: list[str] = []

        def _park(match: re.Match[str]) -> str:
            shielded.append(match.group(0))
            return f"id{len(shielded) - 1}"

        text = _UUID_RE.sub(_park, text)
        if redact_phone_numbers:
            text = _PHONE_RE.sub("[phone-redacted]", text)
        if redact_long_tokens:
            text = _LONG_TOKEN_RE.sub("[token-redacted]", text)
        for position, original in enumerate(shielded):
            text = text.replace(f"id{position}", original)
    if len(text) > max_length:
        return text[: max_length - 3].rstrip() + "..."
    return text


def redact_log_text(value: object, *, max_length: int = MAX_REDACTED_LOG_LENGTH) -> str:
    """Redact text bound for a log sink, preserving correlation identifiers."""
    return redact_text(value, max_length=max_length, redact_identifiers=False)


def redact_provider_error(value: object) -> str:
    """Redact a provider/driver exception for persistence.

    Behaviour is unchanged from the original in ``notification_delivery``: an
    empty value still renders as ``provider_error`` so a stored row never reads
    as "no error occurred".
    """
    if not str(value or "").strip():
        return "provider_error"
    return redact_text(value, max_length=MAX_REDACTED_ERROR_LENGTH)


# Content-bearing field names. Pattern matching cannot recognise privileged
# prose - "PRIVILEGED opinion body" contains no token any regex can key on - so
# DATA-GOV-15's document-text/prompt/name categories are enforced by FIELD NAME
# instead. A field whose name says it carries content is dropped to a length
# summary rather than logged, because the safe amount of a client's document to
# put in Cloud Logging is none of it.
# Content-bearing field names. Pattern matching cannot recognise privileged
# prose - "PRIVILEGED opinion body" contains no token any regex can key on - so
# DATA-GOV-15's document-text/prompt/name categories and DATA-GOV-11's
# tombstone minimisation are enforced by FIELD NAME instead.
#
# Matched as whole underscore-separated TOKENS, not substrings. Substring
# matching withheld `recommendation_context` because "context" ends in "text",
# which would have quietly gutted audit evidence for every key containing
# context, pretext or subtext.
_CONTENT_TOKENS = frozenset(
    {
        "body",
        "chunk",
        "completion",
        "content",
        "excerpt",
        "extract",
        "opinion",
        "prompt",
        "prompts",
        "raw",
        "rationale",
        "snippet",
        "summary",
        "transcript",
        "text",
    }
)
# Phrases whose risk comes from the pair rather than either token alone. A bare
# `name` is an ordinary audit field - a team name, a provider name - and
# withholding it would cost evidence for nothing.
_CONTENT_PHRASES = (
    "client_name",
    "mark_name",
    "party_name",
)


# A key ending in one of these names identifiers, not content. `chunk_ids` holds
# UUIDs that let an auditor find the evidence; withholding them because the key
# also contains "chunk" removes the pointer while protecting nothing, which is
# the opposite of a tombstone.
# DATA-GOV-11 forbids "destinations". In structured metadata a destination is
# identified by its KEY. Pattern-guessing at the value ate
# `GOOGLE-SEARCH-2026-08-17-001`, because the phone rule matches any digit run
# with separators - which is also what a dated provider reference looks like.
_DESTINATION_KEYS = frozenset(
    {
        "addressee",
        "bcc",
        "cc",
        "destination",
        "destinations",
        "email",
        "emailaddress",
        "mobile",
        "msisdn",
        "phone",
        "phonenumber",
        "recipient",
        "recipients",
        "sendto",
        "to",
    }
)
_IDENTIFIER_SUFFIXES = ("id", "ids", "hash", "hashes", "sha256", "count", "counts", "ref", "refs")


def is_content_field(name: str) -> bool:
    """Whether a field name suggests it carries user or document content."""
    lowered = "".join(
        character for character in name.lower() if character.isalnum() or character == "_"
    )
    tokens = lowered.split("_")
    if tokens and tokens[-1] in _IDENTIFIER_SUFFIXES:
        return False
    if any(phrase in lowered for phrase in _CONTENT_PHRASES):
        return True
    return bool(set(tokens) & _CONTENT_TOKENS)


def summarize_content(value: object) -> str:
    """Replace content with a shape description that is still useful to debug."""
    text = str(value or "")
    return f"[content-withheld chars={len(text)}]"


def sanitize_audit_metadata(value: object, *, key: str = "") -> object:
    """Minimise audit metadata to tombstone-safe values (DATA-GOV-11).

    An audit row is immutable legal evidence that outlives the content it
    describes, so it is the one place where a leak cannot later be cleaned up.
    The requirement is explicit: retained evidence "cannot contain raw
    privileged documents, message bodies, prompts, destinations or secrets".

    The write path applied ``json.dumps(metadata)`` with no constraint at all,
    so any of the 400-odd callers could put a draft, a prompt or a recipient
    address into a permanent row - and unlike a log line, it cannot be rotated
    away afterwards.

    Three rules, matched to STRUCTURED data rather than free text:

    - a key naming a secret has its value replaced outright
    - a key naming content is withheld as a length summary, because no pattern
      recognises a privileged paragraph
    - other strings lose URLs, email and phone - the "destinations" half

    The long-opaque-token rule is deliberately NOT applied. It is a blunt
    secret-catcher for free-text error strings, where a 24-character run is
    probably a key. In structured metadata those runs are identifiers and
    content hashes - ``supreme_court_latest_orders``, a SHA-256 digest - which
    are exactly the tombstone fields this requirement wants KEPT. Redacting a
    content hash destroys the tombstone: it identifies evidence without
    revealing it, which is the entire point. Secrets are caught by key name
    instead, which is precise where the value's shape is not.
    """
    normalized_key = _normalized_secret_key(key) if key else ""
    if normalized_key and normalized_key in _SECRET_KEYS:
        return "[redacted]"
    if normalized_key and normalized_key in _DESTINATION_KEYS:
        return "[destination-redacted]"
    if key and is_content_field(key) and not isinstance(value, (dict, list, tuple)):
        return summarize_content(value)
    if isinstance(value, str):
        return redact_text(
            value,
            max_length=MAX_REDACTED_LOG_LENGTH,
            redact_identifiers=False,
            redact_long_tokens=False,
            redact_phone_numbers=False,
        )
    if isinstance(value, dict):
        return {
            item_key: sanitize_audit_metadata(item, key=str(item_key))
            for item_key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_audit_metadata(item, key=key) for item in value]
    return value
