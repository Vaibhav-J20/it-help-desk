# IT Help Desk Chatbot — IBM Watsonx Project Plan

## Top-Level Overview

**Goal:** Build an internal IT Help Desk chatbot for IBM India ISA division — focused on **Red Hat OpenShift (OCP) and Single Node OpenShift (SNO)** — that ingests internal IBM documents (PDFs, Word docs, runbooks) and uses RAG (Retrieval-Augmented Generation) to answer technical questions, summarize documents, and provide step-by-step troubleshooting guidance. The system must support incremental document uploads over time.

**Primary Domain (Phase 1):** Red Hat OpenShift (OCP) and Single Node OpenShift (SNO), covering:
- Installation & bootstrap issues
- Networking & Ingress
- Storage & etcd
- API server & cluster configuration

> Starting narrow with OCP/SNO gives a focused, testable knowledge base and a strong demo narrative: *"an OpenShift troubleshooting copilot for IBM technical teams."* Additional IBM product domains can be added as new Discovery collections in Phase 2.

**Stack:**
- **IBM Watson Discovery v2** — document ingestion, chunking, vector indexing, semantic search (the knowledge base)
- **IBM Watsonx.ai** — LLM inference via the Granite model family (recommended: `ibm/granite-13b-instruct-v2` for RAG tasks on lite/free tier); authenticated via IBM Cloud IAM Bearer tokens (not static API key)
- **IBM Watsonx Orchestrate** — conversational UI, skill orchestration, routing user intents to the right tool
- **IBM Code Engine** — serverless container host for the FastAPI server; `server.py` and `rag_core.py` run in the **same container** (no internal network hop between them)

**Architecture Pattern:** Retrieval-Augmented Generation (RAG)
1. User asks a question in Watsonx Orchestrate chat
2. Orchestrate routes the intent to the appropriate skill (Q&A, Summarize, or Troubleshoot) using semantic intent matching backed by carefully crafted example phrases
3. Each skill calls the FastAPI server, passing the query and an optional `domain` parameter (e.g. `networking`, `storage`, `bootstrap`)
4. The RAG core queries Watson Discovery with both semantic search **and** metadata filters (product, version, deployment\_type)
5. Retrieved context is passed to Watsonx.ai (Granite) as a prompt
6. The LLM generates a grounded answer, citing the source document
7. Response is returned to the user in Watsonx Orchestrate

**Constraints:**
- IBM lite/free tier limits apply — Watsonx.ai token budgets and Discovery storage limits must be respected
- No external document sources at this stage — all knowledge comes from internally uploaded files
- Delivery channel is Watsonx Orchestrate's native chat UI only (no Slack/Teams integration needed now)
- Internship deadline: early August — scope must be achievable solo within that window
- The FastAPI server on Code Engine must be secured with an API key header — Code Engine apps are publicly reachable by default
- Watsonx.ai calls require a short-lived IAM Bearer token fetched from `https://iam.cloud.ibm.com/identity/token` using the API key; tokens expire every 60 minutes and must be refreshed

**Non-Goals:**
- Real-time web crawling of public IBM Docs
- Integration with ticketing systems (e.g. ServiceNow)
- User authentication / access control on a per-document basis
- Fine-tuning the LLM — RAG only
- A separate intent router service or 7-category classification layer (Orchestrate's native semantic matching + good example phrases handles this sufficiently)
- Confidence scoring (requires a calibrated corpus; premature labels mislead users)

---

## Sub-Tasks

---

### Sub-Task 1 — IBM Cloud Service Provisioning & Environment Setup

**Intent:**
Provision and connect the three core IBM Cloud services (Watsonx Discovery, Watsonx.ai, Watsonx Orchestrate) and verify that they can talk to each other. This is the foundation everything else depends on.

**Expected Outcomes:**
- A Watsonx Discovery instance is running with a project and an empty collection created
- A Watsonx.ai project exists with the Granite model available for inference
- Watsonx Orchestrate is configured and can invoke external APIs via a custom skill (API key ready)
- All service credentials (API keys, instance IDs, project IDs) are documented in a `.env` reference file

**Todo List:**
1. Log in to IBM Cloud (cloud.ibm.com) with your IBM intranet credentials
2. Provision **IBM Watson Discovery** (Plus or Lite plan) from the IBM Cloud catalog
3. Inside Watson Discovery: create a new **Project** (type: "Document Retrieval") and inside it create a **Collection** named `ibm-helpdesk-docs`
4. Note down: Discovery API key, Discovery instance URL, Project ID, Collection ID
5. Provision **IBM Watsonx.ai** (from watsonx.ai) — create a new **Project** named `it-helpdesk`
6. In Watsonx.ai, confirm `ibm/granite-13b-instruct-v2` is available under Foundation Models
7. Note down: Watsonx.ai API key, Project ID, region endpoint URL
8. Open **IBM Watsonx Orchestrate** — confirm your account is active and that you can access the "Skills & Apps" section
9. Create a `.env` file in the project root listing all keys/IDs (never commit this to git)
10. Validate connectivity: use the Discovery API Explorer or a simple curl call to confirm the collection endpoint responds

**Relevant Context:**
- Watson Discovery API: `https://api.{region}.discovery.watson.cloud.ibm.com`
- Watsonx.ai inference endpoint: `https://{region}.ml.cloud.ibm.com/ml/v1/text/generation`
- Watsonx Orchestrate: `https://dl.watson-orchestrate.ibm.com`

**Status:** [ ] pending

---

### Sub-Task 2 — Document Ingestion Pipeline (Watson Discovery Knowledge Base)

**Intent:**
Build a repeatable, script-driven pipeline that uploads documents into Watson Discovery with rich metadata, triggering automatic chunking and vectorisation. Metadata (product, version, deployment\_type, component) enables version-aware retrieval, which is critical for IBM technical docs where an OCP 4.12 procedure differs from 4.16. The pipeline must be re-runnable so that new documents can be added incrementally at any time.

**Expected Outcomes:**
- A Python ingestion script (`ingest.py`) that accepts a folder path and uploads all supported files (PDF, DOCX, TXT, MD) to the Discovery collection
- Every document is stored with a structured metadata envelope: `product`, `version`, `deployment_type`, `component`
- Documents are chunked and indexed in Watson Discovery with full-text and semantic search enabled
- The script is idempotent — re-running it with the same file does not create duplicates
- A `docs/` folder exists as the local staging area where new documents are dropped before running the script (gitignored — internal IBM files must not be committed)
- A `manifest.json` file at **project root** (not inside `docs/`) tracks uploaded filenames and their metadata so the script can skip already-ingested files; this file is safe to commit (contains metadata only, no document content)

**Todo List:**
1. Create the project folder structure:
   ```
   it-helpdesk/
   ├── docs/                  # drop new documents here (gitignored — internal IBM files)
   ├── manifest.json          # tracks ingested files + metadata (NOT gitignored — safe to commit, contains no doc content)
   ├── ingest.py              # upload script
   ├── skills/                # Orchestrate skill definitions
   ├── prompts/               # prompt templates
   ├── .env                   # credentials (gitignored)
   └── README.md
   ```
2. Install dependencies: `ibm-watson`, `ibm-watsonx-ai`, `python-dotenv`, `fastapi`, `uvicorn`, `requests` via pip; create `requirements.txt`
3. Write `ingest.py`:
   - Load credentials from `.env`
   - Load `manifest.json` at project root (create if missing)
   - For each file in `docs/` not already in the manifest, interactively prompt the user for metadata:
     - `product` (e.g. `OpenShift`, `IBM Cloud`)
     - `version` (e.g. `4.16`, `4.12`)
     - `deployment_type` (e.g. `SNO`, `HA`, `Compact`)
     - `component` (e.g. `bootstrap`, `etcd`, `networking`, `storage`, `ingress`)
   - Call `discovery.add_document()` passing the file stream + metadata JSON
   - On success, write the filename + metadata into `manifest.json`
   - Print success/failure per file
4. Configure Watson Discovery collection settings:
   - Enable **Smart Document Understanding (SDU)** if available on your plan for better PDF parsing
   - Set chunk size to approximately 500 tokens with 10% overlap for balanced retrieval precision
5. Run the script with a sample test document (any PDF) and verify it appears in the Discovery UI with correct metadata fields
6. Document the ingestion workflow in `README.md` — "How to add new documents"

**Relevant Context:**
- Watson Discovery Python SDK: `ibm_watson.DiscoveryV2` (v2 API — uses `project_id` + `collection_id` concepts)
- Key method: `discovery.add_document(project_id, collection_id, file=..., filename=..., file_content_type=..., metadata=json.dumps({...}))`
- Discovery v2 auto-handles chunking when Smart Document Understanding is enabled
- Metadata fields are stored under `document.metadata` in v2 and used as filters in the query API using the format `document.metadata.fieldname::value` (v2 filter syntax — NOT v1's `metadata.fieldname:"value"`)

**Status:** [ ] pending

---

### Sub-Task 3 — RAG Core Logic (Retrieval + Watsonx.ai Generation)

**Intent:**
Build the core RAG pipeline as a reusable Python module. Given a user query, this module retrieves relevant document chunks from Watson Discovery — optionally filtered by metadata — and passes them to Watsonx.ai Granite for answer generation. This module is what all three Orchestrate skills will call internally.

**Expected Outcomes:**
- A `rag_core.py` module with a `query(user_input, mode, filters=None)` function where `mode` is one of: `qa`, `summarize`, `troubleshoot` and `filters` is an optional dict of metadata constraints (e.g. `{"version": "4.16", "component": "bootstrap"}`)
- Three prompt templates in the `prompts/` folder tailored for each mode
- The `troubleshoot_prompt.txt` template is structured as a checklist-style prompt, guiding Granite to output numbered diagnostic steps (mimics a rule-based checklist from pure prompting — no separate rule engine needed at this stage)
- The module returns a structured response: `{ answer: str, source_documents: list[str] }`
- The module is tested locally via CLI before being wrapped into Orchestrate skills

**Todo List:**
1. Create `rag_core.py` with the following structure:
   - `get_iam_token(api_key)` — exchanges the IBM Cloud API key for a short-lived IAM Bearer token via `POST https://iam.cloud.ibm.com/identity/token`; caches the token and refreshes it when within 5 minutes of the 60-minute expiry
   - `retrieve(query, top_k=5, filters=None)` — calls Watson Discovery v2 `query` API with natural language query; if `filters` is provided, builds a v2 filter string (e.g. `document.metadata.version::4.16`) to narrow results to version-specific chunks; returns top-K passage chunks with their source document names and metadata
   - `generate(context_chunks, user_query, mode)` — builds a prompt using the appropriate template and calls Watsonx.ai `/ml/v1/text/generation` with a fresh IAM Bearer token; if `context_chunks` is empty, returns a "no information found" message without calling the LLM (avoids wasted token spend)
   - `query(user_input, mode='qa', filters=None)` — orchestrates retrieve → generate → return
2. Create prompt templates in `prompts/`:
   - `qa_prompt.txt` — instructs the model to answer only from provided context, cite the document name and version, and say "I don't know" if the context doesn't contain the answer
   - `summarize_prompt.txt` — instructs the model to produce a concise bullet-point summary of the retrieved content
   - `troubleshoot_prompt.txt` — instructs the model to produce a numbered checklist of diagnostic steps (e.g. "1. Verify DNS resolution… 2. Check NTP sync… 3. Confirm API VIP is reachable…") based on the retrieved runbook content
3. Set Watsonx.ai generation parameters for RAG:
   - `max_new_tokens`: 512
   - `temperature`: 0.2 (low for factual accuracy)
   - `repetition_penalty`: 1.1
4. Add a `__main__` block in `rag_core.py` for CLI testing:
   - `python rag_core.py "How do I install SNO on bare metal?"` (no filters)
   - `python rag_core.py "Bootstrap timeout" --mode troubleshoot --version 4.16 --component bootstrap`
5. Test all three modes locally with a sample document in Discovery, including a version-filtered query

**Relevant Context:**
- Watson Discovery v2 query API: `discovery.query(project_id, natural_language_query=..., filter="document.metadata.version::4.16", passages={"enabled": True, "per_document": True, "max_per_document": 3})`
- Discovery v2 filter syntax: `document.metadata.fieldname::value` for exact match; combine with `,` (AND) e.g. `document.metadata.version::4.16,document.metadata.component::bootstrap`
- Watsonx.ai SDK: `ibm_watsonx_ai` package, `ModelInference` class
- IAM token exchange: `POST https://iam.cloud.ibm.com/identity/token` with `grant_type=urn:ibm:params:oauth:grant-type:apikey&apikey={API_KEY}`; returns `access_token` valid for 3600 seconds
- Recommended model: `ibm/granite-13b-instruct-v2` — IBM-native, strong at instruction following and RAG, available on lite tier
- Prompt format for Granite: `<|system|>\n{system}\n<|user|>\n{question}\n<|assistant|>\n`
- Zero-results guard: if `retrieve()` returns an empty list, `generate()` must short-circuit and return the fallback string without invoking the LLM

**Status:** [ ] pending

---

### Sub-Task 4 — Watsonx Orchestrate Skill Definitions

**Intent:**
Wrap the RAG core logic in three distinct Watsonx Orchestrate "skills" — one for each user intent. Orchestrate skills are defined as OpenAPI 3.0 specs backed by a callable API endpoint. A lightweight FastAPI server will expose the RAG core as HTTP endpoints that Orchestrate can call. Each endpoint accepts an optional `domain` parameter so users can specify the problem area (e.g. `networking`, `bootstrap`, `storage`), which maps to metadata filters in the RAG core — this handles ambiguous queries without needing a separate intent router service.

**Expected Outcomes:**
- A `server.py` FastAPI app with three routes: `/ask`, `/summarize`, `/troubleshoot`
- All three routes accept an optional `domain` field that is translated into Discovery metadata filters
- Three OpenAPI skill definition files (YAML) in `skills/` that Orchestrate can import
- All three skills are imported and visible in the Watsonx Orchestrate "Skills & Apps" catalog
- The Orchestrate assistant can invoke each skill based on user intent via semantic matching on well-crafted example phrases

**Todo List:**
1. Dependencies are already captured in `requirements.txt` from Sub-Task 2; confirm `fastapi` and `uvicorn` are included
2. Create `server.py` (co-located with `rag_core.py` in the same project — same container on Code Engine):
   - Add an **API key auth dependency**: every request must include `X-API-Key: {secret}` header; the secret is set as a Code Engine environment variable and checked in a FastAPI dependency function; requests missing or with wrong key return HTTP 401
   - `POST /ask` — accepts `{ "question": str, "version": str | null, "domain": str | null }`, calls `rag_core.query(question, mode='qa', filters={...})`
   - `POST /summarize` — accepts `{ "topic": str, "version": str | null }`, calls `rag_core.query(topic, mode='summarize', filters={...})`
   - `POST /troubleshoot` — accepts `{ "issue": str, "version": str | null, "domain": str | null }`, calls `rag_core.query(issue, mode='troubleshoot', filters={...})`
   - All endpoints return `{ "answer": str, "sources": list[str] }`
   - Map `domain` string values to `component` metadata filter values (e.g. `"bootstrap"` → `document.metadata.component::bootstrap`)
3. Deploy the FastAPI server to IBM Code Engine — `server.py` and `rag_core.py` and `prompts/` are all packaged into **one container image**; Orchestrate must reach it over HTTPS
4. Generate the OpenAPI spec from FastAPI (`/openapi.json`) and save three separate YAML files in `skills/`:
   - `skill-ask.yaml`
   - `skill-summarize.yaml`
   - `skill-troubleshoot.yaml`
5. In Watsonx Orchestrate: go to Skills & Apps → Add Skill → Import from file → upload each YAML
6. For each skill, write **rich, specific example phrases** to maximise Orchestrate's semantic intent matching accuracy (this replaces a separate intent router):
   - Ask skill: "How do I configure ingress on SNO?", "What is the bootstrap process for OCP 4.16?", "Where can I find the pull secret settings?"
   - Summarize skill: "Summarize the SNO installation guide", "Give me an overview of OCP networking", "What does the etcd runbook say about backups?"
   - Troubleshoot skill: "My bootstrap is timing out during installation", "I'm getting a certificate error on the API server", "Help me debug etcd quorum failure", "Walk me through fixing a NetworkPolicy issue"
7. Test each skill end-to-end from the Orchestrate chat UI, including queries with and without `domain`/`version` specified

**Relevant Context:**
- IBM Code Engine (free tier): deploy a container from IBM Container Registry or directly from source; set all secrets (IBM API key, Discovery URL, Watsonx.ai project ID, `X-API-Key` secret) as Code Engine environment variables — never bake them into the container image
- Watsonx Orchestrate skill import: Skills & Apps → Add a skill → Upload an OpenAPI file; the OpenAPI spec must include the `securitySchemes` block declaring the `X-API-Key` header so Orchestrate can authenticate
- FastAPI auto-generates OpenAPI spec at `/openapi.json` — export and split per skill for clarity
- Domain → component mapping: `bootstrap`, `networking`, `storage`, `etcd`, `ingress`, `api-server`, `security`
- Code Engine cold-start latency: first request after idle may take 2–5 seconds; this is acceptable for an internal tool but note it in `README.md`

**Status:** [ ] pending

---

### Sub-Task 5 — Watsonx Orchestrate Assistant Configuration

**Intent:**
Configure a Watsonx Orchestrate AI assistant that ties all three skills together into a coherent conversational experience. The assistant should greet users, understand their intent, invoke the right skill, and present answers cleanly.

**Expected Outcomes:**
- A named assistant (e.g. "IBM IT Help Desk") is created in Watsonx Orchestrate
- The assistant has all three skills connected and correctly routes intents
- The assistant has a professional greeting, fallback message ("I couldn't find relevant information in the knowledge base"), and source citation in responses
- The assistant is accessible via the Watsonx Orchestrate chat UI and works end-to-end with real document queries

**Todo List:**
1. In Watsonx Orchestrate: go to AI Assistants → Create new assistant → name it "IBM IT Help Desk"
2. Connect all three imported skills to this assistant
3. Configure the assistant's **system prompt / persona**:
   - Name: IBM IT Help Desk
   - Role: technical support assistant for IBM India ISA division
   - Instruction: always cite the source document name in responses; if no relevant document is found, say so clearly
4. Set a welcome message: "Hello! I'm the IBM IT Help Desk assistant. I can answer questions, summarize documentation, and help you troubleshoot issues. What do you need help with today?"
5. Set a fallback message for when no skill can handle the query: "I wasn't able to find relevant information in the knowledge base. Please check IBM Docs directly or reach out to your team."
6. Run end-to-end acceptance tests:
   - Upload 2–3 real IBM internal documents into Discovery
   - Ask a factual question answered in one of the docs
   - Ask for a document summary
   - Describe a fictional error and ask for troubleshooting steps
7. Capture screenshots of each successful interaction for the internship demo/presentation

**Relevant Context:**
- Watsonx Orchestrate Assistant builder: watsonx-orchestrate.ibm.com → AI Assistants
- System prompt / instructions are set in the assistant's "Configuration" tab
- Source citation is added in the `answer` string returned by `rag_core.py` (append document name)

**Status:** [ ] pending

---

### Sub-Task 6 — Documentation & Demo Preparation

**Intent:**
Produce the project documentation and a demo-ready state so the internship deliverable can be reviewed by the manager and presented to the team. This is not just a formality — good documentation makes the project maintainable after you leave.

**Expected Outcomes:**
- `README.md` covers: architecture overview, setup instructions, how to add new documents, how to run the server, deploying to Code Engine, known limitations
- A `DEMO.md` file with a scripted walkthrough of 5–6 example queries that showcase all three skill modes
- A `Dockerfile` exists to build the production container image (packages `server.py`, `rag_core.py`, `prompts/`, `requirements.txt`)
- `HIGH-LEVEL-ARCHITECTURE.md` is present and up to date as the formal architecture deliverable for the manager presentation
- The project is committed to a Git repository (IBM GitHub or GitHub.com — confirm with manager)
- Credentials are never committed (`.gitignore` covers `.env` and `docs/`)

**Todo List:**
1. Write `README.md` with sections: Overview, Architecture, Prerequisites, Setup, Adding Documents, Running the Server, Deploying to Code Engine, Limitations (including Code Engine cold-start note)
2. Write `DEMO.md` with 5–6 pre-written queries and their expected answers (based on real documents uploaded)
3. Write `Dockerfile`:
   - Base image: `python:3.11-slim`
   - Copy `server.py`, `rag_core.py`, `prompts/`, `requirements.txt`
   - Run `pip install -r requirements.txt`
   - Entrypoint: `uvicorn server:app --host 0.0.0.0 --port 8080`
4. Create `.gitignore` — exclude `.env`, `__pycache__`, `*.pyc`, `docs/` (documents are internal, not for git); `manifest.json` is NOT gitignored
5. Initialize a Git repository and make an initial commit
6. Push to IBM GitHub Enterprise or a private GitHub repo (confirm policy with manager)
7. Record a short screen recording or prepare slides for the internship final presentation using `DEMO.md` as the script

**Relevant Context:**
- IBM GitHub Enterprise: github.ibm.com (requires IBM intranet access)
- The `docs/` folder should be in `.gitignore` since internal IBM documents must not be committed to any repo

**Status:** [ ] pending

---

## Architecture Diagram (Reference)

```
User (Watsonx Orchestrate Chat UI)
         |
         v
  [Watsonx Orchestrate Assistant]
         | semantic intent matching
         | (example phrases per skill)
    _____|______________________________
    |              |                   |
[Ask Skill]  [Summarize Skill]  [Troubleshoot Skill]
 question        topic              issue
 version?        version?           version?
 domain?                            domain?
    |              |                   |
    |______________|___________________|
         |
         | HTTPS + X-API-Key header
         v
   [IBM Code Engine — single container]
   ┌─────────────────────────────────┐
   │  server.py (FastAPI)            │
   │    │ auth check (X-API-Key)     │
   │    │ build metadata filters     │
   │    v                            │
   │  rag_core.py                    │
   │    ├── get_iam_token()          │
   │    ├── retrieve()               │
   │    │     └─ zero results? ──► fallback response (no LLM call)
   │    └── generate()              │
   └────────┬──────────────────┬────┘
            │                  │
            │ IBM Cloud IAM    │ IBM Cloud IAM
            │ Bearer token     │ Bearer token
            v                  v
   [Watson Discovery v2]   [Watsonx.ai]
    semantic NLQ search     Granite 13B
    + v2 metadata filter    Instruct v2
    document.metadata.*     (answer
    (version/component)      generation)
            │                  │
    [ranked chunks +       [grounded
     source + version]      answer text]
            └──────────────────┘
                     │
                     v
        { answer: str, sources: list[str] }
                     │
                     v
         [Watsonx Orchestrate chat UI]
              displays to user
```

## Technology Summary

| Layer | Service | Purpose |
|---|---|---|
| UI / Orchestration | IBM Watsonx Orchestrate | Chat UI, intent routing, skill execution |
| API Bridge + RAG Runtime | IBM Code Engine (Python 3.11 container) | Hosts `server.py` + `rag_core.py` in a single container; secured with `X-API-Key` |
| Knowledge Base | IBM Watson Discovery **v2** | Document ingestion, chunking, SDU parsing, metadata-filtered semantic search |
| LLM | IBM Watsonx.ai — Granite 13B Instruct v2 | Answer generation from retrieved context; auth via IAM Bearer token |
| Ingestion | Python `ingest.py` (run locally) | Offline document upload with metadata prompting; tracks state in `manifest.json` |

## Key Decisions Log

| Decision | Choice | Reason |
|---|---|---|
| LLM model | `ibm/granite-13b-instruct-v2` | IBM-native, free tier compatible, strong RAG performance |
| Document store | Watson Discovery v2 (not a vector DB like Pinecone) | Already in IBM ecosystem; v2 API uses project/collection model |
| Discovery filter syntax | `document.metadata.fieldname::value` (v2) | v1 syntax `metadata.fieldname:"value"` does NOT work in v2 |
| Skill delivery | OpenAPI-backed FastAPI server | Watsonx Orchestrate requires OpenAPI 3.0 spec for custom skills |
| API security | `X-API-Key` header on all FastAPI endpoints | Code Engine apps are publicly reachable; auth header prevents unauthorized calls |
| IAM authentication | Short-lived Bearer token via `iam.cloud.ibm.com` | Watsonx.ai requires IAM token, not static API key; token cached + refreshed in `rag_core.py` |
| Deployment topology | `server.py` + `rag_core.py` + `prompts/` in one Code Engine container | No internal network hop; simpler deployment, fewer moving parts |
| manifest.json location | Project root (not inside `docs/`) | `docs/` is gitignored; manifest must be committable to preserve ingestion history |
| Zero-result guard | Short-circuit before LLM call if Discovery returns no chunks | Avoids burning Watsonx.ai token budget on unanswerable queries |
| Document intake | Manual upload via script with metadata prompts | Incremental and repeatable; metadata captured at ingest time |
| Domain scope (Phase 1) | OCP + SNO only | Focused corpus → better retrieval quality, stronger demo narrative, achievable solo |
| Intent routing | Orchestrate semantic matching + rich example phrases + optional `domain` param | Same accuracy benefit as a separate router, zero extra infrastructure |
| Metadata filtering | product / version / deployment\_type / component | IBM docs are version-sensitive; wrong version = wrong answer |
| Troubleshoot prompt style | Checklist-format prompt template | Gets structured diagnostic steps from Granite without a rule engine; deterministic trees are Phase 2 |
| Confidence scoring | Deferred (not in Phase 1) | Uncalibrated scores mislead users; needs a real corpus to calibrate first |

---

## Phase 2 — Stretch Goals (Post-Internship / After August)

These are valid improvements that are intentionally out of scope for the internship deadline but should be documented for whoever maintains the project next.

| Item | Description |
|---|---|
| Deterministic troubleshooting trees | Hardcoded diagnostic checklists for known failure patterns (bootstrap timeout, etcd quorum loss, cert rotation) that supplement RAG retrieval |
| Confidence scoring | Surface Watson Discovery's `result_metadata.confidence` score, calibrated against the real document corpus once it exists |
| Additional domain collections | Expand beyond OCP/SNO to other IBM products (IBM Cloud, Db2, MQ, etc.) as separate Discovery collections |
| Slack / Teams integration | Add Watsonx Orchestrate channel integration for team-wide access |
| Document expiry / versioning | Auto-detect when a newer version of a document supersedes an older one and archive stale chunks |
