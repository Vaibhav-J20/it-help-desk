# Developer A (Vaibhav) — IBM Bob Session Prompt
## Use at the start of every build session

**How to use this file:**  
Copy everything inside the code block below and paste it as your first message to IBM Bob.  
Then tell Bob which specific task you are working on today.

---

```
You are contributing to the OpenShift & SNO Technical Support Copilot POC.
This is a two-week IBM internship project (IBM India ISA division).

---

## Project Identity

- Repo: https://github.com/Vaibhav-J20/it-help-desk
- Developer A (you are working with): Vaibhav (GitHub: Vaibhav-J20) — branch: feature/dev-a-api-agent
- Developer B: Anush (GitHub: Anush-28-ibm) — branch: feature/dev-b-ingestion
- Architecture document: ARCHITECTURE_IMPLEMENTATION_V3.md (in repo root)

---

## What This System Does

A citation-grounded OpenShift/SNO technical-support copilot for IBM internal users.

- Users interact through IBM watsonx Orchestrate
- Orchestrate calls a FastAPI backend via POST /v1/assist
- The backend runs a bounded LangGraph workflow
- The workflow retrieves from OpenSearch (BM25 + vector hybrid)
- watsonx.ai generates grounded answers with inline citations
- Every answer must cite exact page numbers from approved PDF documents
- The system never invents answers when evidence is insufficient

---

## Mandatory Technology Stack

| Concern | Technology |
|---|---|
| User interface | IBM watsonx Orchestrate |
| API service | Python 3.11 + FastAPI |
| Agent workflow | LangGraph (bounded, 7 nodes) |
| Retrieval | OpenSearch only (BM25 + vector + metadata filters) |
| PDF storage | IBM Cloud Object Storage |
| Embeddings | watsonx.ai (model ID from config, never hard-coded) |
| Answer generation | watsonx.ai (model ID from config, never hard-coded) |

## Explicitly Excluded (do not introduce these under any circumstances)

- Watson Discovery
- AstraDB, Redis, LangSmith
- ServiceNow, Jira
- Live OpenShift cluster access
- Web search
- Multi-agent systems
- Fine-tuning
- Complex background workers

---

## Repository Structure (ARCHITECTURE_IMPLEMENTATION_V3.md section 13)

it-helpdesk/
├── ARCHITECTURE_IMPLEMENTATION_V3.md
├── PROJECT_CONTEXT.md
├── DECISIONS.md
├── TASKS.md
├── README.md
├── .env.example
├── pyproject.toml
├── Dockerfile
├── config/
│   ├── corpus/ocp_sno_poc.yaml
│   ├── domains.yaml
│   └── taxonomy/ocp_sno.yaml
├── app/
│   ├── main.py
│   ├── api/
│   │   ├── routes.py
│   │   ├── dependencies.py
│   │   └── schemas.py
│   ├── graph/
│   │   ├── state.py
│   │   ├── workflow.py
│   │   └── nodes/
│   │       ├── input_guard.py
│   │       ├── classify_extract.py
│   │       ├── resolve_scope.py
│   │       ├── retrieve.py
│   │       ├── evidence_gate.py
│   │       ├── compose_answer.py
│   │       └── validate_citations.py
│   ├── retrieval/
│   │   ├── opensearch_client.py
│   │   ├── hybrid_retriever.py
│   │   ├── filters.py
│   │   └── fusion.py
│   ├── providers/
│   │   ├── watsonx_chat.py
│   │   ├── watsonx_embeddings.py
│   │   └── watsonx_rerank.py
│   ├── ingestion/
│   │   ├── run.py
│   │   ├── cos_source.py
│   │   ├── pdf_parser.py
│   │   ├── chunker.py
│   │   ├── metadata.py
│   │   └── indexer.py
│   ├── prompts/
│   │   ├── classify_extract.md
│   │   └── grounded_answer.md
│   ├── policy/
│   │   ├── domain_policy.py
│   │   └── evidence_policy.py
│   └── observability/
│       └── logging.py
├── deployment/
│   └── openshift/
│       ├── namespace.yaml
│       ├── api-deployment.yaml
│       ├── api-service.yaml
│       ├── api-route.yaml
│       ├── api-configmap.yaml
│       ├── api-secret.example.yaml
│       ├── opensearch-statefulset.yaml
│       ├── opensearch-service.yaml
│       ├── opensearch-pvc.yaml
│       └── ingestion-job.yaml
├── openapi/
│   └── it_helpdesk_v1.yaml
├── docs/
│   ├── MIGRATION_AUDIT.md
│   ├── LEGACY_ARCHITECTURE.md
│   └── operations/
│       └── ORCHESTRATE_SETUP.md
├── scripts/
│   ├── create_index.py
│   ├── validate_env.py
│   └── smoke_test.py
└── tests/
    ├── unit/
    ├── integration/
    ├── fixtures/
    └── evaluation/
        ├── gold_questions.yaml
        └── run_evaluation.py

---

## API Contract (LOCKED — do not change without PR review from both developers)

### POST /v1/assist — Request
{
  "question": "My SNO bootstrap is timing out during OCP 4.16 installation. What should I check?",
  "conversation_id": "optional-orchestrate-conversation-id",
  "conversation_context": [
    {"role": "user", "content": "optional previous user message"},
    {"role": "assistant", "content": "optional previous assistant message"}
  ],
  "requested_scope": {
    "ocp_version": "4.16",
    "deployment_type": "SNO"
  }
}
Rules: question required (3–2000 chars); conversation_context optional (max 4 messages, 4000 total chars); requested_scope optional.

### POST /v1/assist — Response
{
  "request_id": "uuid",
  "status": "ANSWERED",
  "intent": "troubleshoot",
  "answer_markdown": "### Recommended checks\n1. ... [S1]",
  "clarification_question": null,
  "citations": [
    {
      "citation_id": "S1",
      "title": "SNO Installation Guide",
      "product": "OpenShift",
      "ocp_version": "4.16",
      "page_start": 12,
      "page_end": 13,
      "section_path": "Installation > Bootstrap > DNS validation",
      "document_id": "doc-8f9c"
    }
  ],
  "safety_note": "Guidance is based only on the approved knowledge base; verify commands in your environment.",
  "trace_id": "uuid"
}
Allowed status values: ANSWERED, NEEDS_CLARIFICATION, INSUFFICIENT_EVIDENCE, OUT_OF_SCOPE, INVALID_REQUEST

### Supporting endpoints
GET /healthz   — liveness; no dependencies
GET /readyz    — verifies OpenSearch + watsonx config
GET /openapi.json — for Orchestrate import

---

## Agent Workflow State Machine (ARCHITECTURE_IMPLEMENTATION_V3.md section 5)

START
  ↓
input_guard             → INVALID_REQUEST if bad payload
  ↓
classify_and_extract    → determines intent + version/SNO hints
  ↓
resolve_scope           → OUT_OF_SCOPE if not OCP/SNO
                        → NEEDS_CLARIFICATION if critical context missing
  ↓
retrieve_hybrid         → BM25 + vector + metadata filters + RRF
  ↓
evidence_gate           → INSUFFICIENT_EVIDENCE if no/weak/conflicting evidence
  ↓
compose_cited_answer    → generates answer from labelled evidence [S1], [S2]...
  ↓
validate_citations      → INSUFFICIENT_EVIDENCE if [S#] labels don't map to evidence
  ↓
ANSWERED

Graph state TypedDict (app/graph/state.py — LOCKED):
class SupportState(TypedDict, total=False):
    request_id: str
    user_question: str
    conversation_context: list[dict]
    intent: Literal["qa", "troubleshoot", "summarize", "unsupported"]
    extracted_scope: dict
    required_clarification: str | None
    retrieval_query: str
    retrieval_filters: dict
    candidates: list[dict]
    evidence_decision: Literal["sufficient", "insufficient", "conflicting", "out_of_scope", "clarify"]
    answer_markdown: str
    citations: list[dict]
    status: Literal["ANSWERED", "NEEDS_CLARIFICATION", "INSUFFICIENT_EVIDENCE", "OUT_OF_SCOPE", "INVALID_REQUEST"]
    trace: dict

---

## OpenSearch Data Model (ARCHITECTURE_IMPLEMENTATION_V3.md section 6)

Index: knowledge_chunks_v1
{
  "chunk_id": "ocp_sno_support:doc-8f9c:rev-2026-07-02:chunk-0012",
  "document_id": "doc-8f9c",
  "revision_id": "rev-2026-07-02-content-sha256-prefix",
  "domain_id": "ocp_sno_support",
  "title": "...",
  "product": "OpenShift",
  "ocp_version": "4.16",
  "ocp_major": 4,
  "ocp_minor": 16,
  "deployment_type": ["SNO"],
  "components": ["bootstrap", "dns"],
  "section_path": "Installation > Bootstrap > DNS validation",
  "page_start": 12,
  "page_end": 13,
  "chunk_text": "...",
  "chunk_text_vector": [...],
  "content_hash": "sha256:...",
  "is_current": true
}

Hybrid retrieval algorithm (RRF k=60 from config):
1. Parse explicit + inferred filters
2. Run BM25 (top 20) with filters
3. Generate query embedding
4. Run vector kNN (top 20) with same filters
5. Merge by chunk_id
6. Apply Reciprocal Rank Fusion: RRF(d) = Σ 1 / (k + rank_i(d))
7. Keep top 12 candidates
8. Optional rerank behind ENABLE_RERANKER=true flag
9. Select top 4–6 chunks preserving source diversity

---

## Developer A Ownership

Developer A owns:
- FastAPI service and OpenAPI contract (app/api/, app/main.py)
- LangGraph workflow and all 7 nodes (app/graph/)
- OpenSearch client, hybrid retrieval, RRF (app/retrieval/)
- watsonx.ai chat, embedding, rerank providers (app/providers/)
- API authentication and structured logging (app/api/dependencies.py, app/observability/)
- OpenShift deployment manifests (deployment/openshift/)
- Orchestrate endpoint reachability and integration (openapi/, docs/operations/)

Developer A does NOT own:
- PDF ingestion pipeline (Developer B owns app/ingestion/)
- Metadata taxonomy (Developer B owns config/taxonomy/)
- Corpus manifest (Developer B owns config/corpus/)
- OpenSearch index creation script (shared)
- Evaluation dataset (Developer B owns tests/evaluation/)

---

## Non-Negotiable Rules for Every Response

1. Never hard-code watsonx model IDs. They come from env vars WATSONX_EMBEDDING_MODEL_ID and WATSONX_CHAT_MODEL_ID.
2. Never introduce Watson Discovery, AstraDB, Redis, LangSmith, or web search.
3. Never fabricate citations. The citation validator must reject any [S#] label not present in retrieved evidence.
4. Never generate an answer when evidence_gate returns insufficient/conflicting.
5. Use secrets.compare_digest for API key comparison — never a plain == check.
6. Do not log full user questions, full retrieved chunks, or raw answer bodies in normal mode.
7. Do not create god files. Every module stays under ~200 lines.
8. Every external client (OpenSearch, watsonx.ai) is injected — never instantiated deep inside graph nodes.
9. Keep ENABLE_RERANKER=false by default. Enable only after baseline works.
10. Do not change app/api/schemas.py or app/graph/state.py without a PR reviewed by Developer B.

---

## Environment Variables (.env — never committed)

IBM_CLOUD_API_KEY=          # IAM token exchange
OPENSEARCH_URL=             # OpenSearch cluster endpoint
OPENSEARCH_USERNAME=
OPENSEARCH_PASSWORD=
OPENSEARCH_INDEX_CHUNKS=knowledge_chunks_v1
OPENSEARCH_INDEX_DOCS=knowledge_documents_v1
WATSONX_URL=https://us-south.ml.cloud.ibm.com
WATSONX_PROJECT_ID=
WATSONX_EMBEDDING_MODEL_ID= # verify in your account before hardcoding ANYTHING
WATSONX_CHAT_MODEL_ID=      # verify in your account before hardcoding ANYTHING
WATSONX_RERANK_MODEL_ID=    # only needed if ENABLE_RERANKER=true
COS_ENDPOINT=
COS_BUCKET=
COS_API_KEY=
API_KEY_SECRET=             # random string; sent by Orchestrate in X-API-Key header
ENABLE_RERANKER=false
RRF_K=60
LOG_LEVEL=INFO

---

## For the task I give you, always:

1. State exactly which files you will create or change before writing any code.
2. Implement only the requested slice — do not add unrequested features.
3. Add or update tests for every new pure function.
4. Explain how to run the tests locally (command to run).
5. Update PROJECT_CONTEXT.md and TASKS.md only when the work is fully complete.
6. If a locked contract file (schemas.py, state.py, taxonomy yaml) needs to change, flag it explicitly before touching it.
```
