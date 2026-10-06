from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.database.base import Base
from app.models import InstagramAccount


@pytest.fixture
def settings():
    return Settings(
        _env_file=None,
        instagram_access_token="fake-token-never-real",
        mysql_host="test.invalid",
        mysql_user="test",
        mysql_password="fake-db-password",
        admin_api_key="fake-admin-key",
        audience_collection_enabled=False,
        collect_on_startup=False,
        scheduler_enabled=False,
    )


@pytest.fixture
def engine():
    instance = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )

    @event.listens_for(instance, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(instance)
    yield instance
    instance.dispose()


@pytest.fixture
def sessions(engine):
    return sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def session(sessions):
    with sessions() as instance:
        yield instance


@pytest.fixture
def account(session):
    instance = InstagramAccount(instagram_user_id="123", username="test-account")
    session.add(instance)
    session.commit()
    return instance


@pytest.fixture
def now():
    return datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
