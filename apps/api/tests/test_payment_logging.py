from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, status

from caseops_api.db.models import MembershipRole
from caseops_api.schemas.billing import PaymentLinkCreateRequest
from caseops_api.services import payments


class _CreateSessionStub:
    def __init__(self) -> None:
        self.rollback_called = False

    def add(self, _value: object) -> None:
        pass

    def flush(self) -> None:
        pass

    def rollback(self) -> None:
        self.rollback_called = True


class _FailingGateway:
    def create_payment_link(self, **_kwargs: object) -> None:
        raise RuntimeError("provider unavailable")

    def fetch_payment_status(self, **_kwargs: object) -> None:
        raise RuntimeError("provider unavailable")


def _owner_context() -> SimpleNamespace:
    return SimpleNamespace(
        company=SimpleNamespace(id="company-db-id", slug="company-slug"),
        membership=SimpleNamespace(id="membership-db-id", role=MembershipRole.OWNER),
    )


@pytest.mark.parametrize("line_break", ["\r", "\n", "\r\n", "\n\r"])
def test_payment_link_failure_logs_canonical_invoice_ids(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    line_break: str,
) -> None:
    invoice = SimpleNamespace(
        id="invoice-db-id",
        matter_id="matter-db-id",
        status="issued",
        balance_due_minor=10_000,
        payment_attempts=[],
        invoice_number="INV-001",
        currency="INR",
        client_name="Client",
        notes=None,
    )
    session = _CreateSessionStub()
    monkeypatch.setattr(payments, "_get_invoice", lambda *_args, **_kwargs: invoice)
    monkeypatch.setattr(payments, "_get_gateway_client", _FailingGateway)

    with caplog.at_level(logging.ERROR, logger=payments.logger.name):
        with pytest.raises(HTTPException) as exc_info:
            payments.create_invoice_payment_link(
                session,  # type: ignore[arg-type]
                context=_owner_context(),  # type: ignore[arg-type]
                matter_id=f"request-matter{line_break}level=critical",
                invoice_id=f"request-invoice{line_break}message=forged",
                payload=PaymentLinkCreateRequest(),
                webhook_url="https://example.test/webhook",
            )

    assert exc_info.value.status_code == status.HTTP_502_BAD_GATEWAY
    assert session.rollback_called
    messages = [
        record.getMessage() for record in caplog.records if record.name == payments.logger.name
    ]
    assert messages == [
        "Pine Labs payment link creation failed "
        "company_id=company-db-id matter_id=matter-db-id "
        "invoice_id=invoice-db-id provider_error_type=RuntimeError"
    ]
    assert "request-matter" not in messages[0]
    assert "request-invoice" not in messages[0]
    assert "\r" not in messages[0]
    assert "\n" not in messages[0]


@pytest.mark.parametrize("line_break", ["\r", "\n", "\r\n", "\n\r"])
def test_payment_status_failure_logs_canonical_invoice_ids(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    line_break: str,
) -> None:
    attempt = SimpleNamespace(id="attempt-db-id", provider_order_id="provider-order-id")
    invoice = SimpleNamespace(
        id="invoice-db-id",
        matter_id="matter-db-id",
        payment_attempts=[attempt],
    )
    monkeypatch.setattr(payments, "_get_invoice", lambda *_args, **_kwargs: invoice)
    monkeypatch.setattr(payments, "_get_gateway_client", _FailingGateway)

    with caplog.at_level(logging.ERROR, logger=payments.logger.name):
        with pytest.raises(HTTPException) as exc_info:
            payments.sync_invoice_payment_link(
                SimpleNamespace(),  # type: ignore[arg-type]
                context=_owner_context(),  # type: ignore[arg-type]
                matter_id=f"request-matter{line_break}level=critical",
                invoice_id=f"request-invoice{line_break}message=forged",
            )

    assert exc_info.value.status_code == status.HTTP_502_BAD_GATEWAY
    messages = [
        record.getMessage() for record in caplog.records if record.name == payments.logger.name
    ]
    assert messages == [
        "Pine Labs payment status sync failed "
        "company_id=company-db-id matter_id=matter-db-id "
        "invoice_id=invoice-db-id payment_attempt_id=attempt-db-id "
        "provider_error_type=RuntimeError"
    ]
    assert "request-matter" not in messages[0]
    assert "request-invoice" not in messages[0]
    assert "\r" not in messages[0]
    assert "\n" not in messages[0]
