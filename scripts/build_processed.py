#!/usr/bin/env python3
"""
build_processed.py — Phase 1 driver: runs parser.py + chunker.py over the full
100-doc corpus (documents_manifest.csv) and writes the OKF-normalized output:

  processed/<doc_id>.json     — one file per document, list of chunk dicts
  processed_manifest.csv      — per-document summary (chunk counts, tables, images)
"""
import csv
import json
import time
from pathlib import Path

from legalrag import config
from legalrag.ingestion import chunker as c

ROOT = config.PROJECT_ROOT
PROCESSED = ROOT / "processed"

def main():
    PROCESSED.mkdir(exist_ok=True)
    rows = list(csv.DictReader(open(ROOT / "documents_manifest.csv", encoding="utf-8")))
    summary = []
    errors = []
    t0 = time.time()

    for i, r in enumerate(rows, 1):
        doc_id = Path(r["local_path"]).stem
        try:
            chunks, meta = c.build_chunks_for_document(
                r["local_path"], doc_id, r["title"], r["category"], r["source_org"], r["url"]
            )
        except Exception as e:
            errors.append((r["local_path"], str(e)[:150]))
            print(f"[{i}/{len(rows)}] ERROR {r['local_path']}: {e}")
            continue

        out_path = PROCESSED / f"{doc_id}.json"
        out_path.write_text(json.dumps(chunks, indent=1, ensure_ascii=False), encoding="utf-8")

        prose = [ch for ch in chunks if ch["chunk_type"] == "prose"]
        tables = [ch for ch in chunks if ch["chunk_type"] == "table"]
        total_tokens = sum(ch["token_count"] for ch in chunks)
        summary.append({
            "doc_id": doc_id, "title": r["title"], "category": r["category"],
            "pages": meta["pages"], "images_not_indexed": meta["images_not_indexed"],
            "chunk_count": len(chunks), "prose_chunks": len(prose), "table_chunks": len(tables),
            "total_tokens": total_tokens,
            "avg_prose_tokens": round(sum(ch["token_count"] for ch in prose) / len(prose)) if prose else 0,
            "max_chunk_tokens": max((ch["token_count"] for ch in chunks), default=0),
            "processed_path": str(out_path.relative_to(ROOT)),
        })
        print(f"[{i}/{len(rows)}] {r['category']:10} {len(chunks):4} chunks  {r['title'][:55]}")

    with open(ROOT / "processed_manifest.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(summary[0].keys()) if summary else [])
        w.writeheader()
        w.writerows(summary)

    print(f"\n{'='*50}")
    print(f"DONE in {int(time.time()-t0)}s")
    print(f"  documents processed: {len(summary)}/{len(rows)}")
    print(f"  errors: {len(errors)}")
    for e in errors:
        print(f"    {e}")
    if summary:
        print(f"  total chunks: {sum(s['chunk_count'] for s in summary)}")
        print(f"  total tokens: {sum(s['total_tokens'] for s in summary)}")

if __name__ == "__main__":
    main()
