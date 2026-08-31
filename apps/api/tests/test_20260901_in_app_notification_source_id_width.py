from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, text

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    Company,
    CompanyMembership,
    InAppNotification,
    NotificationDeliveryIntent,
    User,
)
from caseops_api.db.session import clear_engine_cache, get_session_factory
from caseops_api.services.notification_delivery import (
    enqueue_notification_delivery_intent,
    process_notification_delivery_intent,
)
from caseops_api.services.session_context import SessionContext
from tests.test_auth_company import bootstrap_company

MIGRATION_HEAD = "20260901_0001"
MIGRATION_PARENT = "20260831_0002"


def _config() -> Config:
    project_root = Path(__file__).resolve().parents[1]
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    return config


def _source_id_length(database_url: str) -> int | None:
    engine = create_engine(database_url)
    try:
        return next(
            column["type"].length
            for column in inspect(engine).get_columns("in_app_notifications")
            if column["name"] == "source_id"
        )
    finally:
        engine.dispose()


def test_source_id_width_upgrade_and_guarded_downgrade(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'source-width.db').as_posix()}"
    monkeypatch.setenv("CASEOPS_ENV", "e2e")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    clear_engine_cache()
    config = _config()

    command.upgrade(config, MIGRATION_PARENT)
    assert _source_id_length(database_url) == 36

    command.upgrade(config, MIGRATION_HEAD)
    assert _source_id_length(database_url) == 120

    long_source_id = "reminder:" + "x" * 111
    assert len(long_source_id) == 120
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO in_app_notifications (
                        id,
                        company_id,
                        recipient_membership_id,
                        event_type,
                        source_type,
                        source_id,
                        title,
                        status,
                        created_at
                    ) VALUES (
                        :id,
                        :company_id,
                        :recipient_membership_id,
                        :event_type,
                        :source_type,
                        :source_id,
                        :title,
                        :status,
                        CURRENT_TIMESTAMP
                    )
                    """
                ),
                {
                    "id": "notification-source-width-test",
                    "company_id": "company-source-width-test",
                    "recipient_membership_id": "member-source-width-test",
                    "event_type": "hearing_reminder",
                    "source_type": "notification_delivery_intent",
                    "source_id": long_source_id,
                    "title": "Source width regression",
                    "status": "unread",
                },
            )
    finally:
        engine.dispose()

    with pytest.raises(RuntimeError, match="value longer than 36 characters"):
        command.downgrade(config, MIGRATION_PARENT)
    assert _source_id_length(database_url) == 120

    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM in_app_notifications"))
    finally:
        engine.dispose()

    command.downgrade(config, MIGRATION_PARENT)
    assert _source_id_length(database_url) == 36


def test_in_app_delivery_persists_120_character_intent_source_id(
    client: TestClient,
) -> None:
    bootstrap_company(client)
    source_id = "reminder:" + "x" * 111
    assert len(source_id) == 120

    with get_session_factory()() as session:
        membership = session.scalar(select(CompanyMembership))
        assert membership is not None
        company = session.get(Company, membership.company_id)
        user = session.get(User, membership.user_id)
        assert company is not None and user is not None
        context = SessionContext(company=company, membership=membership, user=user)

        intent = enqueue_notification_delivery_intent(
            session,
            context=context,
            recipient_membership=membership,
            channel="in_app",
            event_type="hearing_reminder",
            source_type="notification_delivery_intent",
            source_id=source_id,
            title="Upcoming hearing",
        )
        assert intent is not None
        result = process_notification_delivery_intent(
            session,
            intent_id=intent.id,
            context=context,
        )
        session.commit()

        assert result.delivered is True
        persisted_intent = session.get(NotificationDeliveryIntent, intent.id)
        assert persisted_intent is not None
        notification = session.get(
            InAppNotification,
            persisted_intent.in_app_notification_id,
        )
        assert notification is not None
        assert notification.source_id == source_id


def test_model_source_id_width_matches_delivery_intent() -> None:
    assert InAppNotification.__table__.c.source_id.type.length == 120
    assert NotificationDeliveryIntent.__table__.c.source_id.type.length == 120
