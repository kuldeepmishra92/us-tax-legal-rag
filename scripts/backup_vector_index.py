#!/usr/bin/env python3
"""
backup_vector_index.py — durable, portable backup of the Qdrant vector index.

The Docker named volume (qdrant_data) already persists data across container
restarts, but it's still a single point of failure — `docker compose down -v`,
volume corruption, or moving to a new machine would lose ~4 hours of
rate-limited embedding work. This takes a Qdrant snapshot (a self-contained
point-in-time export) and downloads it to backups/, independent of the volume.

Usage:
    python backup_vector_index.py            # create + download a snapshot
    python backup_vector_index.py --restore <snapshot_file>   # restore from one
"""
import sys
import time
from pathlib import Path

import requests

from legalrag import config
from legalrag.indexing import vector_indexer as vi

ROOT = config.PROJECT_ROOT
BACKUPS_DIR = ROOT / "backups"

def create_backup():
    import os
    host = os.environ.get("QDRANT_HOST", "localhost")
    port = os.environ.get("QDRANT_PORT", "6333")
    base = f"http://{host}:{port}"

    client = vi.get_client()
    if not client.collection_exists(vi.COLLECTION_NAME):
        print(f"collection '{vi.COLLECTION_NAME}' doesn't exist — nothing to back up")
        return None
    count = vi.collection_point_count(client)
    print(f"creating snapshot of '{vi.COLLECTION_NAME}' ({count} points)...")

    r = requests.post(f"{base}/collections/{vi.COLLECTION_NAME}/snapshots", timeout=120)
    r.raise_for_status()
    snapshot_name = r.json()["result"]["name"]
    print(f"snapshot created: {snapshot_name}")

    BACKUPS_DIR.mkdir(exist_ok=True)
    out_path = BACKUPS_DIR / snapshot_name
    with requests.get(f"{base}/collections/{vi.COLLECTION_NAME}/snapshots/{snapshot_name}",
                       stream=True, timeout=300) as resp:
        resp.raise_for_status()
        with open(out_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)

    size_mb = out_path.stat().st_size / 1024 / 1024
    print(f"downloaded to {out_path} ({size_mb:.1f} MB)")
    print(f"\nTo restore later: python backup_vector_index.py --restore {out_path.name}")
    return out_path

def restore_backup(snapshot_filename):
    import os
    host = os.environ.get("QDRANT_HOST", "localhost")
    port = os.environ.get("QDRANT_PORT", "6333")
    base = f"http://{host}:{port}"

    snapshot_path = BACKUPS_DIR / snapshot_filename
    if not snapshot_path.exists():
        print(f"backup file not found: {snapshot_path}")
        sys.exit(1)

    print(f"restoring '{vi.COLLECTION_NAME}' from {snapshot_path} ({snapshot_path.stat().st_size/1024/1024:.1f} MB)...")
    with open(snapshot_path, "rb") as f:
        r = requests.post(
            f"{base}/collections/{vi.COLLECTION_NAME}/snapshots/upload",
            files={"snapshot": f}, timeout=300,
        )
    r.raise_for_status()
    print("restore complete")

    client = vi.get_client()
    print(f"verifying: {vi.collection_point_count(client)} points now in collection")

if __name__ == "__main__":
    if "--restore" in sys.argv:
        idx = sys.argv.index("--restore")
        if idx + 1 >= len(sys.argv):
            print("usage: python backup_vector_index.py --restore <snapshot_filename>")
            sys.exit(1)
        restore_backup(sys.argv[idx + 1])
    else:
        create_backup()
