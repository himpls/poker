from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from poker_bot.db import Database, metadata


def test_initial_migration_matches_models_and_is_repeatable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'migrated.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    db = Database(url)
    inspector = inspect(db.engine)
    assert set(metadata.tables).issubset(inspector.get_table_names())
    for table in metadata.tables.values():
        assert {c.name for c in table.columns} == {c["name"] for c in inspector.get_columns(table.name)}
    db.engine.dispose()
