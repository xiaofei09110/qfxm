import logging
from sqlmodel import SQLModel, create_engine, Session
from config import DB_PATH

logger = logging.getLogger(__name__)

engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)


def init_db():
    from models import account, group, task  # noqa: F401 — triggers table registration
    SQLModel.metadata.create_all(engine)
    _migrate_db()
    logger.info("Database initialized: %s", DB_PATH)


def _migrate_db():
    """向已存在的表补充新列（SQLite 不支持 IF NOT EXISTS，需手动检查）。"""
    import sqlalchemy
    with engine.connect() as conn:
        cols = {row[1] for row in conn.execute(sqlalchemy.text("PRAGMA table_info(tasks)"))}
        if "last_error" not in cols:
            conn.execute(sqlalchemy.text("ALTER TABLE tasks ADD COLUMN last_error TEXT"))
            conn.commit()
            logger.info("DB migration: added column tasks.last_error")
        if "account_history" not in cols:
            conn.execute(sqlalchemy.text("ALTER TABLE tasks ADD COLUMN account_history TEXT"))
            conn.commit()
            logger.info("DB migration: added column tasks.account_history")

        acc_cols = {row[1] for row in conn.execute(sqlalchemy.text("PRAGMA table_info(accounts)"))}
        if "is_resting" not in acc_cols:
            conn.execute(sqlalchemy.text("ALTER TABLE accounts ADD COLUMN is_resting INTEGER DEFAULT 0 NOT NULL"))
            conn.commit()
            logger.info("DB migration: added column accounts.is_resting")


def get_session():
    return Session(engine)
