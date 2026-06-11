"""Pydantic schemas (API contracts)."""
import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class DocumentOut(ORM):
    id: int
    kind: str
    filename: str


class SessionOut(ORM):
    id: int
    name: str
    status: str
    ai_engine: str
    created_at: datetime.datetime
    documents: List[DocumentOut] = []


class MappingOut(ORM):
    id: int
    policy_document: str
    policy_section: str
    excerpt: str
    confidence: float
    evidence: str


class GapOut(ORM):
    id: int
    coverage: str
    risk: str
    explanation: str


class PullRequestOut(ORM):
    id: int
    title: str
    gap_description: str
    citation: str
    proposed_amendment: str
    before_text: str
    after_text: str
    risk: str
    confidence: float
    suggested_owner: str
    status: str
    reviewer_note: str
    decided_at: Optional[datetime.datetime] = None


class ObligationOut(ORM):
    id: int
    statement: str
    citation: str
    confidence: float
    domain: str
    mappings: List[MappingOut] = []
    gap: Optional[GapOut] = None


class AuditEventOut(ORM):
    id: int
    actor: str
    action: str
    detail: str
    reference: str
    created_at: datetime.datetime


class ReviewDecision(BaseModel):
    action: str                 # approve | reject | modify | escalate
    note: str = ""
    modified_amendment: str = ""
    owner: str = ""
