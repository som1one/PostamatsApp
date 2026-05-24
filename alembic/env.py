import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool
from sqlalchemy import inspect, text

from alembic import context
from alembic.script import ScriptDirectory
from dotenv import load_dotenv

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

from backend.core.database import Base
from backend.core.settings import settings
from backend.models import admin_account  # noqa: F401
from backend.models import admin_audit_event  # noqa: F401
from backend.models import admin_auth_session  # noqa: F401
from backend.models import admin_user  # noqa: F401
from backend.models import auth_session  # noqa: F401
from backend.models import auth_verification_session  # noqa: F401
from backend.models import city  # noqa: F401
from backend.models import condition_report  # noqa: F401
from backend.models import condition_report_photo  # noqa: F401
from backend.models import esi_event_log  # noqa: F401
from backend.models import inventory_movement  # noqa: F401
from backend.models import inventory_unit  # noqa: F401
from backend.models import locker_cell  # noqa: F401
from backend.models import locker_location  # noqa: F401
from backend.models import media_file  # noqa: F401
from backend.models import payment  # noqa: F401
from backend.models import payment_event  # noqa: F401
from backend.models import price_plan  # noqa: F401
from backend.models import product  # noqa: F401
from backend.models import product_category  # noqa: F401
from backend.models import product_image  # noqa: F401
from backend.models import rental  # noqa: F401
from backend.models import rental_event  # noqa: F401
from backend.models import return_request  # noqa: F401
from backend.models import reservation  # noqa: F401
from backend.models import user  # noqa: F401
from backend.models import verification_request  # noqa: F401

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env.local"))
load_dotenv(os.path.join(BASE_DIR, "backend", ".env"))
config.set_main_option("sqlalchemy.url", settings.DB_URL)
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        inspector = inspect(connection)
        existing_tables = {name for name in inspector.get_table_names() if name != "alembic_version"}

        if not existing_tables:
            # Fresh database bootstrap: create the current schema directly from metadata
            # and stamp the version table so later upgrades remain consistent.
            Base.metadata.create_all(connection)

            version_table = "alembic_version"
            connection.execute(text(f'CREATE TABLE IF NOT EXISTS "{version_table}" (version_num VARCHAR(32) NOT NULL)'))
            connection.execute(text(f'DELETE FROM "{version_table}"'))

            script = ScriptDirectory.from_config(config)
            current_head = script.get_current_head()
            if current_head is not None:
                connection.execute(
                    text(f'INSERT INTO "{version_table}" (version_num) VALUES (:version_num)'),
                    {"version_num": current_head},
                )
            connection.commit()
            return

        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
