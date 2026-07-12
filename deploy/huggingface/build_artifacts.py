#!/usr/bin/env python3
"""
build_artifacts.py — prebuild the self-contained artifacts the HF Space needs.

Runs ONCE, against the live main-system stores, and writes deterministic files
the Space loads at startup (no Qdrant/ES/Neo4j servers in the deployed variant):

  data/artifacts/vectors.npy    float32 [N, 768]  — the SAME bge vectors that are
                                                    in the main Qdrant (exported,
                                                    not re-embedded -> exact parity)
  data/artifacts/chunk_ids.json list[str]         — chunk_id per row, aligned to vectors
  data/artifacts/graph.pkl      networkx.DiGraph  — the citation graph, built from the
                                                    SAME extraction/resolution logic
                                                    graph_builder uses for Neo4j

Payloads (chunk metadata + text) are NOT duplicated here — the Space loads them
from the bundled processed/*.json by chunk_id, so there is one source of truth.

Run from the repo root (main venv, with services up):
    ./venv/Scripts/python.exe deploy/huggingface/build_artifacts.py
"""
import json
import pickle
from pathlib import Path

import numpy as np

from legalrag import config
from legalrag.indexing import vector_indexer as vi
from legalrag.graph import graph_builder as gb, citation_extractor as ce

OUT = Path(__file__).resolve().parent / "data" / "artifacts"
OUT.mkdir(parents=True, exist_ok=True)


def export_vectors():
    """Scroll every point out of the live Qdrant collection, preserving the
    exact vectors AND payloads (so semantic search, BM25, generation, and
    summarize in the Space use identical data to main — no processed/ needed)."""
    client = vi.get_client()
    total = vi.collection_point_count(client)
    vectors, chunk_ids, payloads = [], [], {}
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=vi.COLLECTION_NAME, limit=1000,
            with_payload=True, with_vectors=True, offset=offset,
        )
        for p in points:
            vectors.append(p.vector)
            chunk_ids.append(p.payload["chunk_id"])
            payloads[p.payload["chunk_id"]] = p.payload
        if offset is None:
            break
    arr = np.asarray(vectors, dtype=np.float32)
    np.save(OUT / "vectors.npy", arr)
    (OUT / "chunk_ids.json").write_text(json.dumps(chunk_ids), encoding="utf-8")
    (OUT / "payloads.json").write_text(json.dumps(payloads), encoding="utf-8")
    assert arr.shape[0] == len(chunk_ids) == len(payloads) == total, "vector/id/payload/count mismatch"
    assert arr.shape[1] == 768, f"unexpected dim {arr.shape[1]}"
    # vectors are already L2-normalized at index time (normalize_embeddings=True),
    # so cosine == dot product in the Space's numpy search. Verify.
    norms = np.linalg.norm(arr, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-3), "vectors are not unit-normalized"
    print(f"  vectors.npy: {arr.shape} (unit-normalized) | chunk_ids.json: {len(chunk_ids)} "
          f"| payloads.json: {len(payloads)}")
    return arr.shape[0]


def build_graph():
    """Rebuild the citation graph as a networkx DiGraph using the EXACT same
    extraction + authority-resolution logic graph_builder uses for Neo4j — so
    the Space's Graph RAG returns identical results without a Neo4j server."""
    import networkx as nx

    pl_to_doc, act_name_to_doc, case_to_doc = gb.build_resolution_index()
    docs = gb.load_docs()
    G = nx.DiGraph()
    # Pass 1: create ALL Document nodes up front (mirrors the main graph_builder
    # fix) so every resolved REFERENCES target exists and no reference is dropped.
    extracted = []
    for chunks in docs:
        meta, doc_cites = ce.extract_for_document(chunks)
        extracted.append((meta, doc_cites))
        G.add_node(("doc", meta["doc_id"]), ntype="Document", doc_id=meta["doc_id"],
                   title=meta["title"], category=meta["category"])
    # Pass 2: CITES (doc->authority) and REFERENCES (doc->doc).
    authorities, cites, references = set(), 0, 0
    for meta, doc_cites in extracted:
        did = meta["doc_id"]
        for kind, ids in doc_cites.items():
            for ident in ids:
                anode = ("auth", kind, ident)
                if not G.has_node(anode):
                    G.add_node(anode, ntype="Authority", kind=kind, id=ident)
                authorities.add((kind, ident))
                G.add_edge(("doc", did), anode, etype="CITES", kind=kind)
                cites += 1
                target = gb.resolve_authority(kind, ident, pl_to_doc, act_name_to_doc, case_to_doc)
                if target and target != did:
                    G.add_edge(("doc", did), ("doc", target), etype="REFERENCES")
                    references += 1
    with open(OUT / "graph.pkl", "wb") as f:
        pickle.dump(G, f, protocol=pickle.HIGHEST_PROTOCOL)
    n_docs = sum(1 for _, d in G.nodes(data=True) if d.get("ntype") == "Document")
    n_auth = len(authorities)
    n_ref = sum(1 for *_, d in G.edges(data=True) if d.get("etype") == "REFERENCES")
    print(f"  graph.pkl: {G.number_of_nodes()} nodes ({n_docs} docs + {n_auth} authorities), "
          f"{cites} CITES, {n_ref} REFERENCES")
    return G.number_of_nodes(), n_auth, cites, n_ref


if __name__ == "__main__":
    print("Exporting vectors from live Qdrant...")
    n_vec = export_vectors()
    print("Building citation graph (networkx)...")
    n_nodes, n_auth, n_cites, n_ref = build_graph()
    print("\n=== artifacts written to", OUT, "===")
    print(f"  vectors: {n_vec} | graph nodes: {n_nodes} (auth {n_auth}) | "
          f"CITES {n_cites} | REFERENCES {n_ref}")
