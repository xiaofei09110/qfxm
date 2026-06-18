import logging
from sqlmodel import SQLModel, create_engine, Session
from config import DB_PATH

logger = logging.getLogger(__name__)

engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)


def init_db():
    from models import account, group, task  # noqa: F401 — triggers table registration
    SQLModel.metadata.create_all(engine)
    logger.info("Database initialized: %s", DB_PATH)


def get_session():
    return Session(engine)
