#!/usr/bin/env python3
"""
embed.py — Phase 2 embedding layer for the US Tax & Legal RAG system.

Local embeddings via sentence-transformers (BAAI/bge-base-en-v1.5) — no API
key, no rate limits, runs on this machine. Switched from voyage-law-2 (a
legal-domain-tuned API model) because the API key was locked to a free-trial
rate limit (3 requests/min, 10,000 tokens/min) that made the full corpus take
7-8+ hours.

Model size chosen deliberately after measuring real throughput on this
machine (no GPU): bge-large-en-v1.5 (335M params) projected ~304 min for the
full corpus — CPU inference on long legal chunks (300-600+ tokens) is slow
regardless of "local = fast" intuition. bge-base-en-v1.5 (109M params)
measured ~113 min, a deliberate speed/quality middle ground over bge-large
(too slow here) and bge-small (faster but a bigger quality drop).

BGE-specific detail that matters for retrieval quality: the model's own
documentation recommends prefixing QUERIES — not documents — with an
instruction string at encode time. This is the same asymmetric-embedding
idea Voyage used (input_type="document" vs "query"), just implemented as a
literal text prefix instead of an API parameter.
"""
from sentence_transformers import SentenceTransformer

MODEL_NAME = "BAAI/bge-base-en-v1.5"
EMBED_DIM = 768
QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "
BATCH_SIZE = 32  # sentence-transformers' own recommended default for this model size

_model = None

def get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)
    return _model

def embed_texts(texts, input_type="document", batch_size=BATCH_SIZE, on_progress=None):
    """Embed a list of texts. input_type='document' (default, no prefix) or
    'query' (adds BGE's recommended search-instruction prefix)."""
    model = get_model()
    if input_type == "query":
        texts = [QUERY_INSTRUCTION + t for t in texts]
    vecs = model.encode(
        texts, batch_size=batch_size, show_progress_bar=False,
        convert_to_numpy=True, normalize_embeddings=True,
    )
    if on_progress:
        on_progress(len(texts), len(texts))
    return vecs.tolist()

def embed_texts_with_usage(texts, input_type="document", batch_size=BATCH_SIZE):
    """Kept for interface parity with the earlier API-based version — local
    embedding has no token-usage accounting, so 'usage' is just a word count."""
    vecs = embed_texts(texts, input_type=input_type, batch_size=batch_size)
    total_words = sum(len(t.split()) for t in texts)
    return vecs, total_words

def embed_query(query_text):
    """Embed a single search query (adds the BGE query instruction prefix)."""
    return embed_texts([query_text], input_type="query")[0]

if __name__ == "__main__":
    vecs = embed_texts(["test chunk one", "test chunk two, about 26 U.S.C. section 501(c)(3)"])
    print(f"embedded {len(vecs)} texts, dim={len(vecs[0])}")
