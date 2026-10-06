"""Database credentials come from the environment, never alembic.ini."""

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from alembic import context
from app import models  # noqa: F401
from app.config import get_settings
from app.database.base import Base

target_metadata = Base.metadata


def run_migrations_offline():
    # Offline SQL generation requires no Instagram token or live database.
    context.configure(
        dialect_name="mysql",
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    # A supplied connection is useful for deterministic migration tests.
    connection = context.config.attributes.get("connection")
    if connection is not None:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
        return
    try:
        engine = create_engine(
            get_settings().database_url, poolclass=NullPool, hide_parameters=True
        )
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
            )
            with context.begin_transaction():
                context.run_migrations()
    except Exception:
        raise RuntimeError(
            "Migration failed; verify database and environment configuration"
        ) from None


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
