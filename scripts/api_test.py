#!/usr/bin/env python3
"""
api_test.py — minimal check that the Gemini connection in .env works.

Dual-mode, mirroring llm_service.get_client():
  - Vertex AI mode (GEMINI_USE_VERTEX=true): bills against Google Cloud credits
    (incl. the $300 free trial, which the AI Studio path can't use). Auth via a
    service-account key file (GOOGLE_APPLICATION_CREDENTIALS) + GCP_PROJECT /
    GCP_LOCATION.
  - AI Studio mode (default): a GOOGLE_API_KEY. Note the account's AQ.-prefixed
    key needs the NEW google-genai SDK (the old google-generativeai cannot
    authenticate AQ. keys — it fails 401 ACCESS_TOKEN_TYPE_UNSUPPORTED).

Run: ./venv/Scripts/python.exe api_test.py
"""
import os
import sys

from dotenv import load_dotenv
from google import genai

MODEL_ID = "gemini-2.5-flash"


def make_client():
    use_vertex = os.environ.get("GEMINI_USE_VERTEX", "").strip().lower() in ("1", "true", "yes")
    if use_vertex:
        project = os.environ.get("GCP_PROJECT", "").strip()
        location = os.environ.get("GCP_LOCATION", "global").strip() or "global"
        cred = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
        if not project:
            print("FAIL: GEMINI_USE_VERTEX=true but GCP_PROJECT is empty")
            sys.exit(1)
        if not cred or not os.path.exists(cred):
            print(f"FAIL: service-account key file not found at GOOGLE_APPLICATION_CREDENTIALS={cred!r}")
            sys.exit(1)
        print(f"mode: Vertex AI  (project={project}, location={location})")
        return genai.Client(vertexai=True, project=project, location=location)
    else:
        key = os.environ.get("GOOGLE_API_KEY", "").strip()
        if not key:
            print("FAIL: GOOGLE_API_KEY is empty in .env")
            sys.exit(1)
        print(f"mode: AI Studio API key  (starts '{key[:5]}...', length {len(key)})")
        return genai.Client(api_key=key)


def main():
    load_dotenv()
    client = make_client()

    # 1. auth + a real generation round-trip
    try:
        resp = client.models.generate_content(model=MODEL_ID, contents="Reply with exactly the word: OK")
        text = (resp.text or "").strip()
        print(f"generation on {MODEL_ID}: got -> {text!r}")
        if "OK" not in text.upper():
            print("WARN: unexpected reply, but the API responded")
    except Exception as e:
        print(f"FAIL: generation call errored: {type(e).__name__}: {str(e)[:300]}")
        sys.exit(1)

    # 2. token counting (used in Phase 5 for context budgeting)
    try:
        tc = client.models.count_tokens(model=MODEL_ID, contents="How much is the standard deduction?")
        print(f"token counting works: {tc.total_tokens} tokens for a sample query")
    except Exception as e:
        print(f"WARN: token counting failed (non-fatal): {str(e)[:150]}")

    print("\nPASS: Gemini connection is working.")


if __name__ == "__main__":
    main()
