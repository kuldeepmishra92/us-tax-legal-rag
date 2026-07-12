"""
Golden set integrity checks (built ahead of Phase 8, for reuse in Phase 4's
retrieval benchmark). Validates structure and traceability, not semantic
correctness — every answer was hand-verified against source PDF text during
authoring; see eval/build_golden_set.py for the row-by-row sourcing.
"""
import csv
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GOLDEN_SET = ROOT / "eval" / "golden_set.csv"
MANIFEST = ROOT / "documents_manifest.csv"


@pytest.fixture(scope="module")
def golden_rows():
    return list(csv.DictReader(open(GOLDEN_SET, encoding="utf-8")))


@pytest.fixture(scope="module")
def manifest_titles():
    return {r["title"] for r in csv.DictReader(open(MANIFEST, encoding="utf-8"))}


def test_exactly_100_rows(golden_rows):
    assert len(golden_rows) == 100


def test_25_per_category(golden_rows):
    from collections import Counter
    counts = Counter(r["category"] for r in golden_rows)
    assert counts == {"acts": 25, "judgments": 25, "pov": 25, "tax": 25}


def test_no_duplicate_queries(golden_rows):
    queries = [r["sample_query"] for r in golden_rows]
    assert len(queries) == len(set(queries))


def test_every_source_document_traces_to_the_corpus(golden_rows, manifest_titles):
    bad = [r["source_document"] for r in golden_rows if r["source_document"] not in manifest_titles]
    assert not bad, f"source_document not found in documents_manifest.csv: {bad}"


def test_no_empty_fields(golden_rows):
    required = ["sample_query", "ground_truth_answer", "source_document", "category", "page_reference"]
    for r in golden_rows:
        for field in required:
            assert r[field].strip(), f"row with empty {field}: {r['sample_query'][:60]}"


def test_difficulty_values_are_valid(golden_rows):
    for r in golden_rows:
        assert r["difficulty"] in ("easy", "medium", "hard")
