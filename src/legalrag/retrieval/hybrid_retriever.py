#!/usr/bin/env python3
"""
hybrid_retriever.py — Phase 4 hybrid retrieval: Reciprocal Rank Fusion (RRF)
over vector search (Qdrant/bge-base-en-v1.5) + keyword search
(Elasticsearch/BM25), optionally followed by cross-encoder reranking.

Fusion happens at chunk level (our actual retrieval granularity), then rolls
up to document-level titles only when a caller needs that view (e.g. the
golden-set accuracy checks, which verify "the correct document," not "the
correct chunk").

RRF formula (standard, k=60 — the constant used in the original RRF paper
and Elastic's own default hybrid retriever): for each ranked list a chunk
appears in, score += 1 / (k + rank). A chunk found by both vector and
keyword search accumulates score from both lists — this is precisely how
RRF lets each method cover the other's blind spots without needing to
calibrate/normalize their very different raw score scales (cosine
similarity vs. BM25 relevance aren't comparable numbers; RANK is).
"""
from legalrag.ingestion import embed
from legalrag.indexing import es_indexer as esi
from legalrag.indexing import vector_indexer as vi
from legalrag.retrieval import reranker as rr

RRF_K = 60
DEFAULT_VECTOR_TOPN = 20
DEFAULT_KEYWORD_TOPN = 20
DEFAULT_FUSED_TOPK = 10

def vector_search(query, top_n=DEFAULT_VECTOR_TOPN, category=None):
    client = vi.get_client()
    qvec = embed.embed_query(query)
    query_filter = None
    if category:
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        query_filter = Filter(must=[FieldCondition(key="category", match=MatchValue(value=category))])
    hits = client.query_points(
        collection_name=vi.COLLECTION_NAME, query=qvec, limit=top_n, query_filter=query_filter,
    ).points
    return [{"chunk_id": h.payload["chunk_id"], "payload": h.payload, "score": h.score} for h in hits]

def keyword_search(query, top_n=DEFAULT_KEYWORD_TOPN, category=None):
    client = esi.get_client()
    hits = esi.search(client, query, category=category, size=top_n)
    return [{"chunk_id": h["_source"]["chunk_id"], "payload": h["_source"], "score": h["_score"]} for h in hits]

def reciprocal_rank_fusion(*ranked_lists, k=RRF_K):
    """Each ranked_list is a list of dicts with 'chunk_id' and 'payload',
    already sorted best-first. Returns a fused list sorted by RRF score."""
    scores = {}
    payloads = {}
    for ranked_list in ranked_lists:
        for rank, item in enumerate(ranked_list, start=1):
            cid = item["chunk_id"]
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
            payloads[cid] = item["payload"]
    fused = [{"chunk_id": cid, "payload": payloads[cid], "rrf_score": s} for cid, s in scores.items()]
    fused.sort(key=lambda x: x["rrf_score"], reverse=True)
    return fused

def hybrid_search(query, top_k=DEFAULT_FUSED_TOPK, category=None, rerank=False,
                   vector_top_n=DEFAULT_VECTOR_TOPN, keyword_top_n=DEFAULT_KEYWORD_TOPN):
    """Full pipeline: vector + keyword search -> RRF fusion -> optional rerank.
    Returns a list of dicts with chunk_id, payload (full chunk metadata +
    text), rrf_score, and rerank_score (if reranked).

    rerank defaults to False: measured on the full 100-query golden set,
    bge-reranker-base makes Top-1 accuracy WORSE here (95.0% RRF-only vs
    91.0% reranked — a real, statistically meaningful regression, not a
    small-sample fluke) with zero benefit at Top-3/Top-5. Investigated
    truncation as a likely cause (chunks exceeding the reranker's 512-token
    limit) and ruled it out — even short, well-under-limit chunks lost to
    longer, wrong ones, so this is a genuine general-purpose-reranker
    limitation on this corpus's near-duplicate-content categories (Tax
    especially), not a fixable bug. The reranking path is kept and tested
    (rerank=True still works) in case a better/fine-tuned reranker is worth
    trying later, but it is not the default until it earns that by the data."""
    vec_hits = vector_search(query, top_n=vector_top_n, category=category)
    kw_hits = keyword_search(query, top_n=keyword_top_n, category=category)
    fused = reciprocal_rank_fusion(vec_hits, kw_hits)
    candidates = fused[:max(top_k, keyword_top_n)]  # keep a slightly wider pool for reranking to work with

    if rerank and candidates:
        for c in candidates:
            c["text"] = c["payload"]["text"]
        reranked = rr.rerank(query, candidates, text_key="text", top_k=top_k)
        return reranked
    return candidates[:top_k]
