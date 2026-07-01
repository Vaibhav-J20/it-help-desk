# Session Log — IBM IT Help Desk Chatbot
**Developer A (Vaibhav) | Project: it-help-desk | Repo: https://github.com/Vaibhav-J20/it-help-desk**

> This file is a chronological record of all decisions made, changes applied, and key conversation outcomes across Bob sessions.
> Bob should read this file at the start of every session for historical context.
> Append a new entry at the bottom after every session — never delete old entries.

---

## Session 1 — Project Kickoff & Architecture Planning

### What happened
- Established full project context: IBM India ISA division internship, Customer Success Manager intern role, deadline early August
- Defined the project goal: an IT Help Desk chatbot using IBM Watsonx Orchestrate, Watsonx.ai, and Watson Discovery
- Confirmed available services: Watsonx Orchestrate, Watsonx.ai (foundation models), Watson Discovery
- Confirmed document source: internal IBM documents (PDFs, Word docs, runbooks) — not public IBM Docs
- Confirmed delivery channel: Watsonx Orchestrate native chat UI only
- Confirmed scope: Q&A + document summarization + step-by-step troubleshooting
- Confirmed LLM preference: no preference — recommended `ibm/granite-13b-instruct-v2` (free tier, IBM-native, strong RAG)
- Confirmed document situation: no documents yet — system must support incremental uploads over time

### Decisions made
- Architecture pattern: RAG (Retrieval-Augmented Generation)
- LLM: `ibm/granite-13b-instruct-v2`
- Knowledge base: Watson Discovery v2 (not a separate vector DB)
- API bridge: FastAPI on IBM Code Engine (single container)
- Delivery: Watsonx Orchestrate chat UI only

### Files created
- `it-helpdesk-chatbot-plan.md` — full 6 sub-task implementation plan

---

## Session 2 — Improvements Review & Plan Update

### What happened
- Reviewed `IT_Helpdesk_Improvements_Proposal.md` (ChatGPT architectural review with 5 suggestions)
- Evaluated each suggestion critically against project constraints and deadline

### Decisions made
| Improvement | Decision | Reason |
|---|---|---|
| Intent Router Layer | Partial — improve example phrases + add `domain` param | Orchestrate's native semantic matching is sufficient; a separate router adds complexity for no gain |
| Metadata-aware Retrieval | Accepted fully | IBM docs are version-sensitive; wrong version = wrong answer |
| Domain-first OCP/SNO scope | Accepted fully | Too broad otherwise for a solo internship; OCP/SNO gives focused corpus + strong demo narrative |
| Deterministic Troubleshooting Trees | Stretch goal only (Phase 2) | Requires runbooks we don't have yet; checklist-format prompt template gives 80% benefit |
| Confidence Scoring | Rejected | Uncalibrated scores mislead users; needs real corpus first |

### Files updated
- `it-helpdesk-chatbot-plan.md` — updated Goal, Stack, RAG flow, Sub-Tasks 2/3/4, Architecture Diagram, Key Decisions Log, added Phase 2 table

---

## Session 3 — HLA Review & Plan Validation

### What happened
- Full review of `it-helpdesk-chatbot-plan.md` against `HIGH-LEVEL-ARCHITECTURE.md`
- Found and fixed 6 correctness gaps in the plan before writing HLA

### Gaps fixed in plan
| Gap | Fix applied |
|---|---|
| No auth on FastAPI endpoints | Added `X-API-Key` header requirement |
| Watsonx.ai uses IAM tokens not static keys | Added `get_iam_token()` to `rag_core.py` with 60-min expiry cache |
| Wrong Discovery filter syntax (v1 used, v2 needed) | Corrected all to `document.metadata.fieldname::value` |
| `server.py` and `rag_core.py` implied as separate services | Clarified: same Code Engine container, no internal network hop |
| No zero-result handling | Added short-circuit in `generate()` if Discovery returns no chunks |
| `manifest.json` inside gitignored `docs/` | Moved to project root |

### Files created
- `HIGH-LEVEL-ARCHITECTURE.md` — full 11-section HLA document (executive summary, system context, 5 architecture layers, E2E request flow, data flow diagram, component inventory, security model, deployment topology, file structure, decisions, Phase 2)

### Files updated
- `it-helpdesk-chatbot-plan.md` — 3 remaining sync gaps fixed (manifest location, Sub-Task 6 deliverables added Dockerfile + HLA, Technology Summary table updated to match HLA layers)

---

## Session 4 — Team Collaboration Plan & Git Setup

### What happened
- Teammate (`Anush-28-ibm`) joined the project
- Designed two-developer work split and git collaboration strategy
- Created all scaffold files and pushed repo to GitHub
- Resolved teammate's 403 git push error

### Work split decided
| Developer | Sub-Tasks Owned |
|---|---|
| Developer A (Vaibhav) | ST-1 (provisioning), ST-3 (rag_core.py), ST-4a (server.py), ST-6a (Dockerfile) |
| Developer B (Anush) | ST-2 (ingest.py), ST-4b (skill YAMLs), ST-5 (Orchestrate assistant), ST-6b (README + DEMO.md) |

### Git setup completed
- Repo: `https://github.com/Vaibhav-J20/it-help-desk` (public, branch protection ON)
- Branches: `main` (protected), `dev/developer-a` (Vaibhav), `dev/developer-b` (Anush)
- Currently on: `dev/developer-a`
- First commit: `cdc8ed0` — "chore: initial project scaffold — planning docs, interface contract, env template"

### Scaffold files committed to main
- `.gitignore` — excludes `.env`, `docs/`, `__pycache__`, `.vscode/`
- `.env.example` — all 8 variable names, no real values
- `manifest.json` — empty `{"ingested": []}` starter
- `rag_core.py` — full interface stub with locked function signatures and `NotImplementedError` bodies

### Files created this session
- `team-collaboration-plan.md` — work split, git workflow, file ownership, coordination checkpoints, parallel timeline
- `CONTEXT.md` — machine-readable project state for Bob session handoff
- `git-setup-reference.md` — git commands reference + Developer B onboarding prompt

### 403 error resolution
- Root cause: teammate had not accepted the GitHub collaborator invite, and/or had no PAT configured
- Fix: accept invite at `https://github.com/Vaibhav-J20/it-help-desk/invitations`, then generate a GitHub PAT at `https://github.com/settings/tokens/new` with `repo` scope
- Alternative fix: switch to SSH authentication

### Bob onboarding prompt for Developer B
```
Bob, I'm Developer B joining an existing IBM internship project. Please read these files in order to understand the full project context before helping me:
1. CONTEXT.md — current state, what's done, what I own, blockers, and shared interface contracts
2. it-helpdesk-chatbot-plan.md — full detail for all 6 sub-tasks
3. team-collaboration-plan.md — work split, git workflow, and how we coordinate
4. HIGH-LEVEL-ARCHITECTURE.md — full system architecture
After reading, tell me: which sub-tasks I own, what my current blockers are, and what branch I should be working on.
Then help me clone the repo https://github.com/Vaibhav-J20/it-help-desk.git, check out dev/developer-b, and start on ST-2 (building ingest.py).
```

---

## Current Project State (as of last session)

- **Active branch:** `dev/developer-a`
- **Next step:** ST-1 — IBM Cloud Service Provisioning (Developer A)
- **ST-1 is unblocked** — nothing depends on it being done first except ST-3
- **Developer B** is setting up their environment and will start ST-2 independently

---

## How to Start the Next Bob Session

Paste this at the start of every new Bob session:

> **"Bob, read `SESSION-LOG.md`, `CONTEXT.md`, and `it-helpdesk-chatbot-plan.md` in that order to understand the full project history and current state. I am Developer A (Vaibhav). Then help me with [your task]."**
