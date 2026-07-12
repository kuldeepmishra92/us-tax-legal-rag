#!/usr/bin/env python3
"""
citation_extractor.py — Phase 7 Graph RAG: pull cross-document legal citations
out of each corpus document's text.

Extracts four high-signal, cleanly-normalizable reference types (chosen for
precision over recall — the graph is only useful if its edges are trustworthy):
  - U.S.C. sections      e.g. "42 U. S. C. § 1395y"  -> "42 USC 1395"
  - Public Laws          e.g. "Public Law 118-42"    -> "PL 118-42"
  - Named Acts           e.g. "Endangered Species Act of 1973" (year-gated to
                         avoid matching generic "this Act")
  - Court cases          e.g. "Mullane v. Central Hanover Bank" -> "Mullane v. Central Hanover Bank"

Everything is whitespace-normalized before matching (the raw text has mid-token
newlines like "Carson v. \\nAmerican" that would otherwise fragment matches).

Each extracted reference is a normalized "authority" identifier. graph_builder
then (a) makes an Authority node per distinct identifier, (b) links each doc to
the authorities it cites, and (c) resolves authorities back to corpus documents
where possible (a cited Act/Public-Law/case that IS one of our 100 docs) to
create the document->document REFERENCES edges the PRD's examples want.
"""
import re

# ---------------- normalization ----------------
def normalize_ws(text):
    return re.sub(r"\s+", " ", text)

# ---------------- U.S.C. ----------------
_USC_RE = re.compile(r"\b(\d{1,2})\s+U\.?\s?S\.?\s?C\.?\s+(?:§+\s*)?(\d+[A-Za-z]?)")

def extract_usc(text):
    out = set()
    for title, sec in _USC_RE.findall(text):
        out.add(f"{title} USC {sec}")
    return out

# ---------------- Public Law ----------------
_PL_RE = re.compile(r"\b(?:Public Law|Pub\.?\s?L\.?(?:\s?No\.?)?|P\.?\s?L\.?)\s+(\d{2,3})[-–](\d{1,4})")

def extract_public_laws(text):
    out = set()
    for congress, num in _PL_RE.findall(text):
        out.add(f"PL {congress}-{num}")
    return out

# ---------------- Named Acts ----------------
# Year-gated: an Act reference we trust is either "<Name> Act of YYYY" or one of
# a small set of well-known short-name acts/codes. This deliberately drops bare
# "this Act"/"the Act" self-references that carry no cross-document signal.
_ACT_YEAR_RE = re.compile(r"\b((?:[A-Z][A-Za-z&'\.]+\s+){1,7}Act)\s+of\s+(\d{4})")
_WELL_KNOWN_ACTS = [
    "Clean Air Act", "Clean Water Act", "Bankruptcy Code", "Internal Revenue Code",
    "Endangered Species Act", "Administrative Procedure Act", "Social Security Act",
    "Foreign Sovereign Immunities Act", "Antiterrorism Act", "Small Business Act",
    "National Environmental Policy Act", "Comprehensive Environmental Response",
    "Higher Education Act", "Balanced Budget and Emergency Deficit Control Act",
    "First Step Act", "Federal Water Pollution Control Act", "Alien Enemies Act",
]
_WELL_KNOWN_RE = re.compile("|".join(re.escape(a) for a in _WELL_KNOWN_ACTS))

def extract_named_acts(text):
    out = set()
    for name, year in _ACT_YEAR_RE.findall(text):
        name = name.strip()
        if len(name.split()) >= 2:  # need at least "<Word> Act"
            out.add(f"{name} of {year}")
    for m in _WELL_KNOWN_RE.findall(text):
        out.add(m.strip())
    return out

# ---------------- Court cases ----------------
_CASE_RE = re.compile(
    r"\b([A-Z][A-Za-z.'&\-]+(?:\s+[A-Z][A-Za-z.'&\-]+){0,3})\s+v\.\s+"
    r"([A-Z][A-Za-z.'&\-]+(?:\s+[A-Za-z.'&\-]+){0,3})"
)
_CASE_STOP = {"the", "this", "that", "a", "an"}

def extract_cases(text):
    out = set()
    for a, b in _CASE_RE.findall(text):
        a, b = a.strip(" .,"), b.strip(" .,")
        if len(a) < 3 or len(b) < 3:
            continue
        if a.split()[0].lower() in _CASE_STOP or b.split()[0].lower() in _CASE_STOP:
            continue
        out.add(f"{a} v. {b}")
    return out

# ---------------- top-level ----------------
def extract_all(text):
    """Return {kind: set(normalized identifiers)} for one document's text."""
    t = normalize_ws(text)
    return {
        "usc": extract_usc(t),
        "public_law": extract_public_laws(t),
        "named_act": extract_named_acts(t),
        "case": extract_cases(t),
    }

def extract_for_document(chunks):
    """chunks: list of chunk dicts for one doc. Returns (doc_meta, citations)."""
    prose = [c for c in chunks if c.get("chunk_type") == "prose"] or chunks
    text = " ".join(c["text"] for c in chunks)
    meta = {"doc_id": prose[0]["doc_id"], "title": prose[0]["title"], "category": prose[0]["category"]}
    return meta, extract_all(text)
