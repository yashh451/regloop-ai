"""AI layer for RegLoop AI.

Two interchangeable engines:

* HeuristicEngine — deterministic, fully offline. Uses modal-verb detection,
  keyword domain classification and TF-cosine semantic matching. Lets the whole
  product run with zero API keys (demo / CI mode).
* GeminiEngine — uses the Google Gemini API (free tier works) for extraction,
  mapping, gap analysis and amendment drafting via plain REST (no SDK needed).
  Activated automatically when GEMINI_API_KEY is set.

Both return identical plain-dict structures so the rest of the app is
provider-agnostic.
"""
from __future__ import annotations

import json
import math
import os
import re
from collections import Counter
from typing import Dict, List, Optional

# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------

OBLIGATION_PATTERN = re.compile(
    r"\b(must(?: not)?|shall(?: not)?|is required to|are required to|is prohibited"
    r"|are prohibited|may not|required to|obligated to|at a minimum)\b",
    re.IGNORECASE,
)

SECTION_PATTERN = re.compile(
    r"^\s*(?:section\s+)?((?:\d+\.)*\d+)\s*[.:)\-]?\s+(.{0,80})", re.IGNORECASE
)

DOMAIN_KEYWORDS: Dict[str, List[str]] = {
    "Data Retention": ["retain", "retention", "record", "archive", "seven years", "storage period"],
    "Data Privacy": ["personal data", "privacy", "consent", "data subject", "confidential"],
    "Information Security": ["encrypt", "security", "access control", "authentication", "incident", "breach"],
    "Customer Due Diligence": ["customer due diligence", "kyc", "identity", "verification", "onboarding"],
    "Anti-Money Laundering": ["money laundering", "suspicious", "aml", "transaction monitoring", "sanctions"],
    "Reporting & Disclosure": ["report", "notify", "disclosure", "regulator", "filing", "within"],
    "Governance & Oversight": ["board", "senior management", "oversight", "accountab", "training", "audit"],
    "Third-Party Risk": ["third party", "third-party", "vendor", "outsourc", "service provider", "due diligence"],
}

STOPWORDS = set(
    """a an and are as at be by for from has have if in into is it its must may not of on or shall
    such that the their there these this to was were will with within all any each""".split()
)


def _tokens(text: str) -> List[str]:
    return [t for t in re.findall(r"[a-z][a-z\-]+", text.lower()) if t not in STOPWORDS and len(t) > 2]


def _cosine(a: Counter, b: Counter) -> float:
    common = set(a) & set(b)
    num = sum(a[t] * b[t] for t in common)
    den = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
    return (num / den) if den else 0.0


def _classify_domain(text: str) -> str:
    lower = text.lower()
    best, best_score = "General Compliance", 0
    for domain, kws in DOMAIN_KEYWORDS.items():
        score = sum(1 for kw in kws if kw in lower)
        if score > best_score:
            best, best_score = domain, score
    return best


def _split_sentences(text: str) -> List[str]:
    chunks = re.split(r"(?<=[.;])\s+(?=[A-Z(])|\n{2,}", text)
    return [re.sub(r"\s+", " ", c).strip() for c in chunks if c.strip()]


def _split_policy_paragraphs(text: str) -> List[Dict[str, str]]:
    """Split a policy into paragraphs, tracking the nearest section header."""
    paragraphs, current_section = [], ""
    for block in re.split(r"\n{2,}", text):
        block = block.strip()
        if not block:
            continue
        m = SECTION_PATTERN.match(block.splitlines()[0])
        if m:
            current_section = f"Section {m.group(1)}"
        clean = re.sub(r"\s+", " ", block)
        if len(clean) > 40:
            paragraphs.append({"section": current_section or "—", "text": clean})
    return paragraphs


# --------------------------------------------------------------------------
# Heuristic engine (offline, deterministic)
# --------------------------------------------------------------------------

class HeuristicEngine:
    name = "heuristic"

    # -- Module 2: obligation extraction ------------------------------------
    def extract_obligations(self, regulation_text: str) -> List[dict]:
        # Build logical units: a line starting with a clause number ("3.1 ...")
        # begins a new unit; wrapped continuation lines join the previous unit.
        units, current = [], None
        for raw_line in regulation_text.splitlines():
            line = raw_line.strip()
            if not line:
                if current:
                    units.append(current)
                    current = None
                continue
            m = SECTION_PATTERN.match(line)
            if m and len(m.group(1)) <= 8:
                if current:
                    units.append(current)
                current = {"citation": m.group(1), "text": line[m.end(1):].lstrip(" .:)-")}
            elif current:
                current["text"] += " " + line
            else:
                current = {"citation": "", "text": line}
        if current:
            units.append(current)

        obligations = []
        for unit in units:
            text = re.sub(r"\s+", " ", unit["text"]).strip()
            for sentence in _split_sentences(text):
                hit = OBLIGATION_PATTERN.search(sentence)
                if not hit or len(sentence) < 30:
                    continue
                strength = 0.92 if "must" in hit.group(0).lower() or "shall" in hit.group(0).lower() else 0.84
                length_bonus = min(len(sentence), 240) / 240 * 0.06
                obligations.append({
                    "statement": sentence[0].upper() + sentence[1:].rstrip(".;") + ".",
                    "citation": f"Section {unit['citation']}" if unit["citation"] else "Unspecified",
                    "confidence": round(min(strength + length_bonus, 0.98), 2),
                    "domain": _classify_domain(sentence),
                })
        # de-duplicate
        seen, unique = set(), []
        for ob in obligations:
            key = ob["statement"].lower()
            if key not in seen:
                seen.add(key)
                unique.append(ob)
        return unique

    # -- Module 3: policy mapping --------------------------------------------
    def map_to_policies(self, obligation: dict, policies: List[dict]) -> List[dict]:
        ob_vec = Counter(_tokens(obligation["statement"]))
        scored = []
        for policy in policies:
            for para in _split_policy_paragraphs(policy["text"]):
                sim = _cosine(ob_vec, Counter(_tokens(para["text"])))
                if sim > 0.12:
                    overlap = sorted(set(_tokens(obligation["statement"])) & set(_tokens(para["text"])))
                    scored.append({
                        "policy_document": policy["filename"],
                        "policy_section": para["section"],
                        "excerpt": para["text"][:400],
                        "confidence": round(min(0.55 + sim, 0.97), 2),
                        "evidence": "Shared terms: " + ", ".join(overlap[:8]),
                        "_sim": sim,
                    })
        scored.sort(key=lambda m: m["_sim"], reverse=True)
        for m in scored:
            m.pop("_sim", None)
        return scored[:3]

    # -- Module 4: gap analysis ----------------------------------------------
    def analyze_gap(self, obligation: dict, mappings: List[dict]) -> dict:
        domain = obligation["domain"]
        high_risk_domains = {"Anti-Money Laundering", "Information Security", "Data Privacy"}
        if not mappings:
            return {
                "coverage": "not_covered",
                "risk": "high" if domain in high_risk_domains else "medium",
                "explanation": (
                    f"No internal policy section was found that addresses this obligation "
                    f"({obligation['citation']}). A new policy provision is required."
                ),
            }
        best = mappings[0]
        ob_terms = set(_tokens(obligation["statement"]))
        covered = set(_tokens(best["excerpt"])) & ob_terms
        ratio = len(covered) / max(len(ob_terms), 1)
        if ratio >= 0.6 and best["confidence"] >= 0.8:
            return {
                "coverage": "fully_covered",
                "risk": "low",
                "explanation": (
                    f"{best['policy_document']} ({best['policy_section']}) addresses the key "
                    f"requirements of this obligation. Term coverage {ratio:.0%}, mapping "
                    f"confidence {best['confidence']:.0%}."
                ),
            }
        missing = sorted(ob_terms - covered)[:6]
        return {
            "coverage": "partially_covered",
            "risk": "high" if domain in high_risk_domains and ratio < 0.35 else "medium",
            "explanation": (
                f"{best['policy_document']} ({best['policy_section']}) is related but does not fully "
                f"satisfy the obligation. Aspects not clearly addressed: {', '.join(missing) or 'specific details'}."
            ),
        }

    # -- Module 5: amendment generation ---------------------------------------
    def generate_amendment(self, obligation: dict, gap: dict, mappings: List[dict], owner: str) -> dict:
        statement = obligation["statement"]
        if gap["coverage"] == "not_covered" or not mappings:
            before = "(no existing policy provision)"
            target = mappings[0]["policy_document"] if mappings else "a new or existing policy"
            after = (f"New clause — To comply with {obligation['citation']} of the regulation, "
                     f"the organization adopts the following requirement: {statement}")
            title = f"Add new provision for {obligation['domain']}"
            amendment = f"Insert a new clause into {target} establishing this requirement explicitly."
        else:
            best = mappings[0]
            before = best["excerpt"]
            after = (best["excerpt"].rstrip(".") +
                     f". In addition, in line with {obligation['citation']}: {statement}")
            title = f"Strengthen {best['policy_section']} of {best['policy_document']}"
            amendment = (f"Amend {best['policy_document']} {best['policy_section']} to explicitly "
                         f"incorporate the regulatory requirement.")
        return {
            "title": title,
            "gap_description": gap["explanation"],
            "citation": obligation["citation"],
            "proposed_amendment": amendment,
            "before_text": before,
            "after_text": after,
            "risk": gap["risk"],
            "confidence": round(min(obligation["confidence"], 0.95) - (0.05 if gap["coverage"] == "not_covered" else 0.0), 2),
            "suggested_owner": owner,
        }


# --------------------------------------------------------------------------
# Gemini-backed engine (free tier friendly — uses plain REST, no SDK needed)
# --------------------------------------------------------------------------

class GeminiEngine(HeuristicEngine):
    """Uses Google Gemini for extraction / gap reasoning, falling back to the
    heuristic implementation on any error (rate limits, network, bad JSON)
    so the demo never breaks."""

    name = "gemini"
    MODEL = os.environ.get("REGLOOP_MODEL", "gemini-2.0-flash")

    def __init__(self):
        self.api_key = os.environ["GEMINI_API_KEY"]
        self.url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
                    f"{self.MODEL}:generateContent")

    def _ask_json(self, prompt: str) -> Optional[object]:
        import urllib.request
        payload = json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "systemInstruction": {"parts": [{"text": (
                "You are a regulatory compliance analysis engine. "
                "Respond ONLY with valid JSON. No prose, no markdown fences.")}]},
            "generationConfig": {"responseMimeType": "application/json",
                                 "temperature": 0.2},
        }).encode()
        req = urllib.request.Request(
            self.url, data=payload, method="POST",
            headers={"Content-Type": "application/json",
                     "x-goog-api-key": self.api_key})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = json.loads(resp.read().decode())
            text = body["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.MULTILINE))
        except Exception:
            return None

    def extract_obligations(self, regulation_text: str) -> List[dict]:
        result = self._ask_json(
            "Extract every distinct compliance obligation from this regulation. "
            'Return a JSON array of objects: {"statement", "citation", "confidence" (0-1), "domain"}. '
            "Citation should reference the section/clause number (e.g. \"Section 3.1\").\n\n"
            + regulation_text[:24000]
        )
        if isinstance(result, list) and result:
            obligations = [
                {
                    "statement": str(o.get("statement", "")).strip(),
                    "citation": str(o.get("citation", "Unspecified")),
                    "confidence": float(o.get("confidence", 0.8)),
                    "domain": str(o.get("domain", "General Compliance")),
                }
                for o in result if o.get("statement")
            ]
            if obligations:
                return obligations
        return super().extract_obligations(regulation_text)

    def analyze_gap(self, obligation: dict, mappings: List[dict]) -> dict:
        result = self._ask_json(
            "Given this regulatory obligation and the best-matching internal policy excerpts, "
            'assess coverage. Return a JSON object: {"coverage": "fully_covered|partially_covered|not_covered", '
            '"risk": "high|medium|low", "explanation"}.\n\nObligation: '
            + json.dumps(obligation) + "\n\nPolicy matches: " + json.dumps(mappings)
        )
        if isinstance(result, dict) and result.get("coverage") in (
                "fully_covered", "partially_covered", "not_covered"):
            return {
                "coverage": result["coverage"],
                "risk": result.get("risk", "medium"),
                "explanation": str(result.get("explanation", "")),
            }
        return super().analyze_gap(obligation, mappings)

    def generate_amendment(self, obligation: dict, gap: dict, mappings: List[dict], owner: str) -> dict:
        result = self._ask_json(
            "Draft a policy amendment ('policy pull request') to close this compliance gap. "
            'Return a JSON object: {"title", "proposed_amendment", "before_text", "after_text"}. '
            "before_text is the current policy excerpt (or \"(no existing policy provision)\"); "
            "after_text is the revised clause wording.\n\nObligation: " + json.dumps(obligation)
            + "\nGap: " + json.dumps(gap) + "\nPolicy matches: " + json.dumps(mappings)
        )
        base = super().generate_amendment(obligation, gap, mappings, owner)
        if isinstance(result, dict) and result.get("after_text"):
            base.update({
                "title": str(result.get("title") or base["title"]),
                "proposed_amendment": str(result.get("proposed_amendment") or base["proposed_amendment"]),
                "before_text": str(result.get("before_text") or base["before_text"]),
                "after_text": str(result["after_text"]),
            })
        return base


def get_engine():
    """Pick the best available engine: Gemini if a key is set, otherwise the
    offline heuristic engine."""
    if os.environ.get("GEMINI_API_KEY"):
        try:
            return GeminiEngine()
        except Exception:
            pass
    return HeuristicEngine()
