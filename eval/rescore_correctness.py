import json, os
from pathlib import Path
from dotenv import load_dotenv
ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT/'.env')
import sys; sys.path.insert(0, str(ROOT/'eval'))
from ragas_score import GeminiVertexRagasLLM, load_dataset, PROJECT, LOCATION, JUDGE_MODEL
from ragas import evaluate
from ragas.run_config import RunConfig
from ragas.metrics import FactualCorrectness
judge = GeminiVertexRagasLLM(JUDGE_MODEL, PROJECT, LOCATION)
ds = load_dataset()
res = evaluate(dataset=ds, metrics=[FactualCorrectness(mode='recall')], llm=judge,
               run_config=RunConfig(max_workers=3, timeout=300, max_retries=4),
               raise_exceptions=False, show_progress=True)
df = res.to_pandas()
df.to_csv(ROOT/'eval'/'ragas_correctness_recall.csv', index=False)
col = [c for c in df.select_dtypes('number').columns][0]
print(f'\nfactual_correctness (recall mode): {df[col].mean():.3f} (n={df[col].notna().sum()})')
