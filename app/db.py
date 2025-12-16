import os
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.dialects.sqlite import JSON as SQLiteJSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session, relationship, sessionmaker

# ========================= CONFIG =========================
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///storage_simple/app.db")

# SQLite necesita este flag para uso en múltiples hilos
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

Base = declarative_base()


# ========================= MODELOS =========================
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    wa_number = Column(String(32), unique=True, nullable=False, index=True)
    name = Column(String(255))
    city = Column(String(255))
    document_id = Column(String(50))
    consent_accepted = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    interactions = relationship("Interaction", back_populates="user", cascade="all, delete-orphan")
    session_state = relationship("SessionState", uselist=False, back_populates="user", cascade="all, delete-orphan")
    consent_events = relationship("ConsentEvent", back_populates="user", cascade="all, delete-orphan")


class ConsentEvent(Base):
    __tablename__ = "consent_events"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    decision = Column(String(32), nullable=False)
    # "metadata" es una palabra reservada en SQLAlchemy Declarative, así que usamos otro nombre en Python
    metadata_json = Column("metadata", Text)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="consent_events")


class Interaction(Base):
    __tablename__ = "interactions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    direction = Column(String(16), nullable=False)
    message_type = Column(String(32), default="text", nullable=False)
    content = Column(Text, nullable=False)
    body_short = Column(String(255))
    intent = Column(String(64))
    program_code = Column(String(64))
    step = Column(String(64))
    context_state = Column(JSON().with_variant(SQLiteJSON, "sqlite"))
    metadata_json = Column("metadata", JSON().with_variant(SQLiteJSON, "sqlite"))
    wa_message_id = Column(String(128))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="interactions")


class SessionState(Base):
    __tablename__ = "session_state"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    state = Column(String(64), default="TERMS_PENDING", nullable=False)
    data = Column(JSON().with_variant(SQLiteJSON, "sqlite"), default=dict)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="session_state")


# ========================= HELPERS =========================
@contextmanager
def get_session():
    session: Session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db():
    if DATABASE_URL.startswith("sqlite"):
        db_path = DATABASE_URL.replace("sqlite:///", "")
        if db_path:
            os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    Base.metadata.create_all(bind=engine)
    _ensure_interaction_lightweight_columns()


def make_json_safe(obj):
    """Recursively convert objects so they are JSON-serializable."""

    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, set):
        return [make_json_safe(item) for item in obj]
    if isinstance(obj, Mapping):
        return {str(k): make_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, Sequence) and not isinstance(obj, (str, bytes, bytearray)):
        return [make_json_safe(item) for item in obj]

    try:
        return str(obj)
    except Exception:
        return repr(obj)


def get_or_create_user(session: Session, wa_number: str) -> User:
    user: Optional[User] = session.query(User).filter_by(wa_number=wa_number).first()
    if user:
        return user
    user = User(wa_number=wa_number, consent_accepted=False)
    session.add(user)
    session.flush()
    # crear estado de sesión base
    state = SessionState(user=user, state="TERMS_PENDING", data={})
    session.add(state)
    session.commit()
    session.refresh(user)
    return user


def get_or_create_session_state(session: Session, user: User) -> SessionState:
    if user.session_state:
        return user.session_state
    state = SessionState(user=user, state="TERMS_PENDING", data={})
    session.add(state)
    session.flush()
    session.refresh(state)
    return state


def _ensure_interaction_lightweight_columns() -> None:
    """Add lightweight analytics columns if they don't exist yet."""

    inspector = inspect(engine)
    if "interactions" not in inspector.get_table_names():
        return

    existing_columns = {col["name"] for col in inspector.get_columns("interactions")}
    additions: list[str] = []

    def _add(column_name: str, ddl: str):
        if column_name not in existing_columns:
            additions.append(f"ALTER TABLE interactions ADD COLUMN {column_name} {ddl}")

    varchar = "VARCHAR"
    json_type = "JSONB" if engine.dialect.name == "postgresql" else "JSON"

    _add("body_short", f"{varchar}(255)")
    _add("intent", f"{varchar}(64)")
    _add("program_code", f"{varchar}(64)")
    _add("step", f"{varchar}(64)")
    _add("context_state", json_type)
    _add("metadata", json_type)

    if not additions:
        return

    with engine.begin() as conn:
        for stmt in additions:
            conn.execute(text(stmt))


def log_interaction(
    session: Session,
    user_id: int | None,
    direction: str,
    body: str | None = None,
    intent: str | None = None,
    program_code: str | None = None,
    step: str | None = None,
    message_type: str | None = None,
    wa_message_id: str | None = None,
    metadata: dict | None = None,
    context_state: dict | None = None,
) -> None:
    """Log a lightweight interaction row without storing heavy payloads.

    Only the short body, intent, program_code and step are persisted; context_state stays
    empty. Extra structured data can be stored in the metadata JSON column.
    """

    intent_value = intent if isinstance(intent, str) else None
    metadata_value = make_json_safe(metadata) if metadata is not None else None
    context_value = make_json_safe(context_state) if context_state is not None else None
    body_short = body[:255] if body else None

    session.add(
        Interaction(
            user_id=user_id,
            direction=direction,
            message_type=message_type or "text",
            content=body_short or "",
            body_short=body_short,
            intent=intent_value,
            program_code=program_code,
            step=step,
            context_state=context_value,
            metadata_json=metadata_value,
            wa_message_id=wa_message_id,
        )
    )
