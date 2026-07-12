# Submission — AI-Powered US Tax & Legal Research System

**Live demo:** https://kuldeepmishra3-legal-rag.hf.space — Ask · Summarize · Explore Citations
**Code:** this repository · start with [README.md](README.md)

A Retrieval-Augmented Generation system for US tax & legal research over **100
curated documents** (Acts, court judgments, legal commentary, IRS tax pubs).
Hybrid retrieval (vector + BM25 + RRF) + **Graph RAG** (citation graph) →
grounded answers via **Gemini 2.5 Pro** with mandatory citations (document /
section / page) and a citation-validation guard.

---

## PRD Final Deliverables → where to find each

| # | PRD deliverable | Delivered | Location |
|---|---|---|---|
| **1** | **Architecture diagram** (full workflow) | ✅ | [ARCHITECTURE.md](ARCHITECTURE.md) + image [`docs/architecture.png`](docs/architecture.png) (flowchart + request-lifecycle sequence diagram) |
| **2** | **Working demo** (queries · retrieval · summaries · citations + page refs) | ✅ | **Live:** https://kuldeepmishra3-legal-rag.hf.space · Local: FastAPI + web UI (`backend/`, `frontend/`) |
| **3** | **Evaluation report** (retrieval, faithfulness, golden set, observations) | ✅ | [evaluation_report.md](evaluation_report.md) |

## PRD Expected Outcome → status

| Requirement | Status |
|---|---|
| Process ~100 US legal & tax documents | ✅ 100 docs (30 Acts / 30 Judgments / 30 POV / 10 Tax) → 6,289 chunks |
| Hybrid Search (Vector + ELK/Elasticsearch keyword) | ✅ Qdrant + Elasticsearch BM25 → Reciprocal Rank Fusion |
| Graph RAG (optional advanced) | ✅ Neo4j citation graph (3,203 authorities, 4,075 edges) |
| Page-level metadata for citations | ✅ every answer cites document · section · page |
| Accurate summaries | ✅ `/summarize` per document |
| Document names, page numbers, references for verification | ✅ clickable citations + source links |
| Measurable performance on a Golden Set | ✅ 100-query golden set → see below |
| OKF (Open Knowledge Format) normalization | ✅ OKF-normalized chunks (`chunker.py`) |

---

## Headline results (100-query golden set)

| Metric | Score |
|---|---|
| Retrieval accuracy (Top-1 / Top-5) | **95% / 99%** |
| Faithfulness (RAGAS) | **0.96** |
| Answer correctness (LLM judge) | **91% correct / 98% correct-or-partial** |
| Grounded / hallucinated | **100% / 0%** |

Full methodology, per-category breakdown, and limitations: [evaluation_report.md](evaluation_report.md).

**Golden set:** [`eval/golden_set.csv`](eval/golden_set.csv) — 100 hand-authored
`query · ground-truth answer · source document · page` rows.

---

## Run it

**Try the live demo** (no setup): https://kuldeepmishra3-legal-rag.hf.space

**Or run locally** (full setup in [README.md](README.md)):
```bash
python3.10 -m venv venv && ./venv/Scripts/python.exe -m pip install -r requirements.txt && ./venv/Scripts/python.exe -m pip install -e .
cp .env.example .env                       # add your Gemini/Vertex credentials
docker compose --profile all up -d          # Qdrant + Elasticsearch + Neo4j
./venv/Scripts/python.exe scripts/build_processed.py
./venv/Scripts/python.exe scripts/build_vector_index.py
./venv/Scripts/python.exe scripts/build_keyword_index.py
./venv/Scripts/python.exe -m legalrag.graph.graph_builder
./venv/Scripts/python.exe -m uvicorn backend.app.main:app --port 8000   # → http://localhost:8000
```

**Tests:** `./venv/Scripts/python.exe -m pytest tests/ -q` — **63 tests** across all phases.

---

## Repo map

- `src/legalrag/` — the pipeline package (ingestion · indexing · retrieval · generation · graph)
- `backend/` · `frontend/` — FastAPI API + web UI
- `eval/` — golden set, evaluation harness, RAGAS, correctness judge
- `deploy/huggingface/` — the self-contained Hugging Face Space (server-less variant)
- `docs/` — PRD, plan, task log, architecture image
- `ARCHITECTURE.md` · `evaluation_report.md` · `README.md`
