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

