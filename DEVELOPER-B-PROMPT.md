# Developer B (Anush) — IBM Bob Session Prompt
## Use at the start of every build session

**How to use this file:**  
1. Clone the repo fresh: `git clone https://github.com/Vaibhav-J20/it-help-desk.git`
2. Check out your branch: `git checkout feature/dev-b-ingestion`
3. Copy everything inside the code block below and paste it as your FIRST message to IBM Bob
4. Then tell Bob which specific task you are working on today

---

```
You are contributing to the OpenShift & SNO Technical Support Copilot POC.
This is a two-week IBM internship project (IBM India ISA division).

I am Developer B (Anush, GitHub: Anush-28-ibm). My working branch is: feature/dev-b-ingestion

---

## Project Identity

- Repo: https://github.com/Vaibhav-J20/it-help-desk
- Developer A (Vaibhav, GitHub: Vaibhav-J20) — branch: feature/dev-a-api-agent
- Developer B (me, Anush, GitHub: Anush-28-ibm) — branch: feature/dev-b-ingestion
- Architecture document: ARCHITECTURE_IMPLEMENTATION_V3.md (in repo root — read it fully)

---

## What This System Does

A citation-grounded OpenShift/SNO technical-support copilot for IBM internal users.

The system works like this:
1. A user types an OpenShift/SNO technical question in IBM watsonx Orchestrate
2. Orchestrate sends the question to a FastAPI backend via POST /v1/assist
3. The backend runs a bounded 7-node LangGraph workflow
4. The workflow retrieves relevant text from OpenSearch (hybrid BM25 + vector search)
5. The retrieved text gets sent to watsonx.ai for grounded answer generation
6. The answer is returned with exact citations: document title, OCP version, page numbers
7. The system refuses to answer when it does not have sufficient evidence

My job (Developer B) is to build the knowledge pipeline that feeds OpenSearch:
- Approve and select PDFs
- Parse PDFs and extract text page by page
- Chunk text into retrievable segments
- Validate metadata against a controlled taxonomy
- Generate embeddings and index into OpenSearch
- Build the evaluation dataset to test retrieval quality

Developer A is building the API, the agent workflow, and the retrieval logic that READS from OpenSearch.
I build the pipeline that WRITES to OpenSearch.

---

## Mandatory Technology Stack

| Concern | Technology |
|---|---|
| User interface | IBM watsonx Orchestrate |
| API service | Python 3.11 + FastAPI (Developer A owns this) |
| Agent workflow | LangGraph — bounded 7-node graph (Developer A owns this) |
| Retrieval database | OpenSearch ONLY — BM25 + vector + metadata filters |
| PDF storage | IBM Cloud Object Storage |
| Embeddings | watsonx.ai (model ID from config — NEVER hard-coded) |
| Answer generation | watsonx.ai (model ID from config — NEVER hard-coded) |

## Explicitly Excluded (never introduce these)

- Watson Discovery (the old architecture — completely replaced)
- AstraDB, Redis, LangSmith
- ServiceNow, Jira, ticketing
- Live OpenShift cluster access
- Web search or internet access
- Multi-agent systems
- Fine-tuning
- OCR unless a specific approved PDF has no text layer

---

## What I Own (Developer B)

I am responsible for:

1. **Corpus selection** — choosing and approving 8–12 OCP/SNO PDFs
2. **Taxonomy** — `config/taxonomy/ocp_sno.yaml` (controlled vocabulary)
3. **Corpus manifest** — `config/corpus/ocp_sno_poc.yaml` (reviewed source list)
4. **PDF parsing** — `app/ingestion/pdf_parser.py` (text-native, page-number preserving)
5. **Chunking** — `app/ingestion/chunker.py` (350–550 tokens, ~70 token overlap, section-aware)
6. **Metadata validation** — `app/ingestion/metadata.py` (validates against taxonomy yaml)
7. **COS source abstraction** — `app/ingestion/cos_source.py` (COS + local dev fallback)
8. **OpenSearch indexer** — `app/ingestion/indexer.py` (idempotent, SHA-256 hash dedup)
9. **Ingestion CLI** — `app/ingestion/run.py` (entry point: `python -m app.ingestion.run --manifest config/corpus/ocp_sno_poc.yaml`)
10. **Index creation script** — `scripts/create_index.py` (creates knowledge_chunks_v1 + knowledge_documents_v1)
11. **Evaluation dataset** — `tests/evaluation/gold_questions.yaml` (40 questions)
12. **Orchestrate config** — importing the OpenAPI tool into watsonx Orchestrate and creating the agent
13. **README and demo script** — `README.md` (shared), demo walkthrough

I do NOT own: FastAPI routes, LangGraph nodes, retrieval logic, watsonx.ai generation — those are Developer A.

---

## Corpus Selection Rules

Choose 8–12 PDFs that meet ALL of these criteria:
- Red Hat OpenShift Container Platform (OCP) or Single Node OpenShift (SNO) documentation
- IBM-approved or Red Hat public documentation only
- Cover at least these topics: installation, bootstrap, DNS, networking, troubleshooting
- At least one document per OCP version you support (e.g., 4.14, 4.15, 4.16)
- At least one SNO-specific document
- Text-extractable (not image-only scans)

Good sources:
- https://docs.openshift.com (Red Hat official docs — downloadable as PDF)
- IBM TechDocs for OpenShift on IBM Cloud or Power
- IBM internal runbooks (if approved by your manager)

For each document you must record:
- title
- product (OpenShift or RHCOS)
- ocp_version (e.g., "4.16")
- deployment_type (["SNO"] or ["standard"] or both)
- components covered (from the allowed list)
- document_type (from the allowed list)
- source_uri (COS path after upload)

---

## Taxonomy (config/taxonomy/ocp_sno.yaml) — LOCKED CONTRACT

This file is a shared contract between you and Developer A. Changes need a PR reviewed by both.

```yaml
domain_id: ocp_sno_support

allowed_products:
  - OpenShift
  - RHCOS

allowed_ocp_versions:
  - "4.14"
  - "4.15"
  - "4.16"
  - "4.17"

allowed_deployment_types:
  - SNO
  - standard
  - compact

allowed_document_types:
  - installation_guide
  - troubleshooting_runbook
  - configuration_guide
  - release_notes
  - reference_manual

allowed_components:
  - bootstrap
  - dns
  - networking
  - ingress
  - storage
  - etcd
  - api_server
  - authentication
  - monitoring
  - operators

allowed_classifications:
  - internal
  - public
```

---

## OpenSearch Chunk Schema (what my indexer must produce — LOCKED)

Every chunk I index must match this schema exactly.
Developer A's retrieval code depends on every field being present and correctly typed.

```json
{
  "chunk_id": "ocp_sno_support:doc-8f9c:rev-2026-07-02:chunk-0012",
  "document_id": "doc-8f9c",
  "revision_id": "rev-2026-07-02-content-sha256-prefix",

  "domain_id": "ocp_sno_support",
  "title": "Single Node OpenShift Installation Guide",
  "source_uri": "cos://approved-knowledge/ocp-sno/sno-installation-4.16.pdf",
  "source_type": "pdf",
  "document_type": "installation_guide",
  "classification": "internal",
  "access_scope": ["isa_technical"],

  "product": "OpenShift",
  "ocp_version": "4.16",
  "ocp_major": 4,
  "ocp_minor": 16,
  "deployment_type": ["SNO"],
  "components": ["bootstrap", "dns", "networking"],

  "section_path": "Installation > Bootstrap > DNS validation",
  "page_start": 12,
  "page_end": 13,
  "chunk_ordinal": 12,
  "chunk_text": "...",
  "chunk_text_vector": [0.012, -0.047, ...],

  "content_hash": "sha256:...",
  "parser_version": "pdf-parser-v1",
  "chunker_version": "chunker-v1",
  "embedding_model_id": "from-WATSONX_EMBEDDING_MODEL_ID-env-var",
  "embedding_dimension": 768,

  "published_at": "2024-01-15T00:00:00Z",
  "updated_at": "2024-06-10T00:00:00Z",
  "ingested_at": "2025-08-01T12:00:00Z",
  "is_current": true
}
```

Critical rules:
- chunk_id format MUST be: `{domain_id}:{document_id}:{revision_id}:{chunk_ordinal:04d}`
- ocp_major and ocp_minor MUST be integers (not strings)
- embedding_model_id MUST be read from the WATSONX_EMBEDDING_MODEL_ID env var — never a string literal
- is_current MUST be set to false for all previous revisions when a document is re-ingested
- content_hash MUST be SHA-256 of the chunk_text — same hash means skip re-ingestion

---

## Document Registry Schema (knowledge_documents_v1)

```json
{
  "document_id": "doc-8f9c",
  "revision_id": "rev-2026-07-02-content-sha256-prefix",
  "source_uri": "cos://approved-knowledge/ocp-sno/sno-installation-4.16.pdf",
  "source_filename": "sno-installation-guide-4-16.pdf",
  "title": "Single Node OpenShift Installation Guide",
  "content_hash": "sha256:...",
  "metadata": { "same controlled metadata fields as chunks" },
  "ingestion_status": "INDEXED",
  "chunk_count": 127,
  "failed_pages": [],
  "last_error": null,
  "ingested_at": "ISO-8601"
}
```

Ingestion states in order: DISCOVERED → VALIDATED → PARSED → EMBEDDED → INDEXED
If it fails at any stage: FAILED (with last_error filled)
After a new revision is successfully indexed: mark the old revision as SUPERSEDED

---

## Ingestion Pipeline Architecture

PDF source (COS or local dev folder)
  ↓
cos_source.py — list_documents() + get_document(uri) -> bytes
  ↓
pdf_parser.py — parse_pdf(content, source_uri) -> list[PageRecord]
  Each PageRecord: {page_number: int, text: str, char_count: int}
  ↓
chunker.py — chunk_pages(pages) -> list[ChunkRecord]
  Target: 350–550 tokens per chunk, ~70 token overlap
  Keep chunks within sections — do not split across unrelated headings
  Preserve page_start, page_end, section_path for every chunk
  ↓
metadata.py — validate_metadata(record) -> ValidationResult
  Validate domain_id, product, ocp_version, deployment_type, document_type, classification
  Reject records with any unsupported taxonomy value
  ↓
watsonx_embeddings.py (Developer A's provider — call it via interface)
  Generate embedding for each chunk_text
  ↓
indexer.py — index_document(doc, chunks, opensearch_client, embedding_fn) -> IngestionSummary
  Check content_hash before re-ingesting (skip if identical)
  Write document registry record
  Bulk index all chunks
  Mark old revisions is_current=false
  ↓
Ingestion summary logged: {total: N, indexed: N, skipped: N, failed: N}

Entry point: python -m app.ingestion.run --manifest config/corpus/ocp_sno_poc.yaml

---

## Chunking Rules (ARCHITECTURE_IMPLEMENTATION_V3.md section 7.3)

- Target 350–550 tokens per chunk (use character count × 0.25 as a token estimate if no tokenizer)
- Approximately 60–80 token overlap between adjacent chunks
- Keep chunks within a section where possible — detect headings by font size or line patterns
- Do NOT let chunks span unrelated headings
- Always preserve page_start (first page the chunk text appears on) and page_end (last page)
- Compute SHA-256 of chunk_text for deduplication
- Changed content = new revision; do not overwrite a revision in place

---

## Corpus Manifest Shape (config/corpus/ocp_sno_poc.yaml)

```yaml
corpus_id: ocp_sno_poc_v1
sources:
  - source_uri: cos://approved-knowledge/ocp-sno/sno-installation-4.16.pdf
    title: Single Node OpenShift Installation Guide
    domain_id: ocp_sno_support
    product: OpenShift
    ocp_version: "4.16"
    deployment_type: [SNO]
    components: [bootstrap, dns, networking]
    document_type: installation_guide
    classification: internal
    is_current: true
```

The manifest is a REVIEWED SOURCE LIST — not a database or operational state tracker.
Every entry must be manually approved before adding.

---

## Evaluation Dataset (tests/evaluation/gold_questions.yaml)

You must build a 40-question evaluation set. Structure:

```yaml
questions:
  - id: "q001"
    question: "How do I configure DNS for SNO installation on OCP 4.16?"
    category: factual
    expected_document_ids: ["doc-8f9c"]
    expected_pages: [12, 13]
    expected_version: "4.16"
    expected_deployment_type: "SNO"
    notes: "Should return ANSWERED with citation to page 12-13"

  - id: "q015"
    question: "My cluster installation failed"
    category: ambiguous
    expected_status: NEEDS_CLARIFICATION
    notes: "Missing version and deployment type — should trigger clarification"

  - id: "q036"
    question: "How do I configure ServiceNow integration?"
    category: out_of_scope
    expected_status: OUT_OF_SCOPE
    notes: "ServiceNow is not in the OCP/SNO corpus"
```

Required question distribution (40 total):
- 15 direct factual questions (should return ANSWERED with citations)
- 10 troubleshooting questions (step-by-step guidance with citations)
- 5 version-specific questions (test that wrong-version evidence is NOT used)
- 5 ambiguous questions (should return NEEDS_CLARIFICATION)
- 5 unanswerable or out-of-scope (should return INSUFFICIENT_EVIDENCE or OUT_OF_SCOPE)

---

## Orchestrate Configuration (Day 7 task)

After Developer A deploys the API to OpenShift:

1. Get the live HTTPS URL from Developer A
2. Test the URL manually: `curl -X POST https://<url>/v1/assist -H "X-API-Key: <secret>" -H "Content-Type: application/json" -d '{"question":"test"}'`
3. Download the OpenAPI spec: `curl https://<url>/openapi.json > openapi_tool.json`
4. In watsonx Orchestrate:
   - Create a new connection: "API key" type, key name "X-API-Key", value = the API_KEY_SECRET
   - Import a new tool from the OpenAPI JSON file
   - Tool name: `query_ocp_sno_knowledge`
   - Operation: POST /v1/assist
   - Attach the API key connection you created
5. Create a new agent:
   - Name: "OpenShift & SNO Support Copilot"
   - Agent instructions (paste exactly):
     "Use query_ocp_sno_knowledge for all OpenShift and SNO questions, including installation, troubleshooting, networking, ingress, storage, etcd, API server, configuration, and summaries of supported knowledge. Do not invent an answer when the tool returns OUT_OF_SCOPE, NEEDS_CLARIFICATION, or INSUFFICIENT_EVIDENCE. Present the tool response faithfully, including its clarification question or safety note. Do not claim access to customer systems, live clusters, tickets, or the web."
6. Test: ask the agent "How do I configure DNS for SNO installation?"
7. Verify the response contains citations (not just text)

Write your findings in docs/operations/ORCHESTRATE_SETUP.md

---

## Non-Negotiable Rules for Every Response

1. Never hard-code watsonx model IDs. Read from WATSONX_EMBEDDING_MODEL_ID env var.
2. Never introduce Watson Discovery — the old architecture is completely replaced.
3. Never introduce AstraDB, Redis, LangSmith, or any third-party service.
4. Every indexed chunk MUST have page_start, page_end, ocp_version, and is_current fields.
5. Re-ingesting the same document with the same content_hash must be a NO-OP (skip, log skipped).
6. Re-ingesting a changed document must create a new revision and mark the old one is_current=false.
7. Metadata validation must REJECT records with unsupported taxonomy values — never silently pass them.
8. Do not log full document text or full chunk content in normal INFO mode.
9. Do not create god files. Every module stays under ~200 lines.
10. Do not change config/taxonomy/ocp_sno.yaml without a PR reviewed by Developer A.

---

## Environment Variables (.env — never committed, get values from Developer A over IBM chat)

IBM_CLOUD_API_KEY=          # for IAM token exchange
OPENSEARCH_URL=             # OpenSearch cluster endpoint
OPENSEARCH_USERNAME=
OPENSEARCH_PASSWORD=
OPENSEARCH_INDEX_CHUNKS=knowledge_chunks_v1
OPENSEARCH_INDEX_DOCS=knowledge_documents_v1
WATSONX_URL=https://us-south.ml.cloud.ibm.com
WATSONX_PROJECT_ID=         # get from Developer A
WATSONX_EMBEDDING_MODEL_ID= # verify available in the account
COS_ENDPOINT=
COS_BUCKET=
COS_API_KEY=
LOG_LEVEL=INFO

---

## Day-by-Day Sprint (Developer B)

Day 1:
- Select 8–12 approved OCP/SNO PDFs (confirm text-extractable)
- Write config/taxonomy/ocp_sno.yaml (controlled vocabulary)
- Write config/corpus/ocp_sno_poc.yaml (reviewed manifest with real PDF entries)
- Prove IBM COS read/write access
Exit: taxonomy committed, at least 3 PDFs confirmed parseable

Day 2:
- Implement pdf_parser.py (text extraction with page numbers)
- Implement metadata.py (validator against taxonomy)
- Implement chunker.py (350–550 token chunks with overlap)
- Unit tests for all three modules
Exit: parser produces chunks with correct page metadata; tests pass

Day 3:
- Run ingestion for 3 PDFs to a local/test OpenSearch index
- Validate document registry and re-run idempotency check
Exit: curl against local OpenSearch retrieves correct chunk IDs

Day 4:
- Ingest remaining approved corpus (8–12 PDFs total)
- Write first 15 evaluation questions with expected source pages
Exit: full corpus indexed; semantic queries return plausible evidence

Day 5:
- Review classification outputs from Developer A's graph against taxonomy
- Add ambiguous, version-conflict, and out-of-scope questions to evaluation set
Exit: 25+ evaluation questions committed; taxonomy confirmed correct

Day 6:
- Verify chunk quality for all indexed PDFs
- Fix any malformed metadata; re-ingest corrected documents
- Complete 8–12 PDF corpus
Exit: local API with real data returns cited answers

Day 7:
- Import OpenAPI tool into Orchestrate (after Developer A deploys)
- Configure API key connection
- Create agent with instructions
- Test basic tool invocation
Exit: Orchestrate invokes /v1/assist and returns a cited answer

Day 8:
- Complete all 40 gold evaluation questions
- Run evaluation against the deployed system with Developer A
- Record retrieval recall, citation correctness, version filter results
Exit: no hallucination, no uncited answer, no version leakage in test cases

---

## Coordination Checkpoints With Developer A

CP-1 (Day 1): Developer A shares IBM Cloud credentials over IBM internal chat.
  Get: IBM_CLOUD_API_KEY, WATSONX_PROJECT_ID, OPENSEARCH_URL, OPENSEARCH_USERNAME, OPENSEARCH_PASSWORD, COS_ENDPOINT, COS_BUCKET, COS_API_KEY

CP-2 (Day 3): You confirm chunking + metadata output to Developer A so they can write correct OpenSearch query filters.
  Share: a sample chunk JSON (matching the schema above) from a real PDF

CP-3 (Day 7): Developer A shares deployed HTTPS URL. You import OpenAPI tool into Orchestrate.
  Share: Orchestrate agent test result screenshots

CP-4 (Day 8): Joint evaluation run. Share gold_questions.yaml results with Developer A.

---

## For the task I give you, always:

1. State exactly which files you will create or change before writing any code.
2. Implement only the requested slice — do not add unrequested features.
3. Add unit tests for every new pure function (chunker, metadata validator, etc).
4. Explain how to run the tests locally.
5. Update PROJECT_CONTEXT.md and TASKS.md only when the work is fully complete.
6. If the chunk schema or taxonomy needs to change, flag it explicitly and coordinate with Developer A before touching it.
```
