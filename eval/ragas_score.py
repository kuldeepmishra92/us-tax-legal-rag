#!/usr/bin/env python3
"""
ragas_score.py — Phase 8 Step 3: score the eval dataset with RAGAS.

RUNS IN THE ISOLATED venv-ragas (NOT the main venv):
    ./venv-ragas/Scripts/python.exe eval/ragas_score.py

Loads eval/eval_dataset.jsonl (from run_eval.py) and computes the standard
RAGAS metrics with Gemini as the judge:
  - faithfulness                    — answer grounded in retrieved context?  [PRD: Faithfulness]
  - factual_correctness             — answer matches the golden ground truth?
  - llm_context_precision_with_ref  — retrieved contexts relevant?           [PRD: Retrieval]
  - context_recall                  — retrieval captured the answer support? [PRD: Retrieval]

Judge integration note: RAGAS's stock LangchainLLMWrapper(ChatVertexAI) fails
against this project's Gemini-2.5 models (thinking tokens break RAGAS's
structured-output parsing -> LLMDidNotFinishException -> all NaN; and 2.0-flash
isn't served on this project's Vertex). So we plug in a CUSTOM RagasLLM that
calls the SAME reliable google-genai Vertex client the whole system uses, with
thinking explicitly disabled (thinking_budget=0) and a generous token budget.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
PROJECT = os.environ["GCP_PROJECT"]
LOCATION = os.environ.get("GCP_LOCATION", "global")

from google import genai
from google.genai import types
from langchain_core.outputs import LLMResult, Generation
from ragas import evaluate
from ragas.dataset_schema import EvaluationDataset, SingleTurnSample
from ragas.llms.base import BaseRagasLLM
from ragas.run_config import RunConfig
from ragas.metrics import (
    Faithfulness, FactualCorrectness, LLMContextPrecisionWithReference, ContextRecall,
)

DATASET = ROOT / "eval" / "eval_dataset.jsonl"
OUT = ROOT / "eval" / "ragas_scores.csv"
JUDGE_MODEL = "gemini-2.5-flash"


class GeminiVertexRagasLLM(BaseRagasLLM):
    """RAGAS judge backed by google-genai's Vertex client (not langchain).
    Thinking disabled + high token budget so structured outputs finish cleanly."""

    def __init__(self, model, project, location, max_output_tokens=6000):
        self.model = model
        self.client = genai.Client(vertexai=True, project=project, location=location)
        self.max_output_tokens = max_output_tokens
        self.run_config = RunConfig()

    def set_run_config(self, run_config):
        self.run_config = run_config

    def _config(self, temperature, stop):
        return types.GenerateContentConfig(
            temperature=0.0 if temperature is None else float(temperature),
            max_output_tokens=self.max_output_tokens,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
            stop_sequences=list(stop) if stop else None,
        )

    def generate_text(self, prompt, n=1, temperature=None, stop=None, callbacks=None):
        text = prompt.to_string()
        gens = []
        for _ in range(n):
            resp = self.client.models.generate_content(
                model=self.model, contents=text, config=self._config(temperature, stop))
            gens.append(Generation(text=resp.text or ""))
        return LLMResult(generations=[gens])

    async def agenerate_text(self, prompt, n=1, temperature=None, stop=None, callbacks=None):
        text = prompt.to_string()
        gens = []
        for _ in range(n):
            resp = await self.client.aio.models.generate_content(
                model=self.model, contents=text, config=self._config(temperature, stop))
            gens.append(Generation(text=resp.text or ""))
        return LLMResult(generations=[gens])


def load_dataset(limit=None):
    samples = []
    for line in DATASET.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        samples.append(SingleTurnSample(
            user_input=r["user_input"], response=r["response"],
            retrieved_contexts=r["retrieved_contexts"], reference=r["reference"]))
        if limit and len(samples) >= limit:
            break
    return EvaluationDataset(samples=samples)


def main(limit=None):
    if not DATASET.exists():
        print(f"dataset not found: {DATASET}")
        sys.exit(1)
    judge = GeminiVertexRagasLLM(JUDGE_MODEL, PROJECT, LOCATION)
    metrics = [Faithfulness(), FactualCorrectness(),
               LLMContextPrecisionWithReference(), ContextRecall()]
    ds = load_dataset(limit=limit)
    print(f"scoring {len(ds.samples)} samples | judge={JUDGE_MODEL} (thinking off) "
          f"| metrics={[m.name for m in metrics]}", flush=True)

    result = evaluate(
        dataset=ds, metrics=metrics, llm=judge,
        run_config=RunConfig(max_workers=3, timeout=300, max_retries=4),
        raise_exceptions=False, show_progress=True,
    )
    df = result.to_pandas()
    df.to_csv(OUT, index=False)
    print(f"\nper-query scores -> {OUT}")
    print("\n=== AGGREGATE RAGAS SCORES ===")
    num = df.select_dtypes("number")
    for col in num.columns:
        print(f"  {col:38}: {num[col].mean():.3f}  (n={num[col].notna().sum()})")


if __name__ == "__main__":
    lim = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
    main(limit=lim)
