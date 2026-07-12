#!/usr/bin/env python3
"""
llm_service.py — Phase 5 answer generation for the US Tax & Legal RAG system.

Ties retrieval (Phase 4 hybrid_search) to grounded LLM answers with mandatory,
verifiable citations. Uses the new google-genai SDK (required for the account's
AQ.-prefixed authorization key — the old google-generativeai SDK can't
authenticate those).

Design for citation precision (the PRD's core "verification" requirement):
each retrieved chunk is presented as a numbered source with its EXACT document
name, section, and page. The model must cite claims with [N] markers pointing
at those sources. Because we control the N->source mapping, every citation
resolves to a specific chunk with a specific page — citations are exact and
machine-verifiable (see citation_validator.py), not free-text the model made up.

We present each chunk's own `text` (not the wider parent_section_text) as the
citable unit, so the page number attached to a citation is exactly the page
that text is on — richer surrounding context usually arrives anyway via the
other top-k chunks retrieved from the same section.
"""
import os
import re
import time

import httpx
from dotenv import load_dotenv
from google import genai
from google.genai import errors as genai_errors

from legalrag import config
from legalrag.retrieval import hybrid_retriever as hr
from legalrag.generation import citation_validator as cv

load_dotenv()

MODEL_ID = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
DEFAULT_TOP_K = 12   # generation context depth. Retrieval nails the right
                     # DOCUMENT reliably (Phase 4: ~95% top-1 doc), but within a
                     # doc that has many similar chunks the specific answer chunk
                     # can rank ~9th (confirmed: a Good Samaritan Act definition
                     # sat at rank 9). Feeding 12 chunks (~5k tokens, trivial for
                     # Gemini) lets the model see the answer instead of refusing.
MAX_RATE_LIMIT_RETRIES = 6

_client = None

def get_client():
    """Dual-mode Gemini client:
      - Vertex AI mode (GEMINI_USE_VERTEX=true): bills against Google Cloud
        credits (incl. the $300 free trial, which AI Studio billing can't use).
        Auth via Application Default Credentials — set GOOGLE_APPLICATION_CREDENTIALS
        to a service-account key file. Needs GCP_PROJECT and GCP_LOCATION.
      - AI Studio mode (default): simple API key via GOOGLE_API_KEY.
    Both use the same google-genai SDK, so nothing else in this module changes."""
    global _client
    if _client is None:
        use_vertex = os.environ.get("GEMINI_USE_VERTEX", "").strip().lower() in ("1", "true", "yes")
        if use_vertex:
            project = os.environ.get("GCP_PROJECT", "").strip()
            location = os.environ.get("GCP_LOCATION", "global").strip() or "global"
            if not project:
                raise RuntimeError("GEMINI_USE_VERTEX is set but GCP_PROJECT is empty (check .env)")
            if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip():
                raise RuntimeError("Vertex mode needs GOOGLE_APPLICATION_CREDENTIALS pointing at a service-account key JSON")
            _client = genai.Client(vertexai=True, project=project, location=location)
        else:
            key = os.environ.get("GOOGLE_API_KEY", "").strip()
            if not key:
                raise RuntimeError("GOOGLE_API_KEY not set (check .env)")
            _client = genai.Client(api_key=key)
    return _client

def _generate_with_retry(model, prompt):
    """Robust generate_content against two transient failure modes on Gemini's
    free tier:
      - 429 RESOURCE_EXHAUSTED: the 5-requests/min quota. Wait out Google's
        suggested retryDelay and retry.
      - 503 UNAVAILABLE: server-side "high demand" spikes (temporary, not our
        fault). Retry with exponential backoff.
    Anything else propagates immediately (a real error we shouldn't mask)."""
    client = get_client()
    for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
        try:
            return client.models.generate_content(model=model, contents=prompt)
        except genai_errors.ClientError as e:
            is_429 = getattr(e, "code", None) == 429 or "RESOURCE_EXHAUSTED" in str(e)
            if not is_429 or attempt == MAX_RATE_LIMIT_RETRIES:
                raise
            m = re.search(r"retryDelay['\":\s]+(\d+(?:\.\d+)?)s", str(e))
            delay = float(m.group(1)) + 1.0 if m else 12.0
            time.sleep(delay)
        except genai_errors.ServerError as e:
            is_503 = getattr(e, "code", None) == 503 or "UNAVAILABLE" in str(e)
            if not is_503 or attempt == MAX_RATE_LIMIT_RETRIES:
                raise
            time.sleep(min(2 ** attempt, 30))  # exponential backoff, capped
        except (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadError,
                httpx.ReadTimeout, httpx.WriteError, httpx.PoolTimeout) as e:
            # transient network blips ("Server disconnected without sending a
            # response", dropped connections) — retry with backoff rather than
            # crash a long batch run (confirmed: killed the eval dataset gen at
            # 44/100 on a single disconnect).
            if attempt == MAX_RATE_LIMIT_RETRIES:
                raise
            time.sleep(min(2 ** attempt, 30))

SYSTEM_PROMPT = """You are a precise US tax and legal research assistant. Answer the user's QUESTION using ONLY the numbered SOURCES provided below.

Rules you must follow exactly:
1. MANDATORY CITATIONS: every sentence that states a fact MUST end with at least one source marker in square brackets, e.g. "Maternity clothes are not deductible [1]." An answer with no [N] marker is invalid. Never write a factual claim without a citation.
2. Only cite source numbers that appear in the SOURCES list. Never invent a citation number.
3. If the SOURCES do not contain enough information to answer the question, reply with exactly this sentence and nothing else: "I could not find the answer in the provided legal sources."
4. Do not use any outside knowledge. Do not guess. Base every word on the SOURCES.
5. Be concise and precise. Preserve exact figures, dollar amounts, dates, and section numbers verbatim from the sources.
6. TAX YEAR: if the SOURCES give different values for different tax years (e.g. a 2025 amount and a 2026 amount), label each figure with its tax year, and if the question names a specific year, lead with that year's figure.
"""

_CITATION_FIX_INSTRUCTION = (
    "\n\nYOUR PREVIOUS ANSWER WAS:\n{prev}\n\n"
    "That answer is invalid because it {problem}. Rewrite the answer so that every factual "
    "statement ends with the correct [N] marker(s) chosen ONLY from the numbered SOURCES above. "
    "Do not change the facts. If the answer truly isn't in the SOURCES, reply with exactly: "
    '"I could not find the answer in the provided legal sources."'
)

def _page_str(page_start, page_end):
    return str(page_start) if page_start == page_end else f"{page_start}-{page_end}"

def build_context_block(chunks):
    """chunks: list of hybrid_search results (each has a 'payload' dict).
    Returns (context_text, sources) where sources maps marker N -> metadata."""
    lines = []
    sources = []
    for i, ch in enumerate(chunks, 1):
        p = ch["payload"]
        page = _page_str(p["page_start"], p["page_end"])
        header = f'[{i}] Document: {p["title"]} | Section: {p["section_title"]} | Page: {page}'
        lines.append(f'{header}\n{p["text"]}')
        sources.append({
            "marker": i,
            "doc": p["title"],
            "section": p["section_title"],
            "page": page,
            "page_start": p["page_start"],
            "page_end": p["page_end"],
            "category": p.get("category", ""),
            "chunk_id": p["chunk_id"],
            "url": p.get("url", ""),
        })
    return "\n\n".join(lines), sources

def generate_answer(query, chunks, model=None):
    """Generate a grounded answer over already-retrieved chunks. Returns a
    structured dict incl. the answer text, the resolved citations, and the
    citation-validator verdict."""
    model = model or MODEL_ID
    context, sources = build_context_block(chunks)
    prompt = f"{SYSTEM_PROMPT}\n\nSOURCES:\n{context}\n\nQUESTION: {query}\n\nANSWER:"

    resp = _generate_with_retry(model, prompt)
    answer_text = (resp.text or "").strip()
    validation = cv.validate(answer_text, sources)

    # One-shot self-correction: LLMs occasionally produce a correct answer but
    # omit the [N] citation marker, or cite a number not in the sources. For a
    # legal system an uncited claim is unusable, so nudge the model once to fix
    # the citation formatting (facts unchanged) rather than shipping it ungrounded.
    if not validation["grounded"] and not validation["is_refusal"]:
        problem = ("cites a source number that was not provided"
                   if validation["invalid_markers"] else "contains factual claims with no [N] citation marker")
        fix_prompt = prompt + _CITATION_FIX_INSTRUCTION.format(prev=answer_text, problem=problem)
        resp2 = _generate_with_retry(model, fix_prompt)
        answer_text2 = (resp2.text or "").strip()
        validation2 = cv.validate(answer_text2, sources)
        if validation2["grounded"]:  # only accept the retry if it actually fixed it
            answer_text, validation = answer_text2, validation2

    return {
        "query": query,
        "answer": answer_text,
        "sources": sources,
        "citations": validation["resolved_citations"],
        "grounded": validation["grounded"],
        "validation": validation,
        "model": model,
    }

def ask(query, top_k=DEFAULT_TOP_K, category=None, model=None):
    """Full end-to-end: retrieve (hybrid) -> generate -> validate. This is the
    function the Phase 6 API/UI will call."""
    chunks = hr.hybrid_search(query, top_k=top_k, category=category)
    result = generate_answer(query, chunks, model=model)
    return result

# ---------------- summarization (PRD Milestone 3, feature 2) ----------------
SUMMARY_PROMPT = """You are a legal document summarizer. Produce a concise, accurate summary of the following {category} document titled "{title}", based ONLY on the provided text. Do not add facts not present in the text. Keep it to a few short paragraphs covering the document's purpose and key provisions."""

def summarize_document(doc_id, max_chars=12000, model=None):
    """Summarize a document from its processed chunks. Caps input length to
    stay within a reasonable context budget for long documents."""
    import glob, json
    model = model or MODEL_ID
    path = config.PROCESSED_DIR / f"{doc_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"no processed doc: {doc_id}")
    chunks = json.loads(path.read_text(encoding="utf-8"))
    prose = [c for c in chunks if c["chunk_type"] == "prose"]
    if not prose:
        prose = chunks
    title = prose[0]["title"]
    category = prose[0]["category"]
    body = "\n".join(c["text"] for c in prose)[:max_chars]
    prompt = SUMMARY_PROMPT.format(category=category, title=title) + "\n\nTEXT:\n" + body
    resp = _generate_with_retry(model, prompt)
    return {"doc_id": doc_id, "title": title, "category": category, "summary": (resp.text or "").strip()}
