"""
Phase 2 gate: vector indexing (bge-base-en-v1.5, local, + Qdrant).

Run: pytest tests/test_phase2_vector.py -v

Reads the real live Qdrant collection — not a mock — because the goal is
validating what actually got indexed, not a stand-in for it. Requires Qdrant
running (`docker compose --profile phase2 up -d`).
"""
import csv
import json
import random
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(ROOT))

from legalrag.ingestion import embed
from legalrag.indexing import vector_indexer as vi

PROCESSED_MANIFEST = ROOT / "processed_manifest.csv"
GOLDEN_SET = ROOT / "eval" / "golden_set.csv"


@pytest.fixture(scope="module")
def client():
    return vi.get_client()


@pytest.fixture(scope="module")
def expected_chunk_count():
    rows = list(csv.DictReader(open(PROCESSED_MANIFEST, encoding="utf-8")))
    return sum(int(r["chunk_count"]) for r in rows)


@pytest.fixture(scope="module")
def sanity_queries():
    """10 queries (2-3 per category), drawn from the hand-verified golden set
    rather than a separate hand-authored set — same reasoning as reusing it
    for Phase 4's benchmark: avoids duplicating query authoring."""
    rows = list(csv.DictReader(open(GOLDEN_SET, encoding="utf-8")))
    easy = [r for r in rows if r["difficulty"] == "easy"]
    random.seed(42)
    by_cat = {}
    for r in easy:
        by_cat.setdefault(r["category"], []).append(r)
    picked = []
    for cat, items in by_cat.items():
        picked.extend(random.sample(items, min(3, len(items))))
    return picked[:10]


def test_collection_exists(client):
    assert client.collection_exists(vi.COLLECTION_NAME)


def test_point_count_matches_chunk_count(client, expected_chunk_count):
    actual = vi.collection_point_count(client)
    assert actual == expected_chunk_count, f"{actual} points vs {expected_chunk_count} chunks"


def test_embedding_dimension_matches_model(client):
    info = client.get_collection(vi.COLLECTION_NAME)
    assert info.config.params.vectors.size == embed.EMBED_DIM


def test_sanity_queries_retrieve_expected_source_doc(client, sanity_queries):
    failures = []
    for row in sanity_queries:
        qvec = embed.embed_query(row["sample_query"])
        hits = client.query_points(collection_name=vi.COLLECTION_NAME, query=qvec, limit=5).points
        titles_in_top5 = [h.payload["title"] for h in hits]
        if row["source_document"] not in titles_in_top5:
            failures.append((row["sample_query"][:70], row["source_document"], titles_in_top5))
    assert not failures, f"queries that failed to retrieve expected doc in top-5: {failures}"


def test_no_degenerate_vectors(client):
    """Fast, no-API-call integrity check: a silently corrupted embedding call
    (e.g. a truncated/failed request that still returns 200) could produce
    zero or NaN vectors without raising an error during indexing — catch that
    here rather than trusting that 'no exception' means 'good embedding'."""
    import math
    points, _ = client.scroll(
        collection_name=vi.COLLECTION_NAME, limit=300, with_vectors=True, with_payload=False,
    )
    assert points, "no points returned to sample"
    bad = []
    for p in points:
        vec = p.vector
        if vec is None or len(vec) != embed.EMBED_DIM:
            bad.append((p.id, "wrong dimension or missing"))
        elif all(v == 0 for v in vec):
            bad.append((p.id, "all-zero vector"))
        elif any(math.isnan(v) or math.isinf(v) for v in vec):
            bad.append((p.id, "NaN/Inf in vector"))
    assert not bad, f"degenerate vectors found: {bad[:10]}"


def test_distinct_chunks_have_distinct_embeddings(client):
    """Sanity check against a broken embedding call that silently returns the
    same (e.g. cached/default) vector regardless of input text."""
    points, _ = client.scroll(
        collection_name=vi.COLLECTION_NAME, limit=50, with_vectors=True, with_payload=False,
    )
    vectors = [tuple(p.vector) for p in points]
    assert len(set(vectors)) == len(vectors), "found duplicate embeddings across distinct chunks"
