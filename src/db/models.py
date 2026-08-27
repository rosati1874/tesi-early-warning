"""Modelli SQLAlchemy, allineati a sql/schema.sql."""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, Float, TIMESTAMP, ForeignKey, Index
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Article(Base):
    """Rappresenta un articolo di notizie acquisito, filtrato e classificato dal sistema."""
    __tablename__ = "articles"
    __table_args__ = (
        Index("idx_articles_pending_classification", "passed_keyword_filter", "is_epidemic_signal", "first_seen_at"),
        Index("idx_articles_first_seen", "first_seen_at"),
    )

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
    classification_attempts = Column(Integer, default=0, nullable=False)

    status = Column(Text, default="active")  # 'active' | 'removed' | 'error' | 'duplicate'
    last_checked_at = Column(TIMESTAMP(timezone=True))

    versions = relationship("ArticleVersion", back_populates="article")
    checks = relationship("AvailabilityCheck", back_populates="article")


class ArticleVersion(Base):
    """Traccia la cronologia e gli snapshot del testo di un articolo nel tempo (RF-06)."""
    __tablename__ = "article_versions"

    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey("articles.id", ondelete="CASCADE"))
    content_hash = Column(Text, nullable=False)
    text_snapshot = Column(Text)
    captured_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow)

    article = relationship("Article", back_populates="versions")


class AvailabilityCheck(Base):
    """Registra l'esito dei controlli di disponibilità HTTP per ciascun articolo (RF-06)."""
    __tablename__ = "availability_checks"

    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey("articles.id", ondelete="CASCADE"))
    checked_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow)
    http_status = Column(Integer)
    result = Column(Text, nullable=False)  # 'available' | 'removed' | 'access_error'

    article = relationship("Article", back_populates="checks")


class BlacklistedModel(Base):
    """Memorizza temporaneamente i modelli LLM disattivati per superamento quota (errore 429)."""
    __tablename__ = "blacklisted_models"

    id = Column(Integer, primary_key=True)
    model_name = Column(String(100), unique=True, nullable=False)
    blacklisted_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow)
    expires_at = Column(TIMESTAMP(timezone=True), nullable=False)
    reason = Column(Text)


class Subscriber(Base):
    """Rappresenta gli iscritti al servizio di notifica Webhook Pub-Sub per i nuovi segnali epidemici."""
    __tablename__ = "subscribers"

    id = Column(Integer, primary_key=True)
    webhook_url = Column(Text, unique=True, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow, nullable=False)
    active = Column(Boolean, default=True, nullable=False)
    last_notified_at = Column(TIMESTAMP(timezone=True))
    failure_count = Column(Integer, default=0, nullable=False)
