"""
Phase 4 gate: hybrid retrieval (RRF fusion + cross-encoder reranking).

Run: pytest tests/test_phase4_hybrid.py -v

Reads the real live Qdrant + Elasticsearch indexes — not mocks — same
reasoning as every prior phase: validating the actual fused pipeline, not a
stand-in for it. Requires both services running.

This is the retrieval quality gate per plan.md: nothing downstream (LLM
generation, backend, Graph RAG) is built on weak retrieval.
"""
import csv
import random
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(ROOT))

from legalrag.retrieval import hybrid_retriever as hr

GOLDEN_SET = ROOT / "eval" / "golden_set.csv"


@pytest.fixture(scope="module")
def benchmark_queries():
    """~20 queries, 5 per category — per plan.md's Phase 4 spec. Drawn from
    the hand-verified golden set rather than a separate hand-authored set,
    same reasoning as Phase 2/3: avoids duplicating query authoring, and
    every answer here was already checked against the real source PDF."""
    rows = list(csv.DictReader(open(GOLDEN_SET, encoding="utf-8")))
    random.seed(7)
    by_cat = {}
    for r in rows:
        by_cat.setdefault(r["category"], []).append(r)
    picked = []
    for cat, items in by_cat.items():
        picked.extend(random.sample(items, min(5, len(items))))
    return picked


def _rank_of_expected(results, expected_title):
    titles = [r["payload"]["title"] for r in results]
    return titles.index(expected_title) + 1 if expected_title in titles else None


def test_hybrid_retrieval_top3_accuracy_at_least_90pct(benchmark_queries):
    """Tests the actual default pipeline (rerank=False) — see
    hybrid_retriever.hybrid_search's docstring for why reranking is off by
    default: measured on the full 100-query golden set, it reduced Top-1
    accuracy (95.0% -> 91.0%) with zero benefit at Top-3/Top-5, so the
    production default is RRF fusion alone."""
    hits_top3 = 0
    failures = []
    for row in benchmark_queries:
        results = hr.hybrid_search(row["sample_query"], top_k=5)
        rank = _rank_of_expected(results, row["source_document"])
        if rank is not None and rank <= 3:
            hits_top3 += 1
        else:
            failures.append((row["category"], row["sample_query"][:70], row["source_document"], rank))
    accuracy = hits_top3 / len(benchmark_queries)
    print(f"\nHybrid (RRF-only, default) Top-3 accuracy: {accuracy:.1%} ({hits_top3}/{len(benchmark_queries)})")
    if failures:
        print("Misses:", failures)
    assert accuracy >= 0.90, f"Top-3 accuracy {accuracy:.1%} below the 90% bar (misses: {failures})"


def test_reranker_path_runs_and_effect_is_within_known_bounds(benchmark_queries):
    """The reranker is NOT the default (see docstring in hybrid_retriever.py —
    measured on the full 100-query golden set: -4.0 points Top-1, +0.0 at
    Top-3/Top-5, a genuine general-purpose-reranker limitation on this
    corpus's near-duplicate content, not a bug). This test isn't asserting
    reranking "should improve" (that would be false) — it's a regression
    guard: confirm the rerank=True path still runs correctly and its effect
    on this 20-query sample stays within the range already measured on the
    full 100-query set, so a future change that makes it *catastrophically*
    worse (e.g. a real bug) still gets caught."""
    rrf_top1 = 0
    reranked_top1 = 0
    for row in benchmark_queries:
        pre_rerank = hr.hybrid_search(row["sample_query"], top_k=5, rerank=False)
        post_rerank = hr.hybrid_search(row["sample_query"], top_k=5, rerank=True)

        rrf_rank = _rank_of_expected(pre_rerank, row["source_document"])
        rerank_rank = _rank_of_expected(post_rerank, row["source_document"])

        if rrf_rank == 1:
            rrf_top1 += 1
        if rerank_rank == 1:
            reranked_top1 += 1

    n = len(benchmark_queries)
    print(f"\nPre-rerank (RRF only) Top-1: {rrf_top1}/{n} ({rrf_top1/n:.1%})")
    print(f"Post-rerank Top-1: {reranked_top1}/{n} ({reranked_top1/n:.1%})")
    # known full-set regression is -4pp; allow generous slack (small-sample
    # noise on n=20 can easily swing +/-1 query = 5pp) without masking a real
    # new bug that would tank it much further
    assert reranked_top1 >= rrf_top1 - 3, (
        f"reranking regression ({reranked_top1}/{n} vs {rrf_top1}/{n} pre-rerank) is worse than the "
        "known baseline from the full 100-query evaluation — investigate before assuming this is just noise"
    )


def test_rrf_fusion_combines_both_sources():
    """Sanity check on the fusion mechanics themselves: a chunk that both
    vector and keyword search agree on should outrank one only a single
    method found, all else equal — verifies RRF scores actually sum across
    lists rather than e.g. silently only using one source."""
    fake_vec = [{"chunk_id": "a", "payload": {"title": "A"}},
                {"chunk_id": "b", "payload": {"title": "B"}}]
    fake_kw = [{"chunk_id": "b", "payload": {"title": "B"}},
               {"chunk_id": "c", "payload": {"title": "C"}}]
    fused = hr.reciprocal_rank_fusion(fake_vec, fake_kw)
    assert fused[0]["chunk_id"] == "b", f"expected 'b' (found by both lists) to rank first, got {fused[0]['chunk_id']}"
