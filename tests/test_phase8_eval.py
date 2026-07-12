"""
Phase 8 gate: evaluation harness.

Run: pytest tests/test_phase8_eval.py -v

Validates the eval pipeline end-to-end without crashing and checks output
schemas. Most checks read the already-generated eval/eval_dataset.jsonl
(deterministic); one light check runs the generator on a single query to
confirm the produce-a-record path still works.
"""
import csv
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DATASET = ROOT / "eval" / "eval_dataset.jsonl"
GOLDEN = ROOT / "eval" / "golden_set.csv"
REQUIRED_FIELDS = {"user_input", "response", "retrieved_contexts", "reference",
                   "category", "difficulty", "expected_doc", "retrieval_rank",
                   "grounded", "has_citation", "is_refusal", "n_citations"}


@pytest.fixture(scope="module")
def dataset():
    assert DATASET.exists(), "eval_dataset.jsonl missing — run eval/run_eval.py first"
    return [json.loads(l) for l in DATASET.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_dataset_covers_full_golden_set(dataset):
    golden = list(csv.DictReader(open(GOLDEN, encoding="utf-8")))
    assert len(dataset) == len(golden) == 100


def test_every_record_has_ragas_ready_schema(dataset):
    for r in dataset:
        assert REQUIRED_FIELDS <= set(r), f"missing fields: {REQUIRED_FIELDS - set(r)}"
        assert isinstance(r["retrieved_contexts"], list) and r["retrieved_contexts"]
        assert r["response"] and r["reference"] and r["user_input"]


def test_retrieval_accuracy_meets_bar(dataset):
    n = len(dataset)
    top5 = sum(1 for r in dataset if r["retrieval_rank"] and r["retrieval_rank"] <= 5) / n
    assert top5 >= 0.90, f"end-to-end Top-5 retrieval accuracy {top5:.1%} below bar"


def test_generation_is_grounded(dataset):
    n = len(dataset)
    grounded = sum(1 for r in dataset if r["grounded"]) / n
    # every answer should be grounded (cited) or a proper refusal
    assert grounded >= 0.95, f"grounded rate {grounded:.1%} below bar"


def test_generator_produces_valid_record_for_one_query():
    """Light end-to-end smoke: the generation path still yields a well-formed
    record (1 live LLM call)."""
    from legalrag.retrieval import hybrid_retriever as hr
    from legalrag.generation import llm_service
    q = "What is the 2025 standard deduction for a single filer?"
    chunks = hr.hybrid_search(q, top_k=llm_service.DEFAULT_TOP_K)
    assert chunks
    result = llm_service.generate_answer(q, chunks)
    assert result["answer"]
    assert "grounded" in result and "citations" in result
