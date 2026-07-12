"""
Phase 1 gate: document parsing & chunking (OKF normalization).

Run: pytest tests/test_phase1_parsing.py -v

Reads real pipeline output (processed/*.json, processed_manifest.csv) — not
mocked fixtures — because the goal is validating what the parser/chunker
actually produced on the real 100-doc corpus, not a stand-in for it.
"""
import csv
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PROCESSED = ROOT / "processed"
MANIFEST = ROOT / "documents_manifest.csv"
PROCESSED_MANIFEST = ROOT / "processed_manifest.csv"

# Confirmed during parser development: rare PDF font-embedding defects (undecodable
# ligature glyphs) can leak a broken word into body text. Documented limitation,
# not a hard failure — but any NEW boilerplate strings leaking through IS a failure.
KNOWN_BOILERPLATE_STRINGS = [
    "Page Proof Pending Publication",
    "typographical or other formal errors",
]

HARD_TOKEN_CEILING = 1200  # chunker._HARD_CEILING


@pytest.fixture(scope="module")
def manifest_rows():
    return list(csv.DictReader(open(MANIFEST, encoding="utf-8")))


@pytest.fixture(scope="module")
def processed_rows():
    assert PROCESSED_MANIFEST.exists(), "processed_manifest.csv missing — run build_processed.py first"
    return list(csv.DictReader(open(PROCESSED_MANIFEST, encoding="utf-8")))


@pytest.fixture(scope="module")
def all_chunks(processed_rows):
    chunks = []
    for r in processed_rows:
        path = ROOT / r["processed_path"]
        chunks.extend(json.loads(path.read_text(encoding="utf-8")))
    return chunks


def test_all_100_docs_processed(manifest_rows, processed_rows):
    assert len(processed_rows) == len(manifest_rows) == 100


def test_every_doc_produced_at_least_one_chunk(processed_rows):
    zero_chunk_docs = [r["doc_id"] for r in processed_rows if int(r["chunk_count"]) == 0]
    assert not zero_chunk_docs, f"docs with zero chunks: {zero_chunk_docs}"


def test_no_empty_or_near_empty_chunks(all_chunks):
    bad = [c["chunk_id"] for c in all_chunks if len(c["text"].strip()) < 10]
    assert not bad, f"near-empty chunks: {bad[:10]}"


def test_every_chunk_has_required_metadata(all_chunks):
    required = ["chunk_id", "doc_id", "title", "category", "section_title",
                "chunk_type", "page_start", "page_end", "text", "parent_section_text"]
    for c in all_chunks:
        for field in required:
            assert field in c and c[field] not in (None, ""), f"{c.get('chunk_id')} missing {field}"


def test_page_numbers_are_valid(all_chunks):
    for c in all_chunks:
        assert isinstance(c["page_start"], int) and c["page_start"] >= 1
        assert isinstance(c["page_end"], int) and c["page_end"] >= c["page_start"]


def test_no_chunk_exceeds_hard_token_ceiling(all_chunks):
    over = [(c["chunk_id"], c["token_count"]) for c in all_chunks if c["token_count"] > HARD_TOKEN_CEILING]
    assert not over, f"chunks over hard ceiling: {over}"


def test_word_count_roughly_matches_source_manifest(manifest_rows, processed_rows):
    """Catches silent text-loss bugs: total extracted words shouldn't drift far
    from the word count already recorded when the corpus was built."""
    by_id = {Path(r["local_path"]).stem: r for r in manifest_rows}
    drift_failures = []
    for r in processed_rows:
        src = by_id.get(r["doc_id"])
        if not src:
            continue
        src_words = int(src["words"])
        # processed token_count isn't word count; approximate word count from chunks
        path = ROOT / r["processed_path"]
        chunks = json.loads(path.read_text(encoding="utf-8"))
        extracted_words = sum(len(c["text"].split()) for c in chunks if c["chunk_type"] == "prose")
        if src_words == 0:
            continue
        ratio = extracted_words / src_words
        # allow generous band: header/footer/watermark stripping legitimately removes
        # text, table markdown isn't counted here, footnotes may shift the count
        if not (0.4 <= ratio <= 1.3):
            drift_failures.append((r["doc_id"], src_words, extracted_words, round(ratio, 2)))
    assert not drift_failures, f"word count drift outside expected band: {drift_failures}"


def test_no_known_boilerplate_leaks_into_chunks(all_chunks):
    for c in all_chunks:
        for bp in KNOWN_BOILERPLATE_STRINGS:
            assert bp not in c["text"], f"{c['chunk_id']} leaked boilerplate: {bp!r}"


def test_tables_detected_in_tax_category(processed_rows):
    tax_table_chunks = sum(int(r["table_chunks"]) for r in processed_rows if r["category"] == "tax")
    assert tax_table_chunks > 0, "expected at least some tables detected across Tax Documents"


def test_all_four_categories_present(processed_rows):
    cats = {r["category"] for r in processed_rows}
    assert cats == {"acts", "judgments", "pov", "tax"}


def test_category_doc_counts_match_corpus_split(processed_rows):
    from collections import Counter
    counts = Counter(r["category"] for r in processed_rows)
    assert counts == {"acts": 30, "judgments": 30, "pov": 30, "tax": 10}


def test_acts_section_titles_are_not_inline_citations(all_chunks):
    """Regression test: 'SEC. NNN of title NN, United States Code, is amended'
    is an inline U.S. Code citation, not a real section heading, even though it
    matches the same SEC./CHAPTER-prefixed-number pattern as a real heading.
    Confirmed real bug: 13 chunks in one Act got mislabeled under a citation
    fragment as their section, losing the real 'SEC. 7' attribution entirely."""
    import re
    citation_pattern = re.compile(
        r"^\s*(sec(?:tion)?|chapter|title|article)\.?\s*[\dIVXLCa-zA-Z]+\.?\s*(?:\([a-zA-Z0-9]+\))*\s*(of|is|shall|and|or)\b",
        re.I,
    )
    bad = [c["chunk_id"] for c in all_chunks
           if c["category"] == "acts" and citation_pattern.match(c["section_title"])]
    assert not bad, f"chunks with a citation fragment as section_title: {bad[:10]}"


def test_section_titles_not_all_generic_introduction(processed_rows, all_chunks):
    """Sanity check that section-boundary detection is actually doing something,
    not just dumping every chunk under the fallback 'Introduction' title."""
    for r in processed_rows:
        path = ROOT / r["processed_path"]
        chunks = json.loads(path.read_text(encoding="utf-8"))
        titles = {c["section_title"] for c in chunks}
        if len(chunks) > 5:
            assert len(titles) > 1, f"{r['doc_id']}: all {len(chunks)} chunks share one section title"
