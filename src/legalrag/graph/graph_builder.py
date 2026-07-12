#!/usr/bin/env python3
"""
graph_builder.py — Phase 7 Graph RAG: build the citation graph in Neo4j.

Graph shape:
  (:Document {doc_id, title, category})
  (:Authority {kind, id})            -- a cited legal reference (usc/public_law/named_act/case)
  (:Document)-[:CITES {kind}]->(:Authority)
  (:Document)-[:REFERENCES]->(:Document)   -- when a cited Authority resolves to
                                              one of our own 100 corpus documents

The REFERENCES edges are what make the PRD's flagship queries answerable
("which Court Judgment cites a particular Act"): we resolve a citation back to a
corpus doc three ways —
  - Public Law number  -> the Act doc whose GovInfo URL is that PLAW id
  - Named Act title    -> the Act doc whose title contains that act name
  - Case name          -> the Judgment doc whose title is that "X v. Y"
"""
import csv
import glob
import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

from legalrag import config
from legalrag.graph import citation_extractor as ce

load_dotenv()
ROOT = config.PROJECT_ROOT

def get_driver():
    return GraphDatabase.driver(
        os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        auth=(os.environ.get("NEO4J_USER", "neo4j"), os.environ.get("NEO4J_PASSWORD", "changeme_local_dev")),
    )

# ---------------- resolution index (authority -> corpus doc) ----------------
def _norm_case(s):
    s = re.sub(r"\s+", " ", s).lower()
    s = re.sub(r"\bet al\.?\b", "", s)
    s = re.sub(r"[^\w\s.]", "", s)
    return re.sub(r"\s+", " ", s).strip()

def _norm_act(s):
    return re.sub(r"\s+", " ", s).lower().strip()

def build_resolution_index():
    """Return dicts mapping a normalized authority identifier -> corpus doc_id."""
    manifest = list(csv.DictReader(open(ROOT / "documents_manifest.csv", encoding="utf-8")))
    pl_to_doc, act_name_to_doc, case_to_doc = {}, {}, {}
    for r in manifest:
        doc_id = Path(r["local_path"]).stem
        cat = r["category"]
        if cat == "acts":
            m = re.search(r"PLAW-(\d+)publ(\d+)", r["url"])
            if m:
                pl_to_doc[f"pl {m.group(1)}-{m.group(2)}"] = doc_id
            # the act's title often IS its short name (e.g. "Save Our Seas 2.0 Act")
            act_name_to_doc[_norm_act(r["title"])] = doc_id
        elif cat == "judgments":
            case_to_doc[_norm_case(r["title"])] = doc_id
    return pl_to_doc, act_name_to_doc, case_to_doc

def resolve_authority(kind, identifier, pl_to_doc, act_name_to_doc, case_to_doc):
    """Return the corpus doc_id this citation refers to, or None."""
    if kind == "public_law":
        return pl_to_doc.get(identifier.lower())
    if kind == "named_act":
        key = _norm_act(identifier)
        if key in act_name_to_doc:
            return act_name_to_doc[key]
        # also try matching act name as a substring of a doc title (title may carry a year)
        for name, did in act_name_to_doc.items():
            if key in name or name in key:
                return did
        return None
    if kind == "case":
        return case_to_doc.get(_norm_case(identifier))
    return None

# ---------------- build ----------------
def load_docs():
    docs = []
    for f in sorted(glob.glob(str(ROOT / "processed" / "*.json"))):
        chunks = json.loads(Path(f).read_text(encoding="utf-8"))
        if chunks:
            docs.append(chunks)
    return docs

def build_graph(wipe=True):
    driver = get_driver()
    pl_to_doc, act_name_to_doc, case_to_doc = build_resolution_index()
    docs = load_docs()

    with driver.session() as s:
        if wipe:
            s.run("MATCH (n) DETACH DELETE n")
        s.run("CREATE CONSTRAINT doc_id IF NOT EXISTS FOR (d:Document) REQUIRE d.doc_id IS UNIQUE")
        # composite NODE KEY needs Neo4j Enterprise; on Community, MERGE on
        # (kind,id) dedupes correctly on its own. A single-property index keeps
        # the Authority MERGEs fast without needing a composite key.
        s.run("CREATE INDEX auth_kind_id IF NOT EXISTS FOR (a:Authority) ON (a.kind, a.id)")

        # Pass 1: create ALL Document nodes up front. REFERENCES edges below use
        # MATCH on both endpoints, so if a citation's target document hasn't been
        # created yet (it appears later in load order) the edge would be silently
        # dropped. Creating every Document node first guarantees every resolved
        # reference is captured (fixes ~10 lost doc->doc references).
        extracted = []
        for chunks in docs:
            meta, cites = ce.extract_for_document(chunks)
            extracted.append((meta, cites))
            s.run("MERGE (d:Document {doc_id:$id}) SET d.title=$t, d.category=$c",
                  id=meta["doc_id"], t=meta["title"], c=meta["category"])

        # Pass 2: authorities (CITES) and document->document (REFERENCES).
        stats = {"documents": len(extracted), "authorities": set(), "cites": 0, "references": 0}
        for meta, cites in extracted:
            did = meta["doc_id"]
            for kind, ids in cites.items():
                for ident in ids:
                    s.run("""
                        MERGE (a:Authority {kind:$k, id:$i})
                        WITH a
                        MATCH (d:Document {doc_id:$did})
                        MERGE (d)-[r:CITES]->(a) SET r.kind=$k
                    """, k=kind, i=ident, did=did)
                    stats["authorities"].add((kind, ident))
                    stats["cites"] += 1

                    target = resolve_authority(kind, ident, pl_to_doc, act_name_to_doc, case_to_doc)
                    if target and target != did:  # don't self-reference
                        s.run("""
                            MATCH (a:Document {doc_id:$src}), (b:Document {doc_id:$dst})
                            MERGE (a)-[:REFERENCES]->(b)
                        """, src=did, dst=target)
                        stats["references"] += 1
        stats["authorities"] = len(stats["authorities"])
    driver.close()
    return stats

def graph_counts():
    driver = get_driver()
    with driver.session() as s:
        docs = s.run("MATCH (d:Document) RETURN count(d) AS n").single()["n"]
        auths = s.run("MATCH (a:Authority) RETURN count(a) AS n").single()["n"]
        cites = s.run("MATCH ()-[r:CITES]->() RETURN count(r) AS n").single()["n"]
        refs = s.run("MATCH ()-[r:REFERENCES]->() RETURN count(r) AS n").single()["n"]
    driver.close()
    return {"documents": docs, "authorities": auths, "cites": cites, "references": refs}

if __name__ == "__main__":
    import time
    t0 = time.time()
    stats = build_graph(wipe=True)
    print(f"built in {time.time()-t0:.1f}s: {stats}")
    print("verified counts:", graph_counts())
