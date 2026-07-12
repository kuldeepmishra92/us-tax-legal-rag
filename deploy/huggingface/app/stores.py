"""
stores.py — server-less replacements for Qdrant and Elasticsearch, for the HF
Space. Both return the SAME shape the main hybrid_retriever expects
(list of {"chunk_id", "payload", "score"}), so downstream fusion + generation
are byte-for-byte the main pipeline.

  VectorStore  — numpy EXACT cosine over the bge vectors exported from Qdrant.
                 Vectors are unit-normalized, so cosine == dot product. Exact
                 top-k >= Qdrant's ANN, so semantic retrieval is >= main.
  KeywordStore — rank_bm25 (BM25Okapi) over the chunk `text`, tuned to match
                 Elasticsearch's defaults: standard-analyzer-style tokenization
                 (lowercase, \\w+), k1=1.2, b=0.75, idf over the full corpus,
                 and only chunks that share >=1 query term count as hits (as ES).
"""
import json
import re
from pathlib import Path

import numpy as np
from rank_bm25 import BM25Okapi

from legalrag.ingestion import embed

ART = Path(__file__).resolve().parent.parent / "data" / "artifacts"

_TOKEN = re.compile(r"\w+", re.UNICODE)


def _tokenize(text):
    """Approximates Elasticsearch's `standard` analyzer for English: Unicode
    word tokens, lowercased, no stemming, no stopword removal (ES standard
    removes no stopwords by default)."""
    return _TOKEN.findall(text.lower())


class _Data:
    """Loads the exported artifacts once and shares them across both stores."""
    def __init__(self):
        self.vectors = np.load(ART / "vectors.npy")                       # [N, 768] float32, unit-norm
        self.chunk_ids = json.loads((ART / "chunk_ids.json").read_text(encoding="utf-8"))
        self.payloads = json.loads((ART / "payloads.json").read_text(encoding="utf-8"))
        assert self.vectors.shape[0] == len(self.chunk_ids) == len(self.payloads)
        # category per row, aligned to vectors/chunk_ids (for filtered search)
        self.categories = np.array([self.payloads[c]["category"] for c in self.chunk_ids])


class VectorStore:
    def __init__(self, data: _Data):
        self.d = data

    def search(self, query, top_n=20, category=None):
        qvec = np.asarray(embed.embed_query(query), dtype=np.float32)      # unit-norm (bge query prefix)
        scores = self.d.vectors @ qvec                                    # cosine (both normalized)
        if category:
            mask = self.d.categories == category
            idx_pool = np.where(mask)[0]
            order = idx_pool[np.argsort(scores[idx_pool])[::-1][:top_n]]
        else:
            order = np.argsort(scores)[::-1][:top_n]
        return [{"chunk_id": self.d.chunk_ids[i],
                 "payload": self.d.payloads[self.d.chunk_ids[i]],
                 "score": float(scores[i])} for i in order]


class KeywordStore:
    def __init__(self, data: _Data):
        self.d = data
        corpus_tokens = [_tokenize(self.d.payloads[c]["text"]) for c in self.d.chunk_ids]
        # ES default BM25 params (k1=1.2, b=0.75); rank_bm25's own default k1 is 1.5.
        self.bm25 = BM25Okapi(corpus_tokens, k1=1.2, b=0.75)

    def search(self, query, top_n=20, category=None):
        q_tokens = _tokenize(query)
        scores = self.bm25.get_scores(q_tokens)
        order = np.argsort(scores)[::-1]
        hits = []
        for i in order:
            if scores[i] <= 0:            # ES `match` only returns docs sharing >=1 term
                break
            cid = self.d.chunk_ids[i]
            if category and self.d.payloads[cid]["category"] != category:
                continue
            hits.append({"chunk_id": cid, "payload": self.d.payloads[cid], "score": float(scores[i])})
            if len(hits) >= top_n:
                break
        return hits


_data = None
_vector = None
_keyword = None


def get_stores():
    """Lazily build and cache the stores (BM25 index build is the only cost,
    a few seconds over 6.3k chunks)."""
    global _data, _vector, _keyword
    if _data is None:
        _data = _Data()
        _vector = VectorStore(_data)
        _keyword = KeywordStore(_data)
    return _vector, _keyword
