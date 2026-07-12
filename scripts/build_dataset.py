#!/usr/bin/env python3
"""
build_dataset.py — Curated PDF-only corpus builder for the US Tax & Legal RAG system.

Goal: ~100 native-text PDFs, ALL within a consistent page band (default 15-60 pages),
balanced across Acts / Court Judgments / POV / Tax Documents. No HTML. Real extractable text only.

Sources (all native PDF, auto-discovered):
  - Court Judgments: supremecourt.gov slip/preliminary-print opinions
  - Acts           : GovInfo public-law PDFs (bulkdata listing per Congress)
  - POV            : Congressional Research Service reports via EveryCRSReport mirror (legal commentary / expert analysis)
  - Tax Documents  : IRS publication PDFs (curated list)

Each candidate is downloaded, verified as a real PDF, opened with PyMuPDF, and KEPT only if:
  - PAGE_MIN <= page_count <= PAGE_MAX
  - it has real extractable text (rejects scanned/image-only/empty PDFs)
  - it is not a duplicate (sha256)

Outputs:
  dataset/<category>/<slug>.pdf         the kept documents
  documents_manifest.csv                final manifest (kept docs only)
  dataset/_reports/build_report.csv     every attempt + outcome/reason
  sources.md                            human-readable source list
"""
import argparse, csv, hashlib, io, re, sys, time
from pathlib import Path
import requests
import fitz  # PyMuPDF

from legalrag import config

# ---------------- config ----------------
ROOT = config.PROJECT_ROOT
DATA = ROOT / "dataset"
REPORTS = DATA / "_reports"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
PAGE_MIN, PAGE_MAX = 15, 60
MIN_WORDS_PER_PAGE = 50      # reject scanned/near-empty PDFs
MIN_TOTAL_WORDS = 400
TARGET_PER_CAT = 25
TOTAL_TARGET = 100
TIMEOUT = 60

SESS = requests.Session()
SESS.headers.update({"User-Agent": UA, "Accept": "*/*"})

def log(msg): print(msg, flush=True)

def slugify(s, maxlen=70):
    s = re.sub(r"[^\w\s-]", "", s.lower()).strip()
    s = re.sub(r"[\s_-]+", "_", s)
    return s[:maxlen].strip("_") or "doc"

def http_get(url, stream=False, tries=3, headers=None):
    last = None
    for i in range(tries):
        try:
            r = SESS.get(url, timeout=TIMEOUT, stream=stream, allow_redirects=True, headers=headers)
            if r.status_code == 200:
                return r
            last = f"HTTP {r.status_code}"
        except Exception as e:
            last = str(e)[:120]
        time.sleep(1.2 * (i + 1))
    raise RuntimeError(last or "failed")

# ---------------- candidate generators ----------------
# Each yields dicts: {title, url, source_org, year, resolve?}  (resolve = callable -> (pdf_url, title))

def gen_judgments():
    src = "Supreme Court of the United States"
    for term in ("24", "23", "22", "21", "20"):
        try:
            html = http_get(f"https://www.supremecourt.gov/opinions/slipopinion/{term}").text
        except Exception as e:
            log(f"  [judgments] term {term} index failed: {e}"); continue
        links = []
        for m in re.findall(rf"/opinions/{term}pdf/[^\"'>]+\.pdf", html):
            if m not in links:
                links.append(m)
        for path in links:
            yield {"title": None, "url": "https://www.supremecourt.gov" + path,
                   "source_org": src, "year": "20" + term}

def gen_acts():
    src = "GovInfo (U.S. GPO)"
    for congress in ("118", "117", "116", "115", "114", "113"):
        try:
            xml = http_get(f"https://www.govinfo.gov/bulkdata/PLAW/{congress}/public",
                           headers={"Accept": "application/xml"}).text
        except Exception as e:
            log(f"  [acts] congress {congress} listing failed: {e}"); continue
        ids = []
        for m in re.findall(rf"PLAW-{congress}publ\d+", xml):
            if m not in ids:
                ids.append(m)
        # newest public-law numbers last; iterate ascending is fine
        for pid in ids:
            url = f"https://www.govinfo.gov/content/pkg/{pid}/pdf/{pid}.pdf"
            yield {"title": None, "url": url, "source_org": src, "year": ""}

CRS_TOPICS = ["american-law", "constitutional-questions", "crime-policy",
              "health-policy", "immigration-policy", "industry-and-trade"]

def gen_pov():
    src = "Congressional Research Service"
    seen = set()
    for topic in CRS_TOPICS:
        try:
            html = http_get(f"https://www.everycrsreport.com/topics/{topic}.html").text
        except Exception as e:
            log(f"  [pov] topic {topic} failed: {e}"); continue
        ids = []
        for m in re.findall(r"/reports/([A-Z0-9]+)\.html", html):
            if m not in ids and m not in seen:
                ids.append(m); seen.add(m)
        for rid in ids:
            def resolve(rid=rid):
                page = http_get(f"https://www.everycrsreport.com/reports/{rid}.html").content.decode("utf-8", errors="replace")
                mm = re.search(r'/files/[^"\']+?_' + re.escape(rid) + r'_[^"\']+?\.pdf', page)
                if not mm:
                    mm = re.search(r'/files/[^"\']+?\.pdf', page)
                if not mm:
                    raise RuntimeError("no pdf link on landing")
                pdf = "https://www.everycrsreport.com" + mm.group(0)
                tm = re.search(r"<title>(.*?)</title>", page, re.S)
                if tm:
                    title = re.sub(r"\s+", " ", tm.group(1)).split("|")[0].strip()
                    title = re.sub(r"\s*-\s*EveryCRSReport\.com\s*$", "", title, flags=re.I)
                else:
                    title = rid
                return pdf, title
            yield {"title": None, "url": None, "resolve": resolve,
                   "source_org": src, "year": "", "rid": rid}

# curated IRS publications (num, human title). Filtered to band on download.
IRS_PUBS = [
    ("17", "Your Federal Income Tax (For Individuals)"),
    ("334", "Tax Guide for Small Business"),
    ("463", "Travel, Gift, and Car Expenses"),
    ("501", "Dependents, Standard Deduction, and Filing Information"),
    ("502", "Medical and Dental Expenses"),
    ("503", "Child and Dependent Care Expenses"),
    ("505", "Tax Withholding and Estimated Tax"),
    ("509", "Tax Calendars"),
    ("514", "Foreign Tax Credit for Individuals"),
    ("515", "Withholding of Tax on Nonresident Aliens"),
    ("517", "Social Security for Members of the Clergy"),
    ("519", "U.S. Tax Guide for Aliens"),
    ("523", "Selling Your Home"),
    ("524", "Credit for the Elderly or the Disabled"),
    ("525", "Taxable and Nontaxable Income"),
    ("526", "Charitable Contributions"),
    ("527", "Residential Rental Property"),
    ("529", "Miscellaneous Deductions"),
    ("530", "Tax Information for Homeowners"),
    ("531", "Reporting Tip Income"),
    ("535", "Business Expenses"),
    ("536", "Net Operating Losses"),
    ("537", "Installment Sales"),
    ("541", "Partnerships"),
    ("542", "Corporations"),
    ("544", "Sales and Other Dispositions of Assets"),
    ("547", "Casualties, Disasters, and Thefts"),
    ("550", "Investment Income and Expenses"),
    ("551", "Basis of Assets"),
    ("554", "Tax Guide for Seniors"),
    ("555", "Community Property"),
    ("556", "Examination of Returns and Appeal Rights"),
    ("559", "Survivors, Executors, and Administrators"),
    ("560", "Retirement Plans for Small Business"),
    ("561", "Determining the Value of Donated Property"),
    ("571", "Tax-Sheltered Annuity Plans (403(b))"),
    ("575", "Pension and Annuity Income"),
    ("587", "Business Use of Your Home"),
    ("590-A", "Contributions to Individual Retirement Arrangements (IRAs)"),
    ("590-B", "Distributions from Individual Retirement Arrangements (IRAs)"),
    ("594", "The IRS Collection Process"),
    ("596", "Earned Income Credit (EIC)"),
    ("597", "Tax on U.S. Income for Residents of Canada"),
    ("721", "Tax Guide to U.S. Civil Service Retirement Benefits"),
    ("915", "Social Security and Equivalent Railroad Retirement Benefits"),
    ("925", "Passive Activity and At-Risk Rules"),
    ("929", "Tax Rules for Children and Dependents"),
    ("936", "Home Mortgage Interest Deduction"),
    ("946", "How To Depreciate Property"),
    ("969", "Health Savings Accounts and Other Tax-Favored Health Plans"),
    ("970", "Tax Benefits for Education"),
    ("971", "Innocent Spouse Relief"),
    ("974", "Premium Tax Credit (PTC)"),
    ("1212", "Guide to Original Issue Discount (OID) Instruments"),
    ("3402", "Taxation of Limited Liability Companies"),
]

def gen_tax():
    src = "Internal Revenue Service"
    for num, title in IRS_PUBS:
        url = f"https://www.irs.gov/pub/irs-pdf/p{num.lower().replace('-','')}.pdf"
        yield {"title": f"IRS Publication {num} — {title}", "url": url,
               "source_org": src, "year": ""}

GENERATORS = {
    "judgments": gen_judgments,
    "acts": gen_acts,
    "pov": gen_pov,
    "tax": gen_tax,
}

# ---------------- title extraction ----------------
_SCOTUS_STOP = r"(?:certiorari|on\s+(?:application|writ|petition)|appeal\s+from|argued|decided|no\.\s*\d+\s*[-–]\s*\d+)"

def title_from_scotus(doc):
    txt = " ".join(doc[p].get_text() for p in range(min(4, len(doc))))
    txt = re.sub(r"­\s*", "", txt)  # PDF soft-hyphen line-wrap markers (e.g. "CALU­ MET" -> "CALUMET")
    txt = re.sub(r"\bSyllabus\b", " ", txt)
    txt = re.sub(r"\s+", " ", txt)
    m = re.search(r"([A-Z][A-Za-z.,'&()\- ]{2,100}?)\s+v\.\s+([A-Z][A-Za-z0-9.,'&()\- ]{2,100}?)(?=\s+" + _SCOTUS_STOP + r"\b)", txt, re.I)
    if not m:
        m = re.search(r"([A-Z][A-Za-z.,'&()\- ]{2,100}?)\s+v\.\s+([A-Z][A-Za-z0-9.,'&()\- ]{2,100})", txt)
    if m:
        a = re.sub(r"\s+", " ", m.group(1)).strip(" ,.")
        b = re.sub(r"\s+", " ", m.group(2)).strip(" ,.")
        b = re.split(r"\b" + _SCOTUS_STOP + r"\b", b, flags=re.I)[0].strip(" ,.")
        return f"{a} v. {b}"
    return None

def title_from_plaw(doc, url):
    txt = "\n".join(doc[p].get_text() for p in range(len(doc)))
    txt = re.sub(r"(\w)-\n(\w)", r"\1\2", txt)   # dehyphenate PDF line-wraps before collapsing whitespace
    txt = re.sub(r"\s+", " ", txt)
    # legal short titles are wrapped in doubled curly quotes: cited as the ''X'' or "X"
    for pat in (r"cited as (?:the )?‘‘(.+?)’’",
                r'cited as (?:the )?"(.+?)"',
                r"cited as (?:the )?'(.+?)'"):
        m = re.search(pat, txt)
        if m and len(m.group(1)) <= 150:
            return re.sub(r"\s+", " ", m.group(1)).strip(" ,.‘’“”\"'")
    pid = re.search(r"PLAW-(\d+)publ(\d+)", url)
    return f"Public Law {pid.group(1)}-{pid.group(2)}" if pid else "Public Law"

# ---------------- core ----------------
def evaluate_pdf(content):
    """Return (ok, pages, words, reason). ok=True only if within band & real text."""
    if not content[:5].startswith(b"%PDF"):
        return False, 0, 0, "not a PDF (bad magic bytes)"
    try:
        doc = fitz.open(stream=content, filetype="pdf")
    except Exception as e:
        return False, 0, 0, f"unreadable: {str(e)[:60]}"
    pages = len(doc)
    words = sum(len(doc[p].get_text().split()) for p in range(pages))
    if pages < PAGE_MIN:
        doc.close(); return False, pages, words, f"too short ({pages}p < {PAGE_MIN})"
    if pages > PAGE_MAX:
        doc.close(); return False, pages, words, f"too long ({pages}p > {PAGE_MAX})"
    if words < MIN_TOTAL_WORDS or words / max(pages, 1) < MIN_WORDS_PER_PAGE:
        doc.close(); return False, pages, words, f"insufficient text ({words}w, scanned/empty?)"
    return True, pages, words, doc  # returns open doc for title extraction

def build(targets):
    REPORTS.mkdir(parents=True, exist_ok=True)
    manifest, report = [], []
    seen_sha, seen_title = set(), set()
    counts = {c: 0 for c in GENERATORS}

    def want(cat):
        return counts[cat] < targets[cat] and sum(counts.values()) < TOTAL_TARGET

    for cat, gen in GENERATORS.items():
        log(f"\n=== {cat.upper()} (target {targets[cat]}) ===")
        for cand in gen():
            if not want(cat):
                break
            url, title = cand.get("url"), cand.get("title")
            try:
                if cand.get("resolve"):
                    url, title = cand["resolve"]()
                r = http_get(url, stream=True)
                content = r.content
            except Exception as e:
                report.append([cat, title or cand.get("rid") or url, url or "", "", "", "skip", f"download failed: {str(e)[:80]}"])
                continue

            res = evaluate_pdf(content)
            ok, pages, words = res[0], res[1], res[2]
            if not ok:
                report.append([cat, title or url, url, pages, words, "skip", res[3]])
                continue
            doc = res[3]

            # derive title
            if cat == "judgments":
                title = title_from_scotus(doc) or title or url.split("/")[-1]
            elif cat == "acts":
                title = title_from_plaw(doc, url)
            elif not title:
                title = (doc.metadata or {}).get("title") or url.split("/")[-1]
            doc.close()

            sha = hashlib.sha256(content).hexdigest()
            tkey = slugify(title)
            if sha in seen_sha or tkey in seen_title:
                report.append([cat, title, url, pages, words, "skip", "duplicate"])
                continue

            slug = slugify(title)
            out = DATA / cat / f"{slug}.pdf"
            n = 2
            while out.exists():
                out = DATA / cat / f"{slug}_{n}.pdf"; n += 1
            out.write_bytes(content)
            seen_sha.add(sha); seen_title.add(tkey); counts[cat] += 1
            manifest.append({
                "title": title, "category": cat, "source_org": cand["source_org"],
                "url": url, "year": cand.get("year", ""), "pages": pages,
                "words": words, "local_path": str(out.relative_to(ROOT)),
                "sha256": sha,
            })
            report.append([cat, title, url, pages, words, "kept", ""])
            log(f"  [{counts[cat]:>2}/{targets[cat]}] {pages:>3}p  {title[:60]}")

    # top-up from large pools if under total target
    total = sum(counts.values())
    if total < TOTAL_TARGET:
        log(f"\n=== TOP-UP: {total}/{TOTAL_TARGET}, drawing extra from large pools ===")
        # already-iterated generators are exhausted-consumed lazily; re-run for headroom cats
        for cat in ("judgments", "pov", "acts"):
            if sum(counts.values()) >= TOTAL_TARGET:
                break
            targets[cat] = 40  # raise cap
            # NOTE: generators are fresh each call
            for cand in GENERATORS[cat]():
                if sum(counts.values()) >= TOTAL_TARGET or counts[cat] >= targets[cat]:
                    break
                url, title = cand.get("url"), cand.get("title")
                try:
                    if cand.get("resolve"):
                        url, title = cand["resolve"]()
                    content = http_get(url, stream=True).content
                except Exception:
                    continue
                res = evaluate_pdf(content)
                if not res[0]:
                    continue
                pages, words, doc = res[1], res[2], res[3]
                if cat == "judgments":
                    title = title_from_scotus(doc) or title or url.split("/")[-1]
                elif cat == "acts":
                    title = title_from_plaw(doc, url)
                doc.close()
                sha = hashlib.sha256(content).hexdigest()
                tkey = slugify(title)
                if sha in seen_sha or tkey in seen_title:
                    continue
                slug = slugify(title); out = DATA / cat / f"{slug}.pdf"; k = 2
                while out.exists():
                    out = DATA / cat / f"{slug}_{k}.pdf"; k += 1
                out.write_bytes(content)
                seen_sha.add(sha); seen_title.add(tkey); counts[cat] += 1
                manifest.append({"title": title, "category": cat, "source_org": cand["source_org"],
                                 "url": url, "year": cand.get("year", ""), "pages": pages,
                                 "words": words, "local_path": str(out.relative_to(ROOT)), "sha256": sha})
                report.append([cat, title, url, pages, words, "kept", "top-up"])
                log(f"  [top-up {cat}] {pages:>3}p  {title[:55]}")

    return manifest, report, counts

def write_outputs(manifest, report, counts):
    # manifest
    with open(ROOT / "documents_manifest.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["title","category","source_org","url","year","pages","words","local_path","sha256"])
        w.writeheader(); w.writerows(manifest)
    # report
    with open(REPORTS / "build_report.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["category","title","url","pages","words","outcome","reason"]); w.writerows(report)
    # sources.md
    display_name = {
        "acts": "Acts",
        "judgments": "Court Judgments",
        "pov": "POV (Point of View)",
        "tax": "Tax Documents",
    }
    lines = ["# Data Sources — US Tax & Legal RAG Corpus\n",
             f"Total documents: **{len(manifest)}**  |  Page band: **{PAGE_MIN}–{PAGE_MAX} pages**  |  Format: **native-text PDF only**\n",
             "| Category | Count |", "|---|---|"]
    for c in GENERATORS:
        lines.append(f"| {display_name[c]} | {counts[c]} |")
    lines.append(f"| **Total** | **{len(manifest)}** |\n")
    pages = [m["pages"] for m in manifest]
    if pages:
        lines.append(f"Page-count range across corpus: **{min(pages)}–{max(pages)}** (mean {round(sum(pages)/len(pages))}).\n")
    src_by_cat = {
        "acts": "GovInfo (U.S. Government Publishing Office) — official public-law PDFs",
        "judgments": "Supreme Court of the United States — official slip/preliminary-print opinions",
        "pov": "Congressional Research Service (CRS) reports, via the EveryCRSReport.com mirror",
        "tax": "Internal Revenue Service (IRS) — official publication PDFs",
    }
    for cat in GENERATORS:
        docs = [m for m in manifest if m["category"] == cat]
        lines.append(f"\n## {display_name[cat]}  ({len(docs)} docs)")
        lines.append(f"*Source: {src_by_cat[cat]}*\n")
        lines.append("| # | Title | Pages | URL |")
        lines.append("|---|---|---|---|")
        for i, m in enumerate(sorted(docs, key=lambda x: x["title"]), 1):
            lines.append(f"| {i} | {m['title']} | {m['pages']} | {m['url']} |")
    (ROOT / "sources.md").write_text("\n".join(lines), encoding="utf-8")

def main():
    global TOTAL_TARGET
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-cat", type=int, default=TARGET_PER_CAT)
    ap.add_argument("--total", type=int, default=None)
    ap.add_argument("--acts", type=int, default=None)
    ap.add_argument("--judgments", type=int, default=None)
    ap.add_argument("--pov", type=int, default=None)
    ap.add_argument("--tax", type=int, default=None)
    args = ap.parse_args()
    targets = {c: args.per_cat for c in GENERATORS}
    for cat in GENERATORS:
        override = getattr(args, cat)
        if override is not None:
            targets[cat] = override
    TOTAL_TARGET = args.total if args.total is not None else sum(targets.values())
    t0 = time.time()
    manifest, report, counts = build(targets)
    write_outputs(manifest, report, counts)
    log(f"\n{'='*50}\nDONE in {int(time.time()-t0)}s")
    for c in GENERATORS:
        log(f"  {c:<12}: {counts[c]}")
    log(f"  {'TOTAL':<12}: {len(manifest)}")
    log(f"Outputs: documents_manifest.csv, sources.md, dataset/_reports/build_report.csv")

if __name__ == "__main__":
    main()
