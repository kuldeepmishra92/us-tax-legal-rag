"""
retrieval.py — hybrid retrieval for the HF Space.

Same shape and defaults as legalrag.retrieval.hybrid_retriever.hybrid_search
(vector top-20 + keyword top-20 -> RRF fuse -> top-k), but backed by the
server-less stores. The RRF fusion function itself is IMPORTED from the main
package, so fusion is byte-for-byte identical (k=60). Reranking is off (the
main default), so this reproduces the main retrieval exactly except that the
keyword arm is rank_bm25 instead of Elasticsearch.
"""
from legalrag.retrieval.hybrid_retriever import (
    reciprocal_rank_fusion, DEFAULT_VECTOR_TOPN, DEFAULT_KEYWORD_TOPN, DEFAULT_FUSED_TOPK,
)

from app.stores import get_stores


def hybrid_search(query, top_k=DEFAULT_FUSED_TOPK, category=None,
                  vector_top_n=DEFAULT_VECTOR_TOPN, keyword_top_n=DEFAULT_KEYWORD_TOPN):
    vector, keyword = get_stores()
    vec_hits = vector.search(query, top_n=vector_top_n, category=category)
    kw_hits = keyword.search(query, top_n=keyword_top_n, category=category)
    fused = reciprocal_rank_fusion(vec_hits, kw_hits)
    return fused[:top_k]
