"""RegLoop AI — application entrypoint.

Run with:  uvicorn backend.main:app --reload
The frontend is served at http://localhost:8000/
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from . import models  # noqa: F401  (registers ORM models)
from .database import Base, engine
from .routers import analysis, documents

Base.metadata.create_all(bind=engine)

app = FastAPI(title="RegLoop AI", version="1.0.0",
              description="AI-powered compliance review platform")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])

app.include_router(documents.router)
app.include_router(analysis.router)

FRONTEND = Path(__file__).resolve().parent.parent / "frontend" / "index.html"


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(FRONTEND)


@app.get("/api/health", tags=["meta"])
def health():
    return {"status": "ok", "service": "regloop-ai"}
