# Enterprise IT Help Desk Copilot

**IBM Internship POC — ISA India Division**
A citation-grounded technical support assistant for IBM IT products, built on the IBM watsonx platform. Covers OpenShift/SNO, watsonx Orchestrate, and IBM Bob. Answers are grounded exclusively in approved documentation and refuse to fabricate.

---

## What It Does

IBM employees ask technical IT questions in natural language. The system:
1. Classifies intent and extracts product/version/domain scope
2. Retrieves relevant chunks from an OpenSearch knowledge base (hybrid BM25 + kNN vector + RRF)
3. Validates evidence sufficiency before generating any answer
4. Generates a grounded answer using watsonx.ai
5. Returns the answer with exact citations — document title, product, page numbers
6. Refuses to answer when evidence is insufficient, citations are missing, or the question is out of scope

---

## Architecture

```
User (Orchestrate) → POST /v1/assist → FastAPI
                                          ↓
                                   LangGraph 7-node workflow
                                    ├── classify_extract
                                    ├── resolve_scope
                                    ├── retrieve (OpenSearch hybrid)
                                    ├── grade_evidence
                                    ├── generate (watsonx.ai Granite)
                                    ├── format_response
                                    └── safety_check
                                          ↓
                                   JSON response with citations
```

| Component | Technology |
|---|---|
| UI | IBM watsonx Orchestrate |
| API | Python 3.11 + FastAPI |
| Agent | LangGraph bounded 7-node workflow |
| Retrieval | OpenSearch (BM25 + kNN vector hybrid + RRF) |
| Embeddings | watsonx.ai `ibm/granite-embedding-278m-multilingual` (dim=768) |
| Generation | watsonx.ai (configurable — `meta-llama/llama-3-3-70b-instruct` default) |
| Document Storage | IBM Cloud Object Storage |
| Ingestion | pdfminer.six + web fetcher + custom chunker-v5 |

---

## Knowledge Base

### OpenShift & SNO (`ocp_sno_support`) — 7,940 chunks

| Document | OCP Version | Status |
|---|---|---|
| SNO Installation Guide | 4.16 | ✅ INDEXED |
| SNO Installation Guide | 4.14 | ✅ INDEXED |
| Networking Guide | 4.16 | ✅ INDEXED |
| Storage Guide | 4.16 | ⚠️ PARTIAL (577/588 — 11 dense-table pages exceed token limit; recovers at v2 re-ingestion) |
| Troubleshooting / Support Guide | 4.16 | ✅ INDEXED |
| Authentication & Authorization Guide | 4.16 | ✅ INDEXED |
| Operators Guide | 4.16 | ✅ INDEXED |
| Updating Clusters Guide | 4.16 | ✅ INDEXED |

### watsonx Orchestrate (`watsonx_orchestrate`) — 4,869 chunks

| Source | Type | Status |
|---|---|---|
| developer.watson-orchestrate.ibm.com (llms.txt) | Web / ADK docs | ✅ INDEXED |
| watsonx Orchestrate L2 client deck | PDF (public) | ✅ INDEXED |
| watsonx Orchestrate L2 seller deck | PDF (internal) | ✅ INDEXED |
| watsonx Orchestrate L2 master notes | PDF (internal) | ✅ INDEXED |
| watsonx Orchestrate L3 demo guide | PDF (internal) | ✅ INDEXED |

### IBM Bob (`ibm_bob`) — 1,136 chunks

| Source | Type | Status |
|---|---|---|
| IBM Bob developer documentation (web) | Web | ✅ INDEXED |

### Total: 13,945 chunks across 198 documents

---

## Demo Flow

### Prerequisites
- Vaibhav's FastAPI server running locally with ngrok tunnel active
- API key available

### Step 1 — Health check
```bash
curl https://<ngrok-url>/healthz
# Expected: {"status":"ok"}

curl https://<ngrok-url>/readyz
# Expected: {"status":"ready","opensearch":true,"watsonx":true}
```

### Step 2 — Factual question (should return ANSWERED with citations)
```bash
curl -X POST https://<ngrok-url>/v1/assist \
  -H "X-API-Key: <API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What DNS records are required before starting SNO 4.16 installation?",
    "requested_scope": {"ocp_version": "4.16", "deployment_type": "SNO"}
  }'
```
Expected: `"status": "ANSWERED"` with citations to SNO installation guide pages.

### Step 3 — Ambiguous question (should return NEEDS_CLARIFICATION)
```bash
curl -X POST https://<ngrok-url>/v1/assist \
  -H "X-API-Key: <API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"question": "My cluster installation failed"}'
```
Expected: `"status": "NEEDS_CLARIFICATION"` asking for OCP version and deployment type.

### Step 4 — Out-of-scope question (should return OUT_OF_SCOPE)
```bash
curl -X POST https://<ngrok-url>/v1/assist \
  -H "X-API-Key: <API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"question": "How do I configure ServiceNow integration?"}'
```
Expected: `"status": "OUT_OF_SCOPE"` — no hallucination, no fabricated answer.

---

## Evaluation Results (Day 9)

**38/40 questions passed = 95%** (target was 70%+)

| Category | Pass | Total | Rate |
|---|---|---|---|
| factual | 11/15 | 73% | ✅ |
| troubleshoot | 10/10 | 100% | ✅ |
| version | 4/5 | 80% | ✅ |
| ambiguous | 5/5 | 100% | ✅ |
| out_of_scope | 5/5 | 100% | ✅ |
| clarification | 4/4 | 100% | ✅ |

Only q026 and q028 fail — both require cross-version comparison (OCP 4.14 vs 4.16) which needs multi-document retrieval not yet implemented.

---

## Repository Structure

```
├── app/
│   ├── api/              # FastAPI routes, schemas, auth dependencies
│   ├── graph/            # LangGraph 7-node workflow
│   ├── ingestion/        # PDF + web → chunks → OpenSearch pipeline
│   ├── policy/           # Domain and evidence policy
│   ├── providers/        # watsonx.ai embeddings + generation
│   ├── retrieval/        # Hybrid retriever, filters, RRF fusion
│   └── services/         # assist_service, domains_service
├── config/
│   ├── corpus/           # Per-domain ingestion manifests
│   ├── domains.yaml      # Domain registry
│   └── taxonomy/         # Controlled vocabulary
├── scripts/
│   ├── create_index.py   # Creates OpenSearch indices
│   ├── podman_opensearch.sh  # Local Podman/OpenSearch helper
│   └── run_eval.py       # Evaluation runner
├── tests/
│   ├── unit/             # 116 unit tests
│   └── evaluation/       # Gold questions + results
└── openapi/              # OpenAPI spec for Orchestrate import
```

---

## Setup

### Environment variables (.env — never commit)
```
OPENSEARCH_URL=http://localhost:9200
OPENSEARCH_USERNAME=
OPENSEARCH_PASSWORD=
OPENSEARCH_VERIFY_CERTS=true
OPENSEARCH_INDEX_CHUNKS=knowledge_chunks_v1
OPENSEARCH_INDEX_DOCS=knowledge_documents_v1
OPENSEARCH_EMBEDDING_DIM=768
WATSONX_URL=https://us-south.ml.cloud.ibm.com
WATSONX_PROJECT_ID=<project-id>
WATSONX_EMBEDDING_MODEL_ID=ibm/granite-embedding-278m-multilingual
WATSONX_CHAT_MODEL_ID=<verified-chat-model-id>
IBM_CLOUD_API_KEY=<api-key>
COS_ENDPOINT=https://s3.us-south.cloud-object-storage.appdomain.cloud
COS_BUCKET=ithelpdeskfinal-donotdelete-pr-9yawx7m9f3akb4
COS_API_KEY=<cos-api-key>
API_KEY_SECRET=<api-key-for-x-api-key-header>
```

> **Embedding model note:** `ibm/slate-125m-english-rtrvr-v2` is **withdrawn** (2026-08-08).
> The current model is `ibm/granite-embedding-278m-multilingual` (768-dim).
> The existing v1 index was built with this model — no migration needed unless rebuilding to v2.

### Start the server
```bash
.venv/bin/uvicorn app.main:app --port 8000 --reload
```

### Verify readiness
```bash
curl http://localhost:8000/readyz
# Expected: {"status":"ready","opensearch":true,"watsonx":true}
```

### Expose to watsonx Orchestrate via ngrok
```bash
ngrok http 8000
# Copy the https://xxxxx.ngrok-free.app URL
# Update servers[0].url in openapi/it_helpdesk_v1.yaml before importing into Orchestrate
```

### Run ingestion
```bash
python3 -m app.ingestion.run --manifest config/corpus/ocp_sno_poc.yaml
```

### Run evaluation
```bash
python3 scripts/run_eval.py --url https://<ngrok-url>
```

### Smoke tests (multi-domain)
```bash
API_KEY=$(grep "^API_KEY_SECRET=" .env | cut -d= -f2)

# List available domains
curl -s http://localhost:8000/v1/domains \
  -H "X-API-Key: $API_KEY" | python3 -m json.tool

# OCP question
curl -s -X POST http://localhost:8000/v1/assist \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{"question":"How do I configure DNS for SNO installation on OCP 4.16?","requested_scope":{"domain_id":"ocp_sno_support","ocp_version":"4.16","deployment_type":"SNO"}}' | python3 -m json.tool

# Orchestrate question
curl -s -X POST http://localhost:8000/v1/assist \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{"question":"How do I create a tool in watsonx Orchestrate ADK?","requested_scope":{"domain_id":"watsonx_orchestrate"}}' | python3 -m json.tool

# Bob question
curl -s -X POST http://localhost:8000/v1/assist \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{"question":"How do I use subagents in IBM Bob?","requested_scope":{"domain_id":"ibm_bob"}}' | python3 -m json.tool
```

### Local OpenSearch with Podman

Use the official Podman installer, then run the local helper:

```bash
scripts/podman_opensearch.sh init
scripts/podman_opensearch.sh start
scripts/podman_opensearch.sh verify
```

The helper uses a rootless Podman machine named `it-helpdesk`, binds data and
snapshots under `~/.local/share/it-helpdesk/opensearch`, and only exposes
OpenSearch on `127.0.0.1:9200`. See `docs/podman-opensearch.md` for recovery,
snapshot, and remote TLS configuration.

---

## Team

| Developer | GitHub | Branch | Owns |
|---|---|---|---|
| Vaibhav | Vaibhav-J20 | `feature/dev-a-api-agent` | FastAPI, LangGraph, retrieval, watsonx.ai |
| Anush | Anush-28-ibm | `feature/dev-b-ingestion` | Ingestion pipeline, taxonomy, evaluation |

---

*IBM India ISA Division — Internship Project 2026*
