#!/usr/bin/env python3
"""
parity_check.py — verify the Space's server-less retrieval matches the main
system on the 100-query golden set.

Runs each golden query through BOTH:
  - main:  legalrag hybrid_retriever (Qdrant + Elasticsearch)   [services must be up]
  - local: app.retrieval hybrid_search (numpy vectors + rank_bm25)

and compares retrieval accuracy against the known correct source document
(rank of the expected title within top-12), plus top-1 agreement.

Run from repo root (main venv, services up):
    ./venv/Scripts/python.exe deploy/huggingface/parity_check.py
"""
import csv
import sys
from pathlib import Path

HF = Path(__file__).resolve().parent
sys.path.insert(0, str(HF))                       # so `app` package imports

from legalrag import config
from legalrag.retrieval import hybrid_retriever as main_hr
from app import retrieval as local_hr

TOP_K = 12
GOLDEN = config.PROJECT_ROOT / "eval" / "golden_set.csv"


def rank_of(chunks, expected_title):
    titles = [c["payload"]["title"] for c in chunks]
    return titles.index(expected_title) + 1 if expected_title in titles else None


def acc(ranks, n):
    top1 = sum(1 for r in ranks if r == 1) / n
    top5 = sum(1 for r in ranks if r and r <= 5) / n
    return top1, top5


def main():
    rows = list(csv.DictReader(open(GOLDEN, encoding="utf-8")))
    main_ranks, local_ranks = [], []
    top1_agree = 0
    regressions = []
    for i, row in enumerate(rows, 1):
        q, expected = row["sample_query"], row["source_document"]
        mc = main_hr.hybrid_search(q, top_k=TOP_K)
        lc = local_hr.hybrid_search(q, top_k=TOP_K)
        mr, lr = rank_of(mc, expected), rank_of(lc, expected)
        main_ranks.append(mr); local_ranks.append(lr)
        if mc and lc and mc[0]["payload"]["title"] == lc[0]["payload"]["title"]:
            top1_agree += 1
        # regression = main found expected in top-5 but local did not (or worse rank tier)
        m_ok5 = mr and mr <= 5
        l_ok5 = lr and lr <= 5
        if (m_ok5 and not l_ok5) or (mr == 1 and lr != 1):
            regressions.append((row["category"], q[:60], mr, lr))
        if i % 20 == 0:
            print(f"  ...{i}/100", flush=True)

    n = len(rows)
    m1, m5 = acc(main_ranks, n)
    l1, l5 = acc(local_ranks, n)
    print("\n=== RETRIEVAL PARITY (n=100) ===")
    print(f"  {'':14}{'Top-1':>8}{'Top-5':>8}")
    print(f"  {'main (Qdrant+ES)':14}{m1:>8.1%}{m5:>8.1%}")
    print(f"  {'local (npy+bm25)':14}{l1:>8.1%}{l5:>8.1%}")
    print(f"  top-1 doc agreement (local==main): {top1_agree}/{n} ({top1_agree/n:.0%})")
    print(f"\n  Top-1 delta: {l1-m1:+.1%}  |  Top-5 delta: {l5-m5:+.1%}")
    if regressions:
        print(f"\n  {len(regressions)} query(ies) where local ranked the correct doc worse:")
        for cat, q, mr, lr in regressions:
            print(f"    [{cat:10}] main_rank={mr} local_rank={lr}  {q}")
    else:
        print("\n  No regressions — local retrieval >= main on every query's correct-doc rank tier.")


if __name__ == "__main__":
    main()
