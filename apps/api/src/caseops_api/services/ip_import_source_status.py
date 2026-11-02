"""Recognised source Status wording for imported IP portfolio rows.

A leaf with no service dependencies: the import writer and the portfolio
date reader both read this vocabulary, so neither depends on the other.
"""

from __future__ import annotations

import re
from typing import Any

# A source "Status" cell (B4-ADJ-11). Each recognised wording becomes a
# declared status; the application is created in the filing phase the
# interactive create command can set for it (draft, pre_filing or filed, the
# last with a confirmed application number). Later legal milestones such as
# registration are kept as the declared, unverified source status: only
# registry evidence or a lifecycle event may record them as legal state.
# Wording outside this table (registry exports vary) never blocks a row: it
# imports in the draft phase with its source wording kept and shown as
# unrecognised, exactly as every Status cell imported before this mapping.
SOURCE_STATUS_ALIASES = {
    "draft": "draft",
    "not filed": "draft",
    "unfiled": "draft",
    "pre filing": "pre_filing",
    "prefiling": "pre_filing",
    "to be filed": "pre_filing",
    "ready to file": "pre_filing",
    "ready for filing": "pre_filing",
    "filed": "filed",
    "application filed": "filed",
    "new application": "filed",
    "pending": "filed",
    "formalities chk pass": "formalities",
    "formalities check pass": "formalities",
    "formalities chk fail": "formalities",
    "formalities check fail": "formalities",
    "send to vienna codification": "formalities",
    "sent to vienna codification": "formalities",
    "marked for exam": "examination",
    "marked for examination": "examination",
    "under examination": "examination",
    "examination": "examination",
    "objected": "objected",
    "objection": "objected",
    "under objection": "objected",
    "examination report issued": "objected",
    "hearing": "hearing",
    "show cause hearing": "hearing",
    "ready for show cause hearing": "hearing",
    "accepted": "accepted",
    "accepted and advertised": "advertised",
    "accepted advertised": "advertised",
    "advertised": "advertised",
    "advertised before acceptance": "advertised",
    "advertised before accepted": "advertised",
    "published": "advertised",
    "opposed": "opposed",
    "under opposition": "opposed",
    "registered": "registered",
    "renewed": "registered",
    "refused": "refused",
    "rejected": "refused",
    "abandoned": "abandoned",
    "withdrawn": "withdrawn",
    "removed": "removed",
    "removed from register": "removed",
    "expired": "removed",
}


def source_status_key(value: Any) -> str | None:
    """Declared status for a source Status cell, or None when unrecognised."""

    text = " ".join(re.sub(r"[^0-9a-z]+", " ", str(value).casefold()).split())
    return SOURCE_STATUS_ALIASES.get(text)
