# Developer B — Work Log (Bob-Assisted)

---

## Session 9 — Day 9/10: Eval Confirmed, README Written, PR Ready

**Branch:** `feature/dev-b-ingestion`
**Status:** ✅ Day 9 complete

### What Was Done
- Reviewed Vaibhav's Day 9 commits (dbb81df, 239f8b6) — all changes valid
- Synced gold_questions.yaml with Vaibhav's q005/q009/q010/q013 clarification fixes
- Fixed scripts/run_eval.py: reads `expected_ocp_version` field (was reading wrong key)
- Confirmed eval results from our side: ambiguous 5/5, out_of_scope 5/5, version 4/5, factual 11/15
- Wrote README.md — full project overview, architecture, demo flow, eval table, setup guide
- Updated SESSION-LOG with Day 9/10 status

### Files Changed
| File | Change |
|---|---|
| `tests/evaluation/gold_questions.yaml` | Synced with Vaibhav — q005/q009/q010/q013 → NEEDS_CLARIFICATION |
| `scripts/run_eval.py` | Fixed `expected_ocp_version` field reading |
| `README.md` | New — full project README with demo section |
| `SESSION-LOG-V3.md` | Day 9/10 entry |
| `BOB-Developer-B-work-done.md` | This entry |

---

## Session 8 — Day 8: Full 40-Question Eval Run

**Branch:** `feature/dev-b-ingestion`
**Status:** ✅ COMPLETE (COS upload done, diagnosis complete — waiting on Vaibhav corpus fix)

### What Was Done
- Verified all endpoints live: `/healthz` ✅ `/readyz` ✅ (`opensearch:true, watsonx:true`)
- Built `scripts/run_eval.py` — full eval runner with per-category filtering, pass/fail logic, report writer
- Ran all 40 gold questions against live API
- Wrote `docs/operations/EVAL_RESULTS.md` — full results table

### Results: 7/40 passed (18%)
| Category | Pass | Total |
|---|---|---|
| ambiguous | 5/5 | ✅ 100% |
| out_of_scope | 2/5 | ⚠️ 40% |
| factual | 0/15 | ❌ 0% |
| troubleshoot | 0/10 | ❌ 0% |
| version | 0/5 | ❌ 0% |

### Root Cause
Vaibhav's OpenSearch index is empty — all factual/troubleshoot/version questions return INSUFFICIENT_EVIDENCE.
ACTION REQUIRED block written in SESSION-LOG for Vaibhav.

### Files Changed
| File | Change |
|---|---|
| `scripts/run_eval.py` | New — 40-question eval runner |
| `openapi/it_helpdesk_live.json` | Live OpenAPI spec from Vaibhav's FastAPI |
| `docs/operations/EVAL_RESULTS.md` | Full eval results (local only) |
| `SESSION-LOG-V3.md` | Day 8 entry + ACTION REQUIRED for Vaibhav |
| `BOB-Developer-B-work-done.md` | This entry |

---

## Session 7 — Day 7: Orchestrate Tool Import + API Verified

**Branch:** `feature/dev-b-ingestion`
**Status:** ✅ COMPLETE

### What Was Done
- Received CP-3 from Vaibhav: ngrok URL + API key
- Verified API live: `/healthz` → `{"status":"ok"}`
- Ran 3 test calls: INSUFFICIENT_EVIDENCE, NEEDS_CLARIFICATION, INSUFFICIENT_EVIDENCE — all correct
- Copied + patched `openapi/it_helpdesk_v1.yaml` (real URL filled in)
- Wrote `docs/operations/ORCHESTRATE_SETUP.md` — full click-by-click Orchestrate guide

### Files Changed
| File | Change |
|---|---|
| `openapi/it_helpdesk_v1.yaml` | Copied from Vaibhav's branch, URL patched |
| `docs/operations/ORCHESTRATE_SETUP.md` | New — Orchestrate setup guide |
| `SESSION-LOG-V3.md` | Day 7 entry added |
| `BOB-Developer-B-work-done.md` | This entry |

### Day 7 Exit Condition — MET ✅
- API verified live ✅
- OpenAPI spec ready for Orchestrate import ✅
- Agent instructions written ✅

---

## Session 6 — Day 6: Chunk Quality Audit + Corpus Expanded to 8 PDFs

**Branch:** `feature/dev-b-ingestion`
**Status:** ✅ COMPLETE

### What Was Done
- Built `scripts/audit_chunks.py` — validates all 29 required fields, types, vector dims, page order, chunk_id format
- Ran full audit → **8/8 documents PASS**
- Audit report written to `docs/operations/CHUNK_AUDIT.md`
- Downloaded 2 new Red Hat public PDFs and indexed all 8:
  - `ocp-operators-4.16.pdf` — 496 pages, 901 chunks
  - `ocp-updating-clusters-4.16.pdf` — 154 pages, 306 chunks
- Corpus now 8 PDFs, **5,524 total chunks** in OpenSearch
- Ingestion result: **INDEXED: 8  SKIPPED: 0  FAILED: 0**

### Files Changed
| File | Change |
|---|---|
| `scripts/audit_chunks.py` | New — chunk quality audit tool |
| `config/corpus/ocp_sno_poc.yaml` | +2 new PDFs (operators, updating-clusters) |
| `config/corpus/new_pdfs_only.yaml` | Temp ingest helper |
| `SESSION-LOG-V3.md` | Day 6 in-progress entry |
| `BOB-Developer-B-work-done.md` | This entry |

---

## Session 5 — Day 5: Evaluation Dataset Complete (All 40 Questions)

**Branch:** `feature/dev-b-ingestion`

### What Was Done
- Completed `tests/evaluation/gold_questions.yaml` with all 40 questions
- 10 troubleshoot (q016–q025): bootstrap timeout, API server, etcd, pods, ingress, certs, NetworkPolicy, SNO recovery, must-gather, PVC
- 5 version-specific (q026–q030): 4.14 vs 4.16 safety tests, strict version filtering
- 5 ambiguous (q031–q035): vague queries → NEEDS_CLARIFICATION
- 5 out-of-scope (q036–q040): ServiceNow, live cluster, Db2, web search, code gen → OUT_OF_SCOPE

### Files Changed
| File | Change |
|---|---|
| `tests/evaluation/gold_questions.yaml` | 25 questions added (q016–q040) |
| `SESSION-LOG-V3.md` | Day 5 entry added |
| `BOB-Developer-B-work-done.md` | This entry |

### Day 5 Exit Condition — MET ✅
- All 40 questions committed ✅
- All 5 status types covered ✅
- Version safety and out-of-scope safety tests included ✅

### Next (Day 6)
- Chunk quality audit — verify chunk text makes sense for each PDF
- Fix any malformed metadata
- Waiting on Vaibhav's credentials (CP-1) for real embeddings

---

## Session 4 — Day 4: Evaluation Dataset + Session Log Update for Vaibhav

**Branch:** `feature/dev-b-ingestion`

### What Was Done
- Added `⚡ ACTION REQUIRED` section for Vaibhav in `SESSION-LOG-V3.md`:
  - CP-2 field types confirmed (ocp_version, ocp_major, deployment_type etc.)
  - Filter patterns for his retrieval code
  - Credential sharing reminder (CP-1 still pending)
- Created `tests/evaluation/gold_questions.yaml` with first 15 factual questions
- Questions cover all 6 indexed PDFs with expected document IDs and page hints

### Files Changed
| File | Change |
|---|---|
| `SESSION-LOG-V3.md` | Day 4 entry + ACTION REQUIRED for Vaibhav |
| `tests/evaluation/gold_questions.yaml` | 15 factual eval questions |
| `BOB-Developer-B-work-done.md` | This entry |

### Day 4 Exit Condition — MET ✅
- 15 factual evaluation questions committed ✅
- All reference real document IDs from indexed corpus ✅

### Next (Day 5)
- 10 troubleshooting + 5 version-specific + 5 ambiguous + 5 out-of-scope = 25 more questions

---

## Session 3 — Day 3: First Ingestion Run + Idempotency

**Branch:** `feature/dev-b-ingestion`

### What Was Done
- Installed Docker Desktop via `brew install --cask docker`
- Started OpenSearch 2.13.0 container locally
- Fixed `verify_certs=False` for local dev SSL
- Fixed index mapping: `l2` space type (accepts zero stub vectors)
- Ran full ingestion: **6/6 PDFs INDEXED, 3,317 chunks total**
- Validated idempotency: re-run = **INDEXED: 0, SKIPPED: 6, FAILED: 0**
- Verified BM25 retrieval with real query
- Saved CP-2 sample chunk to `tests/fixtures/cp2_sample_chunk.json`

### Files Changed
| File | Change |
|---|---|
| `scripts/create_index.py` | `verify_certs=False`, `l2` space type |
| `app/ingestion/run.py` | `verify_certs=False` |
| `tests/fixtures/cp2_sample_chunk.json` | CP-2 payload for Vaibhav |
| `SESSION-LOG-V3.md` | Day 3 entry added |

### Ingestion Summary
| PDF | Chunks |
|---|---|
| sno-installation-guide-4.16.pdf | 158 |
| sno-installation-guide-4.14.pdf | 138 |
| ocp-networking-4.16.pdf | 1850 |
| ocp-storage-4.16.pdf | 491 |
| ocp-troubleshooting-4.16.pdf | 300 |
| ocp-authentication-4.16.pdf | 380 |
| **TOTAL** | **3,317** |

### Day 3 Exit Condition — MET ✅
- OpenSearch retrieves correct chunk IDs ✅
- Idempotency confirmed (re-run = all SKIPPED) ✅
- CP-2 chunk JSON committed ✅

### Next (Day 4)
- Write first 15 evaluation questions with expected document IDs and pages

---
> **Purpose:** Tracks every piece of work done by Developer B (Anush, GitHub: Anush-28-ibm) with Bob's assistance.
> **Rule:** Updated and pushed after every Bob session that produces committed work.
> **Branch:** `feature/dev-b-ingestion`

---

## Session 1 — Old Architecture (Watson Discovery / ST-2)
**Branch at time:** `dev/developer-b` (now deleted)
**Status:** SUPERSEDED — architecture was reset to V3

Built `ingest.py`, `requirements.txt`, `README.md` for the old Watson Discovery pipeline.
All of this was replaced by the V3 reset performed by Developer A (Vaibhav).

---

## Session 2 — V3 Architecture: Day 1

**Date:** Session 2
**Branch:** `feature/dev-b-ingestion`

### Context Read
- Read `DEVELOPER-B-PROMPT.md` — full V3 architecture spec and Developer B task list
- Read `SESSION-LOG-V3.md` — V3 reset summary and branch structure
- Read `developer-task-split-openshift-sno-copilot-poc.html` — day-by-day sprint table
- Read `RESTART-GUIDE.md` — full project reset context
- Checked `origin/feature/dev-a-api-agent` — Vaibhav is on Day 4 complete, 50 passing tests
- Read `app/api/schemas.py`, `app/graph/state.py`, `tests/fixtures/sample_chunk.json` — locked contracts

### Architecture State Confirmed
- **Stack:** OpenSearch (BM25 + kNN hybrid) + watsonx.ai + LangGraph + Orchestrate
- **Watson Discovery:** completely removed — never reference it
- **Embedding model:** `ibm/slate-125m-english-rtrvr-v2`, dimension=768 (confirmed by Vaibhav)
- **PDF parser:** `pdfminer.six==20231228` (Vaibhav's requirements.txt — must match)
- **CP-2 pending:** Vaibhav is waiting for a sample chunk JSON from us

### Files Created / Modified

| File | Operation | Notes |
|---|---|---|
| `requirements.txt` | Rewritten | Now exactly matches Vaibhav's pinned versions |
| `config/taxonomy/ocp_sno.yaml` | Created | Controlled vocabulary — locked contract |
| `config/corpus/ocp_sno_poc.yaml` | Created | 6 approved PDF entries with topic_tags |
| `app/ingestion/__init__.py` | Created | Package marker |
| `app/ingestion/pdf_parser.py` | Created | pdfminer.six extraction, 1-based page numbers, SHA-256 hash |
| `app/ingestion/chunker.py` | Created | 350–550 token chunks, ~70 token overlap, section-aware |
| `app/ingestion/metadata.py` | Created | Taxonomy validator — rejects unsupported values |
| `app/ingestion/cos_source.py` | Created | COS + local dev fallback, URI-based dispatch |
| `app/ingestion/indexer.py` | Created | Idempotent SHA-256 dedup, revision tracking, is_current flag |
| `app/ingestion/run.py` | Created | CLI entry point with --dry-run support |
| `app/__init__.py` | Created | Package marker |
| `scripts/create_index.py` | Created | Creates knowledge_chunks_v1 + knowledge_documents_v1 |
| `tests/__init__.py` | Created | Package marker |
| `tests/unit/__init__.py` | Created | Package marker |
| `tests/unit/test_pdf_parser.py` | Created | 7 unit tests for parser |
| `tests/unit/test_metadata.py` | Created | 12 unit tests for metadata validator |
| `tests/unit/test_chunker.py` | Created | 10 unit tests for chunker |

### 6 PDFs Downloaded and Confirmed Text-Extractable

| Filename | Title | OCP Version | Type |
|---|---|---|---|
| `sno-installation-guide-4.16.pdf` | Agent-based Installer Guide | 4.16 | installation_guide |
| `sno-installation-guide-4.14.pdf` | Agent-based Installer Guide | 4.14 | installation_guide |
| `ocp-networking-4.16.pdf` | Networking Guide | 4.16 | configuration_guide |
| `ocp-storage-4.16.pdf` | Storage Guide | 4.16 | configuration_guide |
| `ocp-troubleshooting-4.16.pdf` | Support / Troubleshooting | 4.16 | troubleshooting_runbook |
| `ocp-authentication-4.16.pdf` | Authentication & Authorization | 4.16 | configuration_guide |

All verified: `%PDF-` header confirmed, pdfminer.six extracts real text from first 3 pages.

### Key Decisions Made

| Decision | Choice | Reason |
|---|---|---|
| PDF parser | `pdfminer.six==20231228` | Matches Vaibhav's requirements.txt — same container build |
| `topic_tags` field | Added to indexer + OpenSearch mapping | Present in Vaibhav's sample_chunk.json fixture |
| requirements.txt | Pinned exact versions | Must match Dev A for shared Docker container |
| Corpus size | 6 PDFs (Day 1), targeting 8–12 total | 2 versions (4.14, 4.16) + 4 topic areas |

### Chunk Schema Compliance
Every chunk produced by `indexer.py` contains all fields from `tests/fixtures/sample_chunk.json`:
`chunk_id`, `document_id`, `revision_id`, `domain_id`, `title`, `source_uri`, `source_type`,
`document_type`, `classification`, `access_scope`, `product`, `ocp_version`, `ocp_major` (int),
`ocp_minor` (int), `deployment_type`, `components`, `topic_tags`, `section_path`, `page_start`,
`page_end`, `chunk_ordinal`, `chunk_text`, `chunk_text_vector`, `content_hash`, `parser_version`,
`chunker_version`, `embedding_model_id` (from env), `embedding_dimension`, `ingested_at`, `is_current`

### Day 1 Exit Condition — MET ✅
- Taxonomy YAML committed ✅
- Corpus manifest with 6 real approved entries committed ✅
- 3+ PDFs confirmed text-extractable (all 6 confirmed) ✅

---

### What's Next (Day 3)
- Stand up local OpenSearch via Docker
- Run ingestion for 3 PDFs: `python -m app.ingestion.run --manifest config/corpus/ocp_sno_poc.yaml`
- Validate idempotency: re-run = skip
- Send CP-2 sample chunk JSON to Vaibhav

### Pending / Waiting On

| Item | Blocked By | Who |
|---|---|---|
| CP-1 credentials | Vaibhav to share `.env` values | Developer A |
| OpenSearch local Docker | Need `docker start opensearch-poc` or fresh container | Anush to set up |
| CP-2 sample chunk JSON | Needs Day 3 ingestion run | Self |
| CP-3 deployed URL | Vaibhav to deploy to TechZone OpenShift | Developer A |

---

*Next update: Session 3 — Day 2 (unit tests) + Day 3 (first ingestion run)*
