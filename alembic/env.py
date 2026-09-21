from logging.config import fileConfig
import os

from alembic import context
from sqlalchemy import create_engine, pool
from dotenv import load_dotenv

from app.database import Base
from app import models

load_dotenv()
config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

database_url = os.getenv('DATABASE_URL', '').strip()
if not database_url:
    raise RuntimeError(
        'DATABASE_URL no está configurada. En Render usa la Internal Database URL '
        'del servicio PostgreSQL.'
    )

if database_url.startswith('postgres://'):
    database_url = 'postgresql+psycopg2://' + database_url[len('postgres://'):]
elif database_url.startswith('postgresql://'):
    database_url = 'postgresql+psycopg2://' + database_url[len('postgresql://'):]
elif not database_url.startswith('postgresql+psycopg2://'):
    raise RuntimeError(
        'DATABASE_URL debe usar postgres://, postgresql:// o '
        'postgresql+psycopg2://.'
    )

config.set_main_option('sqlalchemy.url', database_url.replace('%', '%%'))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option('sqlalchemy.url'), target_metadata=target_metadata, literal_binds=True, dialect_opts={'paramstyle': 'named'})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(
        database_url,
        poolclass=pool.NullPool,
        connect_args={'connect_timeout': 10},
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
