from sqlalchemy import (
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
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime, timezone

Base = declarative_base()


class User(Base):
    __tablename__ = 'users'

    id              = Column(Integer, primary_key=True, autoincrement=True)
    email           = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name       = Column(String, nullable=True)
    is_active       = Column(Boolean, default=True, nullable=False)
    created_at      = Column(DateTime, default=lambda: datetime.now(timezone.utc))

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
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

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
    created_at  = Column(DateTime, default=lambda: datetime.now(timezone.utc))

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
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    user       = relationship('User', back_populates='api_keys')
