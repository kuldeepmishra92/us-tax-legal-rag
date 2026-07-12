# Project Plan — AI-Powered US Tax & Legal Research System

Source of truth for scope: [prd.md](prd.md). This file is the technical build plan derived from it.
Live status lives in [task.md](task.md) — update that file as work progresses; this file only changes when the plan itself changes.

---

## Locked-in tech stack

| Layer | Choice | Notes |
|---|---|---|
| Corpus | 100 curated PDFs (30 Acts / 30 Court Judgments / 30 POV / 10 Tax Documents) | Done — see [sources.md](../sources.md) |
| LLM | **Gemini 2.5 Flash** | `GOOGLE_API_KEY` |
| Embeddings | **bge-base-en-v1.5** (local, sentence-transformers) | switched from voyage-law-2 — API free-tier rate limit made the corpus take 7-8hr; local model finishes in ~38 min on this CPU-only machine. 91%/98% Top-1/Top-5 on the golden set. See [task.md](task.md) Phase 2 for the full story. |
| Vector DB | **Qdrant** | via Docker |
| Keyword search | **Elasticsearch** | via Docker, per PRD's "ELK Stack" requirement |
| Graph store | **Neo4j** | via Docker, Phase 7 (Graph RAG) |
| Reranker | `bge-reranker-base` implemented, available, **off by default** | measured on the full golden set to hurt Top-1 accuracy on this corpus (95.0%→91.0%) — see Phase 4 below |
| Backend | **FastAPI** | |
| Frontend | **Vanilla JS** (HTML/CSS/JS, no framework) | |
| Testing | **pytest**, all test files under `tests/` | |
| Evaluation | **RAGAS** (Context Precision/Recall, Faithfulness) | maps directly to PRD's golden-set metrics |

---

## Working rules (non-negotiable)

1. **Phases are strictly gated.** Phase *N+1* does not start until Phase *N*'s tests are written, green, and you've reviewed/approved the result. No moving forward on a shaky foundation.
2. **Every phase adds its own test file(s)** under `tests/`, named `test_phaseN_<topic>.py`. Tests are written *for that phase's deliverable*, not retrofitted later.
3. **`task.md` is the live tracker.** It gets updated at the start and end of every phase — what's done, what's in progress, what's blocked, open questions for you.
4. **I ask before assuming** on anything with a real tradeoff (data, model, infra, evaluation methodology) — via targeted questions, not silent defaults, especially at phase boundaries.
5. If a phase's tests reveal the foundation is weak (bad chunking, poor retrieval, hallucinated citations), **we fix that phase before advancing** — we do not carry known-bad output into the next layer.

---

## Phase 0 — Environment Setup

**Goal:** project skeleton + infra config ready, nothing running yet.

**Deliverables:**
- `requirements.txt` (phase-annotated)
- `.env.example` (`GOOGLE_API_KEY`, `VOYAGE_API_KEY`)
- `docker-compose.yml` (qdrant, elasticsearch, neo4j services — started only when their phase needs them)
- `tests/` folder + `tests/README.md` (conventions)

**Definition of Done:** files exist, `docker compose config` validates, no services started yet.

---

## Phase 1 — Document Parsing & Chunking (OKF normalization)

**Goal:** convert all 100 PDFs into structure-aware, page/section-tagged chunks in one normalized JSON schema (the PRD's "OKF" — Open Knowledge Format — layer).

**Approach:**
- PyMuPDF extraction, per-page text with page number retained on every chunk.
- Structure-aware chunk boundaries (not fixed-token windows): split at section markers per category —
  - Acts: `SEC. \d+` / `§ \d+`
  - Judgments: opinion sections (Syllabus, majority, concurrence/dissent boundaries)
  - Tax Documents: IRS publication headings
  - POV: CRS report headings
- Small-to-big pattern: index small chunks (~300–600 tokens) for precision, but retain parent-section text for LLM context at answer time.
- Output schema per chunk: `{chunk_id, doc_id, title, category, section_id, page_start, page_end, text, parent_section_text}`

**Deliverables:** `parser.py`, `chunker.py`, `processed/*.json`, `processed_manifest.csv`

**Tests (`tests/test_phase1_parsing.py`):**
- All 100 docs produce ≥1 chunk (no silent failures)
- Every chunk has non-null `page_start`/`page_end`/`doc_id`/`section_id`
- No empty/near-empty chunks (min word count)
- Extracted total word count roughly matches the `words` figure already recorded in `documents_manifest.csv` (catches text-loss bugs)
- Spot-check: 5 hand-picked chunks manually verified against source PDF

**Definition of Done:** 100/100 docs parsed, all tests green, 5 manual spot-checks pass.

---

## Phase 2 — Vector Indexing

**Goal:** embed all chunks with voyage-law-2, index into Qdrant with metadata filtering (category, doc_id, page).

**Deliverables:** `embed.py`, `vector_indexer.py`, populated Qdrant collection

**Tests (`tests/test_phase2_vector.py`):**
- Qdrant point count == chunk count
- Embedding dimension matches voyage-law-2's output dim
- ~10 hand-written sanity queries (one per category+) each return the *expected* source document in top-5

**Definition of Done:** index built, all sanity queries pass, tests green.

---

## Phase 3 — Keyword Indexing (Elasticsearch)

**Goal:** BM25 keyword index of all chunks in Elasticsearch.

**Deliverables:** `es_indexer.py`, populated ES index

**Tests (`tests/test_phase3_keyword.py`):**
- ES doc count == chunk count
- Exact-phrase queries (unique statutory phrases) return the correct doc + page
- Cross-check: a query with quoted exact legal terminology outperforms semantic-only phrasing here (validates BM25 is actually doing its job)

**Definition of Done:** ES populated, tests green.

---

## Phase 4 — Hybrid Retrieval (RRF + Reranker)

**Goal:** fuse vector + keyword results (Reciprocal Rank Fusion); evaluate a local cross-encoder reranker on top of it.

**Deliverables:** `hybrid_retriever.py`, `reranker.py`

**Tests (`tests/test_phase4_hybrid.py`):**
- Benchmark set of ~20 hand-picked queries (5 per category) with known correct source doc, reused from [eval/golden_set.csv](../eval/golden_set.csv)
- Hybrid retrieval (RRF fusion) hits correct doc in top-3 for ≥90% of the benchmark set
- Reranker path runs correctly and its effect stays within the bounds already measured on the full 100-query set (regression guard, not an "improves" assertion — see below)

**Definition of Done:** benchmark accuracy bar met, tests green — **this is the retrieval quality gate; nothing downstream is built on weak retrieval.**

**Result (2026-07-10):** RRF fusion alone reached **95.0% Top-1 / 97.0% Top-3 / 99.0% Top-5** on the full 100-query golden set — comfortably clears the bar. Adding `bge-reranker-base` on top was evaluated (not assumed) and **measurably hurt** Top-1 accuracy (91.0%, a 4-point regression) with zero benefit at Top-3/Top-5. Investigated and ruled out truncation as the cause (chunks scored well under the reranker's 512-token limit); this is a genuine general-purpose-reranker limitation on this corpus's near-duplicate content (Tax especially — many IRS publications cover overlapping topics). **`hybrid_search()` defaults to `rerank=False`** — RRF fusion alone is the production retrieval path. The reranker code is kept, tested, and available (`rerank=True`) for future experimentation with a different/fine-tuned model, but it does not ship on by default without earning that by the data. Full comparison logged in [task.md](task.md).

---

## Phase 5 — LLM Answer Generation + Citations

**Goal:** grounded answers from Gemini 2.5 Flash over hybrid-retrieved context, with mandatory citations (doc name, section, page) and a post-hoc grounding check.

**Deliverables:** `llm_service.py`, prompt templates, `citation_validator.py`

**Tests (`tests/test_phase5_generation.py`):**
- Every generated answer contains ≥1 citation
- Every cited (doc, page) pair actually appears in the retrieved context (no fabricated citations)
- Out-of-corpus question → system refuses/flags rather than hallucinating an answer
- Manual review of 5 sample Q&A pairs for citation accuracy and answer quality

**Definition of Done:** tests green, manual review passes.

---

## Phase 6 — FastAPI Backend + Vanilla JS Frontend (Working Demo)

**Goal:** wire the full pipeline behind an API, with a usable web UI.

**Deliverables:**
- `backend/app/main.py` — endpoints: `/query` (Q&A), `/summarize`, `/health`
- `frontend/index.html` + `app.js` + `style.css` — query box, answer panel, citations panel (doc/section/page, clickable to source)

**Tests (`tests/test_phase6_api.py`):** FastAPI `TestClient` coverage — 200s on valid input, correct response schema, proper error handling on bad input.
**Manual smoke test checklist** (frontend, not automatable without a browser test framework): submit a query → see answer → see citations → error states behave correctly.

**Definition of Done:** API tests green, manual frontend checklist passed.

---

## Phase 7 — Graph RAG (Citation Graph)

**Goal:** extract cross-document citation relationships, build a Neo4j graph, use it to answer relationship queries and enrich retrieval context.

**Approach:**
- Citation extraction (regex): U.S.C. references, `Pub. L. No.`, case citations, "cited as" clauses already used during Acts title-extraction.
- Graph: nodes = documents/sections, edges = `CITES` / `AMENDS` / `REFERENCES`.
- Two usage modes: (1) route relationship-style questions ("which judgments cite the Bankruptcy Code?") straight to Cypher graph traversal, (2) enrich top retrieved chunks with their 1-hop graph neighbors before LLM generation.

**Deliverables:** `citation_extractor.py`, `graph_builder.py`, `graph_retriever.py`

**Tests (`tests/test_phase7_graph.py`):**
- Graph node/edge counts within a sane range (not near-zero, not exploded)
- 3+ hand-verified ground-truth citation pairs from the corpus exist as edges in the graph
- A relationship-style benchmark query returns the graph-correct answer

**Definition of Done:** tests green, manual graph spot-check.

---

## Phase 8 — Evaluation (Golden Set + RAGAS)

**Goal:** run the complete system against the golden set, measure Retrieval Accuracy and Faithfulness.

**Note:** the PRD states a golden set "will be provided." **Need this from you before this phase starts** — if it doesn't materialize, we'll need to construct one from the corpus together.

**Deliverables:** `eval/run_eval.py`, `eval/golden_set.csv`, `evaluation_report.md`

**Tests (`tests/test_phase8_eval.py`):** eval pipeline runs end-to-end on a small subset without crashing, output schema check.

**Definition of Done:** full golden-set run complete, `evaluation_report.md` written with metrics, observations, limitations.

---

## Phase 9 — Final Deliverables

**Goal:** package everything the PRD asks for.

**Deliverables:**
- Architecture diagram (matches PRD's workflow diagram, reflects what was actually built)
- Polished demo
- Final `evaluation_report.md`

**Definition of Done:** full regression — every test file under `tests/` re-run and green — before calling the project complete.

---

## Open items to resolve before/at specific phases

- **Golden set** — needed before Phase 8; ask you when we approach it if not yet provided.
- **Reranker model choice** — default `bge-reranker-base`, will confirm at Phase 4 if a legal-tuned reranker is worth the swap.
