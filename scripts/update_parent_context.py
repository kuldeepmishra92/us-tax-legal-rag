#!/usr/bin/env python3
"""
update_parent_context.py — push the corrected parent_section_text into both
indexes WITHOUT re-embedding.

parent_section_text is not embedded (only `text` is), so fixing it needs no
new vectors. This script:
  1. Loads the regenerated processed/*.json
  2. Verifies every chunk's chunk_id AND text are unchanged vs. what's in
     Qdrant — the whole "no re-embed" correctness argument depends on this;
     if text drifted, the existing vectors would be stale and we'd have to
     re-embed after all. Aborts loudly if it drifted.
  3. Updates only the parent_section_text payload field in Qdrant (set_payload,
     vectors untouched)
  4. Re-indexes Elasticsearch from scratch (cheap, ~2s) so it carries the new
     parent field too
"""
import glob
import json
import sys
from pathlib import Path

from legalrag import config
from legalrag.indexing import vector_indexer as vi
from legalrag.indexing import es_indexer as esi
import build_keyword_index

ROOT = config.PROJECT_ROOT

def load_all_chunks():
    chunks = []
    for f in sorted(glob.glob(str(ROOT / "processed" / "*.json"))):
        chunks.extend(json.loads(Path(f).read_text(encoding="utf-8")))
    return chunks

def log(msg):
    print(msg, flush=True)

def verify_text_unchanged(client, chunks):
    """Pull chunk_id -> text from Qdrant and confirm it matches the new
    processed/ output exactly. If not, vectors are stale and this fast-path
    is invalid."""
    log("verifying chunk texts unchanged (guards the no-re-embed assumption)...")
    qdrant_texts = {}
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=vi.COLLECTION_NAME, limit=1000, offset=offset,
            with_payload=["chunk_id", "text"], with_vectors=False,
        )
        for p in points:
            qdrant_texts[p.payload["chunk_id"]] = p.payload["text"]
        if offset is None:
            break

    new_ids = {c["chunk_id"] for c in chunks}
    old_ids = set(qdrant_texts.keys())
    if new_ids != old_ids:
        only_new = list(new_ids - old_ids)[:5]
        only_old = list(old_ids - new_ids)[:5]
        log(f"  ABORT: chunk_id sets differ. new-only e.g. {only_new}, qdrant-only e.g. {only_old}")
        log("  Chunk boundaries changed — this needs a full re-embed, not a payload update.")
        return False

    drifted = [c["chunk_id"] for c in chunks if c["text"] != qdrant_texts.get(c["chunk_id"])]
    if drifted:
        log(f"  ABORT: {len(drifted)} chunks' text drifted, e.g. {drifted[:5]}")
        log("  Text changed — existing vectors are stale, needs a full re-embed.")
        return False

    log(f"  OK: all {len(chunks)} chunk_ids and texts identical — vectors remain valid.")
    return True

def update_qdrant_payloads(client, chunks):
    from qdrant_client.models import SetPayloadOperation  # noqa: F401 (import guard)
    log("updating Qdrant parent_section_text payloads (no vectors touched)...")
    BATCH = 500
    updated = 0
    for i in range(0, len(chunks), BATCH):
        batch = chunks[i:i + BATCH]
        for c in batch:
            pid = vi.chunk_id_to_point_id(c["chunk_id"])
            client.set_payload(
                collection_name=vi.COLLECTION_NAME,
                payload={"parent_section_text": c["parent_section_text"]},
                points=[pid],
            )
            updated += 1
        log(f"  ...{updated}/{len(chunks)}")
    log(f"  done: {updated} payloads updated")

def main():
    chunks = load_all_chunks()
    log(f"loaded {len(chunks)} chunks from regenerated processed/")

    vclient = vi.get_client()
    if not verify_text_unchanged(vclient, chunks):
        sys.exit(1)

    update_qdrant_payloads(vclient, chunks)

    log("\nre-indexing Elasticsearch (now includes parent_section_text)...")
    build_keyword_index.main(force=True)

    log("\nDONE — both indexes carry the corrected parent context.")

if __name__ == "__main__":
    main()
