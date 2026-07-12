#!/usr/bin/env python3
"""
sample_candidates.py — pulls a diverse spread of real chunks across the corpus
to serve as source material for hand-authoring golden-set Q&A pairs.

Every ground-truth answer in the golden set must be verifiable against actual
extracted text, not general knowledge — this script's only job is surfacing
good, well-formed candidate chunks (reasonable length, spread across many
distinct documents, not clustered in a few) for a human/agent to read and turn
into real question/answer pairs.
"""
import json
import random
import csv
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
PROCESSED = ROOT / "processed"

random.seed(7)

QUERIES_PER_CATEGORY = 25
CANDIDATES_PER_CATEGORY = 60  # oversample so the author can pick the best ones

def load_all_chunks():
    rows = list(csv.DictReader(open(ROOT / "processed_manifest.csv", encoding="utf-8")))
    by_cat = defaultdict(list)
    for r in rows:
        chunks = json.loads((ROOT / r["processed_path"]).read_text(encoding="utf-8"))
        by_cat[r["category"]].append((r["doc_id"], r["title"], chunks))
    return by_cat

def good_prose_chunks(chunks):
    return [c for c in chunks if c["chunk_type"] == "prose" and 80 <= c["token_count"] <= 500]

def good_table_chunks(chunks):
    return [c for c in chunks if c["chunk_type"] == "table" and c["token_count"] <= 400]

def main():
    by_cat = load_all_chunks()
    out = {}
    for cat, docs in by_cat.items():
        random.shuffle(docs)
        candidates = []
        # spread across as many distinct docs as possible: 1-2 candidates per doc
        per_doc = 2 if cat != "tax" else 4  # tax has only 10 docs, needs more per doc
        for doc_id, title, chunks in docs:
            prose = good_prose_chunks(chunks)
            tables = good_table_chunks(chunks) if cat == "tax" else []
            random.shuffle(prose)
            random.shuffle(tables)
            picks = prose[:max(1, per_doc - 1)] + tables[:1]
            for c in picks:
                candidates.append({
                    "doc_id": doc_id, "title": title, "chunk_id": c["chunk_id"],
                    "chunk_type": c["chunk_type"], "page_start": c["page_start"],
                    "page_end": c["page_end"], "section_title": c["section_title"],
                    "text": c["text"],
                })
            if len(candidates) >= CANDIDATES_PER_CATEGORY:
                break
        out[cat] = candidates[:CANDIDATES_PER_CATEGORY]
        print(f"{cat}: {len(out[cat])} candidates from {len(set(c['doc_id'] for c in out[cat]))} distinct docs")

    (ROOT / "eval" / "candidates.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print("\nwrote eval/candidates.json")

if __name__ == "__main__":
    main()
