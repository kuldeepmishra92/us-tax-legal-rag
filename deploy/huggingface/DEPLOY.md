# Deploying to Hugging Face Spaces

This folder **is** the Space — it's fully self-contained (app, vendored
`legalrag` package, prebuilt artifacts, frontend, Dockerfile). You just push it
and set two secrets.

## Prerequisites
- A Hugging Face account and a **write** access token
  (https://huggingface.co/settings/tokens).
- A Google Cloud project with the **Vertex AI API** enabled and a service-account
  key (JSON) with the **Vertex AI User** role.

## 1. Create the Space
On https://huggingface.co/new-space:
- **Owner / name:** e.g. `your-username/legal-rag`
- **SDK:** **Docker** (blank template)
- **Hardware:** CPU basic (free)
- **Visibility:** Public

## 2. Set the secrets
In the Space → **Settings → Variables and secrets** → add two **secrets**:

| Name | Value |
|---|---|
| `GCP_PROJECT` | your Google Cloud project id |
| `GOOGLE_APPLICATION_CREDENTIALS_B64` | base64 of the service-account key JSON (one clean line — recommended) |

**Recommended: base64.** The multi-line key JSON can trip up the secret form; a
base64 string is a single safe line. Generate it (PowerShell):
```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes("D:\assignment\data\vertex-key.json")) | Set-Clipboard
```
…then paste (Ctrl+V) into the `GOOGLE_APPLICATION_CREDENTIALS_B64` value box.

> The **secret _name_** must be a plain identifier (letters/digits/underscore) —
> e.g. `GOOGLE_APPLICATION_CREDENTIALS_B64`. Do NOT paste the key into the *name*
> box (that causes `Invalid string: must match pattern … at key`).

Alternatively you can use `GOOGLE_APPLICATION_CREDENTIALS_JSON` with the **raw**
JSON — the app auto-detects raw JSON or base64 under either name.

(`GEMINI_USE_VERTEX=true`, `GCP_LOCATION=global`, `GEMINI_MODEL=gemini-2.5-pro`
are already baked into the image — no need to set them.)

## 3. Upload this folder

### Option A — huggingface-cli (easiest; handles Git LFS automatically)
```bash
pip install -U "huggingface_hub[cli]"
huggingface-cli login                      # paste your write token
cd deploy/huggingface
huggingface-cli upload your-username/legal-rag . . --repo-type=space
```

### Option B — git (init a fresh repo in this folder)
```bash
cd deploy/huggingface
git init && git lfs install
git lfs track "data/artifacts/vectors.npy" "data/artifacts/payloads.json"
git add -A && git commit -m "Deploy legal RAG space"
git remote add space https://huggingface.co/spaces/your-username/legal-rag
git push --force space main
```
`git lfs track` creates a `.gitattributes` so the two large artifacts upload via
Git LFS (HF requires LFS for files >10 MB).

## 4. Wait for the build
The Space builds the Docker image (installs CPU torch, bakes in the bge model) —
first build takes several minutes. When it finishes, open the Space URL:
**Ask**, **Summarize**, and **Explore Citations** tabs are live.

## Notes
- **Large files:** `data/artifacts/vectors.npy` (19 MB) and `payloads.json`
  (27 MB) are tracked with Git LFS via `.gitattributes` (Option B) or handled
  automatically (Option A).
- **Free-tier sleep:** the Space sleeps after inactivity; the first request after
  a wake takes a little longer (container start).
- **Refreshing the package:** if the main `legalrag` source changes, run
  `./refresh_vendor.sh` to update the vendored copy, then redeploy.
- **Rebuilding artifacts:** run `python build_artifacts.py` from the repo root
  (with the main Qdrant up) to regenerate `data/artifacts/*`.
