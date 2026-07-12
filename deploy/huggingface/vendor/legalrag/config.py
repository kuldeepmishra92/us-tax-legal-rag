"""Central configuration and path resolution for the legalrag package.

One place computes the project root and the on-disk data locations, so the
thirty-odd modules that consume these paths never do their own ``__file__``
arithmetic. If the data directories are ever relocated (e.g. into ``data/``),
only this file changes. Also loads the project ``.env`` once, from a fixed
location independent of the current working directory.
"""
from pathlib import Path

from dotenv import load_dotenv

# src/legalrag/config.py -> parents[2] == project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# On-disk data. Currently at the project root; if relocated, change here only.
PROCESSED_DIR = PROJECT_ROOT / "processed"
PROCESSED_MANIFEST = PROJECT_ROOT / "processed_manifest.csv"
DOCUMENTS_MANIFEST = PROJECT_ROOT / "documents_manifest.csv"
DATASET_DIR = PROJECT_ROOT / "dataset"
BACKUPS_DIR = PROJECT_ROOT / "backups"
ENV_FILE = PROJECT_ROOT / ".env"

# Load environment once, from the project .env regardless of CWD.
load_dotenv(ENV_FILE)
