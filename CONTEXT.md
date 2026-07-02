# Project Context — Current State
> **This file is the single source of truth for Bob and both developers.**
> Update it immediately every time a sub-task PR is merged into `main`.
> At the start of every Bob session, say: *"Bob, read `SESSION-LOG.md`, `CONTEXT.md`, and `it-helpdesk-chatbot-plan.md` in that order first."*
> For full conversation history and decision rationale, see `SESSION-LOG.md`.

---

**Last updated:** 30 July 2025
**Updated by:** Developer A

---

## Sub-Task Status

| ID | Sub-Task | Owner | Status |
|---|---|---|---|
| ST-1 | IBM Cloud Service Provisioning & Environment Setup | Developer A | `[x] complete` |
| ST-2 | Document Ingestion Pipeline (`ingest.py`) | Developer B | `[x] complete` |
| ST-3 | RAG Core Logic (`rag_core.py`) | Developer A | `[-] in progress` |
| ST-4a | FastAPI Server (`server.py`) | Developer A | `[ ] pending` — blocked on ST-3 |
| ST-4b | Skill YAML definitions (`skills/`) | Developer B | `[ ] pending` — blocked on ST-4a deploy |
| ST-5 | Watsonx Orchestrate Assistant Configuration | Developer B | `[ ] pending` — blocked on ST-4b |
| ST-6a | Dockerfile + `requirements.txt` | Developer A | `[ ] pending` — blocked on ST-3 |
| ST-6b | README + DEMO.md | Developer B | `[ ] pending` — blocked on ST-5 |

---

## Interface Contracts In Effect

These are locked. Neither developer changes these signatures without discussing with the other first.

### `rag_core.py` public API
```python
get_iam_token(api_key: str) -> str
retrieve(query: str, top_k: int = 5, filters: dict = None) -> list[dict]
  # returns: [{"text": str, "source": str, "version": str}, ...]
generate(context_chunks: list[dict], user_query: str, mode: str) -> str
  # mode: 'qa' | 'summarize' | 'troubleshoot'
  # returns fallback string (no LLM call) if context_chunks == []
query(user_input: str, mode: str = "qa", filters: dict = None) -> dict
  # returns: {"answer": str, "sources": list[str]}
```

### `server.py` HTTP endpoints
```
POST /ask          { question: str, version?: str, domain?: str }
POST /summarize    { topic: str, version?: str }
POST /troubleshoot { issue: str, version?: str, domain?: str }
All return:        { answer: str, sources: list[str] }
Auth:              X-API-Key header required on all endpoints (HTTP 401 if missing/wrong)
```

### `manifest.json` entry schema
```json
{
  "filename": "string",
  "discovery_doc_id": "string",
  "metadata": {
    "product": "string",
    "version": "string",
    "deployment_type": "string",
    "component": "string"
  },
  "ingested_at": "ISO8601 timestamp"
}
```

### Required `.env` variables
```
IBM_CLOUD_API_KEY
DISCOVERY_URL
DISCOVERY_PROJECT_ID
DISCOVERY_COLLECTION_ID
WATSONX_PROJECT_ID
WATSONX_REGION
WATSONX_URL
API_KEY_SECRET
```

---

## IBM Cloud Service State

| Service | Status | Notes |
|---|---|---|
| Watson Discovery v2 | ✅ Live — Plus plan (TechZone) | URL: `https://api.us-south.discovery.watson.cloud.ibm.com/instances/b9d1ce46-9e77-48d2-b847-28cb7bdabe1a` |
| Watsonx.ai | ✅ Live | Project ID: `50fcfd4e-df29-4a4e-be9a-c49007300f78` — region: `us-south` |
| IBM Code Engine | not provisioned | Developer A to deploy in ST-4a |
| Watsonx Orchestrate | ✅ Live (23 days remaining) | Developer B to configure in ST-5 |

---

## Active Blockers

- **ST-3** — ✅ unblocked — ST-1 complete, starting now
- **ST-4a** — blocked until `rag_core.py` function implementations are complete (ST-3)
- **ST-4b** — blocked until Code Engine URL is live (ST-4a deployed)
- **ST-5** — blocked until skill YAMLs are imported into Orchestrate (ST-4b)
- **ST-6a** — blocked until `rag_core.py` and `server.py` are stable (ST-3 + ST-4a)
- **ST-6b** — blocked until end-to-end testing passes (ST-5)

---

## Coordination Checkpoints (upcoming)

| Checkpoint | Trigger | Action |
|---|---|---|
| CP-1 | ST-1 complete | Developer A shares `.env` values with Developer B over IBM internal chat (NOT git) |
| CP-2 | ST-3 complete | Developer A confirms `rag_core.py` signatures are finalised — unblocks ST-4a and ST-4b stubs |
| CP-3 | ST-4a deployed | Developer A shares live Code Engine HTTPS URL — Developer B pulls `/openapi.json` to generate `skill-*.yaml` |
| CP-4 | ST-5 complete | Both developers run joint end-to-end acceptance tests in Orchestrate |

---

## Key Technical Decisions (summary — full log in `it-helpdesk-chatbot-plan.md`)

| Decision | Choice |
|---|---|
| LLM | `ibm/granite-13b-instruct-v2` |
| Discovery API version | v2 — filter syntax: `document.metadata.field::value` |
| Container | Single Code Engine container: `server.py` + `rag_core.py` + `prompts/` |
| Auth | `X-API-Key` header on FastAPI; IAM Bearer token for Watsonx.ai (cached, auto-refreshed) |
| Domain scope | OCP + SNO only (Phase 1) |
| `manifest.json` | Project root — committed to git (metadata only, no doc content) |
| `docs/` | Gitignored — internal IBM files never committed |

---

## Branch Map

| Branch | Owner | Purpose |
|---|---|---|
| `main` | Both (via PR only) | Always deployable; no direct pushes |
| `dev/developer-a` | Developer A | ST-1, ST-3, ST-4a, ST-6a |
| `dev/developer-b` | Developer B | ST-2, ST-4b, ST-5, ST-6b |

---

## Change Log

| Date | Developer | Change |
|---|---|---|
| project kickoff | Developer A | Initial CONTEXT.md created |
| 30 July 2025 | Developer A | ST-1 complete — Watson Discovery live, .env populated, connectivity verified |

*(Add a row here every time you update this file)*
