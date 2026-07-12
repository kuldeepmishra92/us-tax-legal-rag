"""
Phase 3 gate: keyword indexing (Elasticsearch BM25).

Run: pytest tests/test_phase3_keyword.py -v

Reads the real live Elasticsearch index — not a mock — same reasoning as
Phase 1/2: validating what actually got indexed, not a stand-in for it.
Requires Elasticsearch running (`docker compose --profile phase3 up -d`).
"""
import csv
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(ROOT))

from legalrag.indexing import es_indexer as esi

PROCESSED_MANIFEST = ROOT / "processed_manifest.csv"
GOLDEN_SET = ROOT / "eval" / "golden_set.csv"


@pytest.fixture(scope="module")
def client():
    return esi.get_client()


@pytest.fixture(scope="module")
def expected_chunk_count():
    rows = list(csv.DictReader(open(PROCESSED_MANIFEST, encoding="utf-8")))
    return sum(int(r["chunk_count"]) for r in rows)


@pytest.fixture(scope="module")
def golden_rows():
    return list(csv.DictReader(open(GOLDEN_SET, encoding="utf-8")))


def test_index_exists(client):
    assert client.indices.exists(index=esi.INDEX_NAME)


def test_doc_count_matches_chunk_count(client, expected_chunk_count):
    actual = esi.index_doc_count(client)
    assert actual == expected_chunk_count, f"{actual} docs vs {expected_chunk_count} chunks"


def test_exact_phrase_queries_find_correct_doc_and_page(client):
    """Pull real distinctive phrases straight from indexed chunks and confirm
    an exact-phrase search finds the exact same chunk/page — the core promise
    of BM25 keyword search for legal citation-grade precision."""
    # sample a spread of chunks directly from ES rather than reprocessing JSON
    resp = client.search(index=esi.INDEX_NAME, body={"query": {"match_all": {}}, "size": 15})
    hits = resp["hits"]["hits"]
    failures = []
    for h in hits:
        src = h["_source"]
        text = src["text"]
        # pick a distinctive ~8-word phrase from the middle of the chunk
        words = text.split()
        if len(words) < 12:
            continue
        mid = len(words) // 2
        phrase = " ".join(words[mid:mid + 8])
        phrase = re.sub(r'["\\]', "", phrase)
        if not phrase.strip():
            continue
        results = esi.search_phrase(client, phrase, size=3)
        found = any(r["_source"]["chunk_id"] == src["chunk_id"] for r in results)
        if not found:
            failures.append((src["chunk_id"], phrase[:60]))
    assert not failures, f"exact phrases that failed to retrieve their own chunk: {failures}"


def test_golden_set_keyword_retrieval_baseline(client, golden_rows):
    """Not every query is keyword-friendly (many are natural-language
    questions), but BM25 should still find the right document for a solid
    fraction — this is a baseline, not a bar. Phase 4's hybrid fusion is what
    combines this with vector search for the real accuracy target."""
    hits_top5 = 0
    for row in golden_rows:
        results = esi.search(client, row["sample_query"], size=5)
        titles = [r["_source"]["title"] for r in results]
        if row["source_document"] in titles:
            hits_top5 += 1
    accuracy = hits_top5 / len(golden_rows)
    print(f"\nBM25-only Top-5 accuracy on golden set: {accuracy:.1%}")
    assert accuracy > 0.10, f"BM25-only accuracy suspiciously low: {accuracy:.1%} — index may be broken"


def test_exact_legal_terminology_beats_natural_language_phrasing(client):
    """Validates BM25 is actually doing its job: a query using the EXACT
    statutory phrase should score at least as well as, and typically better
    than, a semantically-equivalent but differently-worded natural-language
    version — that's the whole point of keyword search existing alongside
    vector search."""
    exact = esi.search(client, "SEC. 8. MODIFICATIONS TO UNITED STATES CENTER FOR SAFESPORT", size=1)
    paraphrase = esi.search(client, "the part of the law about changing things at the safety sport center", size=1)
    assert exact, "exact statutory phrase query returned no results at all"
    if exact and paraphrase:
        assert exact[0]["_score"] >= paraphrase[0]["_score"] if paraphrase[0]["_score"] else True
