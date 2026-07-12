"""
graph_local.py — Graph RAG over an in-memory networkx graph, replacing Neo4j
for the HF Space. A 1:1 port of legalrag.graph.graph_retriever's query
functions; the graph itself (graph.pkl) was built by the SAME extraction +
resolution logic graph_builder uses for Neo4j, and verified to have identical
node/edge counts — so these queries return identical results without a server.

Graph shape (built in build_artifacts.py):
  node ("doc", doc_id)        attrs: ntype=Document, doc_id, title, category
  node ("auth", kind, id)     attrs: ntype=Authority, kind, id
  edge doc  -> auth           etype=CITES, kind=<kind>
  edge doc  -> doc            etype=REFERENCES
"""
import pickle
import re
from pathlib import Path

ART = Path(__file__).resolve().parent.parent / "data" / "artifacts"

_G = None


def graph():
    global _G
    if _G is None:
        with open(ART / "graph.pkl", "rb") as f:
            _G = pickle.load(f)
    return _G


def _norm(s):
    return re.sub(r"\s+", " ", s).strip().lower()


def _doc_nodes(G):
    for n, d in G.nodes(data=True):
        if d.get("ntype") == "Document":
            yield n, d


def _citing_docs(G, auth_node):
    """Documents with a CITES edge into this authority node."""
    for u, _, d in G.in_edges(auth_node, data=True):
        if d.get("etype") == "CITES":
            yield u


def _referencing_docs(G, doc_node):
    """Documents with a REFERENCES edge into this document node."""
    for u, _, d in G.in_edges(doc_node, data=True):
        if d.get("etype") == "REFERENCES":
            yield u


def _doc_record(G, node):
    d = G.nodes[node]
    return {"doc_id": d["doc_id"], "title": d.get("title", ""), "category": d.get("category", "")}


# ---------------- authority lookup ----------------
def find_authorities(query, limit=8):
    G = graph()
    q = _norm(query)
    out = []
    for n, d in G.nodes(data=True):
        if d.get("ntype") == "Authority" and q in str(d["id"]).lower():
            doc_count = sum(1 for _ in _citing_docs(G, n))
            out.append({"kind": d["kind"], "id": d["id"], "doc_count": doc_count})
    out.sort(key=lambda r: r["doc_count"], reverse=True)
    return out[:limit]


def documents_citing(authority_query, category=None, limit=25):
    """Which corpus documents cite an authority matching the query text?"""
    G = graph()
    q = _norm(authority_query)
    seen, out = set(), []
    for n, d in G.nodes(data=True):
        if d.get("ntype") != "Authority" or q not in str(d["id"]).lower():
            continue
        for doc in _citing_docs(G, n):
            rec = _doc_record(G, doc)
            if category and rec["category"] != category:
                continue
            if rec["doc_id"] not in seen:
                seen.add(rec["doc_id"]); out.append(rec)
    out.sort(key=lambda r: (r["category"], r["title"]))
    return out[:limit]


# ---------------- document<->document references ----------------
def references_from(doc_id):
    G = graph()
    node = ("doc", doc_id)
    if not G.has_node(node):
        return []
    out = []
    for _, v, d in G.out_edges(node, data=True):
        if d.get("etype") == "REFERENCES":
            out.append(_doc_record(G, v))
    return out


def references_to(doc_id):
    G = graph()
    node = ("doc", doc_id)
    if not G.has_node(node):
        return []
    return [_doc_record(G, u) for u in _referencing_docs(G, node)]


def documents_referencing_title(title_query, category=None, limit=25):
    """'Which [judgments] cite <corpus document Y>?' — resolve Y by title, then
    follow incoming REFERENCES edges. Optionally restrict citing docs by category."""
    G = graph()
    q = _norm(title_query)
    seen, out = set(), []
    for y, dy in _doc_nodes(G):
        if q not in dy.get("title", "").lower():
            continue
        for x in _referencing_docs(G, y):
            rec = _doc_record(G, x)
            if category and rec["category"] != category:
                continue
            if rec["doc_id"] not in seen:
                seen.add(rec["doc_id"]); out.append(rec)
    out.sort(key=lambda r: (r["category"], r["title"]))
    return out[:limit]


def doc_id_by_title(title_query):
    G = graph()
    q = _norm(title_query)
    for n, d in _doc_nodes(G):
        if q in d.get("title", "").lower():
            return d["doc_id"]
    return None


def edge_exists_reference(src_doc_id, dst_doc_id):
    G = graph()
    s, t = ("doc", src_doc_id), ("doc", dst_doc_id)
    return G.has_edge(s, t) and G.get_edge_data(s, t, {}).get("etype") == "REFERENCES"


def document_cites_authority(doc_id, kind, ident):
    G = graph()
    s, a = ("doc", doc_id), ("auth", kind, ident)
    return G.has_edge(s, a)


# ---------------- context enrichment ----------------
def enrich_docs(doc_ids, max_neighbors=5):
    G = graph()
    ids = set(doc_ids)
    refs, seen = [], set()
    shared_counter = {}
    for did in ids:
        node = ("doc", did)
        if not G.has_node(node):
            continue
        # referenced corpus docs (both directions, excluding the input set)
        for nbr in list(G.successors(node)) + list(G.predecessors(node)):
            nd = G.nodes[nbr]
            if nd.get("ntype") == "Document" and nd["doc_id"] not in ids and nd["doc_id"] not in seen:
                seen.add(nd["doc_id"]); refs.append(_doc_record(G, nbr))
        # authorities this doc cites (for shared-authority counting)
        for _, a, d in G.out_edges(node, data=True):
            if d.get("etype") == "CITES":
                shared_counter[a] = shared_counter.get(a, 0) + 1
    shared = [{"kind": G.nodes[a]["kind"], "id": G.nodes[a]["id"], "shared_by": c}
              for a, c in shared_counter.items() if c > 1]
    shared.sort(key=lambda r: r["shared_by"], reverse=True)
    return {"referenced_documents": refs[:max_neighbors],
            "shared_authorities": shared[:max_neighbors]}


# ---------------- relationship-query routing (copied verbatim from graph_retriever) ----------------
_REL_PATTERNS = [
    r"which\s+(judgments?|cases?|acts?|documents?|reports?)\s+.*\b(cite|cites|reference|references|mention|discuss)",
    r"what\s+(documents?|cases?|judgments?|acts?)\s+.*\b(cite|reference|mention)",
    r"\b(cites?|references?)\b.*\b(act|code|u\.?s\.?c|law)\b",
]


def is_relationship_query(query):
    q = query.lower()
    return any(re.search(p, q) for p in _REL_PATTERNS)
