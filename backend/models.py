"""ORM models covering documents, obligations, mappings, gaps, pull requests,
review decisions and the audit trail."""
import datetime

from sqlalchemy import (Column, DateTime, Float, ForeignKey, Integer, String,
                        Text)
from sqlalchemy.orm import relationship

from .database import Base


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc)


class ReviewSession(Base):
    """One compliance review run (a set of uploaded documents + analysis)."""
    __tablename__ = "review_sessions"

    id = Column(Integer, primary_key=True)
    name = Column(String, default="Compliance Review")
    status = Column(String, default="created")  # created -> analyzed -> reviewed
    ai_engine = Column(String, default="heuristic")
    created_at = Column(DateTime, default=utcnow)

    documents = relationship("Document", back_populates="session", cascade="all, delete-orphan")
    obligations = relationship("Obligation", back_populates="session", cascade="all, delete-orphan")
    audit_events = relationship("AuditEvent", back_populates="session", cascade="all, delete-orphan")


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("review_sessions.id"), nullable=False)
    kind = Column(String, nullable=False)  # regulation | policy | matrix
    filename = Column(String, nullable=False)
    text = Column(Text, default="")
    created_at = Column(DateTime, default=utcnow)

    session = relationship("ReviewSession", back_populates="documents")


class Obligation(Base):
    __tablename__ = "obligations"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("review_sessions.id"), nullable=False)
    statement = Column(Text, nullable=False)
    citation = Column(String, default="")
    confidence = Column(Float, default=0.0)
    domain = Column(String, default="General")

    session = relationship("ReviewSession", back_populates="obligations")
    mappings = relationship("PolicyMapping", back_populates="obligation", cascade="all, delete-orphan")
    gap = relationship("GapFinding", back_populates="obligation", uselist=False, cascade="all, delete-orphan")


class PolicyMapping(Base):
    __tablename__ = "policy_mappings"

    id = Column(Integer, primary_key=True)
    obligation_id = Column(Integer, ForeignKey("obligations.id"), nullable=False)
    policy_document = Column(String, default="")
    policy_section = Column(String, default="")
    excerpt = Column(Text, default="")
    confidence = Column(Float, default=0.0)
    evidence = Column(Text, default="")

    obligation = relationship("Obligation", back_populates="mappings")


class GapFinding(Base):
    __tablename__ = "gap_findings"

    id = Column(Integer, primary_key=True)
    obligation_id = Column(Integer, ForeignKey("obligations.id"), nullable=False)
    coverage = Column(String, default="not_covered")  # fully_covered | partially_covered | not_covered
    risk = Column(String, default="medium")           # high | medium | low
    explanation = Column(Text, default="")

    obligation = relationship("Obligation", back_populates="gap")
    pull_request = relationship("PolicyPullRequest", back_populates="gap", uselist=False,
                                cascade="all, delete-orphan")


class PolicyPullRequest(Base):
    __tablename__ = "policy_pull_requests"

    id = Column(Integer, primary_key=True)
    gap_id = Column(Integer, ForeignKey("gap_findings.id"), nullable=False)
    title = Column(String, default="")
    gap_description = Column(Text, default="")
    citation = Column(String, default="")
    proposed_amendment = Column(Text, default="")
    before_text = Column(Text, default="")
    after_text = Column(Text, default="")
    risk = Column(String, default="medium")
    confidence = Column(Float, default=0.0)
    suggested_owner = Column(String, default="Unassigned")
    status = Column(String, default="pending")  # pending | approved | rejected | modified | escalated
    reviewer_note = Column(Text, default="")
    decided_at = Column(DateTime, nullable=True)

    gap = relationship("GapFinding", back_populates="pull_request")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("review_sessions.id"), nullable=False)
    actor = Column(String, default="system")  # system | ai | analyst
    action = Column(String, nullable=False)
    detail = Column(Text, default="")
    reference = Column(String, default="")    # e.g. obligation:3 / pr:7
    created_at = Column(DateTime, default=utcnow)

    session = relationship("ReviewSession", back_populates="audit_events")
