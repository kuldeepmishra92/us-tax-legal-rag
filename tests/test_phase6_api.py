"""
Phase 6 gate: FastAPI backend.

Run: pytest tests/test_phase6_api.py -v

Uses FastAPI's TestClient against the real app (which imports the real
pipeline). Validation/error-path tests need no LLM call; two tests make a real
end-to-end call to confirm the full response schema. Requires Qdrant +
Elasticsearch running and a working Gemini connection (.env).
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend" / "app"))

from backend.app.main import app  # noqa: E402

client = TestClient(app)


# ---------------- no-LLM tests (fast) ----------------
def test_health_reports_services():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["api"] == "ok"
    assert "qdrant" in body and "elasticsearch" in body and "model" in body


def test_documents_lists_corpus():
    r = client.get("/documents")
    assert r.status_code == 200
    docs = r.json()
    assert len(docs) == 100
    assert all({"doc_id", "title", "category"} <= set(d) for d in docs)


def test_index_serves_frontend():
    r = client.get("/")
    assert r.status_code == 200
    assert "US Tax" in r.text and "<html" in r.text.lower()


def test_query_too_short_is_rejected():
    r = client.post("/query", json={"query": "hi"})
    assert r.status_code == 422  # pydantic min_length validation


def test_query_bad_category_is_rejected():
    r = client.post("/query", json={"query": "what is the standard deduction?", "category": "banana"})
    assert r.status_code == 400
    assert "category" in r.json()["detail"].lower()


def test_summarize_unknown_doc_is_404():
    r = client.post("/summarize", json={"doc_id": "this_document_does_not_exist"})
    assert r.status_code == 404


# ---------------- real end-to-end tests (live LLM) ----------------
def test_query_returns_valid_grounded_response():
    r = client.post("/query", json={"query": "What is the 2025 standard deduction for a single filer?"})
    assert r.status_code == 200
    body = r.json()
    # schema
    assert set(body) >= {"query", "answer", "grounded", "citations", "model"}
    assert isinstance(body["citations"], list)
    assert body["answer"]
    # grounded answer should carry at least one citation with doc + page
    if body["grounded"] and body["citations"]:
        c = body["citations"][0]
        assert c["doc"] and str(c["page"]) and isinstance(c["marker"], int)


def test_query_category_filter_works():
    r = client.post("/query", json={
        "query": "Who is defined as the Administrator?",
        "category": "acts",
    })
    assert r.status_code == 200
    body = r.json()
    # every citation returned under an 'acts' filter must be an Acts document
    for c in body["citations"]:
        assert c["category"] in ("", "acts")


def test_graph_citing_relationship_query():
    """Graph RAG endpoint: which judgments cite the Fiscal Responsibility Act?
    (No LLM call — pure graph traversal.)"""
    r = client.post("/graph/citing", json={"reference": "Fiscal Responsibility Act", "category": "judgments"})
    assert r.status_code == 200
    body = r.json()
    titles = [d["title"] for d in body["citing_documents"]]
    assert any("SEVEN COUNTY" in t for t in titles), titles
    assert all(d["category"] == "judgments" for d in body["citing_documents"])
