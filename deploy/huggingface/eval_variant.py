#!/usr/bin/env python3
"""
eval_variant.py — run the 100-query golden set through the HF Space's server-less
pipeline (numpy vectors + rank_bm25 + networkx graph) with the SAME
gemini-2.5-pro generation, and write the same-schema dataset the main eval uses,
so results are directly comparable to eval/eval_dataset.jsonl.

Output: eval/eval_dataset_hf.jsonl  (resumable — skips queries already done)

Run from the repo root (main venv):
    ./venv/Scripts/python.exe deploy/huggingface/eval_variant.py
"""
import csv
import json
import sys
import time
from pathlib import Path

HF = Path(__file__).resolve().parent
sys.path.insert(0, str(HF))

from legalrag import config
from legalrag.generation import llm_service
from app import retrieval as local_hr

GOLDEN = config.PROJECT_ROOT / "eval" / "golden_set.csv"
OUT = config.PROJECT_ROOT / "eval" / "eval_dataset_hf.jsonl"


def already_done():
    if not OUT.exists():
        return set()
    return {json.loads(l)["user_input"] for l in OUT.read_text(encoding="utf-8").splitlines() if l.strip()}


def main(limit=None):
    rows = list(csv.DictReader(open(GOLDEN, encoding="utf-8")))
    if limit:
        rows = rows[:limit]
    done = already_done()
    f = open(OUT, "a", encoding="utf-8")
    t0 = time.time()
    for i, row in enumerate(rows, 1):
        q = row["sample_query"]
        if q in done:
            continue
        expected = row["source_document"]
        chunks = local_hr.hybrid_search(q, top_k=llm_service.DEFAULT_TOP_K)
        titles = [c["payload"]["title"] for c in chunks]
        rank = titles.index(expected) + 1 if expected in titles else None
        contexts = [c["payload"]["text"] for c in chunks]

        result = llm_service.generate_answer(q, chunks)
        val = result["validation"]
        rec = {
            "user_input": q,
            "response": result["answer"],
            "retrieved_contexts": contexts,
            "reference": row["ground_truth_answer"],
            "category": row["category"],
            "difficulty": row["difficulty"],
            "expected_doc": expected,
            "retrieval_rank": rank,
            "grounded": result["grounded"],
            "has_citation": val["has_citation"],
            "is_refusal": val["is_refusal"],
            "n_citations": len(result["citations"]),
        }
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        f.flush()
        print(f"[{i}/{len(rows)}] {row['category']:10} rank={rank} grounded={result['grounded']} "
              f"| {(time.time()-t0)/60:.1f}min", flush=True)
    f.close()
    print(f"\nDONE -> {OUT}")


if __name__ == "__main__":
    lim = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
    main(limit=lim)
