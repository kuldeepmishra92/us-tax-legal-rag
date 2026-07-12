#!/usr/bin/env python3
"""
run_eval.py — Phase 8 Step 1: generate the evaluation dataset.

Runs every golden-set query through the COMPLETE system (hybrid retrieval +
grounded gemini-2.5-pro generation + citation validation) and dumps, per query,
everything RAGAS needs to score plus our own deterministic retrieval metric:

  eval/eval_dataset.jsonl  — one JSON object per line:
    {
      "user_input":         the question,
      "response":           the generated answer,
      "retrieved_contexts": [chunk texts fed to the LLM],
      "reference":          the hand-verified golden ground-truth answer,
      # extras for our own analysis / the report:
      "category", "difficulty", "expected_doc",
      "retrieval_rank",     # rank of the correct source doc in retrieval (deterministic)
      "grounded", "has_citation", "is_refusal", "n_citations"
    }

This runs in the MAIN venv (google-genai only — no ragas/langchain), so
generation never depends on the RAGAS stack. eval/ragas_score.py then scores
this file. Resumable: re-running skips queries already in the output.
"""
import csv
import json
import sys
import time
from pathlib import Path

from legalrag.retrieval import hybrid_retriever as hr
from legalrag.generation import llm_service

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "eval" / "golden_set.csv"
OUT = ROOT / "eval" / "eval_dataset.jsonl"

def already_done():
    if not OUT.exists():
        return set()
    done = set()
    for line in OUT.read_text(encoding="utf-8").splitlines():
        if line.strip():
            done.add(json.loads(line)["user_input"])
    return done

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

        chunks = hr.hybrid_search(q, top_k=llm_service.DEFAULT_TOP_K)
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
        el = (time.time() - t0) / 60
        print(f"[{i}/{len(rows)}] {row['category']:10} rank={rank} grounded={result['grounded']} | {el:.1f}min", flush=True)
    f.close()
    print(f"\nDONE in {(time.time()-t0)/60:.1f} min -> {OUT}")

if __name__ == "__main__":
    lim = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
    main(limit=lim)
