#!/usr/bin/env python3
"""
build_vector_index.py — Phase 2 driver: embeds and indexes every chunk in
processed/*.json into Qdrant.

Local embeddings (BAAI/bge-large-en-v1.5 via embed.py) — no rate limits, no
pacing needed. Processes in outer batches of OUTER_BATCH_SIZE chunks for
progress visibility and resumability checkpoints; sentence-transformers
internally sub-batches each call for compute efficiency.
"""
import glob
import json
import sys
import time
from pathlib import Path

from legalrag import config
from legalrag.ingestion import embed
from legalrag.indexing import vector_indexer as vi

ROOT = config.PROJECT_ROOT
OUTER_BATCH_SIZE = 200

def load_all_chunks():
    chunks = []
    for f in sorted(glob.glob(str(ROOT / "processed" / "*.json"))):
        chunks.extend(json.loads(Path(f).read_text(encoding="utf-8")))
    return chunks

def already_indexed_chunk_ids(client):
    """For resumability: if interrupted, skip chunks already in Qdrant."""
    ids = set()
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=vi.COLLECTION_NAME, limit=1000, offset=offset,
            with_payload=["chunk_id"], with_vectors=False,
        )
        ids.update(p.payload["chunk_id"] for p in points)
        if offset is None:
            break
    return ids

def log(msg):
    print(msg, flush=True)

def main(force=False, resume=False, status_only=False):
    chunks = load_all_chunks()
    total_chunks_all = len(chunks)
    client = vi.get_client()

    exists = client.collection_exists(vi.COLLECTION_NAME)
    existing_count = vi.collection_point_count(client) if exists else 0

    if status_only:
        log(f"corpus: {total_chunks_all} chunks | indexed: {existing_count} "
            f"({'complete' if existing_count == total_chunks_all else 'incomplete'})")
        return

    if exists and existing_count > 0 and not force and not resume:
        log(f"collection '{vi.COLLECTION_NAME}' already has {existing_count}/{total_chunks_all} points.")
        log("refusing to overwrite existing embedding work without an explicit flag.")
        log("  --resume  : continue indexing only the chunks not yet in Qdrant")
        log("  --force   : wipe the collection and rebuild from scratch")
        log("  --status  : just report current state, do nothing")
        sys.exit(1)

    log(f"loaded {len(chunks)} chunks from processed/")
    vi.ensure_collection(client, recreate=force and not resume)

    if resume:
        done_ids = already_indexed_chunk_ids(client)
        chunks = [c for c in chunks if c["chunk_id"] not in done_ids]
        log(f"resuming: {len(done_ids)} already indexed, {len(chunks)} remaining")

    log(f"loading embedding model ({embed.MODEL_NAME})...")
    embed.get_model()  # trigger load now, so it's not hidden inside the first batch's timing
    log("model ready, starting embedding + indexing")

    t0 = time.time()
    done_chunks = 0
    for i in range(0, len(chunks), OUTER_BATCH_SIZE):
        batch = chunks[i:i + OUTER_BATCH_SIZE]
        texts = [c["text"] for c in batch]

        vecs = embed.embed_texts(texts, input_type="document")
        vi.upsert_chunks(client, batch, vecs)

        done_chunks += len(batch)
        elapsed = time.time() - t0
        pct = 100 * done_chunks / len(chunks) if chunks else 100
        rate = done_chunks / elapsed if elapsed > 0 else 0
        eta_min = (len(chunks) - done_chunks) / rate / 60 if rate > 0 else 0
        log(f"[{done_chunks}/{len(chunks)}] ({pct:.1f}%) | elapsed={elapsed/60:.1f}min | "
            f"rate={rate:.1f} chunks/s | ETA={eta_min:.1f}min")

    total_count = vi.collection_point_count(client)
    total_chunks_all = len(load_all_chunks())
    log(f"\nDONE in {(time.time()-t0)/60:.1f} min")
    log(f"  points in Qdrant: {total_count} | expected total: {total_chunks_all}")
    if total_count == total_chunks_all:
        log("  point count matches chunk count: OK")
    else:
        log(f"  MISMATCH: {total_count} vs {total_chunks_all} — may need another --resume pass")

if __name__ == "__main__":
    main(
        force="--force" in sys.argv,
        resume="--resume" in sys.argv,
        status_only="--status" in sys.argv,
    )
