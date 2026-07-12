#!/usr/bin/env python3
"""
chunker.py — Phase 1 OKF-normalized chunk builder for the US Tax & Legal RAG system.

Consumes parser.ParsedPage lists and produces the final chunk schema:
  {chunk_id, doc_id, title, category, section_title, chunk_type,
   page_start, page_end, text, parent_section_text}

- Structure-aware: splits at detected section headings (parser.py), not blind
  fixed-size windows.
- Token-budgeted within each section (sentence-boundary aware, respects legal
  abbreviations so we don't split mid-sentence on "v." or "U.S.C.").
- Small-to-big: every chunk carries parent_section_text (the full section, capped)
  for LLM-time context beyond the precise retrieved chunk.
- Tables become their own chunk_type="table" chunks, tagged with the same
  page/section metadata as surrounding prose.
"""
import re
import hashlib
from dataclasses import dataclass, field

import tiktoken
from legalrag.ingestion import parser as docparser

_ENC = tiktoken.get_encoding("cl100k_base")
TARGET_TOKENS = 450
MAX_TOKENS = 600
PARENT_SECTION_CHAR_CAP = 4000

def count_tokens(text):
    return len(_ENC.encode(text))

# ---------------- section building ----------------
@dataclass
class Section:
    title: str
    pages: list  # list of (page_num, text_piece) in order

def _clean_heading_text(text):
    text = docparser.dehyphenate(text)
    text = docparser.repair_ligatures(text)
    return re.sub(r"[ \t]+", " ", text).strip()

def build_sections(pages):
    """Merge pages into a document-level stream, splitting at detected headings.
    Each text piece keeps its originating page number so chunks spanning a page
    break still get correct page_start/page_end."""
    segments = []  # (page_num, text_piece, heading_title_or_None)
    for pg in pages:
        text = pg.body_text
        if not text:
            continue
        heading_hits = []
        for h in pg.headings:
            ht = _clean_heading_text(h["text"])
            if ht and ht in text:
                idx = text.find(ht)
                heading_hits.append((idx, ht))
        heading_hits.sort()

        cursor = 0
        pieces = []
        for idx, ht in heading_hits:
            if idx < cursor:
                continue
            if idx > cursor:
                pieces.append((text[cursor:idx], None))
            pieces.append((text[idx:idx + len(ht)], ht))
            cursor = idx + len(ht)
        if cursor < len(text):
            pieces.append((text[cursor:], None))
        if not pieces:
            pieces = [(text, None)]

        for piece_text, heading in pieces:
            if piece_text.strip():
                segments.append((pg.page_num, piece_text, heading))

    sections, current_title, current_pages = [], "Introduction", []

    def flush():
        if current_pages:
            full = "\n".join(t for _, t in current_pages).strip()
            if full:
                sections.append(Section(title=current_title, pages=list(current_pages)))

    for page_num, piece_text, heading in segments:
        if heading:
            flush()
            current_title = heading
            current_pages = []
        current_pages.append((page_num, piece_text))
    flush()
    return _merge_tiny_sections(sections)

MIN_SECTION_TOKENS = 40  # below this, a "section" is cover-page/metadata noise, not real content

def _merge_tiny_sections(sections):
    """Noisy medium-confidence headings (cover-page titles, stray metadata lines)
    produce near-empty 'sections' — confirmed on real corpus: 145 chunks for a
    21-page Act, many just 3-word fragments like 'Public Law 118-83' standing
    alone as their own section. Merge anything under the token floor into the
    section that follows it, so real content isn't fragmented around noise."""
    if not sections:
        return sections
    merged = []
    pending_pages = []
    pending_title = None
    for sec in sections:
        tok = count_tokens("\n".join(t for _, t in sec.pages))
        if tok < MIN_SECTION_TOKENS:
            pending_pages.extend(sec.pages)
            if pending_title is None:
                pending_title = sec.title
            continue
        pages = pending_pages + sec.pages
        title = pending_title if pending_title else sec.title
        merged.append(Section(title=title, pages=pages))
        pending_pages, pending_title = [], None
    if pending_pages:
        if merged:
            merged[-1].pages.extend(pending_pages)
        else:
            merged.append(Section(title=pending_title or "Introduction", pages=pending_pages))
    return merged

# ---------------- sentence-aware token chunking ----------------
_ABBREVS = ["U.S.C", "Pub. L. No", "Pub.L.No", "v.", "Inc.", "Corp.", "Mr.", "Mrs.",
            "Dr.", "St.", "Jr.", "Sr.", "etc.", "Fed.", "No.", "Cir.", "i.e.", "e.g.",
            "Stat.", "Op.", "id.", "Id.", "cf.", "Ct.", "L.Ed.", "F.3d", "F.2d", "U.S."]
_PLACEHOLDER = "\x00"

def _split_sentences(text):
    protected = text
    for ab in _ABBREVS:
        protected = protected.replace(ab, ab.replace(".", _PLACEHOLDER))
    raw = re.split(r'(?<=[.!?])\s+(?=[A-Z"“‘(])', protected)
    return [s.replace(_PLACEHOLDER, ".") for s in raw if s.strip()]

_HARD_CEILING = MAX_TOKENS * 2  # absolute ceiling regardless of sentence-boundary detection

def _hard_split(unit):
    """Fallback for text with no usable sentence-boundary punctuation (confirmed
    real case: back-of-book indexes are dense 'Term, page-number' lines with
    almost no periods — the sentence splitter found zero breaks across several
    pages, producing a single ~3500-token blob). Split on newlines first, then
    on raw token windows as an absolute last resort so no chunk can ever exceed
    the hard ceiling no matter how structureless the input is."""
    if count_tokens(unit) <= _HARD_CEILING:
        return [unit]
    lines = [ln for ln in unit.split("\n") if ln.strip()]
    if len(lines) > 1:
        out, buf, buf_tok = [], [], 0
        for ln in lines:
            t = count_tokens(ln)
            if buf and buf_tok + t > MAX_TOKENS:
                out.append("\n".join(buf))
                buf, buf_tok = [ln], t
            else:
                buf.append(ln)
                buf_tok += t
        if buf:
            out.append("\n".join(buf))
        return out
    # single unbroken line longer than the ceiling: hard token-window split
    ids = _ENC.encode(unit)
    return [_ENC.decode(ids[i:i + MAX_TOKENS]) for i in range(0, len(ids), MAX_TOKENS)]

def chunk_section_text(text):
    """Greedily pack sentences into ~TARGET_TOKENS chunks, never exceeding
    MAX_TOKENS unless a single sentence alone is longer (kept whole rather
    than corrupted mid-sentence) — and never exceeding _HARD_CEILING even then,
    via _hard_split for pathologically unpunctuated text."""
    paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    sentences = []
    for para in paragraphs:
        for sent in _split_sentences(para):
            sentences.extend(_hard_split(sent))
        sentences.append("\n\n")  # paragraph-boundary marker

    chunks, current, current_tokens = [], [], 0
    for sent in sentences:
        if sent == "\n\n":
            continue
        t = count_tokens(sent)
        if current and current_tokens + t > MAX_TOKENS:
            chunks.append(" ".join(current).strip())
            current, current_tokens = [sent], t
        else:
            current.append(sent)
            current_tokens += t
            if current_tokens >= TARGET_TOKENS:
                chunks.append(" ".join(current).strip())
                current, current_tokens = [], 0
    if current:
        chunks.append(" ".join(current).strip())
    chunks = [c for c in chunks if c]
    return _merge_tiny_chunks(chunks)

MIN_CHUNK_TOKENS = 25

def _merge_tiny_chunks(chunks):
    """Greedy packing can flush a near-empty chunk anywhere in the sequence, not
    just at the end — confirmed real case: a section opening with a short heading
    like 'TITLE I' gets flushed alone the moment the *next* sentence is itself
    already near/over MAX_TOKENS (the overflow check fires against a 2-token
    'current'). Merge any undersized chunk into a neighbor rather than only
    checking the tail."""
    if len(chunks) <= 1:
        return chunks
    out = list(chunks)
    i = 0
    while i < len(out):
        if count_tokens(out[i]) < MIN_CHUNK_TOKENS and len(out) > 1:
            if i > 0:
                out[i - 1] = (out[i - 1] + " " + out[i]).strip()
                out.pop(i)
            else:
                out[i + 1] = (out[i] + " " + out[i + 1]).strip()
                out.pop(i)
        else:
            i += 1
    return out

def _page_range_for_chunk(section, chunk_text, char_cursor_hint):
    """Best-effort page_start/page_end: locate which of the section's page
    pieces the chunk text actually falls within."""
    pages_seen = []
    remaining = chunk_text[:60]  # anchor on the chunk's opening text
    offset = 0
    concat = ""
    boundaries = []
    for page_num, piece in section.pages:
        boundaries.append((offset, offset + len(piece), page_num))
        concat += piece
        offset += len(piece)
    start_idx = concat.find(chunk_text[:40]) if len(chunk_text) >= 40 else concat.find(chunk_text)
    if start_idx == -1:
        return section.pages[0][0], section.pages[-1][0]
    end_idx = start_idx + len(chunk_text)
    for b_start, b_end, page_num in boundaries:
        if b_end > start_idx and b_start < end_idx:
            pages_seen.append(page_num)
    if not pages_seen:
        return section.pages[0][0], section.pages[-1][0]
    return min(pages_seen), max(pages_seen)

# ---------------- table chunk placement ----------------
def _nearest_section_for_page(sections, page_num):
    for sec in sections:
        if any(pn == page_num for pn, _ in sec.pages):
            return sec.title
    return sections[0].title if sections else "Introduction"

# ---------------- large table splitting ----------------
def _split_large_table(markdown_text):
    """Large IRS worksheets (e.g. a 30+ row, multi-step charitable-contribution
    calculation) can exceed even the hard ceiling as a single markdown blob —
    confirmed real case: 2814 tokens. Split by data rows, repeating the header +
    separator row in every part so each part stays independently readable."""
    lines = markdown_text.split("\n")
    if len(lines) < 3 or count_tokens(markdown_text) <= MAX_TOKENS:
        return [markdown_text]
    header, sep, data_rows = lines[0], lines[1], lines[2:]
    header_tokens = count_tokens(header + "\n" + sep)
    # A single row can itself exceed MAX_TOKENS (confirmed real case: one dense
    # instructional cell in an IRS worksheet) — hard-split that row's raw text
    # first so per-row batching below can never be defeated by one giant row.
    expanded_rows = []
    for row in data_rows:
        if count_tokens(row) > MAX_TOKENS:
            ids = _ENC.encode(row)
            expanded_rows.extend(_ENC.decode(ids[i:i + MAX_TOKENS]) for i in range(0, len(ids), MAX_TOKENS))
        else:
            expanded_rows.append(row)
    data_rows = expanded_rows
    parts, buf, buf_tok = [], [], header_tokens
    for row in data_rows:
        t = count_tokens(row)
        if buf and buf_tok + t > MAX_TOKENS:
            parts.append(header + "\n" + sep + "\n" + "\n".join(buf))
            buf, buf_tok = [], header_tokens
        buf.append(row)
        buf_tok += t
    if buf:
        parts.append(header + "\n" + sep + "\n" + "\n".join(buf))
    return parts if parts else [markdown_text]

def build_parent_windows(piece_chunks, cap_chars=PARENT_SECTION_CHAR_CAP):
    """The 'big' half of small-to-big retrieval: for each small search chunk,
    the wider context passed to the LLM at answer time.

    Each chunk's parent is a window of its neighboring chunks, centered on the
    chunk itself and expanded symmetrically outward until the char cap. This
    replaces the earlier "first N chars of the whole section, stamped on every
    chunk in it" approach, which handed chunks deep inside a long section the
    section's *opening* as their context — measured: 26% of prose chunks had a
    parent that didn't even contain their own text. Building the window from
    the ordered chunk list (rather than char-offset matching into the raw
    section text) guarantees the chunk is always contained and centered, with
    no fragile whitespace matching. For a section small enough to fit under the
    cap, the window naturally expands to the whole section — so the prior
    (correct) behavior for small sections is preserved automatically."""
    parents = []
    n = len(piece_chunks)
    lengths = [len(c) for c in piece_chunks]
    for i in range(n):
        size = lengths[i]
        lo = hi = i
        while True:
            grew = False
            if lo - 1 >= 0 and size + lengths[lo - 1] <= cap_chars:
                lo -= 1
                size += lengths[lo]
                grew = True
            if hi + 1 < n and size + lengths[hi + 1] <= cap_chars:
                hi += 1
                size += lengths[hi]
                grew = True
            if not grew:
                break
        parents.append("\n".join(piece_chunks[lo:hi + 1]))
    return parents

# ---------------- main chunk builder ----------------
def build_chunks(pages, doc_id, title, category, source_org="", url=""):
    sections = build_sections(pages)
    chunks = []
    chunk_idx = 0

    for sec in sections:
        full_text = "\n".join(t for _, t in sec.pages).strip()
        if not full_text:
            continue
        piece_chunks = [p for p in chunk_section_text(full_text) if p.strip()]
        parent_windows = build_parent_windows(piece_chunks)
        for piece, parent_text in zip(piece_chunks, parent_windows):
            page_start, page_end = _page_range_for_chunk(sec, piece, 0)
            chunk_idx += 1
            chunks.append({
                "chunk_id": f"{doc_id}__c{chunk_idx:04d}",
                "doc_id": doc_id,
                "title": title,
                "category": category,
                "source_org": source_org,
                "url": url,
                "section_title": sec.title,
                "chunk_type": "prose",
                "page_start": page_start,
                "page_end": page_end,
                "text": piece,
                "parent_section_text": parent_text,
                "token_count": count_tokens(piece),
            })

    # tables: one chunk per detected table (or per part, for oversized tables),
    # tagged with page + nearest section
    for pg in pages:
        for t_idx, table_md in enumerate(pg.tables):
            parts = _split_large_table(table_md)
            for part_idx, part_md in enumerate(parts):
                chunk_idx += 1
                sec_title = _nearest_section_for_page(sections, pg.page_num)
                suffix = f"_{part_idx}" if len(parts) > 1 else ""
                chunks.append({
                    "chunk_id": f"{doc_id}__t{pg.page_num:03d}_{t_idx}{suffix}",
                    "doc_id": doc_id,
                    "title": title,
                    "category": category,
                    "source_org": source_org,
                    "url": url,
                    "section_title": sec_title,
                    "chunk_type": "table",
                    "page_start": pg.page_num,
                    "page_end": pg.page_num,
                    "text": part_md,
                    "parent_section_text": table_md,  # full original table for LLM-time context
                    "token_count": count_tokens(part_md),
                })

    return chunks

def build_chunks_for_document(path, doc_id, title, category, source_org="", url=""):
    pages = docparser.parse_pdf(path, category=category)
    chunks = build_chunks(pages, doc_id, title, category, source_org, url)
    images_total = sum(pg.image_count for pg in pages)
    return chunks, {"pages": len(pages), "images_not_indexed": images_total}
