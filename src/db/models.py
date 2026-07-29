"""Modelli SQLAlchemy, allineati a sql/schema.sql."""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, Float, TIMESTAMP, ForeignKey
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Article(Base):
    __tablename__ = "articles"

    id = Column(Integer, primary_key=True)
    url = Column(Text, unique=True, nullable=False)
    source = Column(Text, nullable=False)
    acquisition_mode = Column(Text, nullable=False)  # 'mirato' | 'generalista'
    title = Column(Text)
    published_at = Column(TIMESTAMP(timezone=True))
    first_seen_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow)
    raw_text = Column(Text)

    passed_keyword_filter = Column(Boolean)

    is_epidemic_signal = Column(Boolean)
    llm_confidence = Column(Float)
    llm_disease = Column(Text)
    llm_location = Column(Text)
    llm_justification = Column(Text)
    llm_model = Column(Text)

    status = Column(Text, default="active")  # 'active' | 'removed' | 'error'
    last_checked_at = Column(TIMESTAMP(timezone=True))

    versions = relationship("ArticleVersion", back_populates="article")
    checks = relationship("AvailabilityCheck", back_populates="article")


class ArticleVersion(Base):
    __tablename__ = "article_versions"

    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey("articles.id", ondelete="CASCADE"))
    content_hash = Column(Text, nullable=False)
    text_snapshot = Column(Text)
    captured_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow)

    article = relationship("Article", back_populates="versions")


class AvailabilityCheck(Base):
    __tablename__ = "availability_checks"

    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey("articles.id", ondelete="CASCADE"))
    checked_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow)
    http_status = Column(Integer)
    result = Column(Text, nullable=False)  # 'available' | 'removed' | 'access_error'

    article = relationship("Article", back_populates="checks")


class BlacklistedModel(Base):
    __tablename__ = "blacklisted_models"

    id = Column(Integer, primary_key=True)
    model_name = Column(String(100), unique=True, nullable=False)
    blacklisted_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow)
    expires_at = Column(TIMESTAMP(timezone=True), nullable=False)
    reason = Column(Text)
