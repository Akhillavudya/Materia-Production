from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime, timezone

Base = declarative_base()

class Session(Base):
    __tablename__ = 'sessions'

    id         = Column(String,   primary_key=True)
    title      = Column(String,   default='New chat')
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    messages   = relationship(
        'Message', back_populates='session',
        order_by='Message.id', cascade='all, delete-orphan'
    )

class Message(Base):
    __tablename__ = 'messages'

    id          = Column(Integer, primary_key=True, autoincrement=True)
    session_id  = Column(String,  ForeignKey('sessions.id'), nullable=False)
    role        = Column(String,  nullable=False)
    content     = Column(Text,    nullable=False)
    tool_result = Column(Text,    nullable=True)   # ← NEW
    created_at  = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    session     = relationship('Session', back_populates='messages')

