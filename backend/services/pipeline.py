"""Pipeline orchestration: runs Modules 2–5 over a review session and writes
the audit trail (Module 7) at every step."""
import datetime

from sqlalchemy.orm import Session

from .. import models
from . import document_parser
from .ai_engine import get_engine


def log(db: Session, session_id: int, actor: str, action: str, detail: str = "", reference: str = ""):
    db.add(models.AuditEvent(session_id=session_id, actor=actor, action=action,
                             detail=detail, reference=reference))


def run_analysis(db: Session, session: models.ReviewSession) -> None:
    """Execute obligation extraction -> mapping -> gap analysis -> PR generation."""
    engine = get_engine()
    session.ai_engine = engine.name

    regulation = next((d for d in session.documents if d.kind == "regulation"), None)
    policies = [{"filename": d.filename, "text": d.text} for d in session.documents if d.kind == "policy"]
    matrix_doc = next((d for d in session.documents if d.kind == "matrix"), None)
    matrix = document_parser.parse_responsibility_matrix(matrix_doc.text.encode()) if matrix_doc else []

    if regulation is None:
        raise ValueError("A regulatory document must be uploaded before analysis.")
    if not policies:
        raise ValueError("At least one internal policy document is required.")

    # clear previous analysis (idempotent re-runs)
    for ob in list(session.obligations):
        db.delete(ob)
    db.flush()

    log(db, session.id, "ai", "analysis_started",
        f"Engine: {engine.name}. Regulation: {regulation.filename}. "
        f"Policies: {', '.join(p['filename'] for p in policies)}.")

    # Module 2 — obligation extraction
    extracted = engine.extract_obligations(regulation.text)
    log(db, session.id, "ai", "obligations_extracted",
        f"{len(extracted)} obligations extracted from {regulation.filename}.")

    for item in extracted:
        ob = models.Obligation(session_id=session.id, statement=item["statement"],
                               citation=item["citation"], confidence=item["confidence"],
                               domain=item["domain"])
        db.add(ob)
        db.flush()
        log(db, session.id, "ai", "obligation_recorded",
            f"[{item['citation']}] {item['statement'][:140]}", reference=f"obligation:{ob.id}")

        # Module 3 — policy mapping
        mappings = engine.map_to_policies(item, policies)
        for m in mappings:
            db.add(models.PolicyMapping(obligation_id=ob.id, **m))
        log(db, session.id, "ai", "policy_mapped",
            f"{len(mappings)} policy section(s) matched.", reference=f"obligation:{ob.id}")

        # Module 4 — gap analysis
        gap_data = engine.analyze_gap(item, mappings)
        gap = models.GapFinding(obligation_id=ob.id, **gap_data)
        db.add(gap)
        db.flush()
        log(db, session.id, "ai", "gap_assessed",
            f"Coverage: {gap.coverage}, risk: {gap.risk}.", reference=f"obligation:{ob.id}")

        # Module 5 — policy pull request (only where action is needed)
        if gap.coverage != "fully_covered":
            owner = document_parser.owner_for_domain(matrix, item["domain"])
            pr_data = engine.generate_amendment(item, gap_data, mappings, owner)
            pr = models.PolicyPullRequest(gap_id=gap.id, **pr_data)
            db.add(pr)
            db.flush()
            log(db, session.id, "ai", "pull_request_generated",
                pr.title, reference=f"pr:{pr.id}")

    session.status = "analyzed"
    db.commit()


def apply_decision(db: Session, session: models.ReviewSession,
                   pr: models.PolicyPullRequest, action: str, note: str,
                   modified_amendment: str, owner: str) -> models.PolicyPullRequest:
    """Module 6 — human review. The AI never applies changes automatically."""
    status_map = {"approve": "approved", "reject": "rejected",
                  "modify": "modified", "escalate": "escalated"}
    if action not in status_map:
        raise ValueError(f"Unknown review action '{action}'.")
    pr.status = status_map[action]
    pr.reviewer_note = note
    if action == "modify" and modified_amendment:
        pr.after_text = modified_amendment
        pr.proposed_amendment = modified_amendment
    if owner:
        pr.suggested_owner = owner
    pr.decided_at = datetime.datetime.now(datetime.timezone.utc)
    log(db, session.id, "analyst", f"pull_request_{pr.status}",
        note or f"Reviewer {pr.status} the recommendation.", reference=f"pr:{pr.id}")
    db.commit()
    db.refresh(pr)
    return pr
