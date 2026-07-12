#!/usr/bin/env python3
"""
compare_eval.py — build the before/after (main vs HF variant) metrics table.

Reads:
  eval/eval_dataset.jsonl      (main system — Qdrant+ES+Neo4j, gemini-2.5-pro)
  eval/eval_dataset_hf.jsonl   (HF variant — numpy+bm25+networkx, gemini-2.5-pro)

Computes the deterministic metrics for both (retrieval Top-1/Top-5, grounded,
refusal, citation rate), then runs the SAME direct correctness judge
(gemini-2.5-flash, thinking off) on the HF answers so answer-correctness is
comparable to the main 91%/98%.

Run from repo root (main venv):
    ./venv/Scripts/python.exe deploy/huggingface/compare_eval.py
"""
import json
import os
import re
import time
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(ROOT / ".env")
MAIN = ROOT / "eval" / "eval_dataset.jsonl"
HF = ROOT / "eval" / "eval_dataset_hf.jsonl"
HF_VERDICTS = ROOT / "eval" / "correctness_verdicts_hf.json"


def load(p):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def det_metrics(rows):
    n = len(rows)
    top1 = sum(1 for r in rows if r["retrieval_rank"] == 1) / n
    top5 = sum(1 for r in rows if r["retrieval_rank"] and r["retrieval_rank"] <= 5) / n
    grounded = sum(1 for r in rows if r["grounded"]) / n
    refusal = sum(1 for r in rows if r["is_refusal"]) / n
    cited = sum(1 for r in rows if r["has_citation"]) / n
    return dict(n=n, top1=top1, top5=top5, grounded=grounded, refusal=refusal, cited=cited)


PROMPT = """Judge whether the CANDIDATE answer correctly conveys the fact in the REFERENCE answer to the QUESTION.
Reply with ONE word only: CORRECT (candidate contains the reference's key fact), PARTIAL (partially correct or incomplete), or INCORRECT (wrong or missing).

QUESTION: {q}
REFERENCE: {ref}
CANDIDATE: {ans}

Verdict:"""


def judge_correctness(rows):
    client = genai.Client(vertexai=True, project=os.environ["GCP_PROJECT"],
                          location=os.environ.get("GCP_LOCATION", "global"))
    cfg = types.GenerateContentConfig(temperature=0.0, max_output_tokens=200,
                                      thinking_config=types.ThinkingConfig(thinking_budget=0))
    verdicts = []
    for i, r in enumerate(rows, 1):
        p = PROMPT.format(q=r["user_input"], ref=r["reference"], ans=r["response"])
        for _ in range(5):
            try:
                resp = client.models.generate_content(model="gemini-2.5-flash", contents=p, config=cfg)
                m = re.search(r"CORRECT|PARTIAL|INCORRECT", (resp.text or "").upper())
                verdicts.append(m.group(0) if m else "UNKNOWN"); break
            except Exception as e:
                if "RESOURCE_EXHAUSTED" in str(e) or "UNAVAILABLE" in str(e):
                    time.sleep(8); continue
                verdicts.append("ERROR"); break
        if i % 20 == 0:
            print(f"  judged {i}/{len(rows)}", flush=True)
    return verdicts


def main():
    main_rows = load(MAIN)
    hf_rows = load(HF)
    dm, dh = det_metrics(main_rows), det_metrics(hf_rows)

    print("\n=== DETERMINISTIC METRICS: main vs HF variant ===")
    print(f"  {'metric':22}{'main':>10}{'HF variant':>12}")
    for key, label in [("top1", "Retrieval Top-1"), ("top5", "Retrieval Top-5"),
                       ("grounded", "Grounded"), ("cited", "Has citation"), ("refusal", "Refusal")]:
        print(f"  {label:22}{dm[key]:>9.1%}{dh[key]:>12.1%}")

    # correctness on HF answers (main already known: 91% CORRECT / 98% CORRECT+PARTIAL)
    if HF_VERDICTS.exists():
        verdicts = json.loads(HF_VERDICTS.read_text(encoding="utf-8"))
        verdicts = [verdicts[r["user_input"]] for r in hf_rows]
    else:
        print("\nJudging HF answer correctness (gemini-2.5-flash)...")
        verdicts = judge_correctness(hf_rows)
        HF_VERDICTS.write_text(json.dumps(dict(zip([r["user_input"] for r in hf_rows], verdicts)), indent=1),
                               encoding="utf-8")
    c = Counter(verdicts); n = len(verdicts)
    print("\n=== ANSWER CORRECTNESS (HF variant, direct judge) ===")
    print(f"  CORRECT:            {c['CORRECT']}/{n} ({c['CORRECT']/n:.0%})")
    print(f"  PARTIAL:            {c['PARTIAL']}/{n} ({c['PARTIAL']/n:.0%})")
    print(f"  INCORRECT:          {c['INCORRECT']}/{n} ({c['INCORRECT']/n:.0%})")
    print(f"  correct-or-partial: {(c['CORRECT']+c['PARTIAL'])/n:.0%}")
    print("\n  (main system reference: 91% CORRECT / 98% correct-or-partial)")


if __name__ == "__main__":
    main()
