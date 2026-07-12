#!/usr/bin/env python3
"""
parser.py — Phase 1 page-level PDF extraction for the US Tax & Legal RAG system.

Turns a single PDF into a list of per-page structured elements:
  - prose text blocks (header/footer stripped, dehyphenated, ligature-repaired)
  - tables (Markdown, merged-cell duplication collapsed)
  - footnotes (kept, tagged separately from body text)
  - image placeholders (not OCR'd — flagged so coverage gaps are visible)

Output feeds chunker.py, which turns this into the final OKF-normalized chunks.
"""
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF

# ---------------- ligature repair ----------------
# PyMuPDF occasionally fails to decode ligature glyphs (missing ToUnicode CMap
# entries in the source PDF's embedded font) — drops "fi"/"fl" mid-word.
# Confirmed on real corpus: "fifth" -> "fth" in SCOTUS opinions (rare, ~1/10 docs).
_LIGATURE_FIXES = {
    "fth": "fifth", "frst": "first", "ffty": "fifty", "of ce": "office",
    "dif cult": "difficult", "suf cient": "sufficient", "de nition": "definition",
    "signi cant": "significant", "speci c": "specific", "ful ll": "fulfill",
    "quali ed": "qualified", "certi cate": "certificate", "identi ed": "identified",
    "modi ed": "modified", "classi ed": "classified", "notify": "notify",
    "con dential": "confidential", "con rm": "confirm", "in ation": "inflation",
    "in uence": "influence", "re ect": "reflect", "con ict": "conflict",
    "ef cient": "efficient", "suf x": "suffix", "af rm": "affirm",
    "refneries": "refineries", "refnery": "refinery", "re ned": "refined",
    "re nery": "refinery", "re neries": "refineries",
}

def repair_ligatures(text):
    for bad, good in _LIGATURE_FIXES.items():
        text = re.sub(r"\b" + re.escape(bad) + r"\b", good, text)
    return text

def dehyphenate(text):
    """Collapse PDF line-wrap hyphenation: soft-hyphen chars and 'word-\\nword' patterns."""
    text = re.sub(r"­\s*", "", text)                  # soft hyphen (U+00AD) + trailing space
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)       # hard hyphen at line-wrap
    return text

# ---------------- header/footer/watermark boilerplate detection ----------------
# Running headers/footers AND mid-page watermarks (e.g. SCOTUS "Page Proof Pending
# Publication" diagonal stamps) all share one trait: the same short line repeats
# verbatim across most pages, regardless of vertical position. Detect on that basis
# rather than assuming a top/bottom band.
BOILERPLATE_MIN_FRACTION = 0.5  # must repeat on >=50% of pages to count

def _normalize_boilerplate_key(s):
    """Normalize a candidate boilerplate line so page numbers don't break the match."""
    return re.sub(r"\d+", "#", s.strip())

def detect_boilerplate(doc):
    """Scan every page for short lines; return the set of normalized line-keys
    that repeat often enough across the document to be running headers/footers/watermarks."""
    n = len(doc)
    counts = {}
    for p in range(n):
        page = doc[p]
        d = page.get_text("dict")
        for b in d["blocks"]:
            if b.get("type") != 0:
                continue
            for l in b["lines"]:
                text = "".join(s["text"] for s in l["spans"]).strip()
                if not (2 <= len(text) <= 70):
                    continue
                key = _normalize_boilerplate_key(text)
                counts[key] = counts.get(key, 0) + 1
    threshold = max(2, int(n * BOILERPLATE_MIN_FRACTION))
    return {k for k, c in counts.items() if c >= threshold}

def is_boilerplate_line(text, boilerplate_keys):
    return _normalize_boilerplate_key(text.strip()) in boilerplate_keys

def _is_malformed_table(rows):
    """find_tables() can misdetect a text-heavy region as a table, dumping an
    entire page's worth of prose into a single 'cell' — confirmed real case:
    an IRS worksheet page where the detected header cell held 5568 characters
    of concatenated instructions. A real table cell is short; reject the
    detection (falls back to normal prose extraction for that region) if any
    cell is wildly oversized."""
    for row in rows:
        for cell in row:
            if len(cell) > 800:
                return True
    return False

# ---------------- table extraction ----------------
def extract_tables(page):
    """Return list of {bbox, markdown} for tables on this page, with merged-cell
    row duplication collapsed (find_tables() sometimes triples a spanning footnote
    row across all columns — confirmed on IRS Pub 501)."""
    out = []
    try:
        tabs = page.find_tables()
    except Exception:
        return out
    for t in tabs.tables:
        rows = t.extract()
        cleaned_rows = []
        for row in rows:
            cells = [str(c).strip() if c is not None else "" for c in row]
            non_empty = [c for c in cells if c]
            if len(non_empty) >= 2 and len(set(non_empty)) == 1:
                cells = [non_empty[0]] + [""] * (len(cells) - 1)
            cleaned_rows.append(cells)
        if not cleaned_rows:
            continue
        if _is_malformed_table(cleaned_rows):
            continue  # find_tables() misdetected a text block as a table structure
        md = _rows_to_markdown(cleaned_rows)
        out.append({"bbox": t.bbox, "markdown": md})
    return out

def _rows_to_markdown(rows):
    def esc(c):
        return c.replace("\n", " ").replace("|", "/").strip()
    header = rows[0]
    lines = ["| " + " | ".join(esc(c) for c in header) + " |",
              "|" + "|".join(["---"] * len(header)) + "|"]
    for row in rows[1:]:
        lines.append("| " + " | ".join(esc(c) for c in row) + " |")
    return "\n".join(lines)

# ---------------- footnote detection ----------------
def split_body_and_footnotes(page, exclude_bboxes):
    """Return (body_text, footnote_text) for a page, skipping any region in
    exclude_bboxes (table areas). Footnotes = spans with font size well below
    the page's median body size, positioned in the bottom third of the page."""
    h = page.rect.height
    d = page.get_text("dict")
    sizes = []
    lines_info = []
    for b in d["blocks"]:
        if b.get("type") != 0:
            continue
        for l in b["lines"]:
            spans = l["spans"]
            if not spans:
                continue
            text = "".join(s["text"] for s in spans)
            if not text.strip():
                continue
            bbox = l["bbox"]
            if _bbox_overlaps_any(bbox, exclude_bboxes):
                continue
            size = statistics.median(s["size"] for s in spans if s["size"] > 0) if any(s["size"] > 0 for s in spans) else 0
            lines_info.append((bbox, text, size))
            if size > 0:
                sizes.append(size)
    if not sizes:
        return "", ""
    median_size = statistics.median(sizes)
    body_lines, foot_lines = [], []
    for bbox, text, size in lines_info:
        is_small = size > 0 and size < median_size * 0.82
        is_bottom = bbox[1] >= h * 0.75
        if is_small and is_bottom and not _looks_like_heading(text):
            foot_lines.append(text)
        else:
            body_lines.append(text)
    return "\n".join(body_lines), "\n".join(foot_lines)

_HEADING_PATTERNS = [
    r"^\s*SEC(?:TION)?\.?\s*\d+",   # Acts: "SEC. 108."
    r"^\s*§\s*\d+",                 # Acts/regs: "§ 501"
    r"^\s*TITLE\s+[IVXLC]+\b",      # Acts: "TITLE IV"
    r"^\s*ARTICLE\s+[IVXLC\d]+\b",  # Acts
    r"^\s*CHAPTER\s+\d+\b",         # Acts/Tax
]

# Structural markers are category-specific: "§ NUM" reliably starts a real section
# in Acts, but appears constantly mid-sentence in Judgment citations ("§ 924(c)—a
# law that...") — confirmed as a real false-positive on real corpus text. Judgments
# instead use predictable opinion-part phrasing ("Justice X, dissenting").
_HEADING_PATTERNS_BY_CATEGORY = {
    "acts": _HEADING_PATTERNS,
    "judgments": [
        r"^\s*Syllabus\s*$",
        r"^\s*Opinion of the Court\s*$",
        r"^\s*Justice\s+\w+(?:\s+\w+)?,?\s*(?:delivered the opinion|concurring|dissenting)",
        r"^\s*Per Curiam\s*$",
    ],
    "tax": [],   # no reliable structural marker; font-size (medium confidence) only
    "pov": [],   # no reliable structural marker; font-size (medium confidence) only
}

_STRUCTURAL_NUM_RE = re.compile(
    r"^\s*(SEC(?:TION)?|CHAPTER|TITLE|ARTICLE)\.?\s*([\dIVXLCa-zA-Z]+)\.?\s*(?:\([a-zA-Z0-9]+\))*\s*[.\-—]?\s*(.*)$",
    re.I,
)

def _is_real_structural_heading(text):
    """'SEC. 8. MODIFICATIONS TO...' is a real heading; 'section 220504(b)(2); or'
    and 'chapter 2205 of title 36, United States Code, is amended by' match the
    exact same SEC./CHAPTER-prefixed-number regex but are inline U.S. Code
    citations inside flowing prose — confirmed real corpus bug: 13 chunks in one
    Act got mislabeled under a citation fragment as their 'section', silently
    losing the real SEC. 7 attribution. A genuine heading's text immediately
    after the number is either empty or starts a new capitalized title; a
    citation continues in lowercase ('of title 36...') or with clause
    punctuation (';', ',', '('). Only applies to non-Acts-only patterns too —
    harmless no-op for patterns (Syllabus/Justice/...) that never match this shape."""
    m = _STRUCTURAL_NUM_RE.match(text)
    if not m:
        return True  # not a SEC./CHAPTER/TITLE/ARTICLE-numbered pattern; other checks already passed
    remainder = m.group(3).strip()
    if not remainder:
        return True
    if re.match(r"^(of|is|shall|and|or|,|;|\()", remainder, re.I):
        return False
    return remainder[0].isupper()

def _is_toc_line(text):
    """Table-of-contents entries ('Chapter 1. Filing... . . . . . 12') share a
    heading's font/size styling but aren't real section boundaries — exclude them
    via their telltale dot-leader or trailing bare page number."""
    if re.search(r"(\.\s*){4,}\d*\s*$", text):
        return True
    if re.search(r"\.{4,}", text):
        return True
    return False

def _looks_like_heading(text):
    """Section/title headers must never be swept into 'footnote' just because a
    document renders them in a smaller/condensed font near a page break —
    losing them breaks section-boundary detection downstream in the chunker."""
    t = text.strip()
    if any(re.match(p, t, re.I) for p in _HEADING_PATTERNS):
        return True
    letters = [c for c in t if c.isalpha()]
    if letters and sum(1 for c in letters if c.isupper()) / len(letters) > 0.9 and 3 <= len(t.split()) <= 15:
        return True
    return False

def _bbox_overlaps_any(bbox, others, pad=2):
    x0, y0, x1, y1 = bbox
    for ob in others:
        ox0, oy0, ox1, oy1 = ob
        if x0 < ox1 + pad and x1 > ox0 - pad and y0 < oy1 + pad and y1 > oy0 - pad:
            return True
    return False

# ---------------- image placeholders ----------------
def detect_images(page):
    imgs = page.get_images(full=True)
    return len(imgs)

# ---------------- heading detection ----------------
# Font info only exists at parse time (get_text("dict")) — plain body_text has already
# lost it — so headings must be captured here, not re-derived later in the chunker.
def _document_median_font_size(doc):
    """Word-count-weighted median font size — the size that carries the most
    running text, not just the most distinct lines. A raw per-line median is
    skewed by short cover-page/TOC lines and under-represents the true body
    paragraph size on content-heavy pages (confirmed: caused false heading
    matches on normal 11pt paragraphs in a doc whose line-median was 9pt)."""
    sizes = []
    for p in range(len(doc)):
        d = doc[p].get_text("dict")
        for b in d["blocks"]:
            if b.get("type") != 0:
                continue
            for l in b["lines"]:
                for s in l["spans"]:
                    if s["size"] > 0 and s["text"].strip():
                        sizes.extend([s["size"]] * max(1, len(s["text"].split())))
    return statistics.median(sizes) if sizes else 10.0

def extract_headings(page, boilerplate, exclude_bboxes, doc_median_size, category="acts"):
    """Return [{"text":..., "confidence": "high"|"medium"}] for this page.
    high   = matches a category-specific structural marker regex — reliable
             regardless of font styling.
    medium = font size notably larger than the document's body median, short line,
             not a drop-cap/decorative glyph, not a table-of-contents entry.
    """
    patterns = _HEADING_PATTERNS_BY_CATEGORY.get(category, _HEADING_PATTERNS)
    d = page.get_text("dict")
    out = []
    for b in d["blocks"]:
        if b.get("type") != 0:
            continue
        for l in b["lines"]:
            spans = l["spans"]
            if not spans:
                continue
            text = "".join(s["text"] for s in spans).strip()
            if not text or is_boilerplate_line(text, boilerplate) or _is_toc_line(text):
                continue
            if _bbox_overlaps_any(l["bbox"], exclude_bboxes):
                continue
            if any(re.match(p, text, re.I) for p in patterns) and _is_real_structural_heading(text):
                out.append({"text": text, "confidence": "high"})
                continue
            size = max((s["size"] for s in spans), default=0)
            word_count = len(text.split())
            # Pull-quotes/callout boxes also use an enlarged font but are full
            # sentence fragments — a real heading is a short label/title and
            # essentially never starts lowercase mid-sentence (confirmed false
            # positive on real corpus: an 11pt sidebar excerpt on a 9pt-body page).
            starts_upper = text[0].isupper() or not text[0].isalpha()
            if size >= doc_median_size * 1.15 and 2 <= word_count <= 12 and len(text) >= 4 and starts_upper:
                out.append({"text": text, "confidence": "medium"})
    return out

# ---------------- main per-document parse ----------------
@dataclass
class ParsedPage:
    page_num: int  # 1-indexed
    body_text: str
    footnote_text: str
    tables: list = field(default_factory=list)   # list of markdown strings
    image_count: int = 0
    headings: list = field(default_factory=list)  # [{"text":..., "confidence":...}]

def parse_pdf(path, category="acts"):
    """Parse one PDF into a list of ParsedPage. Raises on unreadable files.
    category in {"acts","judgments","tax","pov"} selects the heading pattern set."""
    doc = fitz.open(path)
    boilerplate = detect_boilerplate(doc)
    doc_median_size = _document_median_font_size(doc)
    pages = []
    for i in range(len(doc)):
        page = doc[i]
        tables = extract_tables(page)
        table_bboxes = [t["bbox"] for t in tables]
        body, foot = split_body_and_footnotes(page, table_bboxes)
        headings = extract_headings(page, boilerplate, table_bboxes, doc_median_size, category)

        body = "\n".join(ln for ln in body.split("\n") if not is_boilerplate_line(ln, boilerplate))
        body = dehyphenate(body)
        body = repair_ligatures(body)
        body = re.sub(r"[ \t]+", " ", body)
        body = re.sub(r"\n{3,}", "\n\n", body).strip()

        foot = "\n".join(ln for ln in foot.split("\n") if not is_boilerplate_line(ln, boilerplate))
        foot = dehyphenate(foot)
        foot = repair_ligatures(foot)
        foot = re.sub(r"[ \t]+", " ", foot).strip()

        pages.append(ParsedPage(
            page_num=i + 1,
            body_text=body,
            headings=headings,
            footnote_text=foot,
            tables=[t["markdown"] for t in tables],
            image_count=detect_images(page),
        ))
    doc.close()
    return pages

if __name__ == "__main__":
    import sys
    p = parse_pdf(sys.argv[1])
    for pg in p[:3]:
        print(f"--- page {pg.page_num} ({len(pg.body_text)} chars, {len(pg.tables)} tables, {pg.image_count} images) ---")
        print(pg.body_text[:300])
        if pg.tables:
            print(">>> TABLE:", pg.tables[0][:200])
        if pg.footnote_text:
            print(">>> FOOTNOTE:", pg.footnote_text[:150])
