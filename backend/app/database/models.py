from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime, timezone

Base = declarative_base()

# JSONB on PostgreSQL (indexable, typed); plain JSON elsewhere (e.g. SQLite dev).
JSONType = JSON().with_variant(JSONB, "postgresql")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = 'users'

    id              = Column(Integer, primary_key=True, autoincrement=True)
    email           = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name       = Column(String, nullable=True)
    is_active       = Column(Boolean, default=True, nullable=False)
    created_at      = Column(DateTime, default=_utcnow)

    sessions = relationship('Session', back_populates='user')
    api_keys = relationship('ApiKey', back_populates='user', cascade='all, delete-orphan')


class Session(Base):
    __tablename__ = 'sessions'
    __table_args__ = (
        Index('ix_sessions_user_id_created_at', 'user_id', 'created_at'),
    )

    id         = Column(String, primary_key=True)
    user_id    = Column(Integer, ForeignKey('users.id'), nullable=True, index=True)
    title      = Column(String, default='New chat')
    created_at = Column(DateTime, default=_utcnow)

    user       = relationship('User', back_populates='sessions')
    messages   = relationship(
        'Message', back_populates='session',
        order_by='Message.id', cascade='all, delete-orphan'
    )


class Message(Base):
    __tablename__ = 'messages'
    __table_args__ = (
        Index('ix_messages_session_id_id', 'session_id', 'id'),
    )

    id          = Column(Integer, primary_key=True, autoincrement=True)
    session_id  = Column(String, ForeignKey('sessions.id'), nullable=False, index=True)
    role        = Column(String, nullable=False)
    content     = Column(Text, nullable=False)
    tool_result = Column(Text, nullable=True)
    created_at  = Column(DateTime, default=_utcnow)

    session     = relationship('Session', back_populates='messages')


class ApiKey(Base):
    __tablename__ = 'api_keys'
    __table_args__ = (
        UniqueConstraint('user_id', 'service', name='uq_api_keys_user_service'),
        Index('ix_api_keys_user_id_service', 'user_id', 'service'),
    )

    id         = Column(Integer, primary_key=True, autoincrement=True)
    user_id    = Column(Integer, ForeignKey('users.id'), nullable=True, index=True)
    service    = Column(String, nullable=False)
    key_value  = Column(Text, nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    user       = relationship('User', back_populates='api_keys')


class Job(Base):
    """Async simulation job — source of truth for status, progress, artifacts.

    Long tools (optimize / md) create a row here and enqueue work; the worker
    updates it as it runs. Survives restarts because all state lives in the DB,
    not the broker (redesign §11/§12).
    """

    __tablename__ = 'jobs'
    __table_args__ = (
        Index('ix_jobs_session_id_created_at', 'session_id', 'created_at'),
        Index('ix_jobs_user_id_status', 'user_id', 'status'),
    )

    id          = Column(String, primary_key=True)                 # uuid hex
    user_id     = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    session_id  = Column(String, ForeignKey('sessions.id'), nullable=False, index=True)
    type        = Column(String, nullable=False)                   # optimize | md
    status      = Column(String, nullable=False, default='queued', index=True)
    spec        = Column(JSONType, nullable=False)                 # validated args + input path
    progress    = Column(JSONType, nullable=True)                  # {step,total,energy,...}
    result      = Column(JSONType, nullable=True)                  # final summary
    artifacts   = Column(JSONType, nullable=True)                  # [{name,rel_path,kind}]
    error       = Column(Text, nullable=True)
    calculator  = Column(JSONType, nullable=True)                  # {type,model,device}
    spec_hash   = Column(String, nullable=True, index=True)        # idempotency / dedupe
    created_at  = Column(DateTime, default=_utcnow, index=True)
    started_at  = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
