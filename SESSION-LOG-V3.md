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

*Add new entries below this line as work progresses*

