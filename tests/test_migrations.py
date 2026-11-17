from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from poker_bot.cash import Cash
from poker_bot.clubs import Clubs
from poker_bot.db import Database, metadata
from poker_bot.demo import seed


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


def test_tournament_upgrade_preserves_cash_data(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'upgrade.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config("alembic.ini")
    command.upgrade(config, "0001")
    db = Database(url)
    seed(db)
    club = Clubs(db).list(1)[0]["id"]
    before = Cash(db).stats(1, club)
    db.engine.dispose()
    command.upgrade(config, "head")
    upgraded = Database(url)
    assert Cash(upgraded).stats(1, club) == before
    assert "tournaments" in inspect(upgraded.engine).get_table_names()
    upgraded.engine.dispose()
