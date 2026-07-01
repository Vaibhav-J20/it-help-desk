# Session Log — IBM IT Help Desk Chatbot
**Repo: https://github.com/Vaibhav-J20/it-help-desk**

> **Shared log for both Developer A (Vaibhav) and Developer B (Anush).**
> Every entry is prefixed with the developer who wrote it and the date.
> Both Bob instances read this file at the start of every session.
>
> **Session start prompt:**
> *"Bob, read `SESSION-LOG.md`, `CONTEXT.md`, and `it-helpdesk-chatbot-plan.md` in that order. I am Developer [A/B]. Then help me with [task]."*
>
> **Format for new entries:**
> `## Developer [A/B] Context — [DD Month YYYY]`

---

## Developer A Context — 30 July 2025

### Project Established
- **Project:** IBM IT Help Desk Chatbot — IBM India ISA division internship project
- **Deadline:** Early August 2025
- **Repo:** `https://github.com/Vaibhav-J20/it-help-desk` (public, branch protection ON)
- **Developer A:** Vaibhav (GitHub: `Vaibhav-J20`) — branch `dev/developer-a`
- **Developer B:** Anush (GitHub: `Anush-28-ibm`) — branch `dev/developer-b`

### Architecture Decided
- **Pattern:** RAG (Retrieval-Augmented Generation) — entirely on IBM Watsonx platform
- **LLM:** `ibm/granite-13b-instruct-v2` on Watsonx.ai (free tier compatible)
- **Knowledge base:** IBM Watson Discovery v2 — document ingestion, chunking, metadata-filtered semantic search
- **API bridge:** FastAPI on IBM Code Engine — single container hosting `server.py` + `rag_core.py`
- **UI:** IBM Watsonx Orchestrate native chat — 3 skills: Ask, Summarize, Troubleshoot
- **Domain scope (Phase 1):** OCP + SNO only
- **Auth:** `X-API-Key` header on FastAPI; IAM Bearer token for Watsonx.ai (cached, auto-refreshed)
- **Metadata schema:** `product`, `version`, `deployment_type`, `component` per document

### Improvements Reviewed (from ChatGPT proposal)
| Improvement | Decision |
|---|---|
| Intent Router | Partial — rich example phrases + optional `domain` param instead |
| Metadata-aware Retrieval | Accepted fully — version-sensitive IBM docs need this |
| Domain-first OCP/SNO scope | Accepted fully — focused corpus, stronger demo |
| Deterministic Troubleshooting Trees | Phase 2 stretch goal only |
| Confidence Scoring | Rejected — uncalibrated scores mislead users |

### Work Split
| Developer | Sub-Tasks |
|---|---|
| Developer A (Vaibhav) | ST-1 (IBM Cloud provisioning), ST-3 (rag_core.py), ST-4a (server.py), ST-6a (Dockerfile) |
| Developer B (Anush) | ST-2 (ingest.py), ST-4b (skill YAMLs), ST-5 (Orchestrate assistant), ST-6b (README + DEMO.md) |

### Git Setup Completed
- Repo initialised, all planning docs committed to `main`
- Branches `dev/developer-a` and `dev/developer-b` created and pushed
- Scaffold files on `main`: `.gitignore`, `.env.example`, `manifest.json`, `rag_core.py` (interface stub)
- Branch protection rule active on `main` (public repo, free tier enforced)

### Interface Contracts Locked (do not change without both developers agreeing)
```python
# rag_core.py
get_iam_token(api_key: str) -> str
retrieve(query: str, top_k: int = 5, filters: dict = None) -> list[dict]
generate(context_chunks: list, user_query: str, mode: str) -> str
query(user_input: str, mode: str = "qa", filters: dict = None) -> dict
# returns: {"answer": str, "sources": list[str]}
```
```
# server.py endpoints
POST /ask          { question, version?, domain? }  → { answer, sources }
POST /summarize    { topic, version? }              → { answer, sources }
POST /troubleshoot { issue, version?, domain? }     → { answer, sources }
Auth: X-API-Key header required (HTTP 401 if missing)
```

### Key Files in Repo
| File | Purpose |
|---|---|
| `it-helpdesk-chatbot-plan.md` | Full 6 sub-task implementation plan |
| `HIGH-LEVEL-ARCHITECTURE.md` | Full system HLA — 11 sections |
| `CONTEXT.md` | Machine-readable current project state for Bob |
| `SESSION-LOG.md` | This file — shared conversation log for both developers |
| `team-collaboration-plan.md` | Work split, git workflow, coordination checkpoints |
| `rag_core.py` | Interface stub — Developer A implements in ST-3 |
| `.env.example` | Credential template — copy to `.env`, fill values, never commit `.env` |
| `manifest.json` | Empty ingestion index `{"ingested": []}` — Developer B populates via `ingest.py` |

### Developer B 403 Fix
Anush got a 403 pushing to GitHub. Fix:
1. Accept invite at `https://github.com/Vaibhav-J20/it-help-desk/invitations`
2. Generate a GitHub PAT at `https://github.com/settings/tokens/new` (scope: `repo`)
3. Use PAT as password when git prompts, or switch to SSH

### Current Status
- All planning and architecture complete
- Repo live with scaffold
- **Next:** ST-1 (Developer A — IBM Cloud provisioning) and ST-2 (Developer B — ingest.py) can start in parallel
