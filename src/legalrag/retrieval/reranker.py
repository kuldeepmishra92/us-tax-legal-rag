#!/usr/bin/env python3
"""
reranker.py — Phase 4 cross-encoder reranking for the US Tax & Legal RAG
system.

RRF fusion (hybrid_retriever.py) gets the right documents into a small
candidate set cheaply; the reranker then does a more expensive but more
accurate pairwise (query, candidate) relevance scoring pass over just that
small set (~10-20 candidates), not the whole corpus — so the extra compute
cost is per-query, not per-corpus, unlike Phase 2's embedding step.
"""
from sentence_transformers import CrossEncoder

MODEL_NAME = "BAAI/bge-reranker-base"

_model = None

def get_model():
    global _model
    if _model is None:
        _model = CrossEncoder(MODEL_NAME)
    return _model

def rerank(query, candidates, text_key="text", top_k=None):
    """candidates: list of dicts each containing at least text_key.
    Returns the same dicts, sorted by reranker score descending, with a
    'rerank_score' field added. top_k truncates the output if given."""
    if not candidates:
        return []
    model = get_model()
    pairs = [(query, c[text_key]) for c in candidates]
    scores = model.predict(pairs)
    for c, s in zip(candidates, scores):
        c["rerank_score"] = float(s)
    ranked = sorted(candidates, key=lambda c: c["rerank_score"], reverse=True)
    return ranked[:top_k] if top_k else ranked
