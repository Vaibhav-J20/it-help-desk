# OpenShift & SNO Technical Support Copilot

**IBM Internship POC — ISA India Division**
A citation-grounded technical support chatbot for Red Hat OpenShift Container Platform (OCP) and Single Node OpenShift (SNO), built entirely on the IBM Watsonx platform.

> **Day 11 update:** The backend has been expanded into an Enterprise IT Support Copilot with additional knowledge domains for IBM watsonx Orchestrate and IBM Bob. See `BOB-DAY11-MULTIDOMAIN-CONTEXT.md` for the current multi-domain handoff, Orchestrate UI settings, verification results, and next tasks.

---

## What It Does

Users ask OpenShift/SNO technical questions in natural language. The system:
1. Classifies intent and extracts scope (version, deployment type)
2. Retrieves relevant chunks from an OpenSearch knowledge base (hybrid BM25 + vector)
3. Generates a grounded answer using watsonx.ai Granite
4. Returns the answer with exact citations — document title, OCP version, page numbers
5. Refuses to answer when evidence is insufficient or the question is out of scope

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
| Retrieval | OpenSearch (BM25 + kNN vector hybrid) |
| Embeddings | watsonx.ai `ibm/slate-125m-english-rtrvr-v2` (dim=768) |
| Generation | watsonx.ai Granite |
| PDF Storage | IBM Cloud Object Storage |
| Ingestion | pdfminer.six + custom chunker (350–550 tokens) |

---

## Knowledge Base

| Document | OCP Version | Chunks |
|---|---|---|
| SNO Installation Guide | 4.16 | ~158 |
| SNO Installation Guide | 4.14 | ~138 |
| Networking Guide | 4.16 | ~1850 |
| Storage Guide | 4.16 | ~491 |
| Troubleshooting / Support Guide | 4.16 | ~300 |
| Authentication & Authorization Guide | 4.16 | ~380 |
| Operators Guide | 4.16 | ~901 |
| Updating Clusters Guide | 4.16 | ~306 |
| **Total** | | **~15,400 chunks** |

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
│   ├── api/              # FastAPI routes + schemas (Developer A)
│   ├── graph/            # LangGraph 7-node workflow (Developer A)
│   ├── ingestion/        # PDF → chunks → OpenSearch pipeline (Developer B)
│   ├── policy/           # Domain out-of-scope policy (Developer A)
│   └── providers/        # watsonx.ai embeddings + generation (Developer A)
├── config/
│   ├── corpus/           # Approved PDF manifest (Developer B)
│   └── taxonomy/         # Controlled vocabulary — locked contract
├── scripts/
│   ├── create_index.py   # Creates OpenSearch indices
│   ├── audit_chunks.py   # Chunk quality audit
│   └── run_eval.py       # 40-question evaluation runner
├── tests/
│   ├── unit/             # 33 unit tests (Developer B)
│   └── evaluation/       # 40 gold questions + results
└── openapi/              # OpenAPI spec for Orchestrate import
```

---

## Setup

### Environment variables (.env — never commit)
```
OPENSEARCH_URL=https://localhost:9200
OPENSEARCH_USERNAME=admin
OPENSEARCH_PASSWORD=<password>
OPENSEARCH_INDEX_CHUNKS=knowledge_chunks_v1
OPENSEARCH_INDEX_DOCS=knowledge_documents_v1
WATSONX_URL=https://us-south.ml.cloud.ibm.com
WATSONX_PROJECT_ID=<project-id>
WATSONX_EMBEDDING_MODEL_ID=ibm/slate-125m-english-rtrvr-v2
IBM_CLOUD_API_KEY=<api-key>
COS_ENDPOINT=https://s3.us-south.cloud-object-storage.appdomain.cloud
COS_BUCKET=ithelpdeskfinal-donotdelete-pr-9yawx7m9f3akb4
COS_API_KEY=<cos-api-key>
```

### Run ingestion
```bash
python3 -m app.ingestion.run --manifest config/corpus/ocp_sno_poc.yaml
```

### Run evaluation
```bash
python3 scripts/run_eval.py --url https://<ngrok-url>
```

---

## Team

| Developer | GitHub | Branch | Owns |
|---|---|---|---|
| Vaibhav | Vaibhav-J20 | `feature/dev-a-api-agent` | FastAPI, LangGraph, retrieval, watsonx.ai |
| Anush | Anush-28-ibm | `feature/dev-b-ingestion` | Ingestion pipeline, taxonomy, evaluation |

---

*IBM India ISA Division — Internship Project 2026*
