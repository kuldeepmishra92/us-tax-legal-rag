#!/usr/bin/env python3
"""
main.py — FastAPI backend for the Hugging Face Space (server-less variant).

Same API surface as backend/app/main.py, but the three data stores are
in-process (numpy vectors, rank_bm25, networkx) instead of Qdrant/ES/Neo4j.
Generation and citation validation are the UNCHANGED legalrag pipeline, so
answer quality is identical to the main system.
"""
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# Local-run convenience: load deploy/huggingface/.env if present. On the hosted
# HF Space there is no .env (credentials come from Space Secrets), so this is a
# no-op there — it never overrides real Space secrets.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def _resolve_key_material():
    """Return the service-account key JSON text from a secret env var, or None.

    Accepts EITHER variable name and EITHER format (auto-detected):
      GOOGLE_APPLICATION_CREDENTIALS_B64   base64 of the key JSON  (recommended:
                                           a clean single line, safe for secret
                                           fields — no newlines/quotes/braces)
      GOOGLE_APPLICATION_CREDENTIALS_JSON  the raw key JSON
    For each var we try to parse it as raw JSON first, then as base64-of-JSON,
    so it works no matter which combination the user pastes."""
    import base64
    import json
    for var in ("GOOGLE_APPLICATION_CREDENTIALS_B64", "GOOGLE_APPLICATION_CREDENTIALS_JSON"):
        val = os.environ.get(var, "").strip()
        if not val:
            continue
        try:                                   # raw JSON?
            json.loads(val)
            return val
        except Exception:
            pass
        try:                                   # base64 of JSON?
            decoded = base64.b64decode(val, validate=True).decode("utf-8")
            json.loads(decoded)
            return decoded
        except Exception:
            pass
    return None


def _bootstrap_vertex_credentials():
    """The google-genai Vertex client needs a key *file*, but on HF the key
    arrives as a secret env var. Materialize the resolved JSON to a temp file and
    point GOOGLE_APPLICATION_CREDENTIALS at it. No-op when a valid file path is
    already set (local dev) or no key secret is present."""
    import tempfile
    existing = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if existing and Path(existing).exists():
        return
    raw = _resolve_key_material()
    if not raw:
        return
    path = Path(tempfile.gettempdir()) / "vertex-key.json"
    path.write_text(raw, encoding="utf-8")
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(path)


_bootstrap_vertex_credentials()

from legalrag.generation import llm_service   # reused verbatim (generation + citation guard)
from app import retrieval, graph_local, stores

HF_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = HF_ROOT / "frontend"

app = FastAPI(title="US Tax & Legal Research API (HF Space)", version="1.0")


# ---------------- schemas (mirror backend/app/main.py) ----------------
class QueryRequest(BaseModel):
    query: str = Field(..., min_length=3)
    category: str | None = None
    top_k: int | None = Field(None, ge=1, le=30)

class Citation(BaseModel):
    marker: int
    doc: str
    section: str
    page: str
    category: str = ""
    url: str = ""

class RelatedDoc(BaseModel):
    doc_id: str
    title: str
    category: str

class SharedAuthority(BaseModel):
    kind: str
    id: str
    shared_by: int

class QueryResponse(BaseModel):
    query: str
    answer: str
    grounded: bool
    citations: list[Citation]
    model: str
    related_documents: list[RelatedDoc] = []
    shared_authorities: list[SharedAuthority] = []
    is_relationship_query: bool = False

class SummarizeRequest(BaseModel):
    doc_id: str

class SummarizeResponse(BaseModel):
    doc_id: str
    title: str
    category: str
    summary: str

class DocumentInfo(BaseModel):
    doc_id: str
    title: str
    category: str

class GraphQueryRequest(BaseModel):
    reference: str = Field(..., min_length=2)
    category: str | None = None

class GraphDoc(BaseModel):
    doc_id: str
    title: str
    category: str

class GraphQueryResponse(BaseModel):
    reference: str
    citing_documents: list[GraphDoc]


# ---------------- helpers ----------------
def _norm_cat(category):
    cat = category.strip().lower() if category else None
    if cat in ("", "all", "any"):
        cat = None
    return cat


def _summarize_local(doc_id):
    """Mirror llm_service.summarize_document, but source the document's chunks
    from the exported payload store (no processed/ on the Space)."""
    _, _ = stores.get_stores()
    data = stores._data
    chunks = [data.payloads[c] for c in data.chunk_ids if data.payloads[c]["doc_id"] == doc_id]
    if not chunks:
        raise FileNotFoundError(doc_id)
    chunks.sort(key=lambda c: (c.get("page_start", 0), c.get("page_end", 0), c["chunk_id"]))
    prose = [c for c in chunks if c["chunk_type"] == "prose"] or chunks
    title, category = prose[0]["title"], prose[0]["category"]
    body = "\n".join(c["text"] for c in prose)[:12000]
    prompt = llm_service.SUMMARY_PROMPT.format(category=category, title=title) + "\n\nTEXT:\n" + body
    resp = llm_service._generate_with_retry(llm_service.MODEL_ID, prompt)
    return {"doc_id": doc_id, "title": title, "category": category,
            "summary": (resp.text or "").strip()}


# ---------------- endpoints ----------------
@app.get("/health")
def health():
    status = {"api": "ok", "backend": "serverless (numpy + rank_bm25 + networkx)"}
    try:
        v, _ = stores.get_stores()
        status["vectors"] = int(stores._data.vectors.shape[0])
        status["graph_nodes"] = graph_local.graph().number_of_nodes()
    except Exception as e:
        status["stores"] = f"error: {str(e)[:80]}"
    status["model"] = llm_service.MODEL_ID
    status["gemini_configured"] = bool(
        os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or os.environ.get("GOOGLE_API_KEY"))
    return status


@app.post("/query", response_model=QueryResponse)
def query(req: QueryRequest):
    cat = _norm_cat(req.category)
    if cat and cat not in ("acts", "judgments", "pov", "tax"):
        raise HTTPException(status_code=400, detail=f"invalid category '{cat}' (use acts|judgments|pov|tax)")
    try:
        q = req.query.strip()
        chunks = retrieval.hybrid_search(q, top_k=req.top_k or llm_service.DEFAULT_TOP_K, category=cat)
        result = llm_service.generate_answer(q, chunks)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"generation failed: {str(e)[:200]}")
    # citation-graph neighbours of the docs that informed the answer
    related, shared = [], []
    try:
        doc_ids = list(dict.fromkeys(c["payload"]["doc_id"] for c in chunks))[:5]
        enr = graph_local.enrich_docs(doc_ids)
        related, shared = enr["referenced_documents"], enr["shared_authorities"]
    except Exception:
        pass
    return QueryResponse(
        query=result["query"], answer=result["answer"], grounded=result["grounded"],
        citations=[Citation(**c) for c in result["citations"]], model=result["model"],
        related_documents=[RelatedDoc(**d) for d in related],
        shared_authorities=[SharedAuthority(**a) for a in shared],
        is_relationship_query=graph_local.is_relationship_query(q))


@app.post("/summarize", response_model=SummarizeResponse)
def summarize(req: SummarizeRequest):
    try:
        return SummarizeResponse(**_summarize_local(req.doc_id.strip()))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"document not found: {req.doc_id}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"summarization failed: {str(e)[:200]}")


@app.post("/graph/citing", response_model=GraphQueryResponse)
def graph_citing(req: GraphQueryRequest):
    cat = _norm_cat(req.category)
    try:
        results = graph_local.documents_referencing_title(req.reference, category=cat)
        if not results:
            results = graph_local.documents_citing(req.reference, category=cat)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"graph query failed: {str(e)[:150]}")
    seen, docs = set(), []
    for r in results:
        if r["doc_id"] not in seen:
            seen.add(r["doc_id"])
            docs.append(GraphDoc(doc_id=r["doc_id"], title=r["title"], category=r["category"]))
    return GraphQueryResponse(reference=req.reference, citing_documents=docs)


@app.get("/documents", response_model=list[DocumentInfo])
def documents():
    _, _ = stores.get_stores()
    data = stores._data
    seen, out = {}, []
    for cid in data.chunk_ids:
        p = data.payloads[cid]
        if p["doc_id"] not in seen:
            seen[p["doc_id"]] = True
            out.append(DocumentInfo(doc_id=p["doc_id"], title=p["title"], category=p["category"]))
    out.sort(key=lambda d: (d.category, d.title))
    return out


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
