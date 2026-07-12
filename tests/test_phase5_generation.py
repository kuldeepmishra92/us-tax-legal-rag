"""
Phase 5 gate: LLM answer generation + citations (Gemini via google-genai).

Run: pytest tests/test_phase5_generation.py -v

Two groups:
  - Pure-Python citation_validator unit tests (fast, deterministic, no API) —
    prove the hallucination guard itself catches fabricated/missing citations.
  - Real end-to-end generation tests (make live Gemini calls) — prove the
    actual pipeline produces grounded, cited answers and refuses out-of-corpus
    questions. Requires a working Gemini connection (Vertex AI or AI Studio,
    per .env) and Qdrant + Elasticsearch running.
"""
import csv
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(ROOT))

from legalrag.generation import citation_validator as cv

GOLDEN_SET = ROOT / "eval" / "golden_set.csv"


# ============ Pure-Python validator unit tests (fast, no API) ============

def _sources(n):
    return [{"marker": i, "doc": f"Doc {i}", "section": "S", "page": "1"} for i in range(1, n + 1)]

def test_validator_accepts_valid_citation():
    r = cv.validate("Maternity clothes are not deductible [1].", _sources(3))
    assert r["grounded"] and r["has_citation"] and not r["invalid_markers"]

def test_validator_flags_fabricated_citation():
    # cites [5] but only 3 sources were provided => fabricated
    r = cv.validate("The answer is yes [5].", _sources(3))
    assert not r["grounded"]
    assert 5 in r["invalid_markers"]

def test_validator_flags_uncited_substantive_answer():
    r = cv.validate("The standard deduction is $15,750.", _sources(3))
    assert not r["grounded"]      # substantive claim with zero citations
    assert not r["has_citation"]

def test_validator_accepts_proper_refusal():
    r = cv.validate("I could not find the answer in the provided legal sources.", _sources(3))
    assert r["grounded"] and r["is_refusal"]

def test_validator_multiple_citations():
    r = cv.validate("First point [1]. Second point [2][3].", _sources(3))
    assert r["used_markers"] == [1, 2, 3] and r["grounded"]

def test_validator_handles_comma_separated_markers():
    # LLMs commonly emit "[1, 5]" — must be parsed, not silently missed
    r = cv.validate("Personal jurisdiction exists [1, 3] when service is proper [2].", _sources(5))
    assert r["used_markers"] == [1, 2, 3] and r["grounded"]


# ============ Real end-to-end generation tests (live Gemini calls) ============

@pytest.fixture(scope="module")
def sample_queries():
    """A small spread of in-corpus golden-set queries (one per category) —
    kept small because each makes a live LLM call."""
    rows = list(csv.DictReader(open(GOLDEN_SET, encoding="utf-8")))
    picked, seen = [], set()
    for r in rows:
        if r["category"] not in seen and r["difficulty"] == "easy":
            picked.append(r)
            seen.add(r["category"])
        if len(seen) == 4:
            break
    return picked


@pytest.fixture(scope="module")
def llm():
    from legalrag.generation import llm_service
    return llm_service


@pytest.fixture(scope="module")
def answered(llm, sample_queries):
    """Answer each sample query once and reuse across assertions — each call is
    a live LLM round-trip (slower on gemini-2.5-pro), so we don't re-issue the
    same queries per test."""
    return [(row, llm.ask(row["sample_query"])) for row in sample_queries]


def test_in_corpus_answers_are_grounded_and_cited(answered):
    failures = []
    for row, r in answered:
        if not r["grounded"]:
            failures.append((row["category"], "not grounded", r["answer"][:80]))
        elif not r["validation"]["has_citation"]:
            failures.append((row["category"], "no citation", r["answer"][:80]))
        elif r["validation"]["invalid_markers"]:
            failures.append((row["category"], f"fabricated {r['validation']['invalid_markers']}", r["answer"][:80]))
    assert not failures, f"grounding/citation failures: {failures}"


def test_every_citation_resolves_to_a_real_retrieved_source(answered):
    """No answer may cite a source number that wasn't actually provided to it —
    the core anti-hallucination guarantee for legal citations."""
    for row, r in answered:
        provided_markers = {s["marker"] for s in r["sources"]}
        for c in r["citations"]:
            assert c["marker"] in provided_markers
            assert c["doc"] and c["page"]  # every citation carries doc + page


def test_out_of_corpus_question_is_refused_not_hallucinated(llm):
    r = llm.ask("What is the capital of France and the boiling point of water?")
    assert r["validation"]["is_refusal"], f"expected refusal, got: {r['answer'][:120]}"
    assert not r["validation"]["invalid_markers"]


def test_answer_contains_expected_ground_truth_fact(llm):
    """End-to-end faithfulness spot check: a factual query whose answer we know
    should surface the correct figure from the correct document."""
    r = llm.ask("According to the Standard Deduction Chart in IRS Publication 501, "
                "what is the 2025 standard deduction for a single filer?")
    assert "15,750" in r["answer"], f"expected $15,750 in answer, got: {r['answer'][:150]}"
    cited_docs = {c["doc"] for c in r["citations"]}
    assert any("501" in d for d in cited_docs), f"expected a Pub 501 citation, got {cited_docs}"
