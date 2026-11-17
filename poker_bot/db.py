from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.pool import NullPool

metadata = MetaData()
clubs = Table(
    "clubs",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(80), nullable=False),
    Column("currency", String(3), nullable=False),
    Column("timezone", String(80), nullable=False),
    Column("invite", String(64), unique=True, nullable=False),
    Column("group_id", BigInteger, unique=True),
    Column("group_message", BigInteger),
    Column("season_start", String(10), nullable=False),
)
members = Table(
    "members",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("club_id", ForeignKey("clubs.id"), nullable=False),
    Column("tg_id", BigInteger),
    Column("name", String(80), nullable=False),
    Column("role", String(16), nullable=False, server_default="member"),
    UniqueConstraint("club_id", "tg_id"),
    CheckConstraint("role IN ('owner','organizer','member')"),
)
games = Table(
    "games",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("club_id", ForeignKey("clubs.id"), nullable=False),
    Column("title", String(80), nullable=False),
    Column("starts_at", String(40), nullable=False),
    Column("location", String(250), nullable=False),
    Column("buyin", BigInteger, nullable=False),
    Column("author", BigInteger, nullable=False),
    Column("status", String(16), nullable=False),
    Column("revision", Integer, nullable=False, server_default="0"),
    CheckConstraint("buyin > 0"),
    CheckConstraint("status IN ('planned','active','reconciling','completed','cancelled')"),
)
players = Table(
    "players",
    metadata,
    Column("game_id", ForeignKey("games.id"), primary_key=True),
    Column("member_id", ForeignKey("members.id"), primary_key=True),
)
operations = Table(
    "operations",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("game_id", ForeignKey("games.id"), nullable=False),
    Column("member_id", ForeignKey("members.id"), nullable=False),
    Column("kind", String(12), nullable=False),
    Column("amount", BigInteger, nullable=False),
    Column("status", String(12), nullable=False),
    Column("author", BigInteger, nullable=False),
    Column("created_at", String(40), nullable=False),
    Column("confirmed_by", BigInteger),
    Column("confirmed_at", String(40)),
    Column("key", String(100), unique=True, nullable=False),
    CheckConstraint("amount >= 0 AND (kind = 'cashout' OR amount > 0)"),
    CheckConstraint("kind IN ('buyin','rebuy','cashout')"),
    CheckConstraint("status IN ('pending','confirmed','rejected','void')"),
)
audit = Table(
    "audit",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("game_id", ForeignKey("games.id")),
    Column("club_id", ForeignKey("clubs.id")),
    Column("actor", BigInteger, nullable=False),
    Column("at", String(40), nullable=False),
    Column("reason", Text, nullable=False),
    Column("details", Text, nullable=False),
)
sessions = Table(
    "sessions", metadata, Column("tg_id", BigInteger, primary_key=True), Column("data", Text, nullable=False)
)
actions = Table(
    "actions",
    metadata,
    Column("token", String(32), primary_key=True),
    Column("tg_id", BigInteger, nullable=False),
    Column("generation", String(32), nullable=False),
    Column("data", Text, nullable=False),
)
settings = Table(
    "settings", metadata, Column("key", String(100), primary_key=True), Column("value", Text, nullable=False)
)
inbox = Table(
    "inbox",
    metadata,
    Column("update_id", BigInteger, primary_key=True),
    Column("processed_at", String(40), nullable=False),
)
outbox = Table(
    "outbox",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("game_id", ForeignKey("games.id"), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("sent", Boolean, nullable=False, default=False),
    UniqueConstraint("game_id", "revision"),
)


class Database:
    def __init__(self, url: str):
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+psycopg://", 1)
        elif url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        self.is_sqlite = url.startswith("sqlite:")
        if url.startswith("sqlite:///") and url != "sqlite:///:memory:":
            Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        if self.is_sqlite:
            self.engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})
        else:
            # Serverless не держит локальные/долгоживущие пулы соединений.
            self.engine = create_engine(url, poolclass=NullPool, connect_args={"connect_timeout": 10})

        @event.listens_for(self.engine, "connect")
        def configure(connection, _):
            if self.is_sqlite:
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA busy_timeout=30000")
                connection.execute("PRAGMA journal_mode=WAL")

    @contextmanager
    def tx(self):
        # SQLite допускает одного писателя: блокировка берётся ДО проверки состояния.
        with self.engine.connect() as connection:
            if self.is_sqlite:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            else:
                # Все экземпляры приложения используют одну транзакционную блокировку.
                # Для небольшого клуба это проще и надёжнее распределённых mutex.
                connection.exec_driver_sql("SELECT pg_advisory_xact_lock(7065636572)")
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def create_for_tests(self):
        metadata.create_all(self.engine)
