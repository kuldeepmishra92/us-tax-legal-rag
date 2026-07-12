"""Direct answer-correctness judge — appropriate for terse golden references
that RAGAS FactualCorrectness can't handle (it needs full propositions to run
its claim-by-claim NLI; a bare "$250,000" or "ITIN" reference produces false
zeros even when the answer contains it verbatim).

Runs in the MAIN venv with google-genai (gemini-2.5-flash, thinking off)."""
import json
import os
import re
import time
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
client = genai.Client(vertexai=True, project=os.environ["GCP_PROJECT"],
                      location=os.environ.get("GCP_LOCATION", "global"))
CFG = types.GenerateContentConfig(temperature=0.0, max_output_tokens=200,
                                  thinking_config=types.ThinkingConfig(thinking_budget=0))
PROMPT = """Judge whether the CANDIDATE answer correctly conveys the fact in the REFERENCE answer to the QUESTION.
Reply with ONE word only: CORRECT (candidate contains the reference's key fact), PARTIAL (partially correct or incomplete), or INCORRECT (wrong or missing).

QUESTION: {q}
REFERENCE: {ref}
CANDIDATE: {ans}

Verdict:"""

rows = [json.loads(l) for l in open(ROOT / "eval" / "eval_dataset.jsonl", encoding="utf-8") if l.strip()]
verdicts = []
for i, r in enumerate(rows, 1):
    p = PROMPT.format(q=r["user_input"], ref=r["reference"], ans=r["response"])
    for attempt in range(5):
        try:
            resp = client.models.generate_content(model="gemini-2.5-flash", contents=p, config=CFG)
            m = re.search(r"CORRECT|PARTIAL|INCORRECT", (resp.text or "").upper())
            verdicts.append(m.group(0) if m else "UNKNOWN")
            break
        except Exception as e:
            if "RESOURCE_EXHAUSTED" in str(e) or "UNAVAILABLE" in str(e):
                time.sleep(8)
                continue
            verdicts.append("ERROR")
            break
    if i % 20 == 0:
        print(f"{i}/100", flush=True)

c = Counter(verdicts)
n = len(verdicts)
correct = c["CORRECT"]
partial = c["PARTIAL"]

def pct(x):
    return "{}/{} ({:.0%})".format(x, n, x / n)

print("\n=== ANSWER CORRECTNESS (direct judge) ===")
print("  CORRECT:   " + pct(correct))
print("  PARTIAL:   " + pct(partial))
print("  INCORRECT: " + pct(c["INCORRECT"]))
print("  correct-or-partial: {:.0%}".format((correct + partial) / n))

by_cat = {}
for r, v in zip(rows, verdicts):
    by_cat.setdefault(r["category"], []).append(v)
print("\n  by category (CORRECT rate):")
for cat, vs in sorted(by_cat.items()):
    cc = sum(1 for v in vs if v == "CORRECT") / len(vs)
    print("    {:10} {:.0%}".format(cat, cc))

json.dump(dict(zip([r["user_input"] for r in rows], verdicts)),
          open(ROOT / "eval" / "correctness_verdicts.json", "w"), indent=1)
