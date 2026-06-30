# High Level Architecture — IBM IT Help Desk Chatbot
**IBM India ISA Division | Internship Project | Watsonx Platform**

---

## 1. Executive Summary

The IBM IT Help Desk Chatbot is an internal AI assistant built entirely on IBM's Watsonx platform. It enables IBM India ISA technical staff to query internal OCP/SNO documentation, get grounded answers, request document summaries, and receive step-by-step troubleshooting guidance — all from a single conversational interface in IBM Watsonx Orchestrate.

The system uses **Retrieval-Augmented Generation (RAG)**: instead of relying on the LLM's pre-trained knowledge (which goes stale and hallucinates), every answer is grounded in retrieved passages from the team's own internal documents, with the source document name and version cited in every response.

**Phase 1 scope:** Red Hat OpenShift (OCP) and Single Node OpenShift (SNO) documentation only.

---

## 2. System Context

```
┌─────────────────────────────────────────────────────┐
│                  IBM Internal Network                │
│                                                     │
│   IBM ISA Technical Staff                           │
│         │                                           │
│         │  browser / IBM SSO                        │
│         ▼                                           │
│   Watsonx Orchestrate Chat UI  ◄──────────────────┐ │
│         │                                          │ │
│         │ HTTPS (OpenAPI skill calls)              │ │
│         ▼                                          │ │
│   IBM Code Engine (FastAPI)                        │ │
│         │                                          │ │
│    ┌────┴────┐                                     │ │
│    ▼         ▼                                     │ │
│  Watson    Watsonx.ai  ──── IBM Cloud IAM ─────────┘ │
│  Discovery  (Granite)        (auth)                  │
│  v2                                                  │
└─────────────────────────────────────────────────────┘

All services run within IBM Cloud. No external internet dependencies.
```

---

## 3. Architecture Layers

The system is composed of five distinct layers, each with a single responsibility.

### Layer 1 — Presentation (Watsonx Orchestrate)

| Attribute | Value |
|---|---|
| Service | IBM Watsonx Orchestrate |
| URL | `https://dl.watson-orchestrate.ibm.com` |
| Role | Chat UI, user-facing assistant, skill execution engine |

The Watsonx Orchestrate **AI Assistant** (named "IBM IT Help Desk") is the only user-facing surface. Users interact via the Orchestrate chat interface — no separate web app, no Slack/Teams integration in Phase 1.

The assistant holds three **Skills** (Ask, Summarize, Troubleshoot). When a user sends a message, Orchestrate performs **semantic intent matching** against example phrases registered per skill and invokes the matching skill's API endpoint. Optional `version` and `domain` parameters are extracted from the user's message and forwarded in the request body.

**Fallback behaviour:** If no skill matches the intent, the assistant replies: *"I wasn't able to find relevant information in the knowledge base. Please check IBM Docs directly or reach out to your team."*

---

### Layer 2 — API Bridge (FastAPI on IBM Code Engine)

| Attribute | Value |
|---|---|
| Service | IBM Code Engine (serverless, free tier) |
| Runtime | Python 3.11 container |
| Framework | FastAPI + Uvicorn |
| Files packaged | `server.py`, `rag_core.py`, `prompts/` directory |
| Auth | `X-API-Key` header (secret stored as Code Engine env var) |

This layer is a **single container** hosting both `server.py` (the HTTP interface) and `rag_core.py` (the RAG logic). They communicate via direct Python function calls — no internal network hop.

**Three HTTP endpoints:**

| Endpoint | Method | Request Body | Purpose |
|---|---|---|---|
| `/ask` | POST | `{ question, version?, domain? }` | Factual Q&A from docs |
| `/summarize` | POST | `{ topic, version? }` | Document summarisation |
| `/troubleshoot` | POST | `{ issue, version?, domain? }` | Step-by-step diagnostic guidance |

All endpoints return: `{ "answer": str, "sources": list[str] }`

**Security:** Every request must include an `X-API-Key: {secret}` header. Requests without it return HTTP 401. The secret is injected at runtime via Code Engine environment variables and is never baked into the container image.

**Cold-start note:** IBM Code Engine scales to zero after idle periods. The first request after idle may take 2–5 seconds. This is acceptable for an internal tool.

---

### Layer 3 — RAG Core Logic (`rag_core.py`)

This is the intelligence of the system. It executes in the same Code Engine container as `server.py`.

**Functions:**

```
get_iam_token(api_key)
  └── POSTs to https://iam.cloud.ibm.com/identity/token
  └── Caches token + expiry timestamp
  └── Auto-refreshes when < 5 min from 60-min expiry

retrieve(query, top_k=5, filters=None)
  └── Calls Watson Discovery v2 NLQ query API
  └── If filters provided, builds v2 filter string:
        document.metadata.version::4.16,document.metadata.component::bootstrap
  └── Returns top-K passage chunks + source doc name + version
  └── Returns [] if no results found

generate(context_chunks, user_query, mode)
  └── If context_chunks is EMPTY → return fallback string immediately (no LLM call)
  └── Loads prompt template from prompts/{mode}_prompt.txt
  └── Builds Granite prompt: <|system|> + template + <|user|> + query + context + <|assistant|>
  └── Calls Watsonx.ai /ml/v1/text/generation with IAM Bearer token
  └── Returns generated answer string

query(user_input, mode='qa', filters=None)
  └── Calls retrieve() → calls generate() → returns { answer, sources }
```

**Zero-result guard:** If `retrieve()` returns an empty list, `generate()` short-circuits and returns a "no information found" message without calling the LLM. This is critical for controlling Watsonx.ai token consumption on the free tier.

**Prompt templates** (stored in `prompts/`):

| File | Mode | Instruction style |
|---|---|---|
| `qa_prompt.txt` | `qa` | Answer only from context; cite doc name + version; say "I don't know" if not found |
| `summarize_prompt.txt` | `summarize` | Produce concise bullet-point summary of retrieved content |
| `troubleshoot_prompt.txt` | `troubleshoot` | Produce numbered checklist of diagnostic steps (e.g. "1. Verify DNS… 2. Check NTP…") |

**LLM parameters:**
- Model: `ibm/granite-13b-instruct-v2`
- `max_new_tokens`: 512
- `temperature`: 0.2
- `repetition_penalty`: 1.1

---

### Layer 4 — Knowledge Base (IBM Watson Discovery v2)

| Attribute | Value |
|---|---|
| Service | IBM Watson Discovery (Plus or Lite plan) |
| API version | v2 |
| Project type | Document Retrieval |
| Collection name | `ibm-helpdesk-docs` |
| Indexing | Smart Document Understanding (SDU) — automatic chunking ~500 tokens |

Watson Discovery is the **sole source of truth** for all document content. It handles:
- PDF and DOCX parsing (via SDU)
- Chunking into ~500-token passages with overlap
- Full-text and semantic (vector) indexing
- Metadata-filtered retrieval

**Document metadata schema** (attached to every uploaded document):

```json
{
  "product": "OpenShift",
  "version": "4.16",
  "deployment_type": "SNO",
  "component": "bootstrap"
}
```

**Query filter syntax (v2):** `document.metadata.version::4.16,document.metadata.component::bootstrap`

> ⚠️ Important: Watson Discovery v2 uses `document.metadata.fieldname::value` filter syntax. The v1 syntax `metadata.fieldname:"value"` is **not compatible** with v2 and will silently return unfiltered results.

**Document ingestion** is handled offline by `ingest.py` (not part of the running server). A `manifest.json` at project root tracks which files have been uploaded and their metadata, making re-runs idempotent.

---

### Layer 5 — LLM Inference (IBM Watsonx.ai)

| Attribute | Value |
|---|---|
| Service | IBM Watsonx.ai |
| Inference endpoint | `https://{region}.ml.cloud.ibm.com/ml/v1/text/generation` |
| Model | `ibm/granite-13b-instruct-v2` |
| Authentication | IBM Cloud IAM Bearer token (60-min expiry, auto-refreshed) |

Watsonx.ai receives **only the retrieved context chunks + user query** — it never has direct access to the full document store. This is the RAG guarantee: the LLM is constrained to answer from what Discovery retrieved.

**IAM token flow:**
```
rag_core.py startup / token expiry
    │
    ▼
POST https://iam.cloud.ibm.com/identity/token
  grant_type=urn:ibm:params:oauth:grant-type:apikey
  apikey={IBM_CLOUD_API_KEY}
    │
    ▼
{ access_token: "eyJ...", expires_in: 3600 }
    │
    ▼
Cached in memory; refreshed when < 5 min remaining
```

---

## 4. End-to-End Request Flow

```
Step 1 — User types: "My bootstrap is timing out during SNO 4.16 install"
         in Watsonx Orchestrate chat UI

Step 2 — Orchestrate semantic intent matching identifies: Troubleshoot Skill
         Extracts: version=4.16, domain=bootstrap (from context)
         Sends: POST /troubleshoot
                { "issue": "bootstrap timing out", "version": "4.16", "domain": "bootstrap" }
                X-API-Key: {secret}

Step 3 — server.py (Code Engine)
         Auth check: X-API-Key header validated ✓
         Builds filters: { "version": "4.16", "component": "bootstrap" }
         Calls: rag_core.query(issue, mode='troubleshoot', filters={...})

Step 4 — rag_core.retrieve()
         Discovery v2 NLQ query:
           natural_language_query = "bootstrap timing out"
           filter = "document.metadata.version::4.16,document.metadata.component::bootstrap"
           passages.enabled = True, max_per_document = 3
         Returns: [chunk1, chunk2, chunk3] from "SNO-4.16-bootstrap-runbook.pdf"

         [If 0 results → skip to fallback, return without LLM call]

Step 5 — rag_core.generate()
         Loads: prompts/troubleshoot_prompt.txt
         Builds Granite prompt with system instruction + context chunks + user query
         Calls: Watsonx.ai /ml/v1/text/generation with IAM Bearer token
         Returns: "1. Verify DNS resolution for api.cluster.domain...\n2. Check NTP sync..."

Step 6 — server.py returns:
         {
           "answer": "1. Verify DNS resolution...\n2. Check NTP...\n[Source: SNO-4.16-bootstrap-runbook.pdf, v4.16]",
           "sources": ["SNO-4.16-bootstrap-runbook.pdf"]
         }

Step 7 — Watsonx Orchestrate displays the answer to the user in the chat UI
```

---

## 5. Data Flow Diagram

```
WRITE PATH (document ingestion — offline, run manually)

  Developer drops PDF into docs/
         │
         ▼
  ingest.py
    prompts for metadata (product, version, deployment_type, component)
         │
         ▼
  Watson Discovery v2
    add_document(file, metadata=JSON)
    SDU chunks → vector index
         │
         ▼
  manifest.json updated at project root


READ PATH (runtime — every user query)

  Watsonx Orchestrate
  ──── HTTPS + X-API-Key ────►  IBM Code Engine
                                  server.py
                                    │ auth check
                                    │ build filters
                                    ▼
                                  rag_core.py
                                    │
                          ┌─────────┴──────────┐
                          ▼                    │
                  Watson Discovery v2          │
                  NLQ + metadata filter        │
                          │                    │
                    chunks found?              │
                    NO → fallback ────────────►│
                    YES ↓                      │
                  top-K passages               │
                          │                    │
                          └──────────►  Watsonx.ai
                                       Granite 13B
                                       (with IAM token)
                                           │
                                     generated answer
                                           │
                          ◄────────────────┘
                  { answer, sources }
                          │
  Watsonx Orchestrate  ◄──┘
  displays to user
```

---

## 6. Component Inventory

| Component | Technology | Hosted On | Role |
|---|---|---|---|
| Chat UI | Watsonx Orchestrate Assistant | IBM Cloud (SaaS) | User interface |
| Skill definitions | OpenAPI 3.0 YAML (3 files) | Imported into Orchestrate | Declares API contracts |
| API server | FastAPI + Uvicorn (`server.py`) | IBM Code Engine | HTTP → RAG bridge |
| RAG pipeline | Python (`rag_core.py`) | IBM Code Engine (same container) | Retrieve + generate |
| Prompt templates | Plain text files (`prompts/`) | IBM Code Engine (same container) | LLM instruction control |
| Knowledge base | Watson Discovery v2 | IBM Cloud (managed) | Document store + search |
| LLM | Granite 13B Instruct v2 | Watsonx.ai (IBM Cloud) | Answer generation |
| IAM auth | IBM Cloud Identity & Access Mgmt | IBM Cloud (shared) | Token issuance for Watsonx.ai |
| Ingestion script | Python (`ingest.py`) | Local developer machine | Offline document upload |
| Ingestion index | `manifest.json` | Git repo root | Tracks uploaded docs |
| Secrets | `.env` (local) / Code Engine env vars (prod) | Never in container image | Credential management |

---

## 7. Security Model

| Boundary | Mechanism | Notes |
|---|---|---|
| User → Orchestrate | IBM SSO / IBM Cloud IAM | Orchestrate enforces IBM account login |
| Orchestrate → Code Engine | `X-API-Key` HTTP header | Secret stored in Code Engine env vars; declared in OpenAPI `securitySchemes` |
| Code Engine → Watson Discovery | IBM Cloud API key (IAM) | Set as Code Engine env var `DISCOVERY_API_KEY` |
| Code Engine → Watsonx.ai | Short-lived IAM Bearer token | Exchanged from API key at runtime; cached + refreshed in `rag_core.py` |
| Documents | Not committed to git; `docs/` is gitignored | Only `manifest.json` (metadata only, no content) is committed |
| Secrets | Never in container image; never in git | Managed exclusively via `.env` locally and Code Engine env vars in production |

---

## 8. Deployment Topology

```
IBM Cloud Account
│
├── Watson Discovery (Plus/Lite)
│     └── Project: "it-helpdesk"
│           └── Collection: "ibm-helpdesk-docs"
│
├── Watsonx.ai
│     └── Project: "it-helpdesk"
│           └── Model: ibm/granite-13b-instruct-v2
│
├── IBM Code Engine
│     └── Application: "it-helpdesk-api"
│           └── Container image from IBM Container Registry
│                 ├── server.py
│                 ├── rag_core.py
│                 └── prompts/
│                       ├── qa_prompt.txt
│                       ├── summarize_prompt.txt
│                       └── troubleshoot_prompt.txt
│           └── Environment variables (secrets):
│                 IBM_CLOUD_API_KEY, DISCOVERY_URL,
│                 DISCOVERY_PROJECT_ID, DISCOVERY_COLLECTION_ID,
│                 WATSONX_PROJECT_ID, WATSONX_REGION,
│                 API_KEY_SECRET (for X-API-Key auth)
│
└── Watsonx Orchestrate
      └── Assistant: "IBM IT Help Desk"
            ├── Skill: Ask        (linked to /ask endpoint)
            ├── Skill: Summarize  (linked to /summarize endpoint)
            └── Skill: Troubleshoot (linked to /troubleshoot endpoint)
```

---

## 9. Project File Structure

```
it-helpdesk/
├── docs/                       # GITIGNORED — internal IBM documents go here
├── manifest.json               # committed — tracks ingested files + metadata
├── ingest.py                   # offline ingestion script (run locally)
├── rag_core.py                 # RAG pipeline (packaged into container)
├── server.py                   # FastAPI app (packaged into container)
├── prompts/                    # prompt templates (packaged into container)
│   ├── qa_prompt.txt
│   ├── summarize_prompt.txt
│   └── troubleshoot_prompt.txt
├── skills/                     # OpenAPI skill specs (imported into Orchestrate)
│   ├── skill-ask.yaml
│   ├── skill-summarize.yaml
│   └── skill-troubleshoot.yaml
├── Dockerfile                  # container build definition
├── requirements.txt            # ibm-watson, ibm-watsonx-ai, fastapi, uvicorn, requests, python-dotenv
├── .env                        # GITIGNORED — local credentials only
├── .gitignore
├── README.md
├── DEMO.md
└── HIGH-LEVEL-ARCHITECTURE.md  # this document
```

---

## 10. Key Technical Constraints & Decisions

| Decision | Choice | Rationale |
|---|---|---|
| LLM model | `ibm/granite-13b-instruct-v2` | IBM-native; free tier compatible; strong RAG + instruction-following |
| Discovery API version | v2 | Current IBM offering; project/collection model; v1 is legacy |
| Discovery filter syntax | `document.metadata.field::value` | v2-specific — v1 syntax silently breaks filtering |
| API security | `X-API-Key` header | Code Engine apps are public by default; minimum viable auth for internal tool |
| IAM token handling | Cached + auto-refreshed in `rag_core.py` | Watsonx.ai requires Bearer token, not static key; 60-min expiry must be managed |
| Deployment topology | Single Code Engine container | No network hop between server and RAG core; simpler ops |
| Zero-result guard | Short-circuit before LLM if no chunks | Protects free-tier token budget; prevents confabulation on empty context |
| Intent routing | Orchestrate native matching + rich example phrases | Avoids a separate router service; `domain` param handles ambiguity |
| Metadata schema | product / version / deployment_type / component | IBM docs are version-sensitive; version-unaware retrieval = wrong answers |
| manifest.json location | Project root (not inside `docs/`) | `docs/` gitignored; manifest must survive a fresh clone |
| Domain scope | OCP + SNO (Phase 1) | Focused corpus; stronger retrieval quality; achievable solo before August |

---

## 11. Phase 2 — Future Improvements

The following are valid enhancements intentionally deferred beyond the internship deadline.

| Item | Description | Trigger |
|---|---|---|
| Deterministic troubleshooting trees | Hardcoded diagnostic checklists for known failure patterns (bootstrap timeout, etcd quorum loss) that supplement RAG | When runbooks are available to author the trees |
| Confidence scoring | Surface Discovery's `result_metadata.confidence`, calibrated to the real corpus | After corpus is stable and scores can be evaluated |
| Additional domain collections | Expand to IBM Cloud, Db2, MQ, etc. as separate Discovery collections | When new document domains are identified |
| Slack / Teams integration | Add Watsonx Orchestrate channel integration | When team-wide rollout is requested |
| Document expiry / versioning | Detect and archive chunks from superseded doc versions | When multiple versions of the same doc coexist |
