#!/usr/bin/env python3
"""
graph_retriever.py — Phase 7 Graph RAG query layer over the Neo4j citation graph.

Two usage modes (per the plan):
  1. Relationship-style questions ("which judgments cite the Fiscal
     Responsibility Act?", "which documents reference the Clean Air Act?") are
     answered by Cypher traversal — something pure vector/keyword search
     structurally cannot do.
  2. Context enrichment: given the docs behind a set of retrieved chunks, surface
     their 1-hop graph neighbors (referenced corpus docs + shared authorities)
     so the LLM/answer layer can see cross-document relationships.
"""
import os
import re

from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

_driver = None

def get_driver():
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(
            os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
            auth=(os.environ.get("NEO4J_USER", "neo4j"), os.environ.get("NEO4J_PASSWORD", "changeme_local_dev")),
        )
    return _driver

# ---------------- authority lookup ----------------
def find_authorities(query, limit=8):
    """Fuzzy-match a free-text reference (e.g. 'Clean Air Act', '42 USC 4321',
    'Fiscal Responsibility Act') against Authority node ids."""
    q = re.sub(r"\s+", " ", query).strip().lower()
    with get_driver().session() as s:
        rows = s.run(
            """MATCH (a:Authority)
               WHERE toLower(a.id) CONTAINS $q
               OPTIONAL MATCH (d:Document)-[:CITES]->(a)
               RETURN a.kind AS kind, a.id AS id, count(d) AS doc_count
               ORDER BY doc_count DESC LIMIT $lim""",
            q=q, lim=limit,
        )
        return [dict(r) for r in rows]

def documents_citing(authority_query, category=None, limit=25):
    """Which corpus documents cite an authority matching the query text?
    Optionally restrict the citing docs to a category (e.g. only judgments)."""
    q = re.sub(r"\s+", " ", authority_query).strip().lower()
    cat_clause = "AND d.category = $cat" if category else ""
    with get_driver().session() as s:
        rows = s.run(
            f"""MATCH (d:Document)-[:CITES]->(a:Authority)
                WHERE toLower(a.id) CONTAINS $q {cat_clause}
                RETURN DISTINCT d.doc_id AS doc_id, d.title AS title, d.category AS category
                ORDER BY category, title LIMIT $lim""",
            q=q, cat=category, lim=limit,
        )
        return [dict(r) for r in rows]

# ---------------- document<->document references ----------------
def references_from(doc_id):
    """Corpus documents that this document cites (outgoing REFERENCES)."""
    with get_driver().session() as s:
        rows = s.run(
            """MATCH (d:Document {doc_id:$id})-[:REFERENCES]->(x:Document)
               RETURN x.doc_id AS doc_id, x.title AS title, x.category AS category""",
            id=doc_id,
        )
        return [dict(r) for r in rows]

def references_to(doc_id):
    """Corpus documents that cite this document (incoming REFERENCES)."""
    with get_driver().session() as s:
        rows = s.run(
            """MATCH (x:Document)-[:REFERENCES]->(d:Document {doc_id:$id})
               RETURN x.doc_id AS doc_id, x.title AS title, x.category AS category""",
            id=doc_id,
        )
        return [dict(r) for r in rows]

def documents_referencing_title(title_query, category=None, limit=25):
    """'Which [judgments] cite <corpus document Y>?' — the PRD's flagship
    relationship query. Resolves Y by title, then follows incoming REFERENCES
    edges (which capture BOTH name-based and Public-Law-number-based citation
    resolution, so e.g. a judgment citing 'PL 118-5' still counts as citing the
    Fiscal Responsibility Act). Optionally restrict the citing docs by category."""
    q = re.sub(r"\s+", " ", title_query).strip().lower()
    cat_clause = "AND x.category = $cat" if category else ""
    with get_driver().session() as s:
        rows = s.run(
            f"""MATCH (x:Document)-[:REFERENCES]->(y:Document)
                WHERE toLower(y.title) CONTAINS $q {cat_clause}
                RETURN DISTINCT x.doc_id AS doc_id, x.title AS title, x.category AS category,
                       y.title AS target
                ORDER BY category, title LIMIT $lim""",
            q=q, cat=category, lim=limit,
        )
        return [dict(r) for r in rows]

def doc_id_by_title(title_query):
    q = re.sub(r"\s+", " ", title_query).strip().lower()
    with get_driver().session() as s:
        r = s.run(
            "MATCH (d:Document) WHERE toLower(d.title) CONTAINS $q RETURN d.doc_id AS id LIMIT 1",
            q=q,
        ).single()
        return r["id"] if r else None

def edge_exists_reference(src_doc_id, dst_doc_id):
    with get_driver().session() as s:
        r = s.run(
            """MATCH (:Document {doc_id:$src})-[:REFERENCES]->(:Document {doc_id:$dst})
               RETURN count(*) AS n""", src=src_doc_id, dst=dst_doc_id,
        ).single()
        return r["n"] > 0

def document_cites_authority(doc_id, kind, ident):
    with get_driver().session() as s:
        r = s.run(
            """MATCH (:Document {doc_id:$id})-[:CITES]->(a:Authority {kind:$k, id:$i})
               RETURN count(*) AS n""", id=doc_id, k=kind, i=ident,
        ).single()
        return r["n"] > 0

# ---------------- context enrichment ----------------
def enrich_docs(doc_ids, max_neighbors=5):
    """For a set of retrieved docs, return their graph neighborhood: referenced
    corpus docs + the shared authorities they cite. Feeds cross-document context
    into the answer layer."""
    with get_driver().session() as s:
        refs = s.run(
            """MATCH (d:Document)-[:REFERENCES]-(x:Document)
               WHERE d.doc_id IN $ids AND NOT x.doc_id IN $ids
               RETURN DISTINCT x.doc_id AS doc_id, x.title AS title, x.category AS category
               LIMIT $lim""", ids=list(doc_ids), lim=max_neighbors,
        )
        shared = s.run(
            """MATCH (d:Document)-[:CITES]->(a:Authority)
               WHERE d.doc_id IN $ids
               WITH a, count(DISTINCT d) AS c WHERE c > 1
               RETURN a.kind AS kind, a.id AS id, c AS shared_by ORDER BY c DESC LIMIT $lim""",
            ids=list(doc_ids), lim=max_neighbors,
        )
        return {"referenced_documents": [dict(r) for r in refs],
                "shared_authorities": [dict(r) for r in shared]}

# ---------------- relationship-query routing ----------------
_REL_PATTERNS = [
    r"which\s+(judgments?|cases?|acts?|documents?|reports?)\s+.*\b(cite|cites|reference|references|mention|discuss)",
    r"what\s+(documents?|cases?|judgments?|acts?)\s+.*\b(cite|reference|mention)",
    r"\b(cites?|references?)\b.*\b(act|code|u\.?s\.?c|law)\b",
]

def is_relationship_query(query):
    q = query.lower()
    return any(re.search(p, q) for p in _REL_PATTERNS)
