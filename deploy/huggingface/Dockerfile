# US Tax & Legal RAG — Hugging Face Space (server-less variant).
# Single CPU container: FastAPI + numpy vectors + rank_bm25 + networkx + Gemini.
FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# HF Spaces run the container as uid 1000 — set up a matching non-root user.
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    HF_HOME=/home/user/.cache/huggingface \
    PYTHONPATH=/app/vendor:/app \
    GEMINI_USE_VERTEX=true \
    GCP_LOCATION=global \
    GEMINI_MODEL=gemini-2.5-pro
WORKDIR /app

# CPU-only torch FIRST (from the pytorch CPU index), so sentence-transformers
# reuses it instead of pulling the multi-GB CUDA build.
RUN pip install --user --no-cache-dir torch==2.2.2 --index-url https://download.pytorch.org/whl/cpu

COPY --chown=user:user requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# Bake the bge embedding model into the image so the first query is fast and no
# model download happens on Space restart.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-base-en-v1.5')"

# App code, vendored legalrag package, prebuilt artifacts, and frontend.
COPY --chown=user:user vendor/   ./vendor/
COPY --chown=user:user app/      ./app/
COPY --chown=user:user data/     ./data/
COPY --chown=user:user frontend/ ./frontend/

EXPOSE 7860
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
