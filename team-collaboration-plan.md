# Team Collaboration Plan — IBM IT Help Desk Chatbot
**Two-Developer Split | Version Control | Bob Context Handoff Protocol**

---

## 1. The Core Principle of the Split

The project has a natural seam: **everything that runs in the cloud at query time** vs **everything that runs offline or in config**. These two halves can be developed largely in parallel with a single shared contract — the `rag_core.py` function signatures and the `.env` variable names.

```
Developer A (You)                    Developer B (Teammate)
─────────────────────────────        ──────────────────────────────
BACKEND — The brain                  FRONTEND — The face + ingestion
  rag_core.py                          ingest.py
  server.py                            skills/ (OpenAPI YAMLs)
  prompts/                             Watsonx Orchestrate assistant
  Dockerfile                           manifest.json schema
  IBM Cloud service provisioning       DEMO.md
  requirements.txt                     README.md
```

The contract between the two halves is fixed early and committed to `main` first, so both developers can work without blocking each other.

---

## 2. Work Split by Sub-Task

| Sub-Task | Owner | Rationale |
|---|---|---|
| **ST-1** IBM Cloud Service Provisioning | **Developer A** | One person provisions all services; both get credentials via `.env.example` |
| **ST-2** Document Ingestion Pipeline (`ingest.py`) | **Developer B** | Standalone offline script; no dependency on the running server |
| **ST-3** RAG Core Logic (`rag_core.py`) | **Developer A** | Core intelligence; A owns the retrieval + generation pipeline |
| **ST-4** FastAPI Server + Skill YAMLs (`server.py` + `skills/`) | **Developer A** (`server.py`) + **Developer B** (`skills/` YAMLs) | A writes the API; B writes the OpenAPI specs that describe it |
| **ST-5** Watsonx Orchestrate Assistant Config | **Developer B** | UI/config work; depends on skill YAMLs B already wrote |
| **ST-6** Dockerfile + README + DEMO + `.gitignore` | **Split** — see below | A writes Dockerfile; B writes README + DEMO.md |

### ST-4 Sub-split detail

This is the only sub-task that needs coordination. The split is:
- **Developer A** writes and deploys `server.py` to Code Engine, then shares the live HTTPS URL
- **Developer B** takes the auto-generated `/openapi.json` from that URL and produces the three `skill-*.yaml` files
- These get imported into Orchestrate by B

### ST-6 Sub-split detail

| File | Owner |
|---|---|
| `Dockerfile` | Developer A (knows the runtime) |
| `requirements.txt` | Developer A (owns the Python deps) |
| `README.md` | Developer B (documents the whole system) |
| `DEMO.md` | Developer B (writes demo queries after testing) |
| `HIGH-LEVEL-ARCHITECTURE.md` | Already done — both maintain |
| `.gitignore` | Developer A (first commit) |

---

## 3. The Shared Contract (Lock This First)

Before either developer writes code, one commit to `main` must define the shared interfaces. **Developer A** does this as the first real commit after provisioning.

### 3a — `.env.example` (committed, no real values)

```
# IBM Cloud credentials — copy to .env and fill in real values
IBM_CLOUD_API_KEY=
DISCOVERY_URL=https://api.{region}.discovery.watson.cloud.ibm.com
DISCOVERY_PROJECT_ID=
DISCOVERY_COLLECTION_ID=
WATSONX_PROJECT_ID=
WATSONX_REGION=us-south
WATSONX_URL=https://us-south.ml.cloud.ibm.com
API_KEY_SECRET=
```

### 3b — `rag_core.py` public interface (stub, committed to `main`)

```python
# rag_core.py — PUBLIC INTERFACE CONTRACT
# Developer A implements; Developer B's server.py calls these signatures

def get_iam_token(api_key: str) -> str:
    """Exchange IBM Cloud API key for IAM Bearer token. Caches + auto-refreshes."""
    raise NotImplementedError

def retrieve(query: str, top_k: int = 5, filters: dict = None) -> list[dict]:
    """
    Query Watson Discovery v2 with NLQ + optional metadata filters.
    filters example: {"version": "4.16", "component": "bootstrap"}
    Returns list of {"text": str, "source": str, "version": str}
    """
    raise NotImplementedError

def generate(context_chunks: list[dict], user_query: str, mode: str) -> str:
    """
    Build Granite prompt from template + chunks, call Watsonx.ai.
    mode: one of 'qa' | 'summarize' | 'troubleshoot'
    Returns empty-context fallback string if context_chunks is [].
    """
    raise NotImplementedError

def query(user_input: str, mode: str = "qa", filters: dict = None) -> dict:
    """
    Orchestrates retrieve -> generate.
    Returns {"answer": str, "sources": list[str]}
    """
    raise NotImplementedError
```

### 3c — `manifest.json` schema (empty starter, committed to `main`)

```json
{
  "ingested": []
}
```

Each entry added by `ingest.py` will look like:
```json
{
  "filename": "SNO-4.16-bootstrap-runbook.pdf",
  "discovery_doc_id": "abc123",
  "metadata": {
    "product": "OpenShift",
    "version": "4.16",
    "deployment_type": "SNO",
    "component": "bootstrap"
  },
  "ingested_at": "2025-07-10T14:32:00Z"
}
```

---

## 4. Git Repository Setup

### 4a — Repository structure

```
Repository name: it-helpdesk-chatbot
Visibility:      Private (IBM internal IBM documents are referenced)
Default branch:  main
```

### 4b — Branch strategy

```
main
  └── protected — no direct pushes; only merges via pull request
  └── always deployable

dev/developer-a
  └── Developer A's working branch
  └── merges into main via PR when a sub-task is complete

dev/developer-b
  └── Developer B's working branch
  └── merges into main via PR when a sub-task is complete
```

**Rule:** Neither developer pushes directly to `main`. Every merge goes through a pull request and the other developer does a quick review (even just a skim). This means at any time, `main` is always in a working, reviewable state.

### 4c — Step-by-step GitHub setup

**Developer A does this once:**

```bash
# 1. Create the repo locally
mkdir it-helpdesk-chatbot && cd it-helpdesk-chatbot
git init
git branch -M main

# 2. Create the first-commit files
touch .gitignore .env.example manifest.json rag_core.py README.md

# 3. Populate .gitignore
echo ".env" >> .gitignore
echo "docs/" >> .gitignore
echo "__pycache__/" >> .gitignore
echo "*.pyc" >> .gitignore
echo "*.pyo" >> .gitignore
echo ".DS_Store" >> .gitignore

# 4. Add the stub contract files (rag_core.py interface, .env.example, manifest.json)
# ... populate as per Section 3 above ...

# 5. First commit
git add .
git commit -m "chore: initial project scaffold with shared interface contract"

# 6. Push to GitHub
git remote add origin https://github.com/{your-username}/it-helpdesk-chatbot.git
git push -u origin main

# 7. Create working branches
git checkout -b dev/developer-a
git push -u origin dev/developer-a

# 8. Invite teammate
# GitHub → Settings → Collaborators → Add people → enter teammate's GitHub username
```

**Developer B does this once (after being invited):**

```bash
git clone https://github.com/{developer-a-username}/it-helpdesk-chatbot.git
cd it-helpdesk-chatbot
git checkout -b dev/developer-b
git push -u origin dev/developer-b
```

### 4d — Day-to-day workflow for each developer

```bash
# Start of every work session — sync with main first
git checkout dev/developer-a        # or dev/developer-b
git fetch origin
git merge origin/main               # pull in any changes merged by teammate

# Do your work ...

# Save progress at end of session
git add .
git commit -m "feat(rag-core): implement retrieve() with v2 metadata filters"
git push origin dev/developer-a

# When a full sub-task is complete → open a Pull Request on GitHub
# Title: "ST-3: RAG core logic — retrieve + generate complete"
# Reviewer: the other developer
# Merge: squash and merge into main
```

### 4e — Commit message convention

Use a consistent format so both Bob instances and humans can scan history:

```
<type>(<scope>): <short description>

Types:  feat | fix | chore | docs | test
Scope:  rag-core | server | ingest | skills | orchestrate | dockerfile | docs

Examples:
feat(rag-core): implement get_iam_token with 60-min cache
feat(server): add X-API-Key auth dependency to all endpoints
feat(ingest): interactive metadata prompting + manifest.json write
fix(rag-core): correct Discovery v2 filter syntax to document.metadata.*
docs(readme): add Code Engine deployment steps
chore(dockerfile): add python:3.11-slim base image
```

---

## 5. Bob Context Handoff Protocol

This is how each developer's Bob session stays aware of what the other has built, without needing to share chat history.

### The rule: every merged PR updates `CONTEXT.md`

When a developer merges a sub-task PR into `main`, they update a file called [`CONTEXT.md`](CONTEXT.md) in the root of the repo. This file is the **single source of truth** that any Bob session reads at the start of a session to understand current project state.

### `CONTEXT.md` format

```markdown
# Project Context — Current State
Last updated: {date} by {developer}

## Completed Work
- [x] ST-1: IBM Cloud services provisioned (Developer A) — credentials in .env.example
- [x] ST-2: ingest.py complete (Developer B) — see manifest.json for schema
- [ ] ST-3: rag_core.py — IN PROGRESS (Developer A)
- [ ] ST-4: server.py + skills/ — pending ST-3
- [ ] ST-5: Orchestrate assistant — pending ST-4
- [ ] ST-6: Dockerfile, README, DEMO — pending ST-4

## Active Decisions / State
- Watson Discovery Project ID: documented in .env.example (real value in .env — not committed)
- Collection name: ibm-helpdesk-docs
- Model: ibm/granite-13b-instruct-v2
- Code Engine app not yet deployed

## Current Blockers
- ST-3 blocked on: nothing — can start
- ST-4 blocked on: ST-3 completion (rag_core.py interface must be finalised)
- ST-5 blocked on: ST-4 (need live Code Engine URL to test skills)

## Interface Contracts In Effect
- rag_core.query(user_input, mode, filters) → {answer, sources} [stub in rag_core.py]
- server.py endpoints: POST /ask, /summarize, /troubleshoot [not yet implemented]
- manifest.json schema: see manifest.json at project root
```

### How to start a Bob session with context

At the start of every Bob session, give Bob this prompt:

> **"Bob, read CONTEXT.md and it-helpdesk-chatbot-plan.md to understand the current project state, then help me with [your task]."**

Bob will read both files, understand what's done, what's in progress, what the contracts are, and what's blocked — without needing to re-read the entire chat history.

---

## 6. Coordination Checkpoints

These are the moments where both developers must sync before work can continue. Mark them in your shared calendar or Slack.

| Checkpoint | Trigger | Who | What to share |
|---|---|---|---|
| **CP-1** | After ST-1 (provisioning) | Developer A → Developer B | Share `.env` values over secure channel (IBM internal chat, NOT git). Both need them to test locally. |
| **CP-2** | After ST-3 (`rag_core.py` complete) | Developer A → Developer B | Confirm final function signatures. B's `server.py` calls were unblocked by the stub but now test against real implementation. |
| **CP-3** | After ST-4 server deployed | Developer A → Developer B | Share the live Code Engine HTTPS URL. B uses it to pull `/openapi.json` and generate `skill-*.yaml` files. |
| **CP-4** | After ST-5 (Orchestrate config) | Developer B → Developer A | Share Orchestrate assistant test link. Both do end-to-end acceptance testing together (ST-5, todo item 6). |

---

## 7. Parallel Work Timeline

```
Week 1
  Dev A: ST-1 (provisioning) → ST-3 (rag_core.py)
  Dev B: ST-2 (ingest.py)
  CP-1: Dev A shares .env values with Dev B
                                ↑
                        both can now test locally

Week 2
  Dev A: complete ST-3 → start ST-4 server.py → deploy to Code Engine
  Dev B: finish ST-2 → start skill YAML scaffolding (can stub with mock URL)
  CP-2: Dev A confirms rag_core.py signatures finalised
  CP-3: Dev A shares Code Engine URL → Dev B pulls /openapi.json

Week 3
  Dev A: Dockerfile polish + requirements.txt + .gitignore
  Dev B: ST-5 Orchestrate assistant config + ST-6 README + DEMO.md
  CP-4: Joint end-to-end acceptance testing
  Final: ST-6 cleanup → both review DEMO.md → presentation prep
```

---

## 8. File Ownership Summary (quick reference)

| File | Owner | Can the other touch it? |
|---|---|---|
| `rag_core.py` | Developer A | Only to fix bugs — coordinate first |
| `server.py` | Developer A | Only to fix bugs — coordinate first |
| `prompts/*.txt` | Developer A | Developer B can suggest wording changes via PR |
| `Dockerfile` | Developer A | No — runtime knowledge required |
| `requirements.txt` | Developer A | Developer B adds deps only if their code needs them |
| `ingest.py` | Developer B | Developer A can review but not rewrite |
| `manifest.json` | Developer B (schema) | A never edits; it's auto-updated by ingest.py |
| `skills/*.yaml` | Developer B | Developer A reviews for correctness against server.py |
| `README.md` | Developer B | Developer A adds technical accuracy corrections |
| `DEMO.md` | Developer B | Both contribute example queries |
| `CONTEXT.md` | **Both** | Update immediately after every merged PR |
| `.env.example` | Developer A (initial) | Both add new variable names when needed |
| `HIGH-LEVEL-ARCHITECTURE.md` | **Both review** | Neither edits alone — changes need agreement |
