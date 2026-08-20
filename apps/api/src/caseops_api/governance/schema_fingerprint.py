"""Fingerprint the ORM schema this build actually carries.

Defined in the application rather than in the render script, and imported BY
the script, so there is exactly one implementation. Two implementations - one
stamping the artifact, one checking it - drift, and the failure mode is a check
that quietly always passes.

This is a build-integrity operand: it answers "was the projection rendered from
the same models this image contains?". It is deliberately not a claim about the
deployed DATABASE, which the image cannot see; that comparison lives in
``data_class_projection.review_coverage``.
"""

from __future__ import annotations

import hashlib


def orm_schema_fingerprint() -> str:
    """SHA-256 over every ORM table and its column names, in sorted order.

    Column names are included because a table can gain or lose a column without
    changing the table set, and a projection rendered before that change no
    longer describes the schema it claims to.
    """

    from caseops_api.db.models import Base

    digest = hashlib.sha256()
    for table_name in sorted(Base.metadata.tables):
        table = Base.metadata.tables[table_name]
        digest.update(table_name.encode("utf-8"))
        digest.update(b"\x00")
        for column_name in sorted(column.name for column in table.columns):
            digest.update(column_name.encode("utf-8"))
            digest.update(b"\x01")
        digest.update(b"\x02")
    return digest.hexdigest()
