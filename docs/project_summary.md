# Legal RAG Dataset — Progress Summary

## Goal
Build a 100+ document dataset (Acts, Judgments, Commentary, Tax) for a US Tax & Legal RAG system — page-level citations, hybrid search, Graph RAG.

## What's Done

**1. Downloader script** (`download_legal_rag_dataset.py`)
Reads manifest → downloads → verifies (size, PDF magic bytes, page count) → writes reports. Safe to re-run (skips existing files). HTML sources are saved as `.html`, not force-converted to fake PDFs.

**2. First run — 21 docs**
- 19 succeeded, 2 failed (403/404 dead links)
- Mix of PDF (GovInfo, Supreme Court, IRS) and HTML (Cornell LII, ADA.gov)

**3. Fixed both failures**
| Doc | Old (broken) | New (working) |
|---|---|---|
| ERISA Act | dol.gov (403 Forbidden) | `govinfo.gov/content/pkg/STATUTE-88/pdf/STATUTE-88-Pg829.pdf` |
| NFIB v. Sebelius | supremecourt.gov (404) | `supreme.justia.com/cases/federal/us/567/11-393/case.pdf` |

**4. Expanded manifest → 129 documents**

| Category | Count | Primary source |
|---|---|---|
| Acts | 36 | GovInfo PDFs (major standalone laws) + Cornell LII HTML (U.S. Code titles) |
| Judgments | 35 | Justia `case.pdf` mirrors (reliable, predictable URL pattern) |
| Commentary | 44 | Cornell LII Wex encyclopedia + CRS Reports (PDF) |
| Tax | 14 | IRS publications (native PDF) |

## Key Decision: HTML vs PDF
Cornell LII / ADA.gov don't publish PDFs — only live HTML. Kept as HTML deliberately (forcing PDF conversion would break the parser). **Tradeoff:** cite these by section number (§) instead of page number — this is standard practice for statutes anyway.

## Files Delivered
- `documents_manifest.csv` — 129-row input manifest
- `download_legal_rag_dataset.py` — downloader/verifier script

## Next Steps
1. Run the script: `python3 download_legal_rag_dataset.py`
2. Check `dataset/_reports/failed_downloads.csv` for any new dead links — send back for URL fixes
3. Decide: keep HTML as-is (cite by §) or convert to PDF for uniform page-based citation
4. Build Golden Set eval queries once dataset is populated
