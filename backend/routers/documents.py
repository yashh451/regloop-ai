"""Module 1 — Upload Workspace endpoints."""
from typing import List

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..services import document_parser
from ..services.pipeline import log

router = APIRouter(prefix="/api/sessions", tags=["documents"])

ALLOWED_KINDS = {"regulation", "policy", "matrix"}
MAX_POLICIES = 3


@router.post("", response_model=schemas.SessionOut)
def create_session(name: str = Form("Compliance Review"), db: Session = Depends(get_db)):
    session = models.ReviewSession(name=name)
    db.add(session)
    db.flush()
    log(db, session.id, "analyst", "session_created", f"Review session '{name}' created.")
    db.commit()
    db.refresh(session)
    return session


@router.get("", response_model=List[schemas.SessionOut])
def list_sessions(db: Session = Depends(get_db)):
    return db.query(models.ReviewSession).order_by(models.ReviewSession.id.desc()).all()


@router.get("/{session_id}", response_model=schemas.SessionOut)
def get_session(session_id: int, db: Session = Depends(get_db)):
    session = db.get(models.ReviewSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    return session


@router.post("/{session_id}/documents", response_model=schemas.DocumentOut)
async def upload_document(session_id: int, kind: str = Form(...),
                          file: UploadFile = File(...), db: Session = Depends(get_db)):
    session = db.get(models.ReviewSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    if kind not in ALLOWED_KINDS:
        raise HTTPException(400, f"kind must be one of {sorted(ALLOWED_KINDS)}")

    if kind == "regulation":
        existing = [d for d in session.documents if d.kind == "regulation"]
        for d in existing:  # replace previous regulation
            db.delete(d)
    if kind == "policy":
        if sum(1 for d in session.documents if d.kind == "policy") >= MAX_POLICIES:
            raise HTTPException(400, f"A maximum of {MAX_POLICIES} policy documents is supported.")
    if kind == "matrix":
        for d in [d for d in session.documents if d.kind == "matrix"]:
            db.delete(d)

    data = await file.read()
    try:
        if kind == "matrix":
            rows = document_parser.parse_responsibility_matrix(data)
            if not rows:
                raise HTTPException(400, "The responsibility matrix CSV appears to be empty.")
            text = data.decode("utf-8", errors="replace")
        else:
            text = document_parser.extract_text(file.filename or "document.txt", data)
            if len(text) < 50:
                raise HTTPException(400, "Could not extract meaningful text from this document.")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, f"Failed to parse {file.filename}: {exc}")

    doc = models.Document(session_id=session.id, kind=kind,
                          filename=file.filename or "document", text=text)
    db.add(doc)
    db.flush()
    log(db, session.id, "analyst", "document_uploaded",
        f"{kind.capitalize()} document '{doc.filename}' uploaded ({len(text)} characters).",
        reference=f"document:{doc.id}")
    db.commit()
    db.refresh(doc)
    return doc


@router.delete("/{session_id}/documents/{document_id}")
def delete_document(session_id: int, document_id: int, db: Session = Depends(get_db)):
    doc = db.get(models.Document, document_id)
    if not doc or doc.session_id != session_id:
        raise HTTPException(404, "Document not found")
    log(db, session_id, "analyst", "document_removed", f"Removed '{doc.filename}'.")
    db.delete(doc)
    db.commit()
    return {"ok": True}
