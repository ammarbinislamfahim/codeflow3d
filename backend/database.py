# backend/database.py - SQLALCHEMY MODELS

from sqlalchemy import (
    create_engine, Column, Integer, String, Text, DateTime, Boolean,
    ForeignKey, Index, JSON
)
from sqlalchemy.orm import sessionmaker, relationship, declarative_base
from datetime import datetime
import os

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://codeflow:password@localhost/codeflow_db"
)

# Use JSONB on PostgreSQL
from sqlalchemy.dialects.postgresql import JSONB
_JsonColumn = JSONB

_connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}

engine = create_engine(
    DATABASE_URL,
    echo=False,
    pool_size=10 if not DATABASE_URL.startswith("sqlite") else 5,
    max_overflow=20 if not DATABASE_URL.startswith("sqlite") else 0,
    pool_recycle=3600,
    connect_args=_connect_args
)

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(255), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False, nullable=False)

    api_keys = relationship(
        "APIKey", back_populates="user", cascade="all, delete-orphan"
    )
    analyses = relationship(
        "Analysis",
        back_populates="user",
        cascade="all, delete-orphan")
    saved_graphs = relationship(
        "SavedGraph",
        back_populates="user",
        cascade="all, delete-orphan")
    subscription = relationship(
        "Subscription",
        uselist=False,
        back_populates="user",
        cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User {self.username}>"


class APIKey(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer,
        ForeignKey(
            "users.id",
            ondelete="CASCADE"),
        nullable=False)
    key_hash = Column(String(64), unique=True, nullable=False, index=True)
    key_prefix = Column(String(20))
    name = Column(String(255))
    rate_limit_per_minute = Column(Integer, default=10)
    rate_limit_per_day = Column(Integer, default=1000)
    last_used_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    revoked_at = Column(DateTime)

    user = relationship("User", back_populates="api_keys")
    analyses = relationship("Analysis", back_populates="api_key")

    def is_valid(self) -> bool:
        return self.revoked_at is None

    def __repr__(self):
        return f"<APIKey {self.key_prefix}>"


class Analysis(Base):
    __tablename__ = "analyses"

    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer,
        ForeignKey(
            "users.id",
            ondelete="CASCADE"),
        nullable=False)
    api_key_id = Column(
        Integer,
        ForeignKey(
            "api_keys.id",
            ondelete="CASCADE"),
        nullable=False)
    language = Column(String(50), nullable=False)
    code_hash = Column(String(64), index=True)
    code_length = Column(Integer, nullable=False)
    node_count = Column(Integer)
    edge_count = Column(Integer)
    loop_count = Column(Integer)
    conditional_count = Column(Integer)
    execution_time_ms = Column(Integer)
    status = Column(String(50))
    celery_task_id = Column(String(255), nullable=True, index=True)
    error_message = Column(Text)
    result_data = Column(_JsonColumn, nullable=True)
    ip_address = Column(String(45))
    user_agent = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    user = relationship("User", back_populates="analyses")
    api_key = relationship("APIKey", back_populates="analyses")

    __table_args__ = (
        Index('idx_user_created', 'user_id', 'created_at'),
        Index('idx_code_hash', 'code_hash'),
    )

    def __repr__(self):
        return f"<Analysis {self.language}>"


class SavedGraph(Base):
    __tablename__ = "saved_graphs"

    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer,
        ForeignKey(
            "users.id",
            ondelete="CASCADE"),
        nullable=False)
    analysis_id = Column(
        Integer,
        ForeignKey(
            "analyses.id",
            ondelete="SET NULL"))
    title = Column(String(255), nullable=False)
    description = Column(Text)
    language = Column(String(50))
    code = Column(Text, nullable=False)
    graph_data = Column(_JsonColumn)
    is_public = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow)

    user = relationship("User", back_populates="saved_graphs")

    __table_args__ = (
        Index('idx_user_public', 'user_id', 'is_public'),
    )

    def __repr__(self):
        return f"<SavedGraph {self.title}>"


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer,
        ForeignKey(
            "users.id",
            ondelete="CASCADE"),
        nullable=False,
        unique=True)
    plan = Column(String(50), default="free")
    requests_per_day = Column(Integer, default=100)
    requests_per_month = Column(Integer, default=3000)
    stripe_customer_id = Column(String(255))
    stripe_subscription_id = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow)

    user = relationship("User", back_populates="subscription")

    def __repr__(self):
        return f"<Subscription {self.plan}>"


class SiteSettings(Base):
    __tablename__ = "site_settings"

    id = Column(Integer, primary_key=True)
    key = Column(String(100), unique=True, nullable=False, index=True)
    value = Column(Text, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<SiteSettings {self.key}>"


# Default settings for plan pricing and contact email
SITE_SETTINGS_DEFAULTS = {
    "contact_email": "admin@codeflow3d.com",
    "plan_price_free": "0",
    "plan_price_pro": "19",
    "plan_price_enterprise": "99",
    "upgrade_instructions": "To upgrade your plan, send an email to the address below with your username and desired plan. Our team will process your request within 24 hours.",
}


def init_db():
    """Create all tables if they don't exist yet."""
    Base.metadata.create_all(bind=engine)
    # Seed default site settings
    db = SessionLocal()
    try:
        for key, default_value in SITE_SETTINGS_DEFAULTS.items():
            existing = db.query(SiteSettings).filter_by(key=key).first()
            if not existing:
                db.add(SiteSettings(key=key, value=default_value))
        db.commit()
    finally:
        db.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
