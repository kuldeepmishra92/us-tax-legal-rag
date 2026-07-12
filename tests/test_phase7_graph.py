"""
Phase 7 gate: Graph RAG (citation graph in Neo4j).

Run: pytest tests/test_phase7_graph.py -v

Reads the real live Neo4j graph — not a mock. Requires Neo4j running
(`docker compose --profile phase7 up -d`) and the graph built
(`python graph_builder.py`). Uses title-based doc_id resolution rather than
hardcoded filename stems (some doc_ids differ from their titles due to Phase 1
title-extraction quirks — resolving by title keeps these tests robust).
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from legalrag.graph import graph_builder as gb
from legalrag.graph import graph_retriever as gr


@pytest.fixture(scope="module")
def counts():
    return gb.graph_counts()


def test_graph_populated_with_sane_counts(counts):
    # not near-zero (would mean extraction/build failed), not absurdly exploded
    assert counts["documents"] == 100
    assert 200 <= counts["authorities"] <= 20000, counts
    assert 500 <= counts["cites"] <= 50000, counts
    assert counts["references"] >= 5, "expected some resolved document->document cross-references"


def test_three_hand_verified_citation_pairs_exist():
    """Ground truth confirmed by reading the actual source documents:
      1. Seven County v. Eagle County (judgment) cites the Fiscal Responsibility
         Act of 2023 (that case turns on the Act's NEPA amendments).
      2. Riley v. Bondi (judgment) cites Parrish v. United States (judgment).
      3. Reforming Intelligence and Securing America Act cites 50 U.S.C. 1801
         (the FISA definitions section it amends)."""
    sc = gr.doc_id_by_title("SEVEN COUNTY")
    fra = gr.doc_id_by_title("Fiscal Responsibility Act")
    riley = gr.doc_id_by_title("RILEY v. BONDI")
    parrish = gr.doc_id_by_title("PARRISH")
    fisa = gr.doc_id_by_title("Reforming Intelligence")

    assert sc and fra and riley and parrish and fisa, "could not resolve one of the ground-truth doc titles"
    assert gr.edge_exists_reference(sc, fra), "Seven County -> Fiscal Responsibility Act edge missing"
    assert gr.edge_exists_reference(riley, parrish), "Riley -> Parrish edge missing"
    assert gr.document_cites_authority(fisa, "usc", "50 USC 1801"), "Reforming Intelligence -> 50 USC 1801 missing"


def test_relationship_query_which_judgments_cite_an_act():
    """The PRD's flagship relationship query — structurally impossible for pure
    vector/keyword search — answered by graph traversal."""
    results = gr.documents_referencing_title("Fiscal Responsibility Act", category="judgments")
    titles = [r["title"] for r in results]
    assert any("SEVEN COUNTY" in t for t in titles), f"expected Seven County among judgments citing the Act, got {titles}"
    # every returned doc must actually be a judgment (the category filter works)
    assert all(r["category"] == "judgments" for r in results)


def test_relationship_query_which_documents_cite_an_authority():
    """'Which documents cite the Clean Air Act?' — clusters docs by shared legal
    authority. Should surface the EPA/environmental judgments, not e.g. random
    tax pubs."""
    docs = gr.documents_citing("Clean Air Act")
    assert len(docs) >= 3, docs
    titles = " ".join(d["title"] for d in docs)
    assert "ENVIRONMENTAL PROTECTION AGENCY" in titles or "DIAMOND ALTERNATIVE" in titles


def test_relationship_query_routing():
    assert gr.is_relationship_query("which judgments cite the Fiscal Responsibility Act?")
    assert gr.is_relationship_query("what documents reference the Clean Air Act?")
    assert not gr.is_relationship_query("what is the standard deduction for a single filer?")


def test_context_enrichment_returns_neighbors():
    """Given a retrieved doc known to have cross-references, enrichment surfaces
    its graph neighborhood."""
    sc = gr.doc_id_by_title("SEVEN COUNTY")
    enr = gr.enrich_docs([sc])
    # Seven County references the Fiscal Responsibility Act — should appear as a
    # referenced neighbor, and/or it shares authorities with other docs
    assert "referenced_documents" in enr and "shared_authorities" in enr
    ref_titles = [d["title"] for d in enr["referenced_documents"]]
    assert any("Fiscal Responsibility" in t for t in ref_titles) or enr["shared_authorities"]
