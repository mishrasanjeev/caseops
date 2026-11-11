"""Bounded immutable contract source bytes; validation and serving share one buffer."""

from __future__ import annotations

import errno
import hashlib
import os
import stat
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile
from zlib import error as ZlibError

from fastapi import HTTPException
from sqlalchemy import select

from caseops_api.db.models import Contract, ContractAttachment
from caseops_api.db.session import CaseOpsSession
from caseops_api.services.contracts import lock_contract_actor
from caseops_api.services.document_storage import resolve_storage_path
from caseops_api.services.session_context import SessionContext

MAX_SOURCE_BYTES = 32 * 1024 * 1024
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@dataclass(frozen=True)
class ContractSourceBytes:
    filename: str
    content_type: str
    sha256_hex: str
    data: bytes


def _source(session, context, contract_id, attachment_id):
    row = session.execute(
        select(
            ContractAttachment.original_filename,
            ContractAttachment.content_type,
            ContractAttachment.size_bytes,
            ContractAttachment.sha256_hex,
            ContractAttachment.storage_key,
        )
        .join(Contract, Contract.id == ContractAttachment.contract_id)
        .where(
            Contract.id == contract_id,
            Contract.company_id == context.company.id,
            ContractAttachment.id == attachment_id,
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Contract attachment not found.")
    return tuple(row)


def _changed():
    return HTTPException(
        status_code=409, detail="The attachment source changed. Reload the contract."
    )


def _same_file(opened, named):
    # Windows 3.13 exposes descriptor ChangeTime but pathname CreationTime as ctime.
    time_key = "st_birthtime_ns" if os.name == "nt" else "st_ctime_ns"
    return (
        stat.S_ISREG(named.st_mode)
        and named.st_nlink == 1
        and not getattr(named, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
        and opened.st_ino == named.st_ino
        and (opened.st_dev == named.st_dev or os.name == "nt" and named.st_dev == 0)
        and all(
            getattr(opened, key) == getattr(named, key)
            for key in (
                "st_size",
                "st_mtime_ns",
                time_key,
                "st_mode",
            )
        )
    )


def _read_source(path: Path, expected_size: int, expected_hash: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="Contract attachment file is unavailable."
        ) from exc
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise _changed() from exc
        raise
    with os.fdopen(descriptor, "rb") as source:
        opened = os.fstat(source.fileno())
        if not stat.S_ISREG(opened.st_mode) or not _same_file(opened, _named_source(path)):
            raise _changed()
        if opened.st_size != expected_size:
            raise _changed()
        data = source.read(expected_size + 1)
        after = os.fstat(source.fileno())
        if (
            not _same_file(opened, after)
            or opened.st_ctime_ns != after.st_ctime_ns
            or not _same_file(opened, _named_source(path))
        ):
            raise _changed()
    if len(data) != expected_size or hashlib.sha256(data).hexdigest() != expected_hash:
        raise _changed()
    return data


def _named_source(path: Path):
    try:
        return path.lstat()
    except FileNotFoundError as exc:
        raise _changed() from exc


def get_contract_source_bytes(
    session: CaseOpsSession,
    *,
    context: SessionContext,
    contract_id: str,
    attachment_id: str,
    preview: bool = False,
) -> ContractSourceBytes:
    session.require_read_only_transaction()
    lock_contract_actor(session, context=context)
    snapshot = _source(session, context, contract_id, attachment_id)
    filename, content_type, size, digest, storage_key = snapshot
    if not 0 < size <= MAX_SOURCE_BYTES:
        raise HTTPException(
            status_code=413, detail="This document exceeds the private viewer limit."
        )
    mime = (content_type or "application/octet-stream").lower().strip()
    lower_name = filename.lower()
    if preview and not (
        lower_name.endswith(".pdf")
        and mime == "application/pdf"
        or lower_name.endswith(".docx")
        and mime == DOCX_MIME
    ):
        raise HTTPException(
            status_code=415, detail="Only source-verified PDF and DOCX previews are supported."
        )
    # GCS cache acquisition and archive work must not retain actor/database locks.
    session.require_read_only_transaction()
    session.rollback()
    data = _read_source(resolve_storage_path(storage_key), size, digest)
    if preview:
        if mime == "application/pdf":
            if not data.startswith(b"%PDF-"):
                raise HTTPException(status_code=422, detail="This PDF source is invalid.")
        else:
            from caseops_api.services.matters import _validate_docx_preview_archive

            try:
                _validate_docx_preview_archive(BytesIO(data))
            except (BadZipFile, ParseError, ValueError, ZlibError, NotImplementedError) as exc:
                raise HTTPException(
                    status_code=422,
                    detail="This DOCX could not be rendered safely; download the original instead.",
                ) from exc
    lock_contract_actor(session, context=context)
    if _source(session, context, contract_id, attachment_id) != snapshot:
        raise _changed()
    session.require_read_only_transaction()
    session.rollback()
    return ContractSourceBytes(filename, mime, digest, data)
