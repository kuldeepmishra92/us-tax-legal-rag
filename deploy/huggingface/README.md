---
title: US Tax & Legal Research (RAG)
emoji: ⚖️
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
license: mit
---

# AI-Powered US Tax & Legal Research System

A Retrieval-Augmented Generation (RAG) assistant over 100 curated US legal
documents (Acts, court judgments, legal commentary, IRS tax publications). Ask a
question and get a **grounded answer with exact citations** — document, section,
and page.

Three capabilities:

- **Ask** — hybrid retrieval (semantic + keyword) → grounded answer with mandatory
  `[N]` citations and a citation-validation guard.
- **Summarize** — document-level summaries.
- **Explore Citations (Graph RAG)** — relationship queries pure search can't answer,
  e.g. *"which judgments cite the Fiscal Responsibility Act?"*

## How this Space works (server-less variant)

The full system uses Qdrant, Elasticsearch, and Neo4j. To run in a single free
CPU container, those are replaced by in-process equivalents — with the retrieval
quality verified against the full system on a 100-query golden set:

| Capability | Full system | This Space | Parity |
|---|---|---|---|
| Generation | Gemini 2.5 Pro | **same** | identical |
| Embeddings | bge-base-en-v1.5 | **same** | identical |
| Vector search | Qdrant (ANN) | numpy exact cosine | ≥ (exact) |
| Keyword search | Elasticsearch BM25 | `rank_bm25` | Top-5 identical; Top-1 −2% (2 tax queries) |
| Graph RAG | Neo4j | `networkx` | **exact match** (verified) |
| Fusion | RRF k=60 | same code | identical |

Answer generation and citation validation are the **unchanged** pipeline, so
faithfulness, grounding, and correctness are preserved.

## Configuration (Space secrets)

This Space calls **Gemini 2.5 Pro via Vertex AI**. Set these in
**Settings → Variables and secrets**:

| Name | Type | Value |
|---|---|---|
| `GCP_PROJECT` | secret | your Google Cloud project id |
| `GOOGLE_APPLICATION_CREDENTIALS_B64` | secret | base64 of the service-account key JSON (one clean line — recommended) |

(You can instead use `GOOGLE_APPLICATION_CREDENTIALS_JSON` with the raw JSON —
the app auto-detects raw-JSON or base64 under either name.)

`GEMINI_USE_VERTEX=true`, `GCP_LOCATION=global`, and `GEMINI_MODEL=gemini-2.5-pro`
are already baked into the image. The service account needs the **Vertex AI User**
role and the Vertex AI API enabled on the project.

_Deploying this yourself? See `DEPLOY.md` for the full step-by-step._
