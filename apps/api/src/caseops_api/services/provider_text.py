"""Plain-text presentation of provider-escaped email text.

Gmail returns a message ``snippet`` HTML-escaped (``&#39;``, ``&amp;``,
``&quot;``, ``&nbsp;``). CaseOps keeps the provider's text unchanged as
evidence, so mailbox imports, the communications created from them and the
calendar candidates extracted from those communications all hold escaped
text. Readers decode it exactly once, at presentation; the web renders the
result as text, never as markup, so a decoded ``<`` cannot become HTML.
"""

from __future__ import annotations

from html import unescape


def provider_plain_text(value: str | None) -> str | None:
    if value is None:
        return None
    return unescape(value).replace("\xa0", " ")
