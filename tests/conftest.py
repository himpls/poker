import pytest

from poker_bot.db import Database


@pytest.fixture
def db(tmp_path):
    database = Database(f"sqlite:///{tmp_path / 'test.db'}")
    database.create_for_tests()
    yield database
    database.engine.dispose()
