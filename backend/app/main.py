#!/usr/bin/env python3
"""
main.py — Phase 6 FastAPI backend for the US Tax & Legal RAG system.

Wires the full pipeline (hybrid retrieval -> grounded Gemini answer -> citation
validation) behind a small HTTP API, and serves the vanilla-JS frontend as
static files from the same origin (so no CORS setup needed).

Run from the project root:
    ./venv/Scripts/python.exe -m uvicorn backend.app.main:app --reload --port 8000
Then open http://localhost:8000
"""
import csv
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# project root for locating data files (the pipeline itself is the installed
# `legalrag` package, so no sys.path manipulation is needed to import it)
ROOT = Path(__file__).resolve().parents[2]

from legalrag.generation import llm_service  # noqa: E402
from legalrag.retrieval import hybrid_retriever as hr  # noqa: E402
from legalrag.indexing import vector_indexer as vi  # noqa: E402
from legalrag.indexing import es_indexer as esi  # noqa: E402
try:
    from legalrag.graph import graph_retriever as gr  # noqa: E402
    _GRAPH_OK = True
except Exception:
    _GRAPH_OK = False


def _graph_enrichment(chunks):
    """Citation-graph neighbours of the docs that informed the answer: referenced
    corpus docs + authorities shared across them. Empty/no-op if graph is down."""
    if not _GRAPH_OK:
        return [], []
    try:
        doc_ids = list(dict.fromkeys(c["payload"]["doc_id"] for c in chunks))[:5]
        enr = gr.enrich_docs(doc_ids)
        return enr.get("referenced_documents", []), enr.get("shared_authorities", [])
    except Exception:
        return [], []

FRONTEND_DIR = ROOT / "frontend"
PROCESSED_MANIFEST = ROOT / "processed_manifest.csv"

app = FastAPI(title="US Tax & Legal Research API", version="1.0")


# ---------------- schemas ----------------
class QueryRequest(BaseModel):
    query: str = Field(..., min_length=3, description="A legal/tax question in natural language")
    category: str | None = Field(None, description="Optional filter: acts | judgments | pov | tax")
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
    reference: str = Field(..., min_length=2, description="An Act title, authority, or 'X v. Y' case name")
    category: str | None = Field(None, description="Optional: only citing docs of this category")

class GraphDoc(BaseModel):
    doc_id: str
    title: str
    category: str

class GraphQueryResponse(BaseModel):
    reference: str
    citing_documents: list[GraphDoc]


# ---------------- endpoints ----------------
@app.get("/health")
def health():
    """Report reachability of each backing service so the UI (and ops) can see
    at a glance what's up. Doesn't fail the request if a service is down — it
    reports per-service status instead."""
    status = {"api": "ok"}
    try:
        vc = vi.get_client()
        status["qdrant"] = "ok" if vc.collection_exists(vi.COLLECTION_NAME) else "collection missing"
        status["qdrant_points"] = vi.collection_point_count(vc) if vc.collection_exists(vi.COLLECTION_NAME) else 0
    except Exception as e:
        status["qdrant"] = f"error: {str(e)[:80]}"
    try:
        ec = esi.get_client()
        status["elasticsearch"] = "ok" if ec.indices.exists(index=esi.INDEX_NAME) else "index missing"
    except Exception as e:
        status["elasticsearch"] = f"error: {str(e)[:80]}"
    status["model"] = llm_service.MODEL_ID
    return status


@app.post("/query", response_model=QueryResponse)
def query(req: QueryRequest):
    cat = req.category.strip().lower() if req.category else None
    if cat in ("", "all", "any"):
        cat = None
    if cat and cat not in ("acts", "judgments", "pov", "tax"):
        raise HTTPException(status_code=400, detail=f"invalid category '{cat}' (use acts|judgments|pov|tax)")
    try:
        q = req.query.strip()
        chunks = hr.hybrid_search(q, top_k=req.top_k or llm_service.DEFAULT_TOP_K, category=cat)
        result = llm_service.generate_answer(q, chunks)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"generation failed: {str(e)[:200]}")
    related, shared = _graph_enrichment(chunks)
    rel_q = _GRAPH_OK and gr.is_relationship_query(q)
    return QueryResponse(
        query=result["query"],
        answer=result["answer"],
        grounded=result["grounded"],
        citations=[Citation(**c) for c in result["citations"]],
        model=result["model"],
        related_documents=[RelatedDoc(**d) for d in related],
        shared_authorities=[SharedAuthority(**a) for a in shared],
        is_relationship_query=bool(rel_q),
    )


@app.post("/summarize", response_model=SummarizeResponse)
def summarize(req: SummarizeRequest):
    try:
        result = llm_service.summarize_document(req.doc_id.strip())
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"document not found: {req.doc_id}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"summarization failed: {str(e)[:200]}")
    return SummarizeResponse(**result)


@app.post("/graph/citing", response_model=GraphQueryResponse)
def graph_citing(req: GraphQueryRequest):
    """Graph RAG relationship query: which corpus documents cite/reference the
    given Act, authority, or case? Tries corpus-document resolution first (via
    REFERENCES edges, the PRD's 'which judgment cites which act'), then falls
    back to authority-name citation (e.g. 'Clean Air Act', '42 USC 4321')."""
    if not _GRAPH_OK:
        raise HTTPException(status_code=503, detail="graph service unavailable (is Neo4j running?)")
    cat = req.category.strip().lower() if req.category else None
    if cat in ("", "all", "any"):
        cat = None
    try:
        results = gr.documents_referencing_title(req.reference, category=cat)
        if not results:
            results = gr.documents_citing(req.reference, category=cat)
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
    """List the corpus documents (for the summarize picker)."""
    rows = list(csv.DictReader(open(PROCESSED_MANIFEST, encoding="utf-8")))
    return [DocumentInfo(doc_id=r["doc_id"], title=r["title"], category=r["category"]) for r in rows]


# ---------------- frontend (served last so /api routes take precedence) ----------------
@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
