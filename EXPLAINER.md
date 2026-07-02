# EXPLAINER.md — Complete Intern Guide to the OpenShift & SNO Support Copilot

> **Who is this for?** You're an intern who just cloned this repo. This document explains every piece of this system from the ground up — what it is, why each technology was chosen, how it all connects, and what alternatives exist. No prior knowledge assumed beyond basic Python.

---

## Table of Contents

1. [What Is This Project?](#1-what-is-this-project)
2. [The Problem It Solves](#2-the-problem-it-solves)
3. [High-Level Architecture (The Big Picture)](#3-high-level-architecture-the-big-picture)
4. [Technology Stack — What We Use and Why](#4-technology-stack--what-we-use-and-why)
5. [How a Request Flows Through the System (End-to-End)](#5-how-a-request-flows-through-the-system-end-to-end)
6. [Project Structure — Where Everything Lives](#6-project-structure--where-everything-lives)
7. [The API Layer (FastAPI)](#7-the-api-layer-fastapi)
8. [The Agent Workflow (LangGraph)](#8-the-agent-workflow-langgraph)
9. [Retrieval — How We Find Relevant Information](#9-retrieval--how-we-find-relevant-information)
10. [AI Providers (watsonx.ai)](#10-ai-providers-watsonxai)
11. [The Ingestion Pipeline (How Knowledge Gets In)](#11-the-ingestion-pipeline-how-knowledge-gets-in)
12. [Configuration & Environment Variables](#12-configuration--environment-variables)
13. [Security Decisions](#13-security-decisions)
14. [Observability & Logging](#14-observability--logging)
15. [Comparing Our Choices to Alternatives](#15-comparing-our-choices-to-alternatives)
16. [Key Design Principles](#16-key-design-principles)
17. [Glossary](#17-glossary)

---

## 1. What Is This Project?

This is a **citation-grounded technical support chatbot** for Red Hat OpenShift Container Platform (OCP) and Single Node OpenShift (SNO). It's an IBM internship POC (Proof of Concept) built in two weeks.

**In plain English:** Users ask technical questions about OpenShift, and the system finds the answer in pre-approved PDF documentation, then returns the answer *with exact page citations* — never making things up.

**Example:**
- **User asks:** "How do I configure DNS for SNO installation on OCP 4.16?"
- **System returns:** A step-by-step answer citing pages 12–13 of the "SNO Installation Guide", with `[S1]` labels linking back to the exact source chunk.

---

## 2. The Problem It Solves

**Without this system:** An IBM engineer working on OpenShift needs to manually search through hundreds of pages of PDF documentation to find the right procedure. They might search the wrong version, misremember a step, or waste 30 minutes finding one answer.

**With this system:** They type their question in IBM watsonx Orchestrate, and in ~5 seconds they get the exact answer with page numbers they can verify.

**Critical constraint:** The system **never invents answers**. If it can't find evidence in the approved documents, it says so. This is called being "citation-grounded" — every claim must trace back to a real document and page number.

---

## 3. High-Level Architecture (The Big Picture)

```
┌─────────────────────┐
│  IBM watsonx         │  ← The user interface (IBM's chatbot platform)
│  Orchestrate         │
└────────┬────────────┘
         │ HTTPS POST /v1/assist
         ▼
┌─────────────────────┐
│  FastAPI Backend     │  ← Our Python service (this repo)
│  (this repo)        │
└────────┬────────────┘
         │ runs internally
         ▼
┌─────────────────────┐
│  LangGraph Workflow  │  ← A 7-step pipeline that processes the question
│  (7 nodes)          │
└──┬────────────┬─────┘
   │            │
   ▼            ▼
┌──────────┐ ┌──────────────┐
│ OpenSearch│ │ watsonx.ai   │  ← Where we FIND and GENERATE answers
│ (search) │ │ (LLM)        │
└──────────┘ └──────────────┘
```

**The flow:**
1. User types question in Orchestrate → 
2. Orchestrate calls our API → 
3. Our 7-node workflow classifies the question, searches for evidence, and generates an answer → 
4. Response goes back to Orchestrate → 
5. User sees the answer with citations

---

## 4. Technology Stack — What We Use and Why

### 4.1 Python 3.11

**What:** The programming language for all backend code.  
**Why:** Universal in AI/ML projects, has the best library ecosystem for LLMs, FastAPI is Python-native.  
**Alternative:** Node.js/TypeScript (good for web, worse for AI libraries), Go (fast but fewer AI frameworks).

### 4.2 FastAPI

**What:** A modern Python web framework for building REST APIs.  
**Why:**
- Automatic request validation (from Pydantic models)
- Automatic OpenAPI/Swagger docs generation (critical for Orchestrate)
- Async support out of the box
- Type-safe — catches bugs before runtime

**Alternative:** Flask (older, no auto validation), Django REST Framework (heavyweight, designed for full web apps, overkill here).

**Where in code:** [`app/main.py`](app/main.py) creates the app, [`app/api/routes.py`](app/api/routes.py) defines endpoints.

### 4.3 LangGraph

**What:** A framework for building stateful, multi-step AI workflows as directed graphs.  
**Why:**
- Each step (node) is a pure function that modifies a shared state dict
- Conditional edges let us exit early (e.g., if evidence is insufficient, stop — don't generate)
- Built on top of LangChain's ecosystem
- Makes complex logic testable node-by-node

**Alternative:** 
- Raw Python functions calling each other (no state machine, harder to trace failures)
- LangChain Agents (autonomous, unpredictable loops — we explicitly DON'T want that)
- CrewAI / AutoGen (multi-agent — way overkill and unpredictable)
- Custom state machine (more code to maintain)

**Key insight:** We use a **bounded** graph — exactly 7 nodes, no loops, no autonomous decisions. This is intentional. We DON'T want the AI deciding how many times to retry or which tools to call. We control the flow.

**Where in code:** [`app/graph/workflow.py`](app/graph/workflow.py) wires the nodes together.

### 4.4 OpenSearch

**What:** A search engine (fork of Elasticsearch) that supports both keyword search (BM25) and vector search (kNN).  
**Why:**
- Supports **hybrid retrieval**: combine traditional text matching AND semantic similarity
- Metadata filtering: "show me only OCP 4.16 SNO documents"
- Battle-tested at scale (millions of documents)
- Open source, deployable on OpenShift

**Alternative:**
- Elasticsearch (nearly identical, but licensing concerns with IBM)
- Pinecone/Weaviate (cloud-only vector databases — can't deploy on our OpenShift cluster)
- ChromaDB (toy-scale, no production features)
- PostgreSQL + pgvector (possible but worse at full-text search)

**Where in code:** [`app/retrieval/opensearch_client.py`](app/retrieval/opensearch_client.py) creates the connection.

### 4.5 IBM watsonx.ai

**What:** IBM's enterprise AI platform for running large language models (LLMs).  
**Why:** 
- This is an IBM project — must use IBM's AI platform
- Provides both **embedding models** (convert text to vectors) and **chat models** (generate text answers)
- Enterprise-grade: audit trails, data governance, no data leakage to public APIs

**What we use it for:**
1. **Embeddings** — turning text into number vectors for semantic search
2. **Chat/Generation** — producing the final cited answer from evidence blocks

**Alternative:** OpenAI (not IBM), Azure OpenAI (Microsoft), self-hosted Ollama (no enterprise governance).

**Where in code:** [`app/providers/watsonx_chat.py`](app/providers/watsonx_chat.py) and [`app/providers/watsonx_embeddings.py`](app/providers/watsonx_embeddings.py).

### 4.6 IBM watsonx Orchestrate

**What:** IBM's enterprise chatbot/agent platform — the user-facing layer.  
**Why:** This is where IBM employees will actually interact with the system. It handles conversation UI, session management, and tool invocation.  
**Our role:** We expose an OpenAPI spec (`/openapi.json`), Orchestrate imports it as a "tool", and calls our API whenever a user asks a question.

### 4.7 Pydantic

**What:** A Python library for data validation using type annotations.  
**Why:** 
- Defines the exact shape of API requests and responses
- Automatically rejects malformed input (e.g., question too short)
- Generates JSON Schema for OpenAPI docs

**Where in code:** [`app/api/schemas.py`](app/api/schemas.py) defines all request/response models.

### 4.8 IBM Cloud Object Storage (COS)

**What:** IBM's S3-compatible cloud storage service.  
**Why:** Where the approved PDF documents live. The ingestion pipeline reads PDFs from COS.  
**Alternative:** AWS S3 (not IBM), local filesystem (not production-ready, but used in dev).

---

## 5. How a Request Flows Through the System (End-to-End)

Let's trace a real request step by step:

### Step 0: User types a question
> "My SNO bootstrap is timing out during OCP 4.16 installation. What should I check?"

### Step 1: Orchestrate → FastAPI
Orchestrate sends an HTTPS POST to our `/v1/assist` endpoint with:
```json
{
  "question": "My SNO bootstrap is timing out during OCP 4.16 installation. What should I check?",
  "requested_scope": {"ocp_version": "4.16", "deployment_type": "SNO"}
}
```

### Step 2: Authentication check
[`app/api/dependencies.py`](app/api/dependencies.py) verifies the `X-API-Key` header using constant-time comparison (prevents timing attacks).

### Step 3: Service layer builds initial state
[`app/services/assist_service.py`](app/services/assist_service.py) creates a `SupportState` dict and invokes the LangGraph workflow.

### Step 4: Node 1 — Input Guard
[`app/graph/nodes/input_guard.py`](app/graph/nodes/input_guard.py)
- Validates the question isn't empty or too long
- Normalises whitespace
- If invalid → status = `INVALID_REQUEST`, graph ends

### Step 5: Node 2 — Classify & Extract
[`app/graph/nodes/classify_extract.py`](app/graph/nodes/classify_extract.py)
- Sends the question to watsonx.ai with a classification prompt
- LLM returns: `{"intent": "troubleshoot", "ocp_version": "4.16", "deployment_type": "SNO", "component": "bootstrap"}`
- Merges LLM-extracted scope with any explicitly provided scope (explicit wins)

### Step 6: Node 3 — Resolve Scope
[`app/graph/nodes/resolve_scope.py`](app/graph/nodes/resolve_scope.py)
- Checks if the intent is "unsupported" → `OUT_OF_SCOPE`
- Checks if clarification is needed → `NEEDS_CLARIFICATION`
- Otherwise: builds OpenSearch filter clauses and sets the retrieval query

### Step 7: Node 4 — Retrieve
[`app/graph/nodes/retrieve.py`](app/graph/nodes/retrieve.py)
- Runs BM25 (keyword) search → top 20 results
- Generates query embedding via watsonx.ai
- Runs vector kNN search → top 20 results
- Merges both result sets using Reciprocal Rank Fusion (RRF) → top 12 candidates
- If 0 results, retries with relaxed filters

### Step 8: Node 5 — Evidence Gate
[`app/graph/nodes/evidence_gate.py`](app/graph/nodes/evidence_gate.py)
- If 0 candidates → `INSUFFICIENT_EVIDENCE`
- If user asked for version 4.16 but all evidence is 4.15 → `INSUFFICIENT_EVIDENCE` (version mismatch)
- If sufficient → trim to top 6 candidates and continue

### Step 9: Node 6 — Compose Answer
[`app/graph/nodes/compose_answer.py`](app/graph/nodes/compose_answer.py)
- Formats evidence chunks as labelled blocks: `[S1] SNO Installation Guide — OCP 4.16, pp. 12–13`
- Sends the evidence + question to watsonx.ai with the grounded answer prompt
- LLM generates an answer using ONLY the provided evidence, citing `[S1]`, `[S2]`, etc.

### Step 10: Node 7 — Validate Citations
[`app/graph/nodes/validate_citations.py`](app/graph/nodes/validate_citations.py)
- Parses all `[S#]` labels from the generated answer
- Checks that each `[S#]` maps to a real retrieved chunk (S1 = first candidate, etc.)
- If any citation is invalid → `INSUFFICIENT_EVIDENCE` (rejects the answer entirely)
- If all valid → status = `ANSWERED`, builds citation objects

### Step 11: Response returned
```json
{
  "request_id": "uuid",
  "status": "ANSWERED",
  "intent": "troubleshoot",
  "answer_markdown": "### Recommended checks\n1. Verify DNS... [S1]\n2. Check bootstrap...",
  "citations": [{"citation_id": "S1", "title": "SNO Installation Guide", "page_start": 12, ...}],
  "safety_note": "Guidance is based only on the approved knowledge base..."
}
```

---

## 6. Project Structure — Where Everything Lives

```
it-help-desk/
├── app/                          ← All application code
│   ├── main.py                   ← FastAPI app factory (creates the server)
│   ├── api/                      ← HTTP layer (routes, auth, schemas)
│   │   ├── routes.py             ← Defines POST /v1/assist endpoint
│   │   ├── dependencies.py       ← API key verification middleware
│   │   └── schemas.py            ← Request/response data models (LOCKED)
│   ├── core/                     ← Shared config
│   │   └── config.py             ← Reads all settings from .env
│   ├── graph/                    ← The 7-node LangGraph workflow
│   │   ├── state.py              ← TypedDict shared between all nodes (LOCKED)
│   │   ├── workflow.py           ← Wires nodes together with conditional edges
│   │   └── nodes/                ← Each node is a separate file
│   │       ├── input_guard.py    ← Node 1: validates input
│   │       ├── classify_extract.py ← Node 2: determines intent + scope
│   │       ├── resolve_scope.py  ← Node 3: in-scope? needs clarification?
│   │       ├── retrieve.py       ← Node 4: hybrid search
│   │       ├── evidence_gate.py  ← Node 5: is evidence sufficient?
│   │       ├── compose_answer.py ← Node 6: generate cited answer
│   │       └── validate_citations.py ← Node 7: verify [S#] labels are real
│   ├── retrieval/                ← Search logic
│   │   ├── opensearch_client.py  ← Connection factory
│   │   ├── hybrid_retriever.py   ← BM25 + vector + RRF merge
│   │   ├── filters.py           ← Build OpenSearch filter clauses
│   │   └── fusion.py            ← Reciprocal Rank Fusion algorithm
│   ├── providers/                ← External AI service wrappers
│   │   ├── watsonx_chat.py       ← LLM text generation
│   │   ├── watsonx_embeddings.py ← Text → vector conversion
│   │   └── watsonx_rerank.py     ← Optional re-ranking
│   ├── policy/                   ← Business rules (no I/O)
│   │   ├── domain_policy.py      ← Is this domain active?
│   │   └── evidence_policy.py    ← Is evidence sufficient?
│   ├── prompts/                  ← LLM prompt templates
│   │   ├── classify_extract.md   ← Classification prompt
│   │   └── grounded_answer.md    ← Answer generation prompt
│   ├── services/                 ← Orchestration layer
│   │   └── assist_service.py     ← Bridges API → Graph → Response
│   ├── observability/            ← Logging
│   │   └── logging.py           ← Structured JSON logger
│   └── ingestion/                ← PDF ingestion pipeline (Developer B)
│       ├── run.py                ← CLI entry point
│       ├── cos_source.py         ← Read PDFs from COS
│       ├── pdf_parser.py         ← Extract text from PDFs
│       ├── chunker.py            ← Split text into retrievable chunks
│       ├── metadata.py           ← Validate metadata against taxonomy
│       └── indexer.py            ← Write chunks to OpenSearch
├── config/                       ← Configuration files
│   ├── domains.yaml              ← Domain registry
│   ├── taxonomy/ocp_sno.yaml     ← Controlled vocabulary (LOCKED)
│   └── corpus/ocp_sno_poc.yaml   ← Approved PDF list
├── deployment/openshift/         ← Kubernetes/OpenShift manifests
├── openapi/                      ← OpenAPI spec for Orchestrate
├── scripts/                      ← Utility scripts
├── tests/                        ← Test suite
├── requirements.txt              ← Python dependencies
├── pyproject.toml                ← Project metadata + tool config
└── .env.example                  ← Template for environment variables
```

---

## 7. The API Layer (FastAPI)

### 7.1 What is a REST API?

A REST API is a way for one program to talk to another over HTTP. Think of it like a vending machine:
- You put in a specific input (press button B4)
- You get a specific output (candy bar falls out)
- The machine has a defined set of buttons (endpoints)

Our "vending machine" has one main button:

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/v1/assist` | Ask a technical question |
| GET | `/healthz` | "Am I alive?" (no dependencies checked) |
| GET | `/readyz` | "Am I ready?" (checks OpenSearch + watsonx) |
| GET | `/openapi.json` | Machine-readable API spec |

### 7.2 How authentication works

Every call to `/v1/assist` must include an `X-API-Key` header:

```
X-API-Key: <random-secret-string>
```

The server compares this key against `API_KEY_SECRET` from the environment using `secrets.compare_digest()`. This is a **constant-time comparison** — it takes the same amount of time regardless of where the mismatch occurs. A naive `==` comparison leaks timing information that attackers can exploit.

**File:** [`app/api/dependencies.py`](app/api/dependencies.py)

### 7.3 Request/Response Schemas

Schemas are defined using **Pydantic models** in [`app/api/schemas.py`](app/api/schemas.py). They are a "contract" — any change requires both developers to review.

**Request (`AssistRequest`):**
```python
{
    "question": "3–2000 chars, required",
    "conversation_id": "optional",
    "conversation_context": "optional, max 4 messages, max 4000 total chars",
    "requested_scope": {"ocp_version": "4.16", "deployment_type": "SNO"}
}
```

**Response (`AssistResponse`):**
```python
{
    "request_id": "auto-generated UUID",
    "status": "ANSWERED | NEEDS_CLARIFICATION | INSUFFICIENT_EVIDENCE | OUT_OF_SCOPE | INVALID_REQUEST | ERROR",
    "intent": "qa | troubleshoot | summarize | unsupported",
    "answer_markdown": "The actual answer with [S1] citations",
    "citations": [{...citation objects...}],
    "safety_note": "Standard disclaimer"
}
```

### 7.4 Why status codes matter

The 5 possible `status` values aren't random — they're the ONLY states the system can end in:

| Status | Meaning | When it triggers |
|--------|---------|-----------------|
| `ANSWERED` | Got a grounded answer with valid citations | Happy path |
| `NEEDS_CLARIFICATION` | Question is too vague to answer | Node 3 |
| `INSUFFICIENT_EVIDENCE` | Can't find relevant docs OR citations are broken | Node 5 or 7 |
| `OUT_OF_SCOPE` | Question isn't about OpenShift/SNO | Node 3 |
| `INVALID_REQUEST` | Malformed input | Node 1 |
| `ERROR` | Something crashed | Exception handler |

---

## 8. The Agent Workflow (LangGraph)

### 8.1 What is a state machine?

A state machine is a system that:
1. Has a defined "state" (a bag of data)
2. Goes through a series of steps (nodes)
3. Each step reads the current state, does work, and produces an updated state
4. The system transitions between steps based on conditions

Our state is defined in [`app/graph/state.py`](app/graph/state.py) — it's a Python `TypedDict` with all the fields the workflow needs:

```python
class SupportState(TypedDict, total=False):
    request_id: str
    user_question: str
    conversation_context: list[dict]
    intent: Literal["qa", "troubleshoot", "summarize", "unsupported"]
    extracted_scope: dict
    retrieval_query: str
    candidates: list[dict]       # retrieved chunks
    evidence_decision: ...
    answer_markdown: str
    citations: list[dict]
    status: Literal["ANSWERED", ...]
    trace: dict                  # debugging breadcrumbs
```

### 8.2 Why 7 nodes and not 3 or 20?

Each node does **one thing**. This makes them:
- **Testable in isolation** — you can unit test `input_guard` without a real LLM
- **Traceable** — if something fails, you know exactly which node caused it
- **Replaceable** — you can swap the retrieval strategy without touching answer generation

If we merged them into 3 fat nodes, testing and debugging would be a nightmare. If we split into 20, we'd have unnecessary complexity.

### 8.3 Conditional edges (early exit)

The graph isn't linear. At several points, it can **exit early**:

```
input_guard ──────── INVALID_REQUEST? ─────→ END
     │
classify_extract
     │
resolve_scope ────── OUT_OF_SCOPE? ────────→ END
              ────── NEEDS_CLARIFICATION? ─→ END
     │
retrieve
     │
evidence_gate ────── INSUFFICIENT? ────────→ END
     │
compose_answer
     │
validate_citations ─ INVALID CITATIONS? ──→ END (INSUFFICIENT_EVIDENCE)
     │
     └───→ END (ANSWERED)
```

This is defined in [`app/graph/workflow.py`](app/graph/workflow.py) using `add_conditional_edges()`.

### 8.4 Why NOT use autonomous agents?

Autonomous agents (like "ReAct" pattern) decide their own next step. They think: "Hmm, should I search again? Should I ask the user? Let me call this tool..." This is **dangerous** for enterprise systems because:

1. **Unpredictable latency** — might loop 5 times
2. **Unpredictable cost** — each loop is an LLM call ($$$)
3. **Unpredictable output** — might invent tools or actions
4. **Not auditable** — can't guarantee what path was taken

Our bounded graph guarantees: **at most 7 nodes, 2 LLM calls, 1 search operation, deterministic path**.

---

## 9. Retrieval — How We Find Relevant Information

### 9.1 What is retrieval?

Retrieval = finding the most relevant chunks of text from our knowledge base given a user question.

Think of it like a library:
- **BM25 (keyword search):** "Find me every book with the word 'DNS' in it" — exact matching
- **Vector search (semantic search):** "Find me books that are *about* network name resolution" — meaning matching

We use **both** and merge the results. This is called **hybrid retrieval**.

### 9.2 How BM25 works (keyword search)

BM25 is a scoring algorithm that ranks documents by how well they match search terms:
- Documents with rare words that match score higher (word "etcd" is more specific than "the")
- Shorter documents with matches score higher than long documents with the same matches
- It's like Google Search before neural networks

**Strengths:** Exact terminology matching. If the user says "etcd", BM25 finds every chunk with "etcd".  
**Weaknesses:** Can't handle synonyms. "name resolution" won't find "DNS" unless both words appear.

### 9.3 How vector search works (semantic search)

1. The user's question gets converted to a **vector** (a list of 768 numbers) by the embedding model
2. Every chunk in OpenSearch also has a pre-computed vector
3. We find the chunks whose vectors are **closest** to the question vector (kNN = k-Nearest Neighbors)

**Strengths:** Understands meaning. "name resolution" finds "DNS" because they mean similar things.  
**Weaknesses:** Less precise for exact terminology. Might rank a vaguely related chunk higher than an exactly matching one.

### 9.4 Reciprocal Rank Fusion (RRF) — merging both

We get 20 results from BM25 and 20 from vector search. How do we merge them?

**RRF formula:** `score(d) = Σ 1 / (k + rank)`

For each document `d`:
- If it's rank 1 in BM25: `1 / (60 + 1) = 0.0164`
- If it's rank 3 in vector: `1 / (60 + 3) = 0.0159`
- Combined score: `0.0164 + 0.0159 = 0.0323`

Documents that appear in BOTH result sets get boosted. The `k=60` constant controls how much rank matters (higher k = flatter distribution = less aggressive ranking).

**File:** [`app/retrieval/fusion.py`](app/retrieval/fusion.py) — this is a **pure function** (no I/O, no side effects) — trivial to unit test.

### 9.5 Metadata filtering

Before searching, we add **filter clauses** to narrow results:
- `ocp_version: "4.16"` → only show OCP 4.16 documents
- `deployment_type: "SNO"` → only show SNO documents
- `is_current: true` → only show the latest revision (not superseded old versions)

This prevents "version leakage" — never answer a 4.16 question with 4.15 evidence.

**File:** [`app/retrieval/filters.py`](app/retrieval/filters.py)

### 9.6 Filter relaxation (retry strategy)

If strict filters return 0 results, we **relax** inferred filters (not explicit ones) and retry:
- User explicitly said "4.16" → keep that filter
- System inferred "bootstrap" as the component → remove that filter
- Retry → might find relevant results that aren't strictly in the "bootstrap" section

---

## 10. AI Providers (watsonx.ai)

### 10.1 The two uses of AI in this system

| Use | Model Type | When | Purpose |
|-----|-----------|------|---------|
| Embeddings | Embedding model | During retrieval (Node 4) + during ingestion | Convert text → 768-dim vector |
| Chat/Generation | Foundation model | Classification (Node 2) + Answer (Node 6) | Generate text responses |

### 10.2 Why model IDs are NEVER hard-coded

```python
# WRONG ❌
model_id = "ibm/slate-125m-english-rtrvr-v2"

# RIGHT ✅
model_id = settings.watsonx_embedding_model_id  # from env var
```

**Why?** 
- Models get deprecated/rotated by IBM
- Different environments might use different models
- A hard-coded model ID is a ticking time bomb — deploy to production and it's gone

### 10.3 Generation parameters

```python
_GENERATE_PARAMS = {
    MAX_NEW_TOKENS: 1024,     # maximum answer length
    MIN_NEW_TOKENS: 10,       # don't return empty
    TEMPERATURE: 0.0,         # deterministic — same input = same output
    STOP_SEQUENCES: [],       # no early stopping
}
```

**Temperature = 0.0** means the model always picks the most likely next word. No randomness. For a support system, you want the same answer every time — no creative flourishes.

### 10.4 Dependency injection

Every provider is **injected** into graph nodes, not imported deep inside:

```python
def run(state, generate_fn=None):   # ← injectable!
    if generate_fn is None:
        from app.providers.watsonx_chat import generate as generate_fn
    # use generate_fn(...)
```

This means during testing, you can pass a mock:
```python
def fake_generate(prompt):
    return '{"intent": "qa", ...}'

result = classify_extract.run(state, generate_fn=fake_generate)
```

No real LLM calls needed in unit tests.

---

## 11. The Ingestion Pipeline (How Knowledge Gets In)

### 11.1 What is ingestion?

Ingestion is the process of turning raw PDFs into searchable chunks in OpenSearch. It's a separate offline process — not triggered by user requests.

```
PDF file → Extract text → Split into chunks → Generate embeddings → Index into OpenSearch
```

### 11.2 Pipeline steps

| Step | Module | Input | Output |
|------|--------|-------|--------|
| 1. Source | `cos_source.py` | COS URI | Raw PDF bytes |
| 2. Parse | `pdf_parser.py` | PDF bytes | List of `{page_number, text}` |
| 3. Chunk | `chunker.py` | Pages | 350–550 token chunks with overlap |
| 4. Validate | `metadata.py` | Chunk metadata | Reject if not in taxonomy |
| 5. Embed | `watsonx_embeddings.py` | Chunk text | 768-dim vector |
| 6. Index | `indexer.py` | Chunk + vector | Written to OpenSearch |

### 11.3 Why chunks, not whole pages?

LLMs have **context window limits** (how much text they can process at once). If we fed an entire 50-page PDF into the prompt, it would:
1. Exceed the context window
2. Confuse the LLM with too much irrelevant text
3. Make citation attribution impossible

By chunking into 350–550 tokens (~1–2 paragraphs), we can:
- Retrieve only the 4–6 most relevant chunks
- Fit them all in the prompt with room for the answer
- Point citations to specific pages

### 11.4 Why overlap between chunks?

If a sentence spans the boundary between chunk 12 and chunk 13, without overlap you'd lose context. A ~70-token overlap means the tail of chunk 12 is repeated at the start of chunk 13 — no information lost at boundaries.

### 11.5 Idempotency (re-run safety)

Every chunk has a `content_hash` (SHA-256 of its text). If you re-run ingestion on the same PDF:
- Same content → same hash → **skip** (no duplicate data)
- Changed content → different hash → new revision, old revision marked `is_current=false`

This means you can safely re-run ingestion at any time without creating duplicates.

### 11.6 The taxonomy (controlled vocabulary)

[`config/taxonomy/ocp_sno.yaml`](config/taxonomy/ocp_sno.yaml) defines ALL allowed values:
- Products: OpenShift, RHCOS (only these two)
- Versions: 4.14, 4.15, 4.16, 4.17 (only these four)
- Components: bootstrap, dns, networking, etc.

If ingestion tries to index a chunk with `ocp_version: "4.13"`, the metadata validator **rejects it**. This ensures data quality — the search filters only work if the data is clean.

---

## 12. Configuration & Environment Variables

### 12.1 How configuration works

[`app/core/config.py`](app/core/config.py) uses `pydantic-settings` to load config from `.env`:

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")
    
    opensearch_url: str = "https://localhost:9200"
    watsonx_embedding_model_id: str = ""   # must be set!
    ...
```

**How it works:**
1. Reads `.env` file at startup
2. Environment variables override `.env` values
3. Validates types (str, int, bool)
4. Cached with `@lru_cache` — only parsed once

### 12.2 Key environment variables explained

| Variable | What it does |
|----------|-------------|
| `IBM_CLOUD_API_KEY` | Authenticates with IBM Cloud (gets IAM token) |
| `OPENSEARCH_URL` | Where to find the search engine |
| `OPENSEARCH_USERNAME/PASSWORD` | Credentials for OpenSearch |
| `WATSONX_PROJECT_ID` | Which watsonx.ai project to use |
| `WATSONX_EMBEDDING_MODEL_ID` | Which model to use for embeddings |
| `WATSONX_CHAT_MODEL_ID` | Which model to use for answer generation |
| `API_KEY_SECRET` | The key Orchestrate must send to authenticate |
| `ENABLE_RERANKER` | Feature flag — off by default |
| `RRF_K` | Tuning parameter for result fusion (default: 60) |

### 12.3 Why .env is never committed

The `.env` file contains secrets (API keys, passwords). If committed to git:
- Anyone with repo access sees your production credentials
- Credentials get cached in git history forever
- Automated scanners flag it as a security incident

`.gitignore` ensures `.env` is never committed. `.env.example` shows the structure without real values.

---

## 13. Security Decisions

| Decision | Why |
|----------|-----|
| `secrets.compare_digest()` for API key comparison | Prevents timing attacks — attacker can't guess the key character by character |
| API key in header, not URL | URLs get logged in proxies/load balancers; headers don't |
| Never log full questions/answers | Prevents PII leakage in log aggregators |
| Never hard-code secrets | Secrets rotate; code doesn't change every rotation |
| `verify_certs=False` in dev only | For local development; must be `True` in production |

---

## 14. Observability & Logging

### 14.1 Structured JSON logging

[`app/observability/logging.py`](app/observability/logging.py) outputs logs as JSON:

```json
{"event": "support_request_complete", "request_id": "abc-123", "status": "ANSWERED", "total_ms": 3200}
```

**Why JSON instead of plain text?**
- Machine-parseable: log aggregators (Elasticsearch, Splunk) can query/filter on any field
- Consistent format: every log has `event`, `request_id`, `trace_id`
- No regex needed to extract fields

### 14.2 What we DON'T log

- Full user questions (PII risk)
- Full chunk text (copyright, size)
- API keys or secrets
- Raw LLM prompts/responses in INFO mode

### 14.3 Trace IDs

Every request gets a `trace_id`. If something goes wrong, you can search all logs for that trace_id and see exactly what happened at each node. This is the `trace` field in `SupportState`.

---

## 15. Comparing Our Choices to Alternatives

### 15.1 Why LangGraph over raw code?

| Aspect | Raw Python | LangGraph |
|--------|-----------|-----------|
| State management | Manual dict passing | Built-in TypedDict state |
| Conditional flow | if/else spaghetti | Declared edges + routing functions |
| Debugging | print() and pray | Graph visualization + trace dict |
| Testing | Mock everything | Test nodes independently |
| Adding a new step | Refactor whole function | Add one node + one edge |

### 15.2 Why OpenSearch over a vector-only database?

| Aspect | Vector-only (Pinecone) | OpenSearch |
|--------|----------------------|-----------|
| Keyword search | ❌ Not supported | ✅ BM25 built-in |
| Semantic search | ✅ Core feature | ✅ kNN plugin |
| Metadata filtering | ⚠️ Basic | ✅ Full query DSL |
| Self-hosted | ❌ Cloud only | ✅ Deploy on OpenShift |
| Cost | 💰 Per-query pricing | Free (self-hosted) |

### 15.3 Why watsonx.ai over OpenAI?

| Aspect | OpenAI | watsonx.ai |
|--------|--------|-----------|
| IBM-approved | ❌ Third party | ✅ IBM product |
| Data governance | ⚠️ Data may leave org | ✅ Enterprise controls |
| Model choice | Limited to OpenAI models | IBM + open-source models |
| Audit trail | ⚠️ Limited | ✅ Full enterprise audit |
| This is an IBM project | ❌ | ✅ |

### 15.4 Why FastAPI over Flask?

| Aspect | Flask | FastAPI |
|--------|-------|---------|
| Request validation | Manual/extensions | Automatic (Pydantic) |
| OpenAPI docs | Manual/extensions | Auto-generated |
| Type safety | None | Full (type hints) |
| Async support | Bolt-on | Native |
| Performance | WSGI (synchronous) | ASGI (async) |

### 15.5 Why Pydantic over plain dicts?

```python
# With plain dicts — silent bugs
request = {"question": ""}  # empty question goes through silently

# With Pydantic — caught immediately
request = AssistRequest(question="")  # RAISES: field must be at least 3 chars
```

---

## 16. Key Design Principles

### 16.1 "Never invent answers" (Citation Grounding)

This is the #1 principle. The system MUST:
- Only use evidence from retrieved chunks
- Cite every factual claim with `[S#]` labels
- Return `INSUFFICIENT_EVIDENCE` rather than guess
- Reject citations that don't map to real evidence

**Why?** In enterprise technical support, a wrong answer can cause an outage. It's better to say "I don't know" than to hallucinate a fix that breaks a cluster.

### 16.2 "Every external client is injected"

```python
# Bad — tight coupling, untestable
def run(state):
    from app.providers.watsonx_chat import generate
    result = generate(prompt)

# Good — injectable, testable
def run(state, generate_fn=None):
    if generate_fn is None:
        from app.providers.watsonx_chat import generate as generate_fn
    result = generate_fn(prompt)
```

This pattern means:
- Unit tests don't need a real LLM or real OpenSearch
- You can swap implementations without touching node logic
- Integration tests can use real services, unit tests use mocks

### 16.3 "No god files" (~200 line limit)

Every module stays under ~200 lines. Why?
- Easier to understand (can read entire file in one screen)
- Easier to review in PRs
- Forces single-responsibility (one file = one job)
- Reduces merge conflicts between developers

### 16.4 "Config from environment, never code"

Anything that might differ between environments (dev, staging, production) lives in environment variables:
- Model IDs (might change per account)
- URLs (different clusters)
- Secrets (obviously)
- Feature flags (enable reranker only after testing)
- Tuning parameters (RRF k, top-k counts)

### 16.5 "LOCKED contracts"

Some files are marked "LOCKED CONTRACT":
- `app/api/schemas.py` — the API shape
- `app/graph/state.py` — the workflow state
- `config/taxonomy/ocp_sno.yaml` — the controlled vocabulary

These files are shared between Developer A and Developer B. Changing them requires a PR reviewed by both. This prevents one developer from breaking the other's code.

---

## 17. Glossary

| Term | Meaning |
|------|---------|
| **BM25** | A text-matching algorithm that scores documents by keyword relevance. "Best Match 25". |
| **kNN** | k-Nearest Neighbors — finds the k vectors closest to a query vector in embedding space. |
| **RRF** | Reciprocal Rank Fusion — algorithm to merge multiple ranked lists into one. |
| **Embedding** | A fixed-length vector (list of numbers) representing the meaning of a text. |
| **LLM** | Large Language Model — an AI model that generates text (e.g., GPT-4, Granite). |
| **RAG** | Retrieval-Augmented Generation — retrieve evidence first, then generate an answer from it. |
| **Chunk** | A fragment of a document (350–550 tokens) stored and retrieved independently. |
| **Citation grounding** | Requiring every factual claim to cite a specific source. |
| **Hybrid retrieval** | Combining keyword search (BM25) and semantic search (vectors) for better recall. |
| **Taxonomy** | A controlled vocabulary — only allowed values are accepted during ingestion. |
| **Idempotent** | Running the same operation twice has the same effect as running it once. |
| **State machine** | A system with defined states and transitions between them. |
| **Dependency injection** | Passing dependencies (services, clients) into a function instead of creating them inside. |
| **FastAPI** | A Python web framework for building REST APIs with automatic docs. |
| **Pydantic** | A Python library for data validation using type annotations. |
| **LangGraph** | A framework for building stateful AI workflows as graphs. |
| **OpenSearch** | An open-source search engine supporting keyword + vector search. |
| **watsonx.ai** | IBM's enterprise AI platform for running foundation models. |
| **Orchestrate** | IBM's enterprise chatbot/agent builder that calls our API as a "tool". |
| **COS** | IBM Cloud Object Storage — S3-compatible file storage. |
| **OCP** | OpenShift Container Platform — Red Hat's Kubernetes distribution. |
| **SNO** | Single Node OpenShift — OpenShift deployed on a single machine. |
| **IAM** | Identity and Access Management — IBM Cloud's auth system. |
| **POC** | Proof of Concept — a demo to validate an idea works. |
| **ASGI** | Asynchronous Server Gateway Interface — Python async web standard. |
| **TypedDict** | A Python type hint for dictionaries with known keys and value types. |
| **SHA-256** | A cryptographic hash function producing a unique fingerprint for any data. |
| **Constant-time comparison** | Comparing two strings in a way that takes the same time regardless of where they differ (security measure). |
| **Feature flag** | A config toggle that enables/disables a feature without deploying new code. |
| **OpenAPI** | A machine-readable specification format for REST APIs (JSON/YAML). |

---

## Quick Start for Development

```bash
# 1. Clone and setup
git clone https://github.com/Vaibhav-J20/it-help-desk.git
cd it-help-desk
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Fill in real values (get from team lead)

# 3. Run the server
uvicorn app.main:app --reload --port 8000

# 4. Test it
curl -X POST http://localhost:8000/v1/assist \
  -H "X-API-Key: your-secret-here" \
  -H "Content-Type: application/json" \
  -d '{"question": "How do I configure DNS for SNO?"}'

# 5. Run tests
pytest tests/
```

---

*This document was written to help interns understand the full system. If anything is unclear, ask — that's what mentors are for.*
