"""Modules 2–8 — analysis pipeline, human review, audit trail and export."""
import csv
import datetime
import io
import json
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..services import pipeline

router = APIRouter(prefix="/api/sessions", tags=["analysis"])


def _get_session(db: Session, session_id: int) -> models.ReviewSession:
    session = db.get(models.ReviewSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    return session


# ---- Modules 2–5: run the AI pipeline --------------------------------------

@router.post("/{session_id}/analyze", response_model=List[schemas.ObligationOut])
def analyze(session_id: int, db: Session = Depends(get_db)):
    session = _get_session(db, session_id)
    try:
        pipeline.run_analysis(db, session)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return session.obligations


@router.get("/{session_id}/obligations", response_model=List[schemas.ObligationOut])
def obligations(session_id: int, db: Session = Depends(get_db)):
    return _get_session(db, session_id).obligations


@router.get("/{session_id}/pull-requests", response_model=List[schemas.PullRequestOut])
def pull_requests(session_id: int, db: Session = Depends(get_db)):
    session = _get_session(db, session_id)
    return [ob.gap.pull_request for ob in session.obligations
            if ob.gap and ob.gap.pull_request]


# ---- Module 6: human review --------------------------------------------------

@router.post("/{session_id}/pull-requests/{pr_id}/decision", response_model=schemas.PullRequestOut)
def decide(session_id: int, pr_id: int, decision: schemas.ReviewDecision,
           db: Session = Depends(get_db)):
    session = _get_session(db, session_id)
    pr = db.get(models.PolicyPullRequest, pr_id)
    if not pr or pr.gap.obligation.session_id != session.id:
        raise HTTPException(404, "Pull request not found")
    try:
        pr = pipeline.apply_decision(db, session, pr, decision.action, decision.note,
                                     decision.modified_amendment, decision.owner)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    prs = [ob.gap.pull_request for ob in session.obligations if ob.gap and ob.gap.pull_request]
    if prs and all(p.status != "pending" for p in prs):
        session.status = "reviewed"
        db.commit()
    return pr


# ---- Module 7: audit trail ----------------------------------------------------

@router.get("/{session_id}/audit", response_model=List[schemas.AuditEventOut])
def audit(session_id: int, db: Session = Depends(get_db)):
    session = _get_session(db, session_id)
    return sorted(session.audit_events, key=lambda e: e.id)


# ---- Module 8: export ----------------------------------------------------------

def _package(session: models.ReviewSession) -> dict:
    def iso(dt):
        return dt.isoformat() if isinstance(dt, datetime.datetime) else None

    return {
        "session": {"id": session.id, "name": session.name, "status": session.status,
                    "ai_engine": session.ai_engine, "created_at": iso(session.created_at)},
        "documents": [{"id": d.id, "kind": d.kind, "filename": d.filename}
                      for d in session.documents],
        "obligations": [{
            "id": ob.id, "statement": ob.statement, "citation": ob.citation,
            "confidence": ob.confidence, "domain": ob.domain,
            "policy_mappings": [{
                "policy_document": m.policy_document, "policy_section": m.policy_section,
                "excerpt": m.excerpt, "confidence": m.confidence, "evidence": m.evidence,
            } for m in ob.mappings],
            "gap_analysis": ({
                "coverage": ob.gap.coverage, "risk": ob.gap.risk,
                "explanation": ob.gap.explanation,
            } if ob.gap else None),
            "pull_request": ({
                "id": ob.gap.pull_request.id, "title": ob.gap.pull_request.title,
                "gap_description": ob.gap.pull_request.gap_description,
                "citation": ob.gap.pull_request.citation,
                "proposed_amendment": ob.gap.pull_request.proposed_amendment,
                "before_text": ob.gap.pull_request.before_text,
                "after_text": ob.gap.pull_request.after_text,
                "risk": ob.gap.pull_request.risk,
                "confidence": ob.gap.pull_request.confidence,
                "suggested_owner": ob.gap.pull_request.suggested_owner,
                "status": ob.gap.pull_request.status,
                "reviewer_note": ob.gap.pull_request.reviewer_note,
                "decided_at": iso(ob.gap.pull_request.decided_at),
            } if ob.gap and ob.gap.pull_request else None),
        } for ob in session.obligations],
        "audit_trail": [{
            "id": e.id, "actor": e.actor, "action": e.action, "detail": e.detail,
            "reference": e.reference, "timestamp": iso(e.created_at),
        } for e in sorted(session.audit_events, key=lambda e: e.id)],
    }


@router.get("/{session_id}/export.json")
def export_json(session_id: int, db: Session = Depends(get_db)):
    session = _get_session(db, session_id)
    pipeline.log(db, session.id, "analyst", "package_exported", "JSON compliance package exported.")
    db.commit()
    payload = json.dumps(_package(session), indent=2)
    return Response(payload, media_type="application/json", headers={
        "Content-Disposition": f"attachment; filename=regloop_session_{session.id}.json"})


@router.get("/{session_id}/export.csv")
def export_csv(session_id: int, db: Session = Depends(get_db)):
    session = _get_session(db, session_id)
    pipeline.log(db, session.id, "analyst", "package_exported", "CSV compliance package exported.")
    db.commit()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["obligation_id", "citation", "domain", "statement", "obligation_confidence",
                     "best_policy_document", "best_policy_section", "mapping_confidence",
                     "coverage", "risk", "gap_explanation", "pr_title", "proposed_amendment",
                     "suggested_owner", "review_status", "reviewer_note", "decided_at"])
    for ob in session.obligations:
        best = ob.mappings[0] if ob.mappings else None
        pr = ob.gap.pull_request if ob.gap and ob.gap.pull_request else None
        writer.writerow([
            ob.id, ob.citation, ob.domain, ob.statement, ob.confidence,
            best.policy_document if best else "", best.policy_section if best else "",
            best.confidence if best else "",
            ob.gap.coverage if ob.gap else "", ob.gap.risk if ob.gap else "",
            ob.gap.explanation if ob.gap else "",
            pr.title if pr else "", pr.proposed_amendment if pr else "",
            pr.suggested_owner if pr else "", pr.status if pr else "",
            pr.reviewer_note if pr else "",
            pr.decided_at.isoformat() if pr and pr.decided_at else "",
        ])
    return Response(buf.getvalue(), media_type="text/csv", headers={
        "Content-Disposition": f"attachment; filename=regloop_session_{session.id}.csv"})
