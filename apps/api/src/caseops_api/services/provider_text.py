"""Plain-text presentation of provider-escaped email text.

Gmail returns a message ``snippet`` HTML-escaped (``&#39;``, ``&amp;``,
``&quot;``, ``&nbsp;``); Outlook's Graph preview and text a person pastes or
types are plain. CaseOps keeps the provider's text unchanged as evidence, so a
Gmail mailbox import, the Communication copied from it and the calendar
candidates extracted from that Communication all hold escaped text.

One predicate decides which stored text is escaped:
:func:`mailbox_text_is_escaped` for a mailbox import and
:func:`communication_text_is_escaped` for a Communication (and so for the
calendar candidates extracted from it). Every reader of such text decodes it
exactly once with :func:`provider_plain_text`; text from any other source is
never decoded, so a literal ``AT&amp;T`` someone typed stays as typed. The web
renders the result as text, never as markup, so a decoded ``<`` cannot become
HTML.
"""

from __future__ import annotations

from html import escape, unescape
from typing import Any

# Mailbox providers whose message text arrives HTML-escaped.
_ESCAPING_MAILBOX_PROVIDERS = frozenset({"gmail"})
# Communication sources whose body is a mailbox provider's snippet.
_MAILBOX_COPY_SOURCES = frozenset({"gmail_provider_import", "mailbox_metadata_review"})


def mailbox_text_is_escaped(provider: object) -> bool:
    """Whether a mailbox provider's snippet text is HTML-escaped."""

    return str(getattr(provider, "value", provider)) in _ESCAPING_MAILBOX_PROVIDERS


def communication_text_is_escaped(metadata: Any) -> bool:
    """Whether a Communication's body is an escaped mailbox-provider snippet."""

    return (
        isinstance(metadata, dict)
        and metadata.get("source") in _MAILBOX_COPY_SOURCES
        and mailbox_text_is_escaped(metadata.get("provider"))
    )


def provider_plain_text(value: str | None) -> str | None:
    """Decode provider-escaped text once. Callers gate it with a predicate."""

    if value is None:
        return None
    return unescape(value).replace("\xa0", " ")


def provider_escaped_text(value: str | None) -> str | None:
    """Store derived text in the escaped form its source uses.

    Calendar candidates are extracted from decoded text (so ``&amp;`` cannot
    end a venue at its ``;``) but stored escaped like their Gmail source, so
    old and new candidates are both decoded exactly once on read.
    """

    if value is None:
        return None
    return escape(value, quote=True)
