"""Document text extraction: PDF (pypdf), plain text/markdown, and CSV parsing."""
import csv
import io
from typing import Dict, List


def extract_text(filename: str, data: bytes) -> str:
    """Return plain text from an uploaded regulation/policy document."""
    name = filename.lower()
    if name.endswith(".pdf"):
        try:
            from pypdf import PdfReader
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("pypdf is required to read PDF files. pip install pypdf") from exc
        reader = PdfReader(io.BytesIO(data))
        pages = [(page.extract_text() or "") for page in reader.pages]
        return "\n".join(pages).strip()
    # txt / md fallback
    return data.decode("utf-8", errors="replace").strip()


def parse_responsibility_matrix(data: bytes) -> List[Dict[str, str]]:
    """Parse the responsibility matrix CSV into [{domain, owner, ...}, ...].

    Expected columns (case-insensitive, flexible): domain, owner. Extra columns kept.
    """
    text = data.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    rows: List[Dict[str, str]] = []
    for raw in reader:
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        if any(row.values()):
            rows.append(row)
    return rows


def owner_for_domain(matrix: List[Dict[str, str]], domain: str) -> str:
    """Find the responsible owner for a compliance domain (fuzzy contains-match)."""
    d = domain.strip().lower()
    for row in matrix:
        rd = row.get("domain", "").lower()
        if rd and (rd in d or d in rd):
            return row.get("owner") or row.get("team") or "Unassigned"
    return "Compliance Office"
