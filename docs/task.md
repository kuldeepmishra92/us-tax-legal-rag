# Task Tracker

Live status for the build. See [plan.md](plan.md) for the full phase spec. Updated at the start/end of every phase.

Legend: ✅ Done · 🔄 In Progress · 🔲 Not Started · ⛔ Blocked

---

## Phase 0 — Environment Setup — ✅ Done
- [x] plan.md written
- [x] task.md written
- [x] tests/ folder + tests/README.md
- [x] requirements.txt
- [x] .env.example
- [x] docker-compose.yml (qdrant, elasticsearch, neo4j — profile-gated, validated with `docker compose config`)

## Phase 1 — Document Parsing & Chunking — ✅ Done
- [x] parser.py: page-level extraction (header/footer/watermark strip, dehyphenation, ligature repair, table extraction w/ merged-cell fix + malformed-table rejection, footnote separation w/ heading-safeguard, image counting, category-aware heading detection)
- [x] chunker.py: structure-aware section splitting (category-specific boundaries), sentence-aware token-budget chunking (target 450 / soft cap 600 / hard ceiling 1200), small-to-big (parent_section_text), table chunking w/ oversized-table splitting, tiny-chunk merging
- [x] build_processed.py driver — processed/*.json (100 files) + processed_manifest.csv
- [x] tests/test_phase1_parsing.py — 12/12 passing
- [x] 5 manual spot-checks — including direct byte-for-byte verification of chunk text + page number against source PDF (SEC. 336, Continuing Appropriations Act, page 20 confirmed exact match)

**Final numbers:** 100/100 docs, 0 errors, 6,289 chunks, ~2.12M tokens.

**Parent-context fix (2026-07-10, prompted by user asking about chunk size / overlap):** User asked whether to add chunk overlap. Investigated as an "elite RAG team" question rather than reflexively adding it. Findings, all data-backed: (1) overlap fixes mid-sentence/boundary severing, but this chunker splits only at sentence/section boundaries, so that failure mode is absent by design; (2) the 2 known retrieval misses are cross-document vocabulary confusion, not boundary severing — overlap wouldn't fix either; (3) overlap would actively dilute RRF relevance mass across near-duplicate chunks. So: **did NOT add overlap.** BUT the investigation surfaced a real, worse defect — `parent_section_text` (the "big" half of small-to-big retrieval, the context handed to the LLM at answer time) was computed as just the first 4,000 chars of a section, stamped identically onto every chunk in it. Measured: **26.2% of prose chunks (1,601/6,120) had a parent that didn't even contain their own text** — a chunk from deep in a long section got the section's *opening* as its "context." Fixed with `build_parent_windows()`: each chunk's parent is now a neighbor-window centered on itself, expanded outward to the char cap (small sections still get their full text; large sections get local context). Verified corpus-wide: 26.2% → **0.0%**. Cost was near-zero: `parent_section_text` is NOT embedded (only `text` is), so no re-embed — regenerated processed/ (text/chunk_ids byte-identical, guard-checked), then `update_parent_context.py` pushed only the payload change into Qdrant (`set_payload`, vectors untouched) + re-indexed ES (~4s, now stores parent too). Timing was ideal: caught before Phase 5 (the LLM that consumes parent context) was built, so zero downstream rework. Fresh Qdrant snapshot backup taken (70.6 MB). All 30 non-slow regression tests green; retrieval accuracy provably unchanged (vectors + searchable text identical).

**Bug found via user review (2026-07-10):** user manually inspected `processed/empowering_olympic_paralympic_and_amateur_athletes_act_of_2020.json` and flagged it. Investigation found `section_title` metadata was wrong for 13 consecutive chunks — inline U.S. Code citations like "Section 220504 of title 36, United States Code, is amended—" were matching the same SEC./CHAPTER-prefixed-number regex as real headings (case-insensitive match on "chapter"/"section" mid-sentence), silently overwriting the real "SEC. 7. MODIFICATIONS TO NATIONAL GOVERNING BODIES." attribution. Fixed with `_is_real_structural_heading()`: a real heading's text after the number is either empty or starts a new capitalized title; a citation continues in lowercase or with clause punctuation. Added `test_acts_section_titles_are_not_inline_citations` regression test (13/13 tests now pass). This affected other Acts documents beyond the one flagged — full corpus rebuilt (6,375 → 6,289 chunks after removing spurious fragments).

**Decision (2026-07-10):** Full structured table extraction (Markdown tables, merged-cell dedup) — tax-numeric accuracy matters too much to flatten. Confirmed with real find_tables() test on IRS Pub 501.

**Bugs found + fixed during real-corpus validation (not hypothetical — each confirmed against actual PDFs before and after fix):**
1. Merged-cell table duplication (IRS Pub 501 footnote row tripled across columns)
2. Mid-page watermark not caught by top/bottom-band-only boilerplate detection (SCOTUS "Page Proof Pending Publication" — broadened to whole-page repeat scanning)
3. GPO print-production stamp leaking into "footnotes" + section headers (SEC./TITLE) misclassified as footnotes due to small-font-near-page-bottom heuristic (Acts/PLAW) — added heading-pattern safeguard
4. `§ NUM` citation-in-prose false-triggering Acts-style heading regex on Judgments — made heading patterns category-specific
5. TOC/dot-leader lines matching heading font-size heuristic — added dot-leader exclusion
6. Pull-quote/sidebar callout boxes (larger font, full sentences) misclassified as headings — added "starts-uppercase" guard
7. Document-wide line-count median font size skewed by short cover-page lines, causing false heading matches on normal paragraph text — switched to word-count-weighted median
8. Over-fragmentation: noisy medium-confidence headings created many near-empty "sections" (145 chunks for a 21-page Act) — added tiny-section merging
9. Back-of-book index (dense unpunctuated lines) produced a single 3479-token unsplittable blob — added hard fallback splitter (newline, then raw token-window)
10. Tiny leftover chunks anywhere in a section's sequence (not just at the end) when the next sentence alone triggers an overflow flush — generalized tail-merge into a full-sequence tiny-chunk merge pass
11. `find_tables()` misdetected an IRS worksheet's entire page as one giant table "header" cell (5568 chars) — added malformed-table rejection (falls back to normal prose extraction)
12. Oversized real tables (30+ row worksheets) had no token-budget enforcement — added table splitting with repeated header row per part, plus per-row hard-split safety net

**Known limitation (disclose in eval report):** rare PDF font-embedding defects (undecodable Private-Use-Area ligature glyphs) can drop 1-2 characters in body text; occurs ~1/10 SCOTUS docs, targeted dictionary repair applied for common cases, residual gaps possible. Images/figures are not OCR'd (out of scope) — page-level image counts are tracked in processed_manifest.csv so coverage gaps are visible, not silent.

## Phase 2 — Vector Indexing — ✅ Done
- [x] embed.py (bge-base-en-v1.5, local, 768-dim, asymmetric input_type document/query via BGE's recommended query-instruction prefix)
- [x] vector_indexer.py (Qdrant collection + upsert w/ full metadata payload)
- [x] build_vector_index.py — --resume/--force/--status safety flags (refuses to silently wipe an existing index)
- [x] backup_vector_index.py — Qdrant snapshot export/restore, independent of the Docker volume (tested live mid-build, no disruption; final 6,289-point snapshot taken, 84.7 MB, in backups/)
- [x] evaluate_vector_quality.py — full 100-query golden-set retrieval accuracy (Top-1/3/5, per-category) + embedding integrity checks
- [x] tests/test_phase2_vector.py — 6/6 passing: collection exists, point count matches, dimension matches, 10-query sanity retrieval, no degenerate (zero/NaN) vectors, no duplicate embeddings across distinct chunks
- [x] Full 100-query quality evaluation — **Top-1 91.0% / Top-3 97.0% / Top-5 98.0%**
- [x] Final point-count verification — 6,289/6,289 matches exactly

**Environment change (2026-07-10):** switched from system `py -3.13` to project venv (`venv/`, Python 3.10.0) per user request. All 19 existing tests reverified green under 3.10 — no compatibility issues. All commands now use `./venv/Scripts/python.exe`.

**Embedding provider changed mid-phase: voyage-law-2 (API) → bge-base-en-v1.5 (local).** Full story, in order:
1. Voyage API key is on the free trial tier — confirmed via `x-api-warning` response header: **3 RPM / 10,000 TPM**. First attempt (fixed 100-chunk batches fired back-to-back) hit 429s and crawled with a silently-buffered log, compounding confusion.
2. Rebuilt around proactive token-budgeted pacing — but a second bug (fuzzy string-matching `"token" in error_message` to decide whether to split a batch) misclassified `RateLimitError` as "batch too large" because the error's own free-tier explanation text happens to mention "tokens," causing pointless recursive splitting instead of waiting. Fixed to check exception type, not text.
3. Relaunched — hit persistent rate-limiting again. Root cause #3: batches were sized using `tiktoken`'s count (from Phase 1), but Voyage's real tokenizer counts **~24-41% more tokens** for the same legal text (measured directly: tiktoken=458 vs Voyage real=592 on a real chunk). "Safe" 8-9K-tiktoken-token batches were often already over the true 10K real-token ceiling on arrival. Fixed with adaptive calibration: batch sizing driven by Voyage's own `total_tokens` response field, updated after every batch.
4. With all three bugs fixed, the run was finally stable (~1.2-1.3x real/tiktoken ratio confirmed, batches succeeding) but still projected **7-8 hours** — a hard ceiling from the account tier itself, not fixable in code. **User asked for alternatives.**
5. Explained the actual tradeoff (adding a Voyage payment method unlocks speed, not spending — the free 200M-token allowance still applies regardless of billing status; our corpus is ~2.8M real tokens, ~1.4% of that allowance). **User chose to switch to a local model instead of adding a card.**
6. First pick was `bge-large-en-v1.5` — measured real throughput on this CPU-only (no GPU) machine: **~304 min (~5hr) projected**, worse than fixing Voyage would have been. "Local = fast" doesn't hold for a 335M-param model on long (300-600+ token) legal chunks without a GPU.
7. Measured `bge-base-en-v1.5` (~113 min projected) and `bge-small-en-v1.5` (~20 min projected) for comparison before choosing, rather than guessing again. **User picked bge-base-en-v1.5** as the speed/quality middle ground.
8. Actual full run: **37.6 minutes** (real throughput ~2.8-3.0 chunks/sec, notably better than the ~0.93 chunks/sec isolated-test measurement — likely CPU contention during that earlier test). 6,289/6,289 points, exact match.

**Quality results (full 100-query golden set, not a sample):**
| Category | Top-1 | Top-5 |
|---|---|---|
| Acts | 100.0% | 100.0% |
| POV | 100.0% | 100.0% |
| Judgments | 96.0% | 96.0% |
| Tax | 68.0% | 96.0% |
| **Overall** | **91.0%** | **98.0%** |

Tax is the weakest category on Top-1 (though still 96% by Top-5) — plausible explanation: many IRS publications cover overlapping deduction/threshold concepts, so there's more semantic overlap between *different* tax docs than between e.g. distinct court cases or distinct Acts. Only 2/100 queries missed the top-5 entirely (one tax threshold question, one judgment-dissent-authorship question). Embedding integrity: 0 bad vectors in a 200-point sample (no zero/NaN/wrong-dimension vectors, no duplicate embeddings across distinct chunks).

**Durability:** Docker named volume (`qdrant_data`) persists across container restarts by default; `backup_vector_index.py` adds a second, portable layer — a full Qdrant snapshot downloaded to `backups/`, independent of the volume. `build_vector_index.py` refuses to silently recreate/wipe an existing non-empty collection (`--force` required); `--resume` continues an interrupted run by skipping chunks already indexed (checked via Qdrant scroll, not re-embedded).

**Known limitation (disclose in eval report):** switched away from `voyage-law-2` (legal-domain-tuned) to `bge-base-en-v1.5` (general-purpose) for practical speed reasons on CPU-only hardware. The 91%/98% Top-1/Top-5 accuracy is still strong, but a legal-specialized model would likely do better, particularly on the weaker Tax category.

## Phase 3 — Keyword Indexing — ✅ Done
- [x] es_indexer.py (Elasticsearch, BM25, standard analyzer, category filter support)
- [x] build_keyword_index.py — driver, --force/--status flags matching Phase 2's pattern
- [x] tests/test_phase3_keyword.py — 5/5 passing
- [x] Full corpus indexed: 6,289/6,289 docs, 0 errors, **2.3 seconds** (BM25 indexing is trivially fast vs. embedding generation — no neural network involved)

**Bug found + fixed during test-writing:** `search()`'s "exact phrase" test initially wrapped the query in literal quote characters (`f'"{phrase}"'`) and passed it to a plain Elasticsearch `match` query — but `match` doesn't interpret quote syntax at all; it just tokenizes the quotes as ordinary text. This silently degraded "exact phrase" search into loose bag-of-terms relevance ranking, which failed on 2/15 test phrases that used only common English words (many other chunks in the corpus share those words, so the *actual* source chunk didn't necessarily win top-3 on relevance alone). Fixed by adding a dedicated `search_phrase()` using Elasticsearch's `match_phrase` query type (real word-order/adjacency matching), and pointed the test at it. All 5/5 tests green after the fix.

**Notable:** BM25-only retrieval hit **98.0% Top-5 accuracy** on the full 100-query golden set — matching Phase 2's vector-search accuracy. Makes sense given many golden-set answers were authored close to the source phrasing; still a good sign for Phase 4's hybrid fusion (RRF should benefit from both methods agreeing often, with each covering the other's blind spots on the queries where they diverge).

**Durability note:** unlike Phase 2's embedding index (37.6 min to rebuild), the ES index rebuilds from `processed/*.json` in ~2 seconds — no snapshot/backup mechanism was worth building for something this cheap to regenerate. `build_keyword_index.py --force` is the "backup."

## Phase 4 — Hybrid Retrieval — ✅ Done
- [x] hybrid_retriever.py (RRF fusion, k=60, chunk-level, vector+keyword; `rerank=False` by default — see below)
- [x] reranker.py (bge-reranker-base cross-encoder — implemented, tested, available but off by default)
- [x] tests/test_phase4_hybrid.py — 3/3 passing (20-query benchmark from golden_set.csv)
- [x] evaluate_hybrid_quality.py — full 100-query RRF-vs-reranked comparison
- [x] Full project regression: 33/33 tests passing across all phases

**Final numbers (full 100-query golden set):**
| | Top-1 | Top-3 | Top-5 |
|---|---|---|---|
| **RRF only (default)** | **95.0%** | 97.0% | 99.0% |
| RRF + reranked | 91.0% | 97.0% | 99.0% |

**Disk space incident (2026-07-10):** C: drive hit 0 GB free mid-Phase-4 (reranker model download failed with `OSError: No space left on device`). Root cause: HuggingFace cache (3.49 GB, including `bge-large`/`bge-small` we tested in Phase 2 but aren't using) + pip cache (3.46 GB) + Docker's WSL2 VHDX (26.83 GB, bloated from repeated Qdrant collection rebuilds during Phase 2 debugging — VHDX files don't auto-shrink). **User approved clearing pip cache + unused HF models** (left Docker VHDX and other unrelated cached models — e.g. whisper, timm — untouched, since those aren't ours and compacting Docker needs more care). Freed ~8 GB total (2.05 GB HF + 3.7 GB pip), enough headroom to continue. Worth periodic disk checks going forward given the VHDX will keep growing.

**Reranking decision — measured, not assumed, and it does NOT help on this corpus.** 20-query pytest benchmark first showed a concerning signal (RRF-only 19/20 Top-1, reranked 18/20), too small a sample to trust on its own, so ran the full 100-query comparison: **RRF-only 95.0% vs reranked 91.0% Top-1 — a real 4-point regression**, with zero benefit at Top-3/Top-5 either. Investigated root cause before accepting this: checked whether the reranker's 512-token limit was silently truncating our longer chunks (a plausible bug) — ruled out, since even short, well-under-limit chunks lost to longer, wrong ones in the worsened cases. This is a genuine `bge-reranker-base` limitation on this corpus's near-duplicate content (Tax especially — many IRS publications cover overlapping deduction/threshold topics that a general-purpose reranker struggles to distinguish). Per plan.md's own rule (don't carry known-bad output into the next phase): **`hybrid_search()` now defaults to `rerank=False`.** Reranker code stays in place and tested (`rerank=True` still works correctly) for future experimentation with a better/fine-tuned model, but isn't shipped on by default without earning it. `plan.md`'s Phase 4 section updated to reflect this as the actual (not assumed) result.

## Phase 5 — LLM Answer Generation + Citations — ✅ Done
- [x] llm_service.py — retrieval→grounded-answer→validation, dual-mode client (Vertex AI / AI Studio), 429+503 retry, one-shot citation self-correction, summarize_document()
- [x] citation_validator.py — hallucination guard (marker parsing incl. comma-separated, fabricated-citation + uncited-answer + refusal detection)
- [x] tests/test_phase5_generation.py — 10/10 passing (6 pure-Python validator unit tests + 4 live end-to-end)
- [x] api_test.py — dual-mode connection check
- [x] Manual spot-check: 4 Q&A pairs across categories — all correct, precisely cited to exact doc+page, grounded (e.g. $18,500 expense, 28 U.S.C. § 2107(c), Great Dismal Swamp NHA, IRS admin data — all verbatim-correct with page-accurate citations)

**Model: gemini-2.5-pro** (user chose max-quality GA model over 2.5-flash, fitting the PRD's "high-precision" goal). Configurable via `GEMINI_MODEL` in .env.

**The Gemini API access saga (2026-07-10 → 07-11) — a multi-layer auth/billing journey, all now resolved:**
1. Account issues the new **`AQ.`-prefixed "authorization key"** (Google's 2026 migration away from `AIza` standard keys). The **old `google-generativeai` SDK cannot authenticate AQ. keys** (401 ACCESS_TOKEN_TYPE_UNSUPPORTED). Switched to the new **`google-genai` SDK** (requirements.txt updated). Verified exhaustively (old SDK, new SDK, raw REST × 3 auth methods, 3 API versions) that it was the key, not our code.
2. After the SDK fix, hit **free-tier quotas**: 5 requests/min AND **20 requests/day** for gemini-2.5-flash — far too low for Phase 8's ~100-query eval. Added 429+503 retry to llm_service, but a daily cap can't be waited out.
3. User's **$300 GCP free-trial credit cannot be used on the AI Studio path** (Google explicitly excludes generativelanguage.googleapis.com from the $300 as of March 2026) — but **CAN be used via Vertex AI**. Set up Vertex: enabled Vertex AI API, created a service account (Vertex AI User role) + JSON key, wired dual-mode `get_client()` (GEMINI_USE_VERTEX + GCP_PROJECT + GCP_LOCATION + GOOGLE_APPLICATION_CREDENTIALS). Also fixed a stray-quote parse bug in .env and auto-extracted project_id from the key file. Vertex now runs on the $300 credit with no restrictive per-minute quota (8/8 rapid calls OK). Key file gitignored.

**Bugs/quality issues found + fixed during Phase 5 (against real generations, not hypothetical):**
1. **Citation-compliance slip:** gemini sometimes produced a correct answer but omitted the [N] marker (an uncited legal claim is unusable). Added **one-shot self-correction**: if an answer is substantive but uncited/mis-cited, re-prompt once to fix the citation formatting (facts unchanged). Also strengthened the prompt (MANDATORY CITATIONS).
2. **Validator missed comma-separated markers:** `\[(\d+)\]` matched `[1]` but silently missed `[1, 5]` (a common LLM format), which could wrongly flag a cited answer as uncited. Fixed the extractor to parse all formats; added a regression unit test.
3. **Retrieval-depth refusal:** an in-corpus Acts question refused because its answer chunk ranked #9 — the right *document* was retrieved perfectly (all top-12 were the correct Act), but the specific definition chunk fell outside top-6/8. Raised generation DEFAULT_TOP_K to 12 (~5k tokens, trivial for Gemini), which surfaces the answer instead of refusing. Confirmed fixed.

## Phase 6 — FastAPI Backend + Vanilla JS Frontend — ✅ Done
**User browser-tested (2026-07-11):** Ask tab confirmed working with real queries (mileage deduction, standard deduction, home-office deduction) — grounded answers, clickable citations, correct doc/section/page. Approved to move on.

**Deferred polish (user chose to skip for now, logged for the eval report / future improvement):** For year-agnostic tax questions ("standard deduction if I'm single"), the corpus spans multiple tax years (2025 IRS pubs + 2026 guidance), so retrieval pulls figures from both years and the answer surfaces both ($15,750 for 2025, $16,100 for 2026). Each figure is faithful/correct for its year, but the answer doesn't always label the year cleanly on every figure. Fix (not applied): a system-prompt tweak to always attach the tax year to dollar amounts and explicitly reconcile cross-year differences. No re-indexing needed. Genuine multi-year-corpus characteristic, not a hallucination.

- [x] backend/app/main.py — endpoints: /health, /query, /summarize, /documents, / (serves frontend), /static (assets). Pydantic schemas, category-filter validation, graceful 400/404/502 errors.
- [x] frontend/ — index.html + style.css + app.js. Two tabs (Ask / Summarize), category filter, clickable [N] citation markers that highlight the matching reference, per-citation doc/section/page + source link, grounded/not-grounded badge, live health banner, loading + error states. Vanilla JS, no framework, served same-origin (no CORS).
- [x] tests/test_phase6_api.py — 8/8 passing (6 fast no-LLM: health, documents=100, index HTML, too-short-query 422, bad-category 400, unknown-doc 404; 2 live: valid grounded response schema, category-filter correctness)
- [x] Live HTTP smoke test (server, not just TestClient): /health shows qdrant 6289 + ES ok + gemini-2.5-pro; real query "What penalties apply for unauthorized disclosure of a FISA electronic surveillance application?" → grounded answer cited to Reforming Intelligence and Securing America Act, SEC. 13, p.21-22 (this is literally the PRD's flagship "penalties under Section XYZ" example)
- [ ] User's own browser smoke-test (submit query → answer → citations → error states) — server running at http://127.0.0.1:8000

**Run command:** `./venv/Scripts/python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000` (from project root), then open http://127.0.0.1:8000

## Phase 7 — Graph RAG — ✅ Done
- [x] citation_extractor.py — precision-focused extraction of 4 reference types (U.S.C. sections, Public Laws, named Acts [year-gated], court cases), whitespace-normalized + identifier-normalized
- [x] graph_builder.py — Neo4j graph: Document + Authority nodes, CITES edges, and REFERENCES (doc→doc) edges via 3-way resolution (Public-Law-number → Act doc, Act-name → Act doc, case-name → Judgment doc)
- [x] graph_retriever.py — relationship queries (documents_citing, documents_referencing_title, references_to/from), ground-truth edge checks, context enrichment (enrich_docs), relationship-query routing
- [x] tests/test_phase7_graph.py — 6/6 passing
- [x] Integrated into the demo: /graph/citing API endpoint + "Explore Citations" frontend tab (verified over live HTTP)

**Graph built:** 100 docs, 3,203 distinct legal authorities, 4,075 CITES edges, 12 resolved document→document REFERENCES.

**Real value demonstrated — the PRD's flagship "which Court Judgment cites which Act" works:**
- "which judgments cite the Fiscal Responsibility Act?" → SEVEN COUNTY INFRASTRUCTURE COALITION v. EAGLE COUNTY (correct — that case turns on the Act's NEPA amendments)
- "which documents cite the Clean Air Act?" → 10 docs, correctly clustering the EPA/environmental judgments (Diamond Alternative Energy, EPA v. Calumet, Oklahoma v. EPA...) — something pure vector/keyword search structurally cannot do
- Hand-verified edges: Seven County→Fiscal Responsibility Act, Riley→Parrish (judgment→judgment), Reforming Intelligence Act→50 USC 1801 (FISA)

**Infra notes / issues handled:**
- Neo4j Community Edition doesn't support composite NODE KEY constraints (Enterprise-only) — MERGE on (kind,id) dedupes correctly without it; used a plain composite index for speed instead.
- Discovered a Phase-1 title-extraction quirk: the Seven County judgment's doc_id is `robertson_v_methow_valley_citi` (filename says Robertson, content is Seven County). Tests resolve doc_ids by title rather than hardcoding stems, so they're robust to this.
- Key insight during retriever build: relationship queries by Act *name* miss citations made via the Act's *Public Law number* (e.g. Seven County cites "PL 118-5", not "Fiscal Responsibility Act" by name). The REFERENCES doc→doc edges capture both resolution paths, so `documents_referencing_title()` is the robust way to answer "which X cite Act Y".

## Phase 8 — Evaluation — ✅ Done
- [x] eval/golden_set.csv — 100 rows, 25/category, hand-authored + verified against source PDFs
- [x] tests/test_eval_golden_set.py — 6/6 passing
- [x] eval/run_eval.py — Step 1: 100 queries through the full system → eval/eval_dataset.jsonl (100/100)
- [x] eval/ragas_score.py — Step 3: RAGAS scoring in isolated venv-ragas (custom Gemini-Vertex judge)
- [x] eval/judge_correctness.py — direct correctness judge (RAGAS FactualCorrectness unusable on terse refs, see below)
- [x] tests/test_phase8_eval.py — 5/5 passing
- [x] eval/ragas_scores.csv — full 100-query RAGAS scores
- [x] evaluation_report.md — complete

**FINAL RESULTS (full 100-query end-to-end):**
| Metric | Score |
|---|---|
| Retrieval Top-1 / Top-5 | **95% / 99%** |
| RAGAS Faithfulness | **0.96** (only 3/100 < 0.5) |
| RAGAS Context Recall | **0.98** |
| RAGAS Context Precision | **0.74** |
| Answer Correctness (direct judge) | **91% correct, 98% correct-or-partial** |
| Grounded (cited or proper refusal) | **100%** |
| Hallucinated/ungrounded | **0%** |

**RAGAS FactualCorrectness rejected as invalid for this golden set (documented in report).** It reported 0.23 (F1) / 0.34 (recall) — but 60/100 correct answers scored 0.0. Root cause: our golden references are terse fragments (bare "$250,000", "ITIN") that aren't propositions, so RAGAS's claim-by-claim NLI can't entail them even when the answer contains them verbatim (e.g. reference "ITIN", answer literally contains "Individual Taxpayer Identification Number (ITIN)" → scored 0.0). Replaced with a direct LLM-judge correctness metric (correct/partial/incorrect) appropriate for terse refs → 91% correct / 98% correct-or-partial, which aligns with grounding (100%), faithfulness (0.96), retrieval (95%). This is a genuine RAGAS limitation caught by investigating an anomalous number rather than reporting it blindly.

**Judge model:** gemini-2.5-flash with thinking disabled (thinking_budget=0). All judge calls use the reliable google-genai Vertex path.

**Deterministic metrics (from eval_dataset.jsonl, full 100-query end-to-end):**
- Retrieval Accuracy: **Top-1 95.0% / Top-3 97.0% / Top-5 99.0%** (correct doc in generation context 99%)
- Generation: **Grounded 100%** (every answer cited or a proper refusal), Cited 99%, Refusal 1%
- By category Top-1: Acts 100%, POV 100%, Judgments 96%, Tax 84% (Tax 100% by Top-5 — overlapping IRS-pub vocabulary is the soft spot, consistent with Phase 2)

**RAGAS integration — the hard part, solved cleanly (isolated env + custom judge):**
1. RAGAS is import-incompatible with the main venv's langchain 1.x (ragas even at 0.4.3 hard-imports `langchain_community.chat_models.vertexai`, removed in langchain 1.0). Verified our system has ZERO langchain imports, so the conflict is library-only.
2. Solution: isolated `venv-ragas` (Python 3.10) with a pinned, mutually-consistent stack — ragas 0.2.6 + langchain 0.3.30 + langchain-google-vertexai 2.1.2. Main system 100% untouched (re-verified: 21 fast tests + generation still green after the exploratory in-main-venv install, which was purely additive per pip dry-run).
3. RAGAS's stock LangchainLLMWrapper(ChatVertexAI) failed on this project's Gemini-2.5 models: thinking tokens broke RAGAS's structured-output parsing → LLMDidNotFinishException → all NaN. And gemini-2.0-flash isn't served on this project's Vertex (404 at global and us-central1). Even thinking_budget=0 via ChatVertexAI didn't fix it.
4. Fix: wrote a **custom `GeminiVertexRagasLLM(BaseRagasLLM)`** that calls the same reliable `google-genai` Vertex client the whole system uses, with `thinking_config(thinking_budget=0)` + a high token budget. 3-sample smoke test then produced real scores (faithfulness 1.0, context_recall 1.0, context_precision 0.86) — pipeline validated before the full run.

**Design decision — decouple generation from scoring:** run_eval (main venv) produces the dataset; ragas_score (isolated venv) scores it. Best practice — lets us re-score without re-running the expensive generation, and keeps RAGAS's broken deps fully quarantined.

**Transient-error fix:** the first dataset-gen run died at 44/100 on a one-off `httpx.RemoteProtocolError` ("Server disconnected"). Added httpx transient-error retry to llm_service._generate_with_retry (benefits the live app too); resumed from 44 → 100.

**Decision (2026-07-10):** Built golden set now (in parallel with Phase 2) rather than waiting for Phase 8 — avoids duplicating Phase 4's retrieval-benchmark query set, and surfaces corpus weak spots early. User chose 100 queries, mixed difficulty (56 easy / 34 medium / 10 hard), 25 per category.

**Process:** `eval/sample_candidates.py` sampled a diverse pool of real chunks (1 per doc for Acts/Judgments/POV, ~4 per doc for Tax) into `eval/candidates.json`. Each of the 100 Q&A pairs was then hand-authored directly against that real text and written into `eval/build_golden_set.py`.

**Bug found during re-verification:** one Acts answer (Taxpayer First Act, SEC. 1206) described the wrong provision — the "summonses" effective-date clause I quoted actually belongs to SEC. 1207, not SEC. 1206 (misattribution from a truncated preview during authoring; the 45-day figure coincidentally matched both sections, masking it). Caught by re-checking full page context against every claimed page/fact, fixed to describe SEC. 1206's real clause (about notices/contacts, not summonses). Two other apparent mismatches during re-verification turned out to be false alarms caused by naive substring search not handling PDF line-wraps (e.g. "Great Dismal \nSwamp") — content was correct.

## Phase 9 — Final Deliverables — ✅ Done
- [x] Architecture diagram — `ARCHITECTURE.md` (Mermaid: high-level flowchart + request-lifecycle sequence diagram + component table + design rationale)
- [x] `README.md` — full setup/run/API/testing/evaluation docs + project structure (was missing; primary deliverable)
- [x] Full regression (all tests/ green) — **63/63 passing** across all 8 phases
- [x] Final evaluation_report.md — complete (95%/99% retrieval, 0.96 faithfulness, 91%/98% correctness, 100% grounded / 0% hallucinated)
- [x] Demo polish — backend imports clean (10 routes), frontend's 5 `fetch` calls verified against the 5 API endpoints

**Deliverables shipped:** `README.md`, `ARCHITECTURE.md` (both new), `evaluation_report.md`, 63-test regression suite, isolated `venv-ragas` eval harness. All 9 phases complete.

---

## Phase 10 — Hugging Face Deployment (server-less variant) — ✅ Done

Goal: deploy the system on the HF Spaces free CPU tier **without quality loss**, keeping all four capabilities including Graph RAG. Built as a fully additive, self-contained folder (`deploy/huggingface/`); the main Neo4j/Qdrant/ES system and the `legalrag` package are reused read-only and never modified. Auth: **Vertex AI (service account) · gemini-2.5-pro · public Space** (user-chosen).

**Architecture — servers replaced by in-process equivalents (single container):**
| Capability | Main | HF variant | Parity |
|---|---|---|---|
| Generation | Gemini 2.5 Pro | reused verbatim (`generate_answer`) | identical |
| Embeddings | bge-base-en-v1.5 | reused | identical |
| Vector search | Qdrant (ANN) | numpy exact cosine over exported vectors | ≥ (exact) |
| Keyword search | Elasticsearch BM25 | `rank_bm25` (ES-matched: k1=1.2, b=0.75, standard-analyzer tokens) | Top-5 identical |
| Graph RAG | Neo4j | `networkx` in-memory (same extraction/resolution) | **exact match** |
| Fusion | RRF k=60 | same RRF code (imported) | identical |

**Measured before/after (100-query golden set, gemini-2.5-pro):**
| Metric | Main | HF variant |
|---|---|---|
| Retrieval Top-1 | 95.0% | 93.0% (−2%, 2 tax queries) |
| Retrieval Top-5 | 99.0% | **99.0%** |
| Grounded | 100% | **100%** |
| Has citation | 99% | **99%** |
| Answer correctness | 91% / 98% | **91% / 98%** |
- Graph parity independently verified: 300 queries (all doc titles + 200 authorities) → **0 mismatches**.
- The only delta is a 2% Top-1 retrieval dip (BM25 swap) on 2 tax queries whose correct doc still lands in the top-12 generation context — hence **answer correctness is unchanged**.

**Deliverables (`deploy/huggingface/`):** `Dockerfile` (single CPU container, port 7860, bge baked in), `README.md` (HF Space metadata), `DEPLOY.md` (push guide + secrets), `app/` (FastAPI + stores + graph_local + retrieval), vendored `legalrag`, prebuilt `data/artifacts/` (vectors.npy, payloads.json, graph.pkl), `build_artifacts.py`, `parity_check.py`, `eval_variant.py`, `compare_eval.py`.

**Gate:** `docker build` OK (1.88 GB); container serves `/health`, a live gemini-2.5-pro `/query` (grounded, cited, via the Vertex secret shim), and `/graph/citing` (real citing docs) — verified then cleaned up. Ready for the user to push (they hold the HF token).

**Finding — FIXED (2026-07-12):** building the graph surfaced a latent bug in the main Neo4j `graph_builder` — its `MATCH..MERGE` dropped ~10 of 22 real doc→doc REFERENCES (any whose target is created later in sorted-glob order). **Fix:** create all Document nodes in a first pass, then add edges, so every resolved reference is captured. Applied to **both** the main builder and the HF `build_artifacts.py`, then Neo4j and `graph.pkl` were rebuilt (**references 12 → 22**) and graph parity re-verified exact (300 queries, 0 mismatches). Phase 7 tests stay green (they assert `references >= 5`, not an exact count).

---

## Phase 11 — Post-deployment fixes — ✅ Done (2026-07-12)
- [x] **Graph RAG references bug fix** — `graph_builder.build_graph` now creates all Document nodes before edges; recovers ~10 previously-dropped doc→doc references (12 → 22). Applied to main + HF variant; both rebuilt and re-verified at exact parity.
- [x] **Tax-year disambiguation** — added rule 6 to `llm_service.SYSTEM_PROMPT`: when sources give different figures for different tax years, label each figure with its year and lead with the asked-for year. Flows to the HF Space via the reused generation path (vendor refreshed).

---

## Open questions for user
- [ ] Golden set: will it be provided, or should we construct one from the corpus? (needed before Phase 8, not urgent yet)
- [ ] Reranker model: default `bge-reranker-base` planned — confirm or swap at Phase 4.

## Decisions log
- 2026-07-10 — LLM: Gemini 2.5 Flash. Backend: FastAPI. Frontend: Vanilla JS.
- 2026-07-10 — Docker available → Elasticsearch + Neo4j run as Docker containers.
- 2026-07-10 — Embeddings: voyage-law-2 (legal-domain-tuned).
- 2026-07-10 — Vector DB: Qdrant.
- 2026-07-10 — Data corpus finalized: 100 docs (30 Acts / 30 Court Judgments / 30 POV / 10 Tax Documents), 15–60 page band, native PDF only.
