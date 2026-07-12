#!/usr/bin/env python3
"""
evaluate_vector_quality.py — quantified quality check for the vector index,
run once build_vector_index.py has fully completed.

Goes beyond "did it run without errors" to actually measure whether the
embeddings are good:
  1. Integrity — no zero/NaN vectors, dimensions consistent (a silently
     corrupted embedding call can return degenerate vectors without erroring)
  2. Retrieval accuracy — the full 100-query golden set (not a 10-query
     sample), Top-1/Top-3/Top-5 hit rate against the verified expected source
     document, broken down by category
  3. Score calibration — similarity score distribution isn't degenerate
     (e.g. everything clustered at ~1.0, which would indicate near-duplicate
     embeddings regardless of input text)
"""
import csv
import math
from pathlib import Path

from legalrag import config
from legalrag.ingestion import embed
from legalrag.indexing import vector_indexer as vi

ROOT = config.PROJECT_ROOT
GOLDEN_SET = ROOT / "eval" / "golden_set.csv"


def check_integrity(client, sample_size=200):
    """Scan a sample of indexed points for zero/NaN/wrong-dimension vectors."""
    points, _ = client.scroll(
        collection_name=vi.COLLECTION_NAME, limit=sample_size, with_vectors=True, with_payload=False,
    )
    bad = []
    for p in points:
        vec = p.vector
        if vec is None or len(vec) != embed.EMBED_DIM:
            bad.append((p.id, "wrong dimension or missing"))
            continue
        if all(v == 0 for v in vec):
            bad.append((p.id, "all-zero vector"))
            continue
        if any(math.isnan(v) or math.isinf(v) for v in vec):
            bad.append((p.id, "NaN/Inf in vector"))
    return len(points), bad


def run_golden_set_retrieval(client, top_k=5):
    rows = list(csv.DictReader(open(GOLDEN_SET, encoding="utf-8")))
    results = []
    for i, row in enumerate(rows, 1):
        qvec = embed.embed_query(row["sample_query"])
        hits = client.query_points(collection_name=vi.COLLECTION_NAME, query=qvec, limit=top_k).points
        titles = [h.payload["title"] for h in hits]
        scores = [h.score for h in hits]
        rank = titles.index(row["source_document"]) + 1 if row["source_document"] in titles else None
        results.append({
            "query": row["sample_query"], "category": row["category"],
            "expected": row["source_document"], "rank": rank, "top_score": scores[0] if scores else None,
        })
        if i % 20 == 0:
            print(f"  ...{i}/{len(rows)} queries evaluated", flush=True)
    return results


def summarize(results):
    n = len(results)
    top1 = sum(1 for r in results if r["rank"] == 1) / n
    top3 = sum(1 for r in results if r["rank"] and r["rank"] <= 3) / n
    top5 = sum(1 for r in results if r["rank"] and r["rank"] <= 5) / n
    print(f"\n=== Retrieval Accuracy (n={n}) ===")
    print(f"  Top-1: {top1:.1%}")
    print(f"  Top-3: {top3:.1%}")
    print(f"  Top-5: {top5:.1%}")

    print("\n=== By category ===")
    cats = sorted(set(r["category"] for r in results))
    for cat in cats:
        cat_results = [r for r in results if r["category"] == cat]
        n_cat = len(cat_results)
        t1 = sum(1 for r in cat_results if r["rank"] == 1) / n_cat
        t5 = sum(1 for r in cat_results if r["rank"] and r["rank"] <= 5) / n_cat
        print(f"  {cat:12} Top-1: {t1:.1%}  Top-5: {t5:.1%}  (n={n_cat})")

    scores = [r["top_score"] for r in results if r["top_score"] is not None]
    print(f"\n=== Score calibration ===")
    print(f"  top-hit score range: {min(scores):.3f} - {max(scores):.3f}, mean {sum(scores)/len(scores):.3f}")

    misses = [r for r in results if r["rank"] is None or r["rank"] > 5]
    print(f"\n=== Misses (not in top-5): {len(misses)}/{n} ===")
    for m in misses[:15]:
        print(f"  [{m['category']}] {m['query'][:70]!r} -> expected {m['expected'][:50]!r}, rank={m['rank']}")

    return {"top1": top1, "top3": top3, "top5": top5, "n": n, "misses": misses}


def main():
    client = vi.get_client()
    count = vi.collection_point_count(client)
    print(f"collection has {count} points")

    print("\n=== Integrity check ===")
    sampled, bad = check_integrity(client)
    print(f"sampled {sampled} points, {len(bad)} bad vectors found")
    for pid, reason in bad[:10]:
        print(f"  {pid}: {reason}")

    print("\n=== Running full 100-query golden set retrieval ===")
    results = run_golden_set_retrieval(client)
    summary = summarize(results)

    print(f"\n{'='*50}")
    if bad:
        print(f"INTEGRITY: {len(bad)} bad vectors — FAIL")
    else:
        print(f"INTEGRITY: clean sample — OK")
    print(f"RETRIEVAL: Top-1 {summary['top1']:.1%} / Top-5 {summary['top5']:.1%}")


if __name__ == "__main__":
    main()
