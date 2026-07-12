#!/usr/bin/env python3
"""
es_indexer.py — Phase 3 Elasticsearch (BM25) indexing for the US Tax & Legal
RAG system.

Keyword search complements the vector index from Phase 2: embeddings are
good at "what does this mean," BM25 is good at "this exact phrase/citation
appears verbatim" — critical for legal text where an exact statutory phrase
or case citation matters more than semantic similarity.
"""
import os

from dotenv import load_dotenv
from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk

load_dotenv()

INDEX_NAME = "legal_rag_chunks"

MAPPING = {
    "properties": {
        "chunk_id": {"type": "keyword"},
        "doc_id": {"type": "keyword"},
        "title": {"type": "text", "analyzer": "standard"},
        "category": {"type": "keyword"},
        "source_org": {"type": "keyword"},
        "url": {"type": "keyword"},
        "section_title": {"type": "text", "analyzer": "standard"},
        "chunk_type": {"type": "keyword"},
        "page_start": {"type": "integer"},
        "page_end": {"type": "integer"},
        "text": {"type": "text", "analyzer": "standard"},
        # parent_section_text is stored for LLM-time context retrieval (Phase 5)
        # but NOT analyzed/searched — BM25 keyword matching runs on `text` only,
        # so the wider window doesn't dilute keyword relevance scoring.
        "parent_section_text": {"type": "text", "index": False},
        "token_count": {"type": "integer"},
    }
}

def get_client():
    url = os.environ.get("ELASTICSEARCH_URL", "http://localhost:9200")
    return Elasticsearch(url)

def ensure_index(client, recreate=False):
    exists = client.indices.exists(index=INDEX_NAME)
    if exists and recreate:
        client.indices.delete(index=INDEX_NAME)
        exists = False
    if not exists:
        client.indices.create(index=INDEX_NAME, mappings=MAPPING)

def chunk_id_to_doc_id(chunk_id):
    """ES document _id — chunk_id is already a clean deterministic string,
    no UUID conversion needed (unlike Qdrant, which requires int/UUID)."""
    return chunk_id

def index_chunks(client, chunks):
    actions = []
    for c in chunks:
        actions.append({
            "_index": INDEX_NAME,
            "_id": chunk_id_to_doc_id(c["chunk_id"]),
            "_source": {
                "chunk_id": c["chunk_id"],
                "doc_id": c["doc_id"],
                "title": c["title"],
                "category": c["category"],
                "source_org": c.get("source_org", ""),
                "url": c.get("url", ""),
                "section_title": c["section_title"],
                "chunk_type": c["chunk_type"],
                "page_start": c["page_start"],
                "page_end": c["page_end"],
                "text": c["text"],
                "parent_section_text": c.get("parent_section_text", ""),
                "token_count": c.get("token_count", 0),
            },
        })
    success, errors = bulk(client, actions, raise_on_error=False)
    return success, errors

def index_doc_count(client):
    client.indices.refresh(index=INDEX_NAME)
    return client.count(index=INDEX_NAME)["count"]

def search(client, query_text, category=None, size=5):
    """General BM25 relevance search over the text field (bag-of-terms, not
    phrase-order-sensitive), optionally filtered by category."""
    must = [{"match": {"text": query_text}}]
    filt = [{"term": {"category": category}}] if category else []
    body = {"query": {"bool": {"must": must, "filter": filt}}, "size": size}
    resp = client.search(index=INDEX_NAME, body=body)
    return resp["hits"]["hits"]

def search_phrase(client, phrase, category=None, size=5):
    """Exact phrase search — word order/adjacency matters, unlike search()'s
    bag-of-terms match. This is Elasticsearch's match_phrase query, not a
    plain match() with literal quote characters in the string (which does
    nothing special — confirmed as a real bug: quotes passed into match()
    are just tokenized like any other text, so it silently degraded to loose
    relevance ranking on common words instead of real phrase matching)."""
    must = [{"match_phrase": {"text": phrase}}]
    filt = [{"term": {"category": category}}] if category else []
    body = {"query": {"bool": {"must": must, "filter": filt}}, "size": size}
    resp = client.search(index=INDEX_NAME, body=body)
    return resp["hits"]["hits"]
