#!/usr/bin/env python3
"""
vector_indexer.py — Phase 2 Qdrant indexing for the US Tax & Legal RAG system.

Creates the collection (1024-dim, matches voyage-law-2) and upserts chunks with
full metadata as payload, so retrieval can filter by category/doc_id/page, not
just similarity-search blindly.
"""
import os
import uuid

from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

from legalrag.ingestion.embed import EMBED_DIM

load_dotenv()

COLLECTION_NAME = "legal_rag_chunks"

def get_client():
    return QdrantClient(
        host=os.environ.get("QDRANT_HOST", "localhost"),
        port=int(os.environ.get("QDRANT_PORT", 6333)),
    )

def ensure_collection(client, recreate=False):
    exists = client.collection_exists(COLLECTION_NAME)
    if exists and recreate:
        client.delete_collection(COLLECTION_NAME)
        exists = False
    if not exists:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=EMBED_DIM, distance=Distance.COSINE),
        )

def chunk_id_to_point_id(chunk_id):
    """Qdrant point IDs must be int or UUID — derive a deterministic UUID5 from
    chunk_id so re-running indexing is idempotent (same chunk -> same point)."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))

def upsert_chunks(client, chunks, embeddings):
    points = []
    for chunk, vec in zip(chunks, embeddings):
        points.append(PointStruct(
            id=chunk_id_to_point_id(chunk["chunk_id"]),
            vector=vec,
            payload={
                "chunk_id": chunk["chunk_id"],
                "doc_id": chunk["doc_id"],
                "title": chunk["title"],
                "category": chunk["category"],
                "source_org": chunk.get("source_org", ""),
                "url": chunk.get("url", ""),
                "section_title": chunk["section_title"],
                "chunk_type": chunk["chunk_type"],
                "page_start": chunk["page_start"],
                "page_end": chunk["page_end"],
                "text": chunk["text"],
                "parent_section_text": chunk.get("parent_section_text", ""),
                "token_count": chunk.get("token_count", 0),
            },
        ))
    client.upsert(collection_name=COLLECTION_NAME, points=points)

def collection_point_count(client):
    return client.count(COLLECTION_NAME, exact=True).count
