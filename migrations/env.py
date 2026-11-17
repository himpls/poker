import os
from alembic import context
from dotenv import load_dotenv
from poker_bot.db import Database, metadata

load_dotenv()
url = os.getenv("DATABASE_URL", context.config.get_main_option("sqlalchemy.url"))
db = Database(url)
with db.engine.connect() as connection:
    context.configure(connection=connection, target_metadata=metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()
