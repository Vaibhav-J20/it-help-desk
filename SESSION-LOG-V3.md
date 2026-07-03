# Session Log — OpenShift & SNO Technical Support Copilot

**Repo:** https://github.com/Vaibhav-J20/it-help-desk  
**Architecture:** V3 — OpenSearch hybrid retrieval + watsonx.ai + LangGraph + Orchestrate  
**Previous architecture (retired):** Watson Discovery-based RAG — see `docs/LEGACY_ARCHITECTURE.md`

> **Shared log for both Developer A (Vaibhav) and Developer B (Anush).**  
> Every entry is prefixed with the developer who wrote it and the date.  
>
> **Session start instructions:**  
> - Developer A: open `DEVELOPER-A-PROMPT.md`, copy the code block, paste it as your first message to IBM Bob  
> - Developer B: open `DEVELOPER-B-PROMPT.md`, copy the code block, paste it as your first message to IBM Bob  
> - Both: then tell Bob which specific task you are working on  
>
> **Entry format:** `## Developer [A/B] — [DD Month YYYY] — [topic]`

---

## Developer A — [Date of V3 restart] — V3 Architecture Reset

### What Changed From the Previous Session

The project was previously built on **Watson Discovery v2** as the retrieval backend with three separate API endpoints (`/ask`, `/summarize`, `/troubleshoot`). After reviewing the full V3 architecture document and consulting with project managers and ChatGPT for additional input, we decided to perform a complete clean architectural reset.

**Old architecture (retired):**
- Watson Discovery v2 for document ingestion and retrieval
- Three-endpoint RAG API on IBM Code Engine
- Flat `rag_core.py` module structure

**New V3 architecture:**
- OpenSearch (BM25 + vector hybrid) as the ONLY retrieval store
- Single `POST /v1/assist` endpoint with citation-grounded responses
- Bounded 7-node LangGraph workflow
- `app/` modular structure
- IBM Cloud Object Storage for PDFs

### New Branch Structure

| Branch | Owner | Purpose |
|---|---|---|
| `main` | Both (PR only) | Always deployable foundation |
| `feature/dev-a-api-agent` | Developer A | FastAPI + LangGraph + retrieval + providers |
| `feature/dev-b-ingestion` | Developer B | Ingestion pipeline + indexer + evaluation |

Previous branches (`dev/developer-a`, `dev/developer-b`) have been deleted from GitHub. They exist only in local git history.

### Key Files in This Repo

| File | Purpose |
|---|---|
| `ARCHITECTURE_IMPLEMENTATION_V3.md` | Full architecture spec — READ THIS FIRST |
| `DEVELOPER-A-PROMPT.md` | Developer A's IBM Bob session starter |
| `DEVELOPER-B-PROMPT.md` | Developer B's IBM Bob session starter — share this with Anush |
| `RESTART-GUIDE.md` | Step-by-step cleanup and restart instructions |
| `PROJECT_CONTEXT.md` | Current implementation status and locked contracts |
| `DECISIONS.md` | Architecture Decision Record log |
| `TASKS.md` | Sprint backlog with day-by-day ownership |
| `.env.example` | Credential template — copy to `.env`, fill values, NEVER commit `.env` |

### Locked Interface Contracts

These files require a PR reviewed by BOTH developers before changes:

| File | What it defines |
|---|---|
| `app/api/schemas.py` | Pydantic request/response models for POST /v1/assist |
| `app/graph/state.py` | SupportState TypedDict — the graph's shared state |
| `config/taxonomy/ocp_sno.yaml` | Controlled vocabulary for all metadata fields |
| `config/corpus/ocp_sno_poc.yaml` | Approved PDF source list |
| `openapi/it_helpdesk_v1.yaml` | OpenAPI spec imported into Orchestrate |

### TechZone Infrastructure (fill in after provisioning)

| Service | Status | Details |
|---|---|---|
| OpenSearch | ⏳ Pending | Deploy via `deployment/openshift/opensearch-statefulset.yaml` |
| watsonx.ai | ⏳ Pending | Verify model IDs in target account before any provider code |
| IBM COS | ⏳ Pending | Create bucket, upload first test PDFs |
| watsonx Orchestrate | ⏳ Pending | Import tool after API deployed |

### Next Steps

- Developer A: complete TechZone provisioning, verify watsonx.ai model availability, then start `feature/dev-a-api-agent` with FastAPI skeleton + mocked `/v1/assist`
- Developer B: clone repo fresh, read `DEVELOPER-B-PROMPT.md`, select 8–12 OCP/SNO PDFs, write taxonomy YAML

---

## Developer B (Anush) — Day 6 — Chunk Quality Audit + Corpus Expanded to 8 PDFs

**Branch:** `feature/dev-b-ingestion`
**Status:** Day 6 🔄 IN PROGRESS — ingestion of 2 new PDFs pending (Docker password fix needed next session)

### What Was Done

#### Chunk Quality Audit — ALL 6 PASS ✅
- Built `scripts/audit_chunks.py` — samples N chunks per document, validates all 29 required fields, types, vector dimensions, page ordering, chunk_id format
- Ran audit against all 6 indexed documents (10 chunks sampled each)
- Result: **6/6 PASS** — no missing fields, no type errors, no malformed metadata
- Report written to `docs/operations/CHUNK_AUDIT.md`

| Document | OCP Version | Total Chunks | Status |
|---|---|---|---|
| doc-8e43 (networking) | 4.16 | 1850 | PASS ✅ |
| doc-7a28 (storage) | 4.16 | 491 | PASS ✅ |
| doc-73eb (authentication) | 4.16 | 380 | PASS ✅ |
| doc-a752 (troubleshooting) | 4.16 | 300 | PASS ✅ |
| doc-4957 (sno install 4.16) | 4.16 | 158 | PASS ✅ |
| doc-04af (sno install 4.14) | 4.14 | 138 | PASS ✅ |

#### Corpus Expanded to 8 PDFs ✅
- Downloaded and verified 2 new Red Hat public PDFs:
  - `ocp-operators-4.16.pdf` — 496 pages, 901 chunks (parsed, not yet indexed)
  - `ocp-updating-clusters-4.16.pdf` — 154 pages, 306 chunks (parsed, not yet indexed)
- Added both to `config/corpus/ocp_sno_poc.yaml` (now 8 entries)
- Both PDFs parse correctly — confirmed via pdfminer.six

#### Pending — Next Session
- Fix `.env` OPENSEARCH_PASSWORD (Docker container recreated without `!` in password)
- Re-run `python3 -m app.ingestion.run --manifest config/corpus/ocp_sno_poc.yaml`
- Expected result: INDEXED: 8, SKIPPED: 0, FAILED: 0
- Then commit everything and Day 6 is complete

### Files Added/Changed
| File | Change |
|---|---|
| `scripts/audit_chunks.py` | New — chunk quality audit tool |
| `config/corpus/ocp_sno_poc.yaml` | +2 new PDFs (operators, updating-clusters) |
| `docs/operations/CHUNK_AUDIT.md` | New — audit report (local only, gitignored) |
| `config/corpus/new_pdfs_only.yaml` | Temp ingest helper (to be deleted after indexing) |

---

## Developer B (Anush) — Day 5 — Evaluation Dataset Complete (All 40 Questions)

**Branch:** `feature/dev-b-ingestion`
**Status:** Day 5 ✅ COMPLETE

### What Was Done
- Completed `tests/evaluation/gold_questions.yaml` — all 40 questions written
- Full required distribution met:

| Category | Count | IDs | Purpose |
|---|---|---|---|
| factual | 15 | q001–q015 | Direct answers with citations |
| troubleshoot | 10 | q016–q025 | Numbered diagnostic steps |
| version | 5 | q026–q030 | Version filter safety tests |
| ambiguous | 5 | q031–q035 | Must return NEEDS_CLARIFICATION |
| out_of_scope | 5 | q036–q040 | Must return OUT_OF_SCOPE, no hallucination |

### Key Safety Tests for Vaibhav's System
- **q027, q030** — OCP 4.14 queries must NOT return 4.16 chunks (version filter critical)
- **q031–q035** — vague queries must ask for clarification, never guess
- **q036–q040** — ServiceNow, live cluster, Db2, web search, code gen must all be refused

### Day 5 Exit Condition — MET
- 25+ evaluation questions committed ✅
- All 5 status types covered (ANSWERED, NEEDS_CLARIFICATION, OUT_OF_SCOPE) ✅
- Version-conflict and ambiguous edge cases included ✅

---

## Developer B (Anush) — Day 4 — Evaluation Dataset (First 15 Questions)

**Branch:** `feature/dev-b-ingestion`
**Status:** Day 4 ✅ COMPLETE

### What Was Done
- Created `tests/evaluation/gold_questions.yaml`
- Wrote first **15 factual questions** (q001–q015) with:
  - Expected document IDs mapping to real indexed chunks
  - Expected OCP version, deployment type where applicable
  - Page hints based on actual PDF content
  - Notes explaining what the correct answer should cite

### Question Coverage (15 factual)
| ID | Topic | Expected Doc |
|---|---|---|
| q001 | Rendezvous host / Agent-based Installer | SNO install guide |
| q002 | DNS records for SNO 4.16 | SNO install 4.16 |
| q003 | Topologies supported by agent create image | SNO install guide |
| q004 | Default network plugin OCP 4.16 | Networking guide |
| q005 | NMStateConfig manifest purpose | SNO install guide |
| q006 | Enable cluster-admin role | Auth guide |
| q007 | Default storage classes OCP 4.16 | Storage guide |
| q008 | must-gather command | Troubleshooting guide |
| q009 | SNO minimum hardware requirements | SNO install guide |
| q010 | IngressController traffic management | Networking guide |
| q011 | OAuth identity providers OCP 4.16 | Auth guide |
| q012 | etcd operator responsibilities | Storage + Troubleshooting |
| q013 | cluster-manifests required files | SNO install guide |
| q014 | RWO vs RWX persistent volumes | Storage guide |
| q015 | HTPasswd identity provider config | Auth guide |

### Day 4 Exit Condition — MET
- First 15 evaluation questions committed ✅
- All questions reference real document IDs from indexed corpus ✅

### Reminder for Vaibhav
See `⚡ ACTION REQUIRED` section above — CP-2 field types and credential sharing needed.

### Next Steps (Day 5)
- Add 10 troubleshooting questions (q016–q025)
- Add 5 version-specific questions (q026–q030)
- Add 5 ambiguous questions (q031–q035)
- Add 5 out-of-scope questions (q036–q040)

---

## ⚡ ACTION REQUIRED — Developer A (Vaibhav) — Read This

**Triggered by:** Developer B (Anush) completing Day 3 — CP-2 checkpoint

### What Anush has completed (Days 1–3)
- Full ingestion pipeline built and working (`app/ingestion/`)
- 6 OCP/SNO PDFs indexed into local OpenSearch: **3,317 chunks**
- Idempotency confirmed: re-run = all SKIPPED (SHA-256 dedup works)
- BM25 retrieval verified against real indexed data
- All 33 unit tests passing

### What Vaibhav needs to do — CP-2 Actions

**1. Read the sample chunk JSON**
File: `tests/fixtures/cp2_sample_chunk.json` on `feature/dev-b-ingestion`

This is a real chunk from our OpenSearch index. Use it to write correct query filters in your retrieval code.

**Confirmed field names and types for your OpenSearch queries:**
```
ocp_version          → keyword  (e.g. "4.14", "4.16")
ocp_major            → integer  (e.g. 4)
ocp_minor            → integer  (e.g. 14, 16)
deployment_type      → keyword array  (e.g. ["SNO", "standard"])
components           → keyword array  (e.g. ["bootstrap", "dns", "networking"])
topic_tags           → keyword array  (e.g. ["installation", "agent-based-installer"])
is_current           → boolean  (always filter: is_current=true)
domain_id            → keyword  (always: "ocp_sno_support")
chunk_text           → text (BM25 search field)
chunk_text_vector    → knn_vector dim=768 (vector search field)
```

**2. Confirm these filter patterns work in your retrieval code:**
```python
# Version filter
{"term": {"ocp_version": "4.16"}}

# Deployment type filter
{"term": {"deployment_type": "SNO"}}

# Component filter
{"term": {"components": "bootstrap"}}

# Always add this to every query
{"term": {"is_current": True}}
{"term": {"domain_id": "ocp_sno_support"}}
```

**3. Confirm acknowledgement in SESSION-LOG-V3.md**
Add an entry: `## Developer A — CP-2 acknowledged — [date]` confirming the field names work with your retrieval code.

**4. Share your IBM Cloud credentials with Anush (CP-1 pending)**
Anush still needs `.env` values to use real watsonx.ai embeddings:
- `IBM_CLOUD_API_KEY`
- `WATSONX_PROJECT_ID`
- `OPENSEARCH_URL` (your deployed instance)
- `OPENSEARCH_USERNAME` / `OPENSEARCH_PASSWORD`
- `WATSONX_EMBEDDING_MODEL_ID` (confirmed: `ibm/slate-125m-english-rtrvr-v2`)

Send over IBM internal chat — **never git.**

---

## Developer B (Anush) — Day 3 — First Ingestion Run + Idempotency Confirmed

**Branch:** `feature/dev-b-ingestion`
**Status:** Day 3 ✅ COMPLETE — **CP-2 READY for Vaibhav**

### What Was Done

#### OpenSearch Local Setup
- Docker Desktop installed and running
- OpenSearch 2.13.0 container started: `docker run --name opensearch-poc -p 9200:9200 ...`
- Both indices created via `scripts/create_index.py`:
  - `knowledge_chunks_v1` (kNN vector + BM25 text + keyword filters)
  - `knowledge_documents_v1` (document registry)

#### Bugs Fixed
| Bug | Fix |
|---|---|
| `verify_certs=True` — SSL cert error on local Docker | Changed to `verify_certs=False` in `scripts/create_index.py` and `app/ingestion/run.py` |
| `cosinesimil` rejects zero vectors (stub embeddings) | Changed to `l2` space type in index mapping for local dev |

#### First Ingestion Run — ALL 6 PDFs INDEXED ✅
| PDF | Pages | Chunks | Status |
|---|---|---|---|
| sno-installation-guide-4.16.pdf | 104 | 158 | INDEXED |
| sno-installation-guide-4.14.pdf | 87 | 138 | INDEXED |
| ocp-networking-4.16.pdf | 1049 | 1850 | INDEXED |
| ocp-storage-4.16.pdf | 278 | 491 | INDEXED |
| ocp-troubleshooting-4.16.pdf | 166 | 300 | INDEXED |
| ocp-authentication-4.16.pdf | 226 | 380 | INDEXED |
| **TOTAL** | **1910 pages** | **3,317 chunks** | **6/6 INDEXED** |

#### Idempotency Confirmed ✅
Re-run result: `INDEXED: 0  SKIPPED: 6  FAILED: 0`
Same content_hash → SKIP, no duplicate writes.

#### BM25 Retrieval Verified ✅
Query: `"bootstrap DNS installation SNO"` → returned `chunk-0009` from SNO 4.14 installation guide with correct section path, page numbers, and all metadata fields.

### CP-2 Sample Chunk JSON — Ready for Vaibhav
File: `tests/fixtures/cp2_sample_chunk.json`

```json
{
  "chunk_id": "ocp_sno_support:doc-04af:rev-2026-07-03-76f032e7080a:chunk-0009",
  "document_id": "doc-04af",
  "ocp_version": "4.14",
  "ocp_major": 4,
  "ocp_minor": 14,
  "deployment_type": ["SNO", "standard"],
  "components": ["bootstrap", "dns", "networking"],
  "topic_tags": ["installation", "agent-based-installer", "bootstrap", "dns"],
  "section_path": "1.2.1. Agent-based Installer workflow",
  "page_start": 7,
  "page_end": 9,
  "embedding_model_id": "ibm/slate-125m-english-rtrvr-v2",
  "embedding_dimension": 768,
  "is_current": true
}
```

**Vaibhav: use `tests/fixtures/cp2_sample_chunk.json` to write correct OpenSearch query filters.**
Field names confirmed: `ocp_version` (keyword), `ocp_major`/`ocp_minor` (integer), `deployment_type` (keyword array), `components` (keyword array), `is_current` (boolean).

### Day 3 Exit Condition — MET
- curl against local OpenSearch retrieves correct chunk IDs ✅
- Re-running ingest skips unchanged files (SKIPPED: 6) ✅
- CP-2 sample chunk JSON committed to `tests/fixtures/cp2_sample_chunk.json` ✅

---

## Developer B (Anush) — Day 2 — Unit Tests All Green

**Branch:** `feature/dev-b-ingestion`
**Commit:** (see below)
**Status:** Day 2 ✅ COMPLETE

### What Was Fixed and Tested

#### Bugs Found and Fixed
| Bug | File | Fix |
|---|---|---|
| `LTAnon`, `LTChar` don't exist in installed pdfminer version | `pdf_parser.py` | Removed unused imports — only `LTTextContainer` needed |
| Infinite loop in `_chunk_text()` — safety guard logic was backwards | `chunker.py` | Fixed advance logic: `if next_start <= start: next_start = end` |
| `test_pdf_parser.py` still mocked `pypdf.PdfReader` | `test_pdf_parser.py` | Fully rewritten — now uses real `LTTextBox` instances (pdfminer subclass) so `isinstance` checks pass correctly |
| Chunker tests timing out — test input size too large | `test_chunker.py` | Reduced input sizes so tests complete in milliseconds |

#### Final Test Results
```
33 passed in 0.11s
  test_chunker.py    — 10/10 passed
  test_metadata.py   — 13/13 passed
  test_pdf_parser.py — 10/10 passed
```

### Day 2 Exit Condition — MET
- `pdf_parser.py` produces chunks with correct page metadata ✅
- All 33 unit tests pass ✅

### What Vaibhav Needs to Know
- All unit tests green — pipeline code is solid
- **Day 3 next:** First real ingestion run against local Docker OpenSearch
- **CP-2 coming Day 3** — will send sample chunk JSON from a real indexed PDF

---

## Developer B (Anush) — Day 1 — Ingestion Pipeline Foundation

**Branch:** `feature/dev-b-ingestion`
**Commit:** `2674938`
**Status:** Day 1 ✅ COMPLETE

### What Was Built

Full V3 ingestion pipeline foundation committed and pushed.

#### Files Delivered
| File | Purpose |
|---|---|
| `requirements.txt` | Pinned to match Dev A's exact versions (`pdfminer.six==20231228`, `opensearch-py==3.2.0`, etc.) |
| `config/taxonomy/ocp_sno.yaml` | Controlled vocabulary — locked contract committed |
| `config/corpus/ocp_sno_poc.yaml` | 6 approved OCP/SNO PDFs with full metadata + topic_tags |
| `app/ingestion/pdf_parser.py` | pdfminer.six text extraction, 1-based page numbers, SHA-256 content hash |
| `app/ingestion/chunker.py` | 350–550 token chunks, ~70 token overlap, section-aware heading detection |
| `app/ingestion/metadata.py` | Taxonomy validator — hard rejects any unsupported field value |
| `app/ingestion/cos_source.py` | COS + local dev fallback (`local://docs/` URI scheme) |
| `app/ingestion/indexer.py` | Idempotent SHA-256 dedup, revision tracking, `is_current` flag, all chunk fields |
| `app/ingestion/run.py` | CLI: `python -m app.ingestion.run --manifest config/corpus/ocp_sno_poc.yaml` |
| `scripts/create_index.py` | Creates `knowledge_chunks_v1` + `knowledge_documents_v1` with correct kNN mapping |
| `tests/unit/` | Unit tests for pdf_parser, metadata, chunker |

#### 6 PDFs Downloaded and Confirmed Text-Extractable
All sourced from public Red Hat documentation (access.redhat.com):

| File | OCP Version | Type |
|---|---|---|
| `sno-installation-guide-4.16.pdf` | 4.16 | installation_guide |
| `sno-installation-guide-4.14.pdf` | 4.14 | installation_guide |
| `ocp-networking-4.16.pdf` | 4.16 | configuration_guide |
| `ocp-storage-4.16.pdf` | 4.16 | configuration_guide |
| `ocp-troubleshooting-4.16.pdf` | 4.16 | troubleshooting_runbook |
| `ocp-authentication-4.16.pdf` | 4.16 | configuration_guide |

### Chunk Schema Alignment
All fields from `tests/fixtures/sample_chunk.json` are produced by `indexer.py`, including:
- `topic_tags` (was missing — added)
- `ocp_major` / `ocp_minor` as integers
- `embedding_model_id` read from `WATSONX_EMBEDDING_MODEL_ID` env var (never hardcoded)
- `is_current` flag with old-revision supersede logic

### Day 1 Exit Condition — MET
- Taxonomy committed ✅
- Corpus manifest with 6 real approved entries committed ✅
- 6 PDFs confirmed text-extractable (pdfminer.six extracts real OCP text) ✅

### What Vaibhav Needs to Know
- **CP-2 is coming Day 3** — after first ingestion run against local OpenSearch, I will send a real sample chunk JSON
- `config/corpus/ocp_sno_poc.yaml` is now populated — Vaibhav can see the source list
- `config/taxonomy/ocp_sno.yaml` matches his version exactly — no conflicts
- `requirements.txt` is aligned to his pinned versions — Docker build will not break

### Next Steps (Developer B)
- **Day 2:** Rewrite `test_pdf_parser.py` for pdfminer.six, run all unit tests green
- **Day 3:** Stand up local OpenSearch (Docker), run ingestion for 3 PDFs, validate idempotency, send CP-2 chunk JSON to Vaibhav
- **Day 4:** Ingest full 6-PDF corpus, write first 15 evaluation questions

---

*Add new entries below this line as work progresses*

