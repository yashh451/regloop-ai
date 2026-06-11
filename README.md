
# RegLoop AI

AI-powered compliance review platform. RegLoop AI turns a new regulation plus your
internal policies into a structured compliance review package — extracted obligations,
policy mappings, gap analysis, proposed policy amendments ("policy pull requests"),
a human review workflow and a complete audit trail — in minutes instead of days.

The AI proposes; the analyst decides. Nothing is ever applied automatically.

## Quick start

Requirements: Python 3.10+

```bash
pip install -r requirements.txt
uvicorn backend.main:app --reload
```

Open http://localhost:8000 — the full UI is served by the backend.
Interactive API docs are at http://localhost:8000/docs.

### Demo in 60 seconds

1. In **§1 Upload workspace**, upload from `sample_data/`:
   `regulation_fcd_2026_04.txt` as the regulation, the two `policy_*.txt`
   files as policies, and `responsibility_matrix.csv` as the matrix.
2. Click **Run compliance analysis**.
3. Walk the docket rail: obligations (§2) → mappings (§3) → gaps (§4) →
   review queue (§5–6) where you approve / modify / escalate / reject each
   recommendation → audit trail (§7) → export JSON/CSV (§8).

PDF uploads are supported too (text-based PDFs, via `pypdf`).

## AI engines

The AI layer is pluggable (`backend/services/ai_engine.py`):

| Engine | When it's used | What it does |
|---|---|---|
| `heuristic` | Default — no API key needed | Deterministic, fully offline: modal-verb obligation detection, keyword domain classification, TF-cosine semantic matching, rule-based gap scoring and templated amendments. Great for demos, tests and CI. |
| `gemini` | Automatically when `GEMINI_API_KEY` is set | Uses Google Gemini (free tier is enough) for obligation extraction, gap reasoning and amendment drafting via JSON-mode prompts over plain REST — no SDK to install. Falls back to the heuristic engine on any error (rate limit, network, malformed JSON), so a live demo can never break. |

Get a free key at https://aistudio.google.com/apikey, then:

```bash
export GEMINI_API_KEY=AIza...              # Windows: set GEMINI_API_KEY=AIza...
export REGLOOP_MODEL=gemini-2.0-flash      # optional override (default)
```

## Architecture

```
┌──────────────────────────────┐
│  frontend/index.html (SPA)   │  vanilla JS, served by FastAPI at /
└──────────────┬───────────────┘
               │ JSON over HTTP
┌──────────────▼───────────────┐
│  FastAPI (backend/main.py)   │
│  ├ routers/documents.py      │  Module 1  upload workspace
│  └ routers/analysis.py       │  Modules 2–8
├──────────────────────────────┤
│  services/                   │
│  ├ document_parser.py        │  PDF / TXT extraction, CSV matrix parsing
│  ├ ai_engine.py              │  Heuristic + Gemini engines (Modules 2–5)
│  └ pipeline.py               │  Orchestration + audit logging (Module 7)
├──────────────────────────────┤
│  SQLAlchemy ORM (models.py)  │  SQLite locally; set DATABASE_URL for Postgres
└──────────────────────────────┘
```

Data model: `ReviewSession → Documents`, `ReviewSession → Obligations →
PolicyMappings + GapFinding → PolicyPullRequest`, `ReviewSession → AuditEvents`.

## API surface

| Method & path | Purpose |
|---|---|
| `POST /api/sessions` | Create a review session |
| `GET /api/sessions` / `GET /api/sessions/{id}` | List / fetch sessions |
| `POST /api/sessions/{id}/documents` | Upload regulation / policy / matrix |
| `DELETE /api/sessions/{id}/documents/{doc_id}` | Remove a document |
| `POST /api/sessions/{id}/analyze` | Run Modules 2–5 (extraction → mapping → gaps → PRs) |
| `GET /api/sessions/{id}/obligations` | Obligations with mappings + gap findings |
| `GET /api/sessions/{id}/pull-requests` | Proposed policy amendments |
| `POST /api/sessions/{id}/pull-requests/{pr_id}/decision` | Approve / reject / modify / escalate |
| `GET /api/sessions/{id}/audit` | Full audit trail |
| `GET /api/sessions/{id}/export.json` / `.csv` | Export the compliance package |

## Design principles

- **Explainability** — every mapping carries an excerpt, evidence terms and a
  confidence score; every gap verdict includes a written explanation.
- **Traceability** — obligations carry regulatory citations; PRs link gap →
  obligation → policy section.
- **Auditability** — every system, AI and analyst action is written to an
  append-only audit ledger with actor, action, reference and timestamp.
- **Human-in-the-loop** — review decisions are the only path to "approved";
  the AI never applies changes.

## Project layout

```
regloop-ai/
├── backend/
│   ├── main.py            FastAPI app + static frontend
│   ├── database.py        engine / session factory
│   ├── models.py          ORM models
│   ├── schemas.py         Pydantic API contracts
│   ├── routers/           documents.py, analysis.py
│   └── services/          document_parser.py, ai_engine.py, pipeline.py
├── frontend/index.html    single-file SPA
├── sample_data/           demo regulation, policies, responsibility matrix
├── requirements.txt
└── README.md
```

## Notes & next steps

- The frontend is intentionally a zero-build single file for the prototype; the
  API is clean JSON, so swapping in Next.js + shadcn/ui later is a drop-in.
- Production hardening: authentication/RBAC, PostgreSQL (`DATABASE_URL`),
  embedding-based retrieval (RAG) in place of TF-cosine, background jobs for
  long analyses, and per-tenant isolation.


