# Submission — AI-Powered US Tax & Legal Research System

**Live demo:** https://kuldeepmishra3-legal-rag.hf.space — Ask · Summarize · Explore Citations
**Code:** this repository (see [README.md](README.md))

Hybrid retrieval (vector + BM25 + RRF) + **Graph RAG** (Neo4j citation graph) →
grounded answers via **Gemini 2.5 Pro** with mandatory citations (document ·
section · page) over 100 curated US legal & tax documents.

## Deliverables

| Deliverable | File / link |
|---|---|
| **Architecture diagram** | [`docs/architecture.png`](docs/architecture.png) |
| **Working demo** | https://kuldeepmishra3-legal-rag.hf.space |
| **Evaluation report** | [`evaluation_report.md`](evaluation_report.md) · one-page PDF: [`docs/Submission.pdf`](docs/Submission.pdf) |
| **Golden set** | [`golden_set.csv`](golden_set.csv) — 100 hand-authored Q/A |

## Results (100-query golden set)

| Retrieval (Top-1 / Top-5) | Faithfulness | Answer correctness | Grounded / Hallucinated |
|---|---|---|---|
| **95% / 99%** | **0.96** | **91% / 98%** | **100% / 0%** |

_One-page PDF of the architecture + evaluation: **[`docs/Submission.pdf`](docs/Submission.pdf)**._
