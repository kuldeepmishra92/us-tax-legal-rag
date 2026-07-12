#!/usr/bin/env python3
"""
evaluate_hybrid_quality.py — full 100-query golden-set evaluation of the
hybrid retrieval pipeline, with and without reranking, for a statistically
meaningful read on whether the reranker actually helps on this corpus.

Run after the 20-query pytest benchmark shows a borderline/negative result —
20 queries is too small a sample to draw a firm conclusion from a 1-query
swing (confirmed real case: RRF-only 19/20 vs reranked 18/20 Top-1 on a
random 20-query draw).
"""
import csv
from pathlib import Path

from legalrag import config
from legalrag.retrieval import hybrid_retriever as hr

ROOT = config.PROJECT_ROOT
GOLDEN_SET = ROOT / "eval" / "golden_set.csv"


def rank_of_expected(results, expected_title):
    titles = [r["payload"]["title"] for r in results]
    return titles.index(expected_title) + 1 if expected_title in titles else None


def main():
    rows = list(csv.DictReader(open(GOLDEN_SET, encoding="utf-8")))
    n = len(rows)
    print(f"Evaluating {n} queries, RRF-only vs RRF+reranked...")

    rrf_ranks, reranked_ranks = [], []
    changes = []
    for i, row in enumerate(rows, 1):
        pre = hr.hybrid_search(row["sample_query"], top_k=5, rerank=False)
        post = hr.hybrid_search(row["sample_query"], top_k=5, rerank=True)
        rrf_rank = rank_of_expected(pre, row["source_document"])
        rerank_rank = rank_of_expected(post, row["source_document"])
        rrf_ranks.append(rrf_rank)
        reranked_ranks.append(rerank_rank)
        if rrf_rank != rerank_rank:
            changes.append({
                "category": row["category"], "query": row["sample_query"][:70],
                "expected": row["source_document"][:50],
                "rrf_rank": rrf_rank, "rerank_rank": rerank_rank,
            })
        if i % 20 == 0:
            print(f"  ...{i}/{n} done", flush=True)

    def summarize(ranks, label):
        top1 = sum(1 for r in ranks if r == 1) / n
        top3 = sum(1 for r in ranks if r and r <= 3) / n
        top5 = sum(1 for r in ranks if r and r <= 5) / n
        print(f"\n{label}: Top-1 {top1:.1%} | Top-3 {top3:.1%} | Top-5 {top5:.1%}")
        return top1, top3, top5

    rrf_top1, rrf_top3, rrf_top5 = summarize(rrf_ranks, "RRF only (no rerank)")
    rr_top1, rr_top3, rr_top5 = summarize(reranked_ranks, "RRF + reranked")

    improved = sum(1 for c in changes if (c["rrf_rank"] is None or c["rrf_rank"] > (c["rerank_rank"] or 999)))
    worsened = sum(1 for c in changes if (c["rerank_rank"] is None or (c["rrf_rank"] or 999) < c["rerank_rank"]))
    print(f"\n{len(changes)} queries changed rank after reranking: {improved} improved, {worsened} worsened")
    for c in changes:
        direction = "IMPROVED" if (c["rrf_rank"] is None or (c["rerank_rank"] or 999) < c["rrf_rank"]) else "WORSENED"
        print(f"  [{direction}] [{c['category']}] {c['query']} | rrf={c['rrf_rank']} -> rerank={c['rerank_rank']} | expected={c['expected']}")

    print(f"\n{'='*50}")
    print(f"NET EFFECT on Top-1: {(rr_top1-rrf_top1)*100:+.1f} percentage points ({rr_top1*n:.0f} vs {rrf_top1*n:.0f} of {n})")
    print(f"NET EFFECT on Top-3: {(rr_top3-rrf_top3)*100:+.1f} percentage points")
    print(f"NET EFFECT on Top-5: {(rr_top5-rrf_top5)*100:+.1f} percentage points")


if __name__ == "__main__":
    main()
