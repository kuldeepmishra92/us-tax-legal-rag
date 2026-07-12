#!/usr/bin/env python3
"""
build_keyword_index.py — Phase 3 driver: indexes every chunk in
processed/*.json into Elasticsearch for BM25 keyword search.
"""
import glob
import json
import sys
import time
from pathlib import Path

from legalrag import config
from legalrag.indexing import es_indexer as esi

ROOT = config.PROJECT_ROOT

def load_all_chunks():
    chunks = []
    for f in sorted(glob.glob(str(ROOT / "processed" / "*.json"))):
        chunks.extend(json.loads(Path(f).read_text(encoding="utf-8")))
    return chunks

def log(msg):
    print(msg, flush=True)

def main(force=False, status_only=False):
    chunks = load_all_chunks()
    client = esi.get_client()

    exists = client.indices.exists(index=esi.INDEX_NAME)
    existing_count = esi.index_doc_count(client) if exists else 0

    if status_only:
        log(f"corpus: {len(chunks)} chunks | indexed: {existing_count} "
            f"({'complete' if existing_count == len(chunks) else 'incomplete'})")
        return

    if exists and existing_count > 0 and not force:
        log(f"index '{esi.INDEX_NAME}' already has {existing_count}/{len(chunks)} docs.")
        log("refusing to overwrite without --force.")
        sys.exit(1)

    log(f"loaded {len(chunks)} chunks from processed/")
    esi.ensure_index(client, recreate=force)

    t0 = time.time()
    success, errors = esi.index_chunks(client, chunks)
    elapsed = time.time() - t0

    count = esi.index_doc_count(client)
    log(f"DONE in {elapsed:.1f}s")
    log(f"  bulk success: {success} | errors: {len(errors)}")
    log(f"  docs in ES: {count} | expected: {len(chunks)}")
    if errors:
        log(f"  first few errors: {errors[:3]}")
    if count == len(chunks):
        log("  doc count matches chunk count: OK")
    else:
        log(f"  MISMATCH: {count} vs {len(chunks)}")

if __name__ == "__main__":
    main(force="--force" in sys.argv, status_only="--status" in sys.argv)
