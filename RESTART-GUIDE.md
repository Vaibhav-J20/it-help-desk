# Complete Project Restart Guide
## OpenShift & SNO Technical Support Copilot — V3 Clean Start

**Who reads this:** Developer A (Vaibhav) — you run every step below in order.  
**Purpose:** Wipe the old Watson Discovery architecture from GitHub cleanly, create a single `main` branch with the correct V3 foundation, and give Developer B (Anush) a self-contained starting prompt so they have full context.

---

## Before You Begin — What We Are Doing and Why

Your current GitHub repo (`Vaibhav-J20/it-help-desk`) has:
- `main` — scaffold files for the old Watson Discovery architecture
- `dev/developer-a` — your working branch (same content + `ARCHITECTURE_IMPLEMENTATION_V3.md` and `v3-migration-plan.md` not yet committed)
- `dev/developer-b` — Anush's old Discovery-based `ingest.py` and `requirements.txt`

**We will:**
1. Wipe all three branches and replace `main` with a clean V3 foundation
2. Delete `dev/developer-a` and `dev/developer-b` from GitHub (they had no production value)
3. Create two new working branches: `feature/dev-a-api-agent` and `feature/dev-b-ingestion`
4. Commit a complete, correct set of project documents so Anush can start from scratch without needing any prior context

**We will NOT:**
- Rewrite git history with `--force` on `main` (we push a clean replacement instead)
- Delete any local files you want to keep as reference — your local `.git` has the old history safe

---

## Step 1 — Back Up What You Want (Optional, 2 minutes)

If you want to keep a local copy of any old files before we delete them:

```bash
cd /Users/vaibhavjanga/projects/IT-help-desk
cp ARCHITECTURE_IMPLEMENTATION_V3.md ~/Desktop/ARCHITECTURE_IMPLEMENTATION_V3.md
cp v3-migration-plan.md ~/Desktop/v3-migration-plan.md
```

These two files are the only ones worth keeping. Everything else is being replaced.

---

## Step 2 — Provision Your TechZone Environment (Do This First)

Before touching code, confirm your new TechZone instance is live. You need these services:

| Service | Why you need it | How to get it |
|---|---|---|
| **OpenSearch** | The ONLY retrieval database in V3 | TechZone OpenShift cluster — deploy via StatefulSet (manifests in `deployment/openshift/`) |
| **watsonx.ai** | Embeddings + answer generation | TechZone "watsonx.ai" reservation — get Project ID and list available model IDs |
| **IBM Cloud Object Storage** | Original PDF storage | Create a bucket in your IBM Cloud account |
| **watsonx Orchestrate** | User-facing agent UI | TechZone Orchestrate reservation |

**Critical check before writing any code:**

```bash
# After getting your watsonx.ai project, run this to list available models:
curl -H "Authorization: Bearer $(YOUR_IAM_TOKEN)" \
  "https://us-south.ml.cloud.ibm.com/ml/v1/foundation_model_specs?version=2024-01-01" | \
  jq '.resources[].model_id'
```

You need a model available for:
- Embeddings (look for `ibm/slate-*` or `intfloat/multilingual-e5-large`)
- Generation (look for `ibm/granite-*-instruct`)

**Write down the exact model IDs you will use before Day 2.** They go in `.env`, never in code.

---

## Step 3 — Clean the Local Repo (Run These Commands)

```bash
cd /Users/vaibhavjanga/projects/IT-help-desk

# Make sure you're on dev/developer-a (you are, per git status)
git status

# Delete every file tracked in git (leaves .git/ intact)
git rm -rf .

# Also remove untracked files that haven't been committed yet
rm -f ARCHITECTURE_IMPLEMENTATION_V3.md
rm -f v3-migration-plan.md

# Confirm the working tree is empty
ls -la
# You should see only .git/
```

---

## Step 4 — Create the New Foundation Files

Run these commands to create the V3 directory structure and all foundation files.  
**IBM Bob will create every file with correct content** — run this session prompt after cleaning:

> **Open a new IBM Bob session and paste this exact prompt:**
>
> *(See `DEVELOPER-A-PROMPT.md` in this repo after Step 5 creates it)*

Actually, do Steps 5–6 first (below), which create the prompt files locally, then come back and run the Bob session.

---

## Step 5 — Stage All New Files and Commit to a New main

After IBM Bob creates all the files (see `DEVELOPER-A-PROMPT.md`):

```bash
cd /Users/vaibhavjanga/projects/IT-help-desk

# Stage everything
git add -A

# Commit the V3 foundation
git commit -m "feat: V3 architecture foundation — clean OpenSearch/watsonx.ai/Orchestrate stack

Replaces Watson Discovery architecture with V3 design:
- FastAPI + LangGraph bounded agent workflow
- OpenSearch hybrid retrieval (BM25 + vector + metadata filters)  
- watsonx.ai embeddings and grounded generation
- IBM COS PDF ingestion pipeline
- watsonx Orchestrate single-tool integration
- POST /v1/assist with citation-grounded responses

Removes: rag_core.py, manifest.json, Watson Discovery references
Adds: complete app/ skeleton, ingestion pipeline, tests structure,
      deployment manifests, OpenAPI spec, project documentation"

# Verify the commit looks right
git log --oneline -3
git diff HEAD~1 --stat
```

---

## Step 6 — Push to GitHub and Clean Up Remote Branches

```bash
# Switch to main branch locally
git checkout main

# Fast-forward main to your new commit (or merge from current branch)
git merge dev/developer-a --no-ff -m "V3 clean architecture foundation"

# Push main
git push origin main

# Delete the old dev branches from GitHub
git push origin --delete dev/developer-a
git push origin --delete dev/developer-b

# Delete them locally too
git branch -d dev/developer-a
git branch -d dev/developer-b

# Verify remote only has main now
git remote show origin

# Create the two new working branches from the clean main
git checkout -b feature/dev-a-api-agent
git push origin feature/dev-a-api-agent

git checkout main
git checkout -b feature/dev-b-ingestion
git push origin feature/dev-b-ingestion

# Go back to your working branch
git checkout feature/dev-a-api-agent
```

---

## Step 7 — Share Context With Developer B (Anush)

1. Push everything to GitHub (`git push origin main`)
2. Send Anush the link to the repo
3. Tell Anush to clone fresh: `git clone https://github.com/Vaibhav-J20/it-help-desk.git`
4. Anush reads `DEVELOPER-B-PROMPT.md` and pastes it into their IBM Bob session
5. Anush checks out their branch: `git checkout feature/dev-b-ingestion`

**Credentials to share with Anush (over IBM internal chat ONLY — never in git):**
- `IBM_CLOUD_API_KEY` (your IAM key)
- `WATSONX_PROJECT_ID`
- `OPENSEARCH_URL`, `OPENSEARCH_USERNAME`, `OPENSEARCH_PASSWORD`
- `COS_ENDPOINT`, `COS_BUCKET`, `COS_API_KEY`

---

## Step 8 — Your Day-by-Day Sprint (Developer A)

| Day | Your focus | Exit condition |
|---|---|---|
| **1** | TechZone proof: list watsonx model IDs, verify OpenSearch PVC, confirm Orchestrate can reach a test URL | All 3 services reachable; model IDs written in `.env` |
| **2** | FastAPI skeleton + Pydantic schemas + API key auth + mocked `/v1/assist` | `curl localhost:8000/v1/assist` returns a valid mocked `ANSWERED` response |
| **3** | BM25 lexical retrieval + filter builder + `INSUFFICIENT_EVIDENCE` path | `curl` retrieves real chunk IDs from a test-indexed document |
| **4** | watsonx.ai embedding provider + vector search + RRF fusion | Semantic query returns plausible evidence; unit tests for filters + RRF pass |
| **5** | Full LangGraph 7-node workflow — all conditional paths | Graph returns all 5 status types deterministically with mocked providers |
| **6** | watsonx.ai chat provider + evidence-labelled prompt + citation validator | Local API returns a cited answer from real corpus evidence |
| **7** | Containerize + deploy to TechZone OpenShift + secrets/configmaps | Orchestrate can invoke `/v1/assist` on deployed URL |
| **8** | 40-question evaluation with Anush + defect fixes | No hallucination, no uncited answer, no version leakage in test cases |
| **9** | Quality hardening — chunking, filters, RRF tuning based on eval failures | Eval metrics pass acceptance targets from V3 section 17.2 |
| **10** | Freeze code + demo dry run x2 + final docs | Demo works end-to-end; README complete; evaluation results archived |

---

## What To Do If OpenSearch Storage Is Not Available on TechZone

This is the #1 risk. If TechZone's OpenShift does not give you a PersistentVolumeClaim:

1. Try requesting storage via the OpenShift console → Storage → PersistentVolumeClaims
2. If that fails, ask your IBM manager for a managed OpenSearch endpoint (IBM Cloud OpenSearch)
3. Do NOT use Code Engine for OpenSearch — it is ephemeral and will lose your index on restart
4. Do NOT switch to AstraDB — the V3 architecture decision (ADR-001) explicitly rejects it

---

## Branch Rules Going Forward

| Branch | Owner | Purpose | Merge target |
|---|---|---|---|
| `main` | Both (PR only) | Always deployable foundation | — |
| `feature/dev-a-api-agent` | Developer A | FastAPI + LangGraph + retrieval + providers | `main` via PR |
| `feature/dev-b-ingestion` | Developer B | Ingestion pipeline + indexer + evaluation | `main` via PR |

**PR merge rules (do not merge until):**
- Unit tests pass
- No secrets in changed files
- The other developer has reviewed the locked interface files (`app/api/schemas.py`, `app/graph/state.py`, `config/taxonomy/ocp_sno.yaml`)
- No Watson Discovery references appear in new code
