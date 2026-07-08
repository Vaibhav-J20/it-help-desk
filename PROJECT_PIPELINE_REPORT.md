# OpenShift & SNO Support Copilot — Complete Project Pipeline Report

This report explains the project from scratch. It is written for a student or intern who needs to understand what the system does, how the pieces connect, and what each important file is responsible for.

The project was mostly generated with AI assistance, so this document intentionally explains not only what the code is doing, but also why the pieces exist. You can use this as your personal study guide before presenting, debugging, or extending the project.

---

## 1. What This Project Is

This project is a backend service for a citation-grounded technical support copilot.

The target use case is:

> A user asks a question about Red Hat OpenShift Container Platform, especially Single Node OpenShift, and the system answers using only approved documentation. The answer must include citations to the source document and page numbers.

In simpler words:

1. A user asks: "How do I configure DNS for SNO installation on OCP 4.16?"
2. The system searches approved OpenShift/SNO documentation.
3. The system finds relevant document chunks.
4. The system gives those chunks to an IBM watsonx.ai language model.
5. The model writes an answer with source labels like `[S1]`.
6. The backend checks that those citations are valid.
7. The user receives the answer, citations, and a safety note.

The most important rule is:

> The system should not invent answers. If it cannot find enough evidence, it should return `INSUFFICIENT_EVIDENCE` instead of guessing.

---

## 2. The Big Picture

The intended production flow looks like this:

```text
User
  |
  v
IBM watsonx Orchestrate
  |
  | HTTPS POST /v1/assist
  v
FastAPI backend in this repo
  |
  v
LangGraph 7-node workflow
  |
  +--> watsonx.ai chat model for classification
  |
  +--> OpenSearch for document retrieval
  |
  +--> watsonx.ai embedding model for vector search
  |
  +--> watsonx.ai chat model for final answer generation
  |
  v
Citation validator
  |
  v
JSON API response back to Orchestrate
```

The backend has one main API endpoint:

```text
POST /v1/assist
```

There are also two health endpoints:

```text
GET /healthz
GET /readyz
```

`/healthz` checks whether the app process is alive.

`/readyz` checks whether important dependencies like OpenSearch and watsonx.ai embeddings can be reached.

---

## 3. The Main Technologies

### Python

The backend is written in Python. Python is commonly used for AI and backend projects because it has strong libraries for APIs, data processing, and language model integrations.

### FastAPI

FastAPI is the web framework. It receives HTTP requests, validates request bodies, and returns JSON responses.

In this project, FastAPI is responsible for:

- Creating the web server application.
- Defining `/v1/assist`.
- Defining `/healthz` and `/readyz`.
- Validating request and response schemas through Pydantic.
- Generating OpenAPI documentation automatically.

### Pydantic

Pydantic defines the shape of data. It checks that incoming requests contain the right fields and types.

For example, the user question must be between 3 and 2000 characters.

### LangGraph

LangGraph is used to build the internal workflow as a graph.

A graph is a controlled pipeline of steps. In this project, there are exactly seven major steps. The graph can exit early if the question is invalid, out of scope, ambiguous, or unsupported by evidence.

This is safer than an autonomous agent because the system does not decide randomly what tools to call. The path is bounded and predictable.

### OpenSearch

OpenSearch is the search database. It stores chunks of documentation and lets the system search them in two ways:

- BM25 keyword search.
- Vector similarity search.

The project combines both methods into hybrid retrieval.

### watsonx.ai

watsonx.ai is IBM's AI platform. The project uses it for:

- Embeddings: converting text into vectors for semantic search.
- Chat/generation: classifying questions and writing final answers.

Model IDs are read from environment variables. They are not hard-coded in the application code.

### IBM watsonx Orchestrate

Orchestrate is the expected user-facing chatbot/agent interface. This repo does not implement the Orchestrate UI. Instead, it exposes an OpenAPI-compatible backend that Orchestrate can import as a tool.

---

## 4. Important Vocabulary

### OCP

OpenShift Container Platform. It is Red Hat's Kubernetes-based platform.

### SNO

Single Node OpenShift. It is an OpenShift deployment where the cluster runs on one node.

### RAG

Retrieval-Augmented Generation.

This means the system retrieves evidence first, then asks a language model to answer using that evidence.

### Chunk

A chunk is a small piece of a document. Instead of searching or sending an entire PDF to the language model, the system stores and retrieves smaller sections.

### Citation grounding

Citation grounding means that the generated answer must be tied to source material. In this project, source labels look like `[S1]`, `[S2]`, and so on.

### BM25

BM25 is a classic keyword search ranking algorithm. It is good at finding exact words and technical terms.

### Vector search

Vector search finds text with similar meaning, even if exact words differ. It depends on embeddings.

### Embedding

An embedding is a list of numbers that represents the meaning of text. For this project, the embedding dimension is expected to be 768 by default.

### RRF

Reciprocal Rank Fusion. This algorithm combines two ranked search result lists, such as BM25 results and vector results.

---

## 5. Repository Structure

The actual tracked project files are organized like this:

```text
.
├── app/
│   ├── api/
│   ├── core/
│   ├── graph/
│   │   └── nodes/
│   ├── ingestion/
│   ├── observability/
│   ├── policy/
│   ├── prompts/
│   ├── providers/
│   ├── retrieval/
│   ├── services/
│   └── main.py
├── config/
│   ├── corpus/
│   ├── taxonomy/
│   └── domains.yaml
├── deployment/
├── openapi/
├── scripts/
├── tests/
├── Dockerfile
├── pyproject.toml
├── requirements.txt
└── documentation files
```

The most important folder is `app/`. That is where the runtime backend code lives.

The next most important folders are:

- `config/`: controlled values and corpus manifest.
- `scripts/`: utility scripts for setup and smoke testing.
- `tests/`: unit and integration tests.
- `openapi/`: OpenAPI YAML for Orchestrate/import tooling.
- `deployment/`: deployment instructions.

---

## 6. End-to-End Request Lifecycle

This section traces what happens when a user asks a question.

Suppose the user asks:

```text
How do I configure DNS for SNO installation on OCP 4.16?
```

The request body might look like:

```json
{
  "question": "How do I configure DNS for SNO installation on OCP 4.16?",
  "conversation_id": "test-session-001",
  "conversation_context": [],
  "requested_scope": {
    "ocp_version": "4.16",
    "deployment_type": "SNO"
  }
}
```

### Step 1: Orchestrate calls FastAPI

The request enters:

```text
app/api/routes.py
```

The route is:

```text
POST /v1/assist
```

Before the route handler runs, FastAPI validates the request body using `AssistRequest` from:

```text
app/api/schemas.py
```

The request must include:

- `question`: required.
- `conversation_id`: optional.
- `conversation_context`: optional.
- `requested_scope`: optional.

### Step 2: API key authentication

The request must contain this HTTP header:

```text
X-API-Key: <secret>
```

Authentication happens in:

```text
app/api/dependencies.py
```

The code compares the provided key to `API_KEY_SECRET` from environment settings.

It uses:

```python
secrets.compare_digest(...)
```

This is safer than `==` because it avoids timing attacks.

### Step 3: Assist service builds the initial graph state

After authentication, the route calls:

```text
app/services/assist_service.py
```

The main function is:

```python
handle_request(request)
```

This function creates:

- A `request_id`.
- A `trace_id`.
- An initial `SupportState` dictionary.

The initial state contains:

- The user question.
- Conversation context.
- Requested scope.
- Trace information.

Then it calls the compiled LangGraph workflow:

```python
support_graph.invoke(initial_state)
```

### Step 4: LangGraph runs the seven workflow nodes

The workflow is defined in:

```text
app/graph/workflow.py
```

The state type is defined in:

```text
app/graph/state.py
```

The graph nodes run in this order:

```text
input_guard
  ↓
classify_and_extract
  ↓
resolve_scope
  ↓
retrieve
  ↓
evidence_gate
  ↓
compose_answer
  ↓
validate_citations
```

The graph can stop early at several points.

For example:

- Bad question -> `INVALID_REQUEST`.
- Unsupported topic -> `OUT_OF_SCOPE`.
- Ambiguous question -> `NEEDS_CLARIFICATION`.
- No evidence -> `INSUFFICIENT_EVIDENCE`.
- Invalid citations -> `INSUFFICIENT_EVIDENCE`.

### Step 5: Response is mapped back to API schema

When the graph finishes, `assist_service.py` converts the final graph state into an `AssistResponse`.

The response includes:

- `request_id`
- `status`
- `intent`
- `answer_markdown`
- `clarification_question`
- `citations`
- `safety_note`
- `trace_id`

---

## 7. API Layer Files

### `app/main.py`

This file creates the FastAPI app.

Responsibilities:

- Calls `get_settings()` to load config.
- Creates the FastAPI application object.
- Includes the `/v1` API router.
- Defines `/healthz`.
- Defines `/readyz`.

Important endpoints:

```text
GET /healthz
```

Returns:

```json
{"status": "ok"}
```

This endpoint does not check external services. It only tells you the app is running.

```text
GET /readyz
```

Returns whether OpenSearch and watsonx embeddings are reachable.

Possible response:

```json
{
  "status": "ready",
  "opensearch": true,
  "watsonx": true
}
```

If either dependency fails, `status` becomes `degraded`.

### `app/api/routes.py`

This file defines the main API route:

```text
POST /v1/assist
```

It uses:

```python
Depends(verify_api_key)
```

That means the API key check must pass before the route logic runs.

Then it calls:

```python
handle_request(request)
```

from `app/services/assist_service.py`.

### `app/api/dependencies.py`

This file contains reusable FastAPI dependencies.

Right now, its main job is authentication.

The function:

```python
verify_api_key(...)
```

does three things:

1. Reads the configured secret from settings.
2. Rejects the request if the server has no API key configured.
3. Compares the incoming `X-API-Key` header to the configured secret.

Possible errors:

- If the server is missing `API_KEY_SECRET`, return HTTP 500.
- If the client key is wrong, return HTTP 401.

### `app/api/schemas.py`

This is one of the most important files.

It defines the API contract.

The file is marked as a locked contract. That means changing it can break other people or systems, such as Orchestrate or the ingestion/evaluation work.

Important classes:

#### `ConversationMessage`

Represents one prior message in the conversation.

Fields:

- `role`: either `"user"` or `"assistant"`.
- `content`: text content between 1 and 2000 characters.

#### `RequestedScope`

Represents optional scope hints from the caller.

Fields:

- `ocp_version`
- `deployment_type`
- `component`

Example:

```json
{
  "ocp_version": "4.16",
  "deployment_type": "SNO",
  "component": "dns"
}
```

#### `AssistRequest`

Represents the input body for `POST /v1/assist`.

Rules:

- `question` must be between 3 and 2000 characters.
- `conversation_context` can contain at most 4 messages.
- Total conversation context text must not exceed 4000 characters.
- `requested_scope` defaults to an empty `RequestedScope`.

#### `Citation`

Represents one citation returned to the user.

Fields:

- `citation_id`, such as `"S1"`.
- `title`.
- `product`.
- `ocp_version`.
- `page_start`.
- `page_end`.
- `section_path`.
- `document_id`.
- `chunk_id`.

#### `AssistResponse`

Represents the output body from `POST /v1/assist`.

Possible `status` values:

- `ANSWERED`
- `NEEDS_CLARIFICATION`
- `INSUFFICIENT_EVIDENCE`
- `OUT_OF_SCOPE`
- `INVALID_REQUEST`
- `ERROR`

The response always includes a safety note:

```text
Guidance is based only on the approved knowledge base; verify commands in your environment.
```

---

## 8. Configuration System

### `app/core/config.py`

This file defines the `Settings` class.

It uses `pydantic-settings` to read configuration from:

- Environment variables.
- `.env` file during local development.

The function:

```python
get_settings()
```

is decorated with:

```python
@lru_cache
```

That means settings are loaded once and reused.

Important settings:

#### IBM Cloud/watsonx

- `ibm_cloud_api_key`
- `watsonx_url`
- `watsonx_project_id`
- `watsonx_embedding_model_id`
- `watsonx_chat_model_id`
- `watsonx_rerank_model_id`

#### OpenSearch

- `opensearch_url`
- `opensearch_username`
- `opensearch_password`
- `opensearch_index_chunks`
- `opensearch_index_docs`

#### API security

- `api_key_secret`

#### Retrieval tuning

- `rrf_k`
- `retrieval_top_bm25`
- `retrieval_top_vector`
- `retrieval_top_candidates`
- `evidence_top_k`

#### Feature flags

- `enable_reranker`

The main design idea is:

> Things that change between environments should live in environment variables, not in code.

---

## 9. Service Layer

### `app/services/assist_service.py`

This file connects the API layer to the graph layer.

It is the bridge between:

```text
FastAPI request/response models
```

and:

```text
LangGraph SupportState
```

Main function:

```python
handle_request(request: AssistRequest) -> AssistResponse
```

Detailed flow:

1. Generate `request_id`.
2. Generate `trace_id`.
3. Convert request into an initial `SupportState`.
4. Invoke the graph.
5. Catch graph errors and return `ERROR` if something crashes.
6. Log a structured request-complete event.
7. Convert final state into an `AssistResponse`.

Helper functions:

#### `_scope_to_dict`

Converts the Pydantic `requested_scope` object into a normal Python dictionary.

#### `_state_to_response`

Converts the final graph state back into the Pydantic response model.

---

## 10. Graph State

### `app/graph/state.py`

This file defines:

```python
class SupportState(TypedDict, total=False)
```

This is the shared dictionary passed through all graph nodes.

Think of it as the workflow's memory.

At the beginning, it contains only request information. As each node runs, more fields are added.

Important fields:

#### Request fields

- `request_id`
- `user_question`
- `conversation_context`

#### Classification fields

- `intent`
- `extracted_scope`
- `required_clarification`

#### Retrieval fields

- `retrieval_query`
- `retrieval_filters`
- `candidates`

#### Evidence fields

- `evidence_decision`

#### Answer fields

- `answer_markdown`
- `citations`

#### Final status

- `status`

#### Observability

- `trace`

The graph state file is a locked contract. If this changes, many nodes and tests may need updates.

---

## 11. Graph Workflow

### `app/graph/workflow.py`

This file wires the nodes together using LangGraph.

The graph is built by:

```python
build_graph()
```

At the end of the file, the graph is compiled once:

```python
support_graph = build_graph()
```

That compiled graph is imported by `assist_service.py`.

### Conditional routing

The graph has conditional edges.

That means after some nodes, the graph checks the state and decides whether to continue or stop.

#### After `input_guard`

If status is `INVALID_REQUEST`, stop.

Otherwise, continue to classification.

#### After `resolve_scope`

If status is `OUT_OF_SCOPE`, stop.

If status is `NEEDS_CLARIFICATION`, stop.

Otherwise, continue to retrieval.

#### After `evidence_gate`

If status is `INSUFFICIENT_EVIDENCE`, stop.

Otherwise, continue to answer generation.

#### After `validate_citations`

The graph always stops after citation validation.

---

## 12. Graph Node 1: Input Guard

### `app/graph/nodes/input_guard.py`

Purpose:

> Validate and normalize the user input before expensive AI/search work happens.

This node does not call watsonx or OpenSearch.

What it checks:

1. The question exists.
2. The question is at least 3 characters.
3. The question is not more than 2000 characters.
4. Whitespace is normalized.
5. Empty conversation messages are removed.
6. A request ID exists.

Example whitespace normalization:

```text
"  How  do  I  install  SNO?  "
```

becomes:

```text
"How do I install SNO?"
```

If invalid:

```python
status = "INVALID_REQUEST"
```

---

## 13. Graph Node 2: Classify and Extract

### `app/graph/nodes/classify_extract.py`

Purpose:

> Ask the language model what kind of question this is and extract scope hints.

This node uses the prompt:

```text
app/prompts/classify_extract.md
```

The model should return JSON with:

- `intent`
- `ocp_version`
- `deployment_type`
- `component`
- `needs_clarification`
- `clarification_question`

Allowed intents:

- `qa`
- `troubleshoot`
- `summarize`
- `unsupported`

Example classification result:

```json
{
  "intent": "troubleshoot",
  "ocp_version": "4.16",
  "deployment_type": "SNO",
  "component": "dns",
  "needs_clarification": false,
  "clarification_question": null
}
```

### Explicit scope wins

If the API request provided `requested_scope`, those explicit values override values inferred by the model.

For example, if the model guesses `4.15`, but the API request explicitly says `4.16`, then `4.16` wins.

This is important because explicit user-provided information should be trusted more than model inference.

### Failure fallback

If classification fails, the node uses safe defaults:

- intent: `qa`
- no version
- no deployment type
- no component
- no clarification required

This prevents one model-formatting mistake from crashing the whole app.

---

## 14. Graph Node 3: Resolve Scope

### `app/graph/nodes/resolve_scope.py`

Purpose:

> Decide whether the question can proceed to retrieval.

This node handles:

- Unsupported topics.
- Clarification requests.
- Retrieval query construction.
- Retrieval filter construction.

If `intent == "unsupported"`, it sets:

```python
status = "OUT_OF_SCOPE"
```

If `required_clarification` exists, it sets:

```python
status = "NEEDS_CLARIFICATION"
```

Otherwise, it prepares retrieval.

The retrieval query is currently the original user question:

```python
retrieval_query = state["user_question"]
```

It also adds the supported domain:

```python
domain_id = "ocp_sno_support"
```

Then it calls:

```python
build_filters(extracted_scope)
```

from:

```text
app/retrieval/filters.py
```

---

## 15. Graph Node 4: Retrieve

### `app/graph/nodes/retrieve.py`

Purpose:

> Run hybrid retrieval against OpenSearch.

This node does the searching.

It can receive injected dependencies for testing:

- `opensearch_client`
- `embedding_fn`

If those are not provided, it uses the real implementations:

- `get_opensearch_client()`
- `embed_text()`

Then it calls:

```python
hybrid_retrieve(query, filters, opensearch_client, embedding_fn)
```

from:

```text
app/retrieval/hybrid_retriever.py
```

### Retry with relaxed filters

If strict retrieval returns no candidates, the node retries once with relaxed inferred filters.

The current inferred fields list is:

```python
["component", "domain_id"]
```

Important detail:

The relaxation function checks actual OpenSearch filter field names. A component filter becomes `components`, not `component`. This is something to be aware of if debugging filter relaxation behavior.

---

## 16. Graph Node 5: Evidence Gate

### `app/graph/nodes/evidence_gate.py`

Purpose:

> Decide whether the retrieved chunks are good enough to let the model write an answer.

This is a safety checkpoint.

It calls:

```python
is_evidence_sufficient(candidates, requested_version)
```

from:

```text
app/policy/evidence_policy.py
```

If no candidates exist:

```python
status = "INSUFFICIENT_EVIDENCE"
```

If the user requested a version and candidates do not match that version:

```python
status = "INSUFFICIENT_EVIDENCE"
```

If evidence is sufficient, it keeps only the top candidates.

The number of candidates is controlled by:

```python
settings.evidence_top_k
```

Default:

```text
6
```

---

## 17. Graph Node 6: Compose Answer

### `app/graph/nodes/compose_answer.py`

Purpose:

> Build a grounded prompt and ask watsonx.ai to generate the final answer.

This node only runs after evidence is considered sufficient.

It reads the prompt:

```text
app/prompts/grounded_answer.md
```

It formats evidence blocks like:

```text
[S1] Single Node OpenShift Installation Guide — OCP 4.16, pp. 12–13
<chunk text>
```

Then it fills the prompt with:

- The user question.
- The evidence blocks.

Then it calls the watsonx chat generation function:

```python
generate(prompt)
```

The result becomes:

```python
state["answer_markdown"]
```

Important rule:

This node trusts the language model to follow the prompt, but the next node checks whether the citations are valid.

---

## 18. Graph Node 7: Validate Citations

### `app/graph/nodes/validate_citations.py`

Purpose:

> Check that every `[S#]` citation in the generated answer maps to a real retrieved chunk.

This node uses a regular expression:

```python
\[S(\d+)\]
```

It finds citation labels like:

- `[S1]`
- `[S2]`
- `[S10]`

Then it checks whether each cited number is within the available evidence range.

For example, if there are only 3 candidates:

- `[S1]` is valid.
- `[S2]` is valid.
- `[S3]` is valid.
- `[S4]` is invalid.

If invalid citations exist:

```python
status = "INSUFFICIENT_EVIDENCE"
```

If citations are valid, it builds citation objects from the corresponding candidates and sets:

```python
status = "ANSWERED"
```

### Current caveat

The current implementation allows an answer with no citations at all to become `ANSWERED` with an empty citations list.

This behavior is also encoded in the current tests.

However, the project principle says every factual answer should be citation-grounded. So a future improvement may be:

> If the generated answer contains no `[S#]` citations, reject it as `INSUFFICIENT_EVIDENCE`.

That would require changing both the implementation and tests.

---

## 19. Retrieval System

The retrieval code lives in:

```text
app/retrieval/
```

Retrieval is how the system finds relevant document chunks before generating an answer.

---

## 20. OpenSearch Client

### `app/retrieval/opensearch_client.py`

Purpose:

> Create and cache an OpenSearch client.

Main function:

```python
get_opensearch_client()
```

It reads:

- `OPENSEARCH_URL`
- `OPENSEARCH_USERNAME`
- `OPENSEARCH_PASSWORD`

from settings.

It parses the URL into:

- host
- port
- whether SSL should be used

Then it creates an `OpenSearch` client.

Important current setting:

```python
verify_certs=False
```

This is acceptable for local development or quick demos, but production should use real certificates and set certificate verification correctly.

The file also defines:

```python
ping_opensearch()
```

which returns `True` or `False`.

This is used by `/readyz` and integration test skip checks.

---

## 21. Filter Builder

### `app/retrieval/filters.py`

Purpose:

> Convert extracted scope into OpenSearch filter clauses.

Input example:

```python
{
    "ocp_version": "4.16",
    "deployment_type": "SNO",
    "domain_id": "ocp_sno_support",
    "component": "dns"
}
```

Output example:

```python
[
    {"term": {"ocp_version": "4.16"}},
    {"term": {"deployment_type": "SNO"}},
    {"term": {"domain_id": "ocp_sno_support"}},
    {"term": {"components": "dns"}},
    {"term": {"is_current": True}}
]
```

Notice:

`component` becomes an OpenSearch filter on `components`, because indexed chunks store components as an array field.

The filter builder always adds:

```python
{"term": {"is_current": True}}
```

unless explicitly overridden.

This prevents old/superseded document versions from being used.

### `relax_inferred_filters`

This function removes filters that are considered inferred and safe to relax.

It is used when strict retrieval returns no results.

---

## 22. Hybrid Retriever

### `app/retrieval/hybrid_retriever.py`

Purpose:

> Run BM25 search, run vector search, combine results with RRF, and return the top candidates.

Main function:

```python
hybrid_retrieve(query, filters, opensearch_client, embedding_fn)
```

Detailed flow:

1. Read retrieval settings.
2. Run BM25 keyword search.
3. Generate an embedding for the query.
4. Run vector kNN search.
5. Merge both result lists using RRF.
6. Keep only the top configured number of candidates.

Default retrieval sizes:

- BM25 top 20.
- Vector top 20.
- Final candidates top 12.

### BM25 search

BM25 query searches:

```text
chunk_text
```

using the user's question.

The query also applies filters.

### Vector search

Vector search uses:

```text
chunk_text_vector
```

It first converts the user question into a vector using the embedding model. Then it asks OpenSearch for the nearest chunk vectors.

### Source exclusion

Both searches exclude:

```text
chunk_text_vector
```

from the returned source.

This is good because vectors are large and not needed for answer generation.

---

## 23. RRF Fusion

### `app/retrieval/fusion.py`

Purpose:

> Merge BM25 and vector search rankings.

Main function:

```python
reciprocal_rank_fusion(...)
```

The formula is:

```text
score = sum(1 / (k + rank))
```

where:

- `rank` is the item's position in a search result list.
- `k` is usually 60.

Why this helps:

- A document found by both BM25 and vector search gets boosted.
- A document ranked very high in one list still matters.
- The algorithm is simple and testable.

The function adds metadata to each returned chunk:

- `_rrf_score`
- `_sources`

Example:

```json
{
  "chunk_id": "example",
  "_rrf_score": 0.032522,
  "_sources": ["bm25", "vector"]
}
```

---

## 24. Policy Layer

The policy layer contains business rules that should not require external I/O.

---

## 25. Evidence Policy

### `app/policy/evidence_policy.py`

Purpose:

> Decide whether retrieved chunks are good enough.

Main function:

```python
is_evidence_sufficient(candidates, requested_version)
```

Rules:

1. If there are no candidates, evidence is insufficient.
2. If the user requested a version, at least some candidates must match that version.
3. If version-matched candidates exist, the candidate list is narrowed to only those matches.
4. At least one candidate must remain.

Return value:

```python
(sufficient: bool, reason: str)
```

Examples of reasons:

- `"no_candidates"`
- `"version_mismatch"`
- `"below_threshold"`
- `"sufficient"`

---

## 26. Domain Policy

### `app/policy/domain_policy.py`

Purpose:

> Load the domain registry and check whether a domain is active.

It reads:

```text
config/domains.yaml
```

Main functions:

- `load_domains()`
- `is_in_scope(domain_id)`

Important note:

`resolve_scope.py` imports `is_in_scope`, but the current `run()` implementation does not actually call it. Instead, out-of-scope behavior is based on the classification intent being `"unsupported"`.

That means the model's classification currently controls whether a question is considered out of scope.

---

## 27. Provider Layer

Providers are wrappers around external AI services.

They live in:

```text
app/providers/
```

---

## 28. watsonx Embeddings

### `app/providers/watsonx_embeddings.py`

Purpose:

> Convert text into embedding vectors using watsonx.ai.

Important functions:

```python
embed_text(text: str) -> list[float]
```

Embeds one text string.

```python
embed_texts(texts: list[str]) -> list[list[float]]
```

Embeds multiple texts. This is intended for ingestion.

```python
ping_watsonx_embeddings() -> bool
```

Checks whether the embedding client can be initialized.

The embedding model ID comes from:

```text
WATSONX_EMBEDDING_MODEL_ID
```

Important rule:

> The model ID must be configured through the environment, not hard-coded.

---

## 29. watsonx Chat

### `app/providers/watsonx_chat.py`

Purpose:

> Generate text using a watsonx.ai chat/generation model.

Main function:

```python
generate(prompt: str) -> str
```

It sends a single user message containing the full prompt to the model.

Generation parameters:

```python
{
    "max_tokens": 1024,
    "temperature": 0.0
}
```

`temperature = 0.0` means the model should behave more deterministically and less creatively.

The chat model ID comes from:

```text
WATSONX_CHAT_MODEL_ID
```

---

## 30. watsonx Rerank

### `app/providers/watsonx_rerank.py`

Purpose:

> Placeholder for future reranking.

Current behavior:

- If `ENABLE_RERANKER=false`, it returns the original candidates capped to `top_k`.
- If `ENABLE_RERANKER=true` but no rerank model is configured, it logs and skips.
- If `ENABLE_RERANKER=true` and a rerank model exists, it raises `NotImplementedError`.

So right now, reranking is not implemented.

Keep:

```text
ENABLE_RERANKER=false
```

unless reranking is built later.

---

## 31. Prompt Files

Prompt files are plain Markdown text files used to instruct the language model.

---

## 32. Classification Prompt

### `app/prompts/classify_extract.md`

Purpose:

> Tell the model how to classify a user question and extract scope.

It tells the model to output only JSON.

It asks for:

- intent
- OCP version
- deployment type
- component
- whether clarification is needed
- clarification question

The code replaces:

```text
{question}
```

with the actual user question.

---

## 33. Grounded Answer Prompt

### `app/prompts/grounded_answer.md`

Purpose:

> Tell the model how to answer using only evidence blocks.

Important rules in the prompt:

- Use only supplied evidence.
- Cite every factual statement.
- Do not invent behavior, commands, versions, URLs, or citations.
- If evidence is incomplete, say what is missing.
- For troubleshooting, use numbered diagnostic steps.
- Do not claim live cluster access.
- End with a `### Sources` section.

The code replaces:

```text
{question}
```

and:

```text
{evidence_blocks}
```

with runtime values.

---

## 34. Observability and Logging

### `app/observability/logging.py`

Purpose:

> Provide structured JSON logging.

Main functions/classes:

- `get_logger(name)`
- `log_request_event(...)`
- `_JsonFormatter`

The logger outputs JSON logs.

This is useful because logs can be searched and filtered by fields like:

- `event`
- `request_id`
- `trace_id`
- `status`
- `intent`
- `candidate_count`
- `total_ms`

Important privacy/security rule:

Normal logs should not include:

- Full user questions.
- Full document chunks.
- Full prompts.
- Raw answers.
- Secrets.

---

## 35. Ingestion Folder

### `app/ingestion/__init__.py`

Current status:

> The ingestion pipeline is not implemented in this checkout.

The planning docs describe future files such as:

- `run.py`
- `cos_source.py`
- `pdf_parser.py`
- `chunker.py`
- `metadata.py`
- `indexer.py`

But currently only `__init__.py` exists.

That means this repo currently focuses on Developer A's API/retrieval/graph side. The pipeline that reads PDFs, chunks them, embeds them, and writes to OpenSearch is still planned or belongs to a separate branch/workstream.

---

## 36. Configuration Files

---

## 37. Domain Registry

### `config/domains.yaml`

Purpose:

> Define supported knowledge domains.

Current domain:

```yaml
ocp_sno_support:
  label: "OpenShift & SNO Technical Support"
  active: true
```

This says the project supports the `ocp_sno_support` domain.

---

## 38. Taxonomy

### `config/taxonomy/ocp_sno.yaml`

Purpose:

> Define controlled vocabulary for document metadata.

This file is a locked contract.

Allowed products:

- `OpenShift`
- `RHCOS`

Allowed OCP versions:

- `4.14`
- `4.15`
- `4.16`
- `4.17`

Allowed deployment types:

- `SNO`
- `standard`
- `compact`

Allowed document types:

- `installation_guide`
- `troubleshooting_runbook`
- `configuration_guide`
- `release_notes`
- `reference_manual`

Allowed components:

- `bootstrap`
- `dns`
- `networking`
- `ingress`
- `storage`
- `etcd`
- `api_server`
- `authentication`
- `monitoring`
- `operators`

Allowed classifications:

- `internal`
- `public`

Why this matters:

Search filters only work reliably if metadata values are consistent. For example, if one chunk says `"dns"` and another says `"DNS"` and another says `"name_resolution"`, filtering becomes unreliable.

The taxonomy prevents that.

---

## 39. Corpus Manifest

### `config/corpus/ocp_sno_poc.yaml`

Purpose:

> List approved source documents for the POC corpus.

Current status:

```yaml
sources: []
```

There are no real corpus sources currently listed.

The file includes a commented example showing what a real source entry should look like.

This is important because the backend can only retrieve answers from OpenSearch if documents have already been ingested and indexed.

With an empty corpus manifest and no ingestion pipeline implemented, real production-quality answers depend on data being manually indexed or provided by another branch/process.

---

## 40. OpenSearch Data Model

The main index is:

```text
knowledge_chunks_v1
```

This index stores searchable document chunks.

Each chunk should include fields such as:

- `chunk_id`
- `document_id`
- `revision_id`
- `domain_id`
- `title`
- `source_uri`
- `source_type`
- `document_type`
- `classification`
- `access_scope`
- `product`
- `ocp_version`
- `ocp_major`
- `ocp_minor`
- `deployment_type`
- `components`
- `section_path`
- `page_start`
- `page_end`
- `chunk_ordinal`
- `chunk_text`
- `chunk_text_vector`
- `content_hash`
- `parser_version`
- `chunker_version`
- `embedding_model_id`
- `embedding_dimension`
- timestamps
- `is_current`

The second index is:

```text
knowledge_documents_v1
```

This stores document-level registry information, such as:

- document ID
- revision ID
- source URI
- title
- content hash
- ingestion status
- chunk count
- errors
- ingestion timestamp

---

## 41. Scripts

---

## 42. Create Index Script

### `scripts/create_index.py`

Purpose:

> Create the OpenSearch indices needed by the project.

Usage:

```bash
python scripts/create_index.py
```

or:

```bash
python scripts/create_index.py --recreate
```

The `--recreate` flag deletes existing indices first.

Be careful with `--recreate` because it can remove indexed data.

The script defines mappings for:

- `knowledge_chunks_v1`
- `knowledge_documents_v1`

Important mapping details:

- `chunk_text` is a text field with English analyzer for BM25.
- `chunk_text_vector` is a `knn_vector`.
- metadata fields are mostly `keyword` fields.
- page fields are integers.
- `is_current` is boolean.

Embedding dimension is read from:

```text
OPENSEARCH_EMBEDDING_DIM
```

Default:

```text
768
```

---

## 43. Smoke Test Script

### `scripts/smoke_test.py`

Purpose:

> Prove the retrieval path works end to end with one fixture chunk.

It does the following:

1. Embeds a test query.
2. Creates a temporary smoke test OpenSearch index.
3. Loads `tests/fixtures/sample_chunk.json`.
4. Embeds the fixture chunk.
5. Indexes the chunk.
6. Runs BM25 retrieval.
7. Runs vector kNN retrieval.
8. Runs hybrid RRF retrieval.
9. Deletes the smoke test index.

Requirements:

- OpenSearch running.
- watsonx.ai credentials set.

Usage:

```bash
python scripts/smoke_test.py
```

---

## 44. Environment Validation Script

### `scripts/validate_env.py`

Purpose:

> Check whether important environment variables are set.

Usage:

```bash
python scripts/validate_env.py
```

It checks required variables such as:

- `IBM_CLOUD_API_KEY`
- `OPENSEARCH_URL`
- `OPENSEARCH_INDEX_CHUNKS`
- `OPENSEARCH_INDEX_DOCS`
- `WATSONX_URL`
- `WATSONX_PROJECT_ID`
- `WATSONX_EMBEDDING_MODEL_ID`
- `WATSONX_CHAT_MODEL_ID`
- `API_KEY_SECRET`

It also reports optional variables like COS and rerank settings.

---

## 45. Docker and Deployment

---

## 46. Dockerfile

### `Dockerfile`

Purpose:

> Build a container image for the FastAPI backend.

Steps:

1. Start from `python:3.11-slim`.
2. Set working directory to `/app`.
3. Copy `requirements.txt`.
4. Install Python dependencies.
5. Copy `app/`.
6. Copy `config/`.
7. Create a non-root user.
8. Expose port 8080.
9. Run Uvicorn.

Final command:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

Why non-root user matters:

Running containers as non-root is safer. If someone exploits the app, they get fewer permissions inside the container.

---

## 47. Code Engine Deployment Guide

### `deployment/CODE_ENGINE_DEPLOY.md`

Purpose:

> Explain how to deploy the FastAPI app to IBM Code Engine.

The guide covers:

1. Logging into IBM Cloud.
2. Setting up IBM Container Registry.
3. Building and pushing Docker image.
4. Creating a Code Engine project.
5. Creating a registry secret.
6. Deploying the app with environment variables.
7. Exposing local OpenSearch for a demo.
8. Getting the public app URL.
9. Updating the app after code changes.

Important note:

Some planning docs mention OpenShift manifests under `deployment/openshift/`, but those files are not present in the current checkout. The deployment file that actually exists is the Code Engine guide.

---

## 48. OpenAPI Specification

### `openapi/it_helpdesk_v1.yaml`

Purpose:

> Provide an OpenAPI description of the backend API.

This is useful for:

- watsonx Orchestrate tool import.
- API documentation.
- Showing request/response examples.

It defines:

- `POST /v1/assist`
- `GET /healthz`
- `GET /readyz`
- API key security scheme
- request schemas
- response schemas
- example responses

Important operation ID:

```text
query_ocp_sno_knowledge
```

This is the tool-like name Orchestrate can use when importing the API.

---

## 49. Tests

The test suite lives in:

```text
tests/
```

It has:

- unit tests
- integration tests
- fixtures

Current local result:

```text
49 passed, 11 skipped
```

The skipped tests require live OpenSearch and/or watsonx.ai.

---

## 50. Unit Tests

### `tests/unit/test_schemas.py`

Tests Pydantic API schemas.

It checks:

- valid requests.
- too-short questions.
- too-long questions.
- conversation context length.
- requested scope validation.
- response defaults.
- citation model.

### `tests/unit/test_filters.py`

Tests OpenSearch filter construction.

It checks:

- empty scope still adds `is_current`.
- version filters.
- deployment type filters.
- domain filters.
- component-to-components mapping.
- relaxing inferred filters.

### `tests/unit/test_fusion.py`

Tests RRF fusion.

It checks:

- single-list ordering.
- overlap boosting.
- no-overlap merging.
- empty input behavior.
- RRF score creation.
- source tracking.

### `tests/unit/test_nodes.py`

Tests individual graph nodes:

- input guard.
- evidence gate.
- citation validation.

It checks:

- valid input.
- invalid input.
- whitespace normalization.
- evidence sufficiency.
- version mismatch.
- valid citations.
- invalid citations.
- no-citation current behavior.

### `tests/unit/test_graph_workflow.py`

Tests the full graph with mocked providers.

It proves the graph can return:

- `ANSWERED`
- `INSUFFICIENT_EVIDENCE`
- `OUT_OF_SCOPE`
- `NEEDS_CLARIFICATION`
- `INVALID_REQUEST`

It uses fake OpenSearch and fake model functions, so no real external services are needed.

---

## 51. Integration Tests

### `tests/integration/test_opensearch.py`

Tests real OpenSearch behavior.

It is skipped automatically if OpenSearch is not reachable.

It checks:

- test index creation.
- BM25 retrieval.
- OCP version filtering.
- wrong-version filtering.
- deployment type filtering.
- `is_current` filtering.
- page field round-trip.
- chunk text retrieval.

### `tests/integration/test_vector_retrieval.py`

Tests real vector retrieval and hybrid retrieval.

It requires:

- OpenSearch.
- watsonx.ai credentials.

It checks:

- vector search returns the expected chunk.
- hybrid RRF returns the expected chunk.
- RRF score is positive.

---

## 52. Fixtures

### `tests/fixtures/sample_chunk.json`

This is a sample chunk representing a piece of SNO installation documentation.

It includes:

- metadata
- page numbers
- chunk text
- empty vector placeholder
- content hash
- current revision flag

The text is about DNS records required before SNO bootstrap.

This fixture is used by integration tests and the smoke test.

### `tests/fixtures/sample_request.json`

This is a sample `/v1/assist` request.

It asks:

```text
How do I configure DNS for SNO installation on OCP 4.16?
```

with requested scope:

```json
{
  "ocp_version": "4.16",
  "deployment_type": "SNO"
}
```

---

## 53. Project Metadata Files

---

## 54. Requirements

### `requirements.txt`

Purpose:

> Pin Python dependencies.

Major dependencies:

- `fastapi`
- `uvicorn`
- `pydantic`
- `pydantic-settings`
- `python-dotenv`
- `opensearch-py`
- `ibm-watsonx-ai`
- `langgraph`
- `langchain-core`
- `pdfminer.six`
- `pyyaml`
- `httpx`
- `structlog`
- `pytest`
- `pytest-asyncio`

The `pdfminer.six` dependency is for the planned ingestion pipeline.

### `pyproject.toml`

Purpose:

> Store project metadata and tool settings.

It declares:

- project name
- version
- description
- Python requirement
- pytest settings
- Ruff settings

Important:

```toml
requires-python = ">=3.11"
```

Local note:

The existing `.venv` reported Python 3.14.6 when tests were run. The Dockerfile uses Python 3.11, which better matches the project declaration.

### `.env.example`

Purpose:

> Show which environment variables are needed without committing secrets.

You copy it to `.env` locally, then fill in real values.

Never commit `.env`.

### `.gitignore`

Purpose:

> Prevent secrets, virtual environments, caches, logs, and data artifacts from being committed.

Important ignored items:

- `.env`
- `.venv/`
- `__pycache__/`
- `.pytest_cache/`
- `data/artifacts/`
- `data/corpus/`
- `opensearch-data/`

---

## 55. Existing Documentation Files

### `EXPLAINER.md`

This is an intern-friendly explanation of the project architecture and sprint progress.

It covers:

- project purpose
- technology choices
- request flow
- architecture
- retrieval
- ingestion plan
- security
- observability

### `RESTART-GUIDE.md`

This describes the V3 restart plan and branch cleanup process.

It explains how the project moved away from a previous Watson Discovery architecture.

### `SESSION-LOG-V3.md`

This records project history, architecture reset notes, branch ownership, and locked contracts.

### `DEVELOPER-A-PROMPT.md`

This is a long prompt intended for Developer A sessions. Developer A owns:

- FastAPI backend.
- LangGraph workflow.
- retrieval.
- watsonx providers.
- deployment.

### `DEVELOPER-B-PROMPT.md`

This is a long prompt intended for Developer B sessions. Developer B owns:

- corpus selection.
- taxonomy.
- ingestion pipeline.
- PDF parsing.
- chunking.
- metadata validation.
- OpenSearch indexing.
- evaluation dataset.
- Orchestrate setup.

---

## 56. Status Values Explained

The backend does not only return success or failure. It returns specific statuses.

### `ANSWERED`

The system found evidence, generated an answer, and citation validation passed.

### `NEEDS_CLARIFICATION`

The system thinks the question is too vague.

Example:

```text
My cluster installation failed.
```

The system may ask:

```text
Which OCP version and deployment type are you using?
```

### `INSUFFICIENT_EVIDENCE`

The system could not find enough valid evidence.

This can happen when:

- OpenSearch returns no results.
- Results do not match the requested version.
- The generated answer cites an invalid source label.

### `OUT_OF_SCOPE`

The question is not about supported OpenShift/SNO topics.

Example:

```text
How do I configure ServiceNow integration?
```

### `INVALID_REQUEST`

The input is malformed or fails validation.

Example:

- Empty question.
- Too-short question.
- Too-long question.

### `ERROR`

Something unexpected crashed during graph execution.

---

## 57. How the System Avoids Hallucinations

The project tries to avoid hallucinations through several layers:

### Layer 1: Scope classification

Unsupported topics can be rejected early.

### Layer 2: Metadata filters

Search is limited by version, deployment type, domain, component, and current revision.

### Layer 3: Evidence gate

If no candidates or wrong-version candidates are found, the answer generation step is skipped.

### Layer 4: Grounded prompt

The answer prompt tells the model to use only the provided evidence.

### Layer 5: Citation validation

The generated answer is checked for invalid citation labels.

### Current weakness

The system currently does not reject answers with zero citations. That should be considered a future hardening task if strict citation grounding is required.

---

## 58. How to Run Locally

### Create and activate a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate
```

### Install dependencies

```bash
pip install -r requirements.txt
```

### Configure environment

```bash
cp .env.example .env
```

Then fill in real values.

### Validate environment

```bash
python scripts/validate_env.py
```

### Run the API

```bash
uvicorn app.main:app --reload --port 8000
```

### Test health endpoint

```bash
curl http://localhost:8000/healthz
```

Expected:

```json
{"status": "ok"}
```

### Call the assist endpoint

```bash
curl -X POST http://localhost:8000/v1/assist \
  -H "X-API-Key: your-secret-here" \
  -H "Content-Type: application/json" \
  -d '{"question": "How do I configure DNS for SNO on OCP 4.16?", "requested_scope": {"ocp_version": "4.16", "deployment_type": "SNO"}}'
```

This requires:

- API key configured.
- watsonx credentials.
- OpenSearch running.
- indexed chunks available.

---

## 59. How to Run Tests

The local command that worked was:

```bash
.venv/bin/pytest
```

If your virtual environment is active, this should also work:

```bash
pytest
```

Expected current behavior:

- Unit tests pass.
- Integration tests skip if OpenSearch/watsonx are not available.

---

## 60. How to Create OpenSearch Indices

With OpenSearch reachable and environment configured:

```bash
python scripts/create_index.py
```

To recreate indices:

```bash
python scripts/create_index.py --recreate
```

Be careful:

`--recreate` deletes existing indices.

---

## 61. How to Prove Retrieval Works

Use:

```bash
python scripts/smoke_test.py
```

This requires:

- OpenSearch.
- watsonx embeddings.

The smoke test creates a temporary index, inserts one sample chunk, tests BM25, vector search, and hybrid RRF, then deletes the temporary index.

---

## 62. Current Project Gaps

These are important to understand before presenting the project as complete.

### 1. Ingestion pipeline is not implemented

The docs describe PDF parsing, chunking, metadata validation, embedding, and indexing. But the actual files are not present yet.

### 2. Corpus manifest is empty

`config/corpus/ocp_sno_poc.yaml` has:

```yaml
sources: []
```

So no real approved PDF list is currently committed.

### 3. No OpenShift manifests are present

Some docs reference `deployment/openshift/`, but that folder has no manifests in the current checkout.

The existing deployment guide is for IBM Code Engine.

### 4. Reranker is not implemented

The rerank provider is a placeholder.

### 5. Citation validator allows no-citation answers

This is a safety gap relative to the strict project goal.

### 6. Domain policy is not actively used by scope resolution

`resolve_scope.py` imports `is_in_scope`, but currently relies on LLM intent for out-of-scope detection.

### 7. Integration tests require external services

OpenSearch and watsonx.ai are needed to run all tests.

---

## 63. A Beginner-Friendly Mental Model

If you are explaining this in an interview or internship review, say:

> This is a FastAPI backend that exposes one support endpoint. When a user asks a question, the backend sends it through a controlled LangGraph workflow. The workflow validates the input, classifies the question, builds filters, retrieves relevant chunks from OpenSearch using both keyword and vector search, checks whether the evidence is strong enough, asks watsonx.ai to write a grounded answer, validates the citation labels, and returns a structured response to Orchestrate.

Then explain:

> The project is designed to avoid hallucinations by refusing to answer when it cannot retrieve enough evidence.

Then add:

> The current implementation covers the API, graph, retrieval, provider wrappers, tests, Docker, and OpenAPI specification. The ingestion pipeline and real corpus population are still the major remaining pieces.

---

## 64. How to Debug Common Issues

### API returns 401

Likely cause:

- Missing or wrong `X-API-Key` header.

Check:

- `.env` has `API_KEY_SECRET`.
- curl request includes the same value.

### API returns 422

Likely cause:

- Request body does not match schema.

Check:

- `question` exists.
- `question` length is at least 3.
- `deployment_type` is one of `SNO`, `standard`, `compact`.

### `/readyz` returns degraded

Likely cause:

- OpenSearch not reachable.
- watsonx credentials missing.
- embedding model ID missing.

Check:

```bash
python scripts/validate_env.py
```

### `INSUFFICIENT_EVIDENCE`

Possible causes:

- No chunks indexed.
- Wrong filters.
- Requested version does not match indexed chunks.
- OpenSearch query returns no candidates.
- Generated answer used invalid citation labels.

### Integration tests skipped

This is normal if local OpenSearch or watsonx credentials are unavailable.

---

## 65. Safe Ways to Modify the Project

### If changing API request/response shape

Be careful with:

```text
app/api/schemas.py
openapi/it_helpdesk_v1.yaml
```

These are external contracts.

Update tests too.

### If changing graph state

Be careful with:

```text
app/graph/state.py
```

Many nodes depend on this shape.

### If changing retrieval filters

Update:

```text
app/retrieval/filters.py
tests/unit/test_filters.py
```

Also make sure OpenSearch mappings support the field.

### If changing chunk schema

Update:

- index mappings in `scripts/create_index.py`
- fixtures
- retrieval logic
- citation mapping
- ingestion pipeline when implemented

### If enforcing stricter citation validation

Update:

```text
app/graph/nodes/validate_citations.py
tests/unit/test_nodes.py
tests/unit/test_graph_workflow.py
```

---

## 66. File-by-File Quick Reference

### Root files

| File | Purpose |
|---|---|
| `.env.example` | Template for required environment variables. |
| `.gitignore` | Prevents secrets, caches, data, and virtualenv files from being committed. |
| `Dockerfile` | Builds the containerized FastAPI app. |
| `pyproject.toml` | Project metadata and pytest/Ruff config. |
| `requirements.txt` | Python dependencies. |
| `EXPLAINER.md` | Existing intern-friendly architecture explanation. |
| `RESTART-GUIDE.md` | V3 restart and branch cleanup guide. |
| `SESSION-LOG-V3.md` | Project session notes and locked contracts. |
| `DEVELOPER-A-PROMPT.md` | Prompt/context for API/agent developer. |
| `DEVELOPER-B-PROMPT.md` | Prompt/context for ingestion developer. |
| `PROJECT_PIPELINE_REPORT.md` | This detailed project report. |

### App files

| File | Purpose |
|---|---|
| `app/main.py` | Creates FastAPI app and health/readiness endpoints. |
| `app/api/routes.py` | Defines `POST /v1/assist`. |
| `app/api/dependencies.py` | API key authentication. |
| `app/api/schemas.py` | Request/response Pydantic models. |
| `app/core/config.py` | Environment-based settings. |
| `app/services/assist_service.py` | Bridges API request to graph and graph state to API response. |
| `app/graph/state.py` | Shared graph state type. |
| `app/graph/workflow.py` | LangGraph wiring and conditional routing. |
| `app/graph/nodes/input_guard.py` | Validates and normalizes input. |
| `app/graph/nodes/classify_extract.py` | Uses LLM to classify question and extract scope. |
| `app/graph/nodes/resolve_scope.py` | Handles out-of-scope/clarification and builds filters. |
| `app/graph/nodes/retrieve.py` | Runs hybrid retrieval. |
| `app/graph/nodes/evidence_gate.py` | Stops if evidence is insufficient. |
| `app/graph/nodes/compose_answer.py` | Builds evidence prompt and calls chat model. |
| `app/graph/nodes/validate_citations.py` | Checks generated citation labels. |
| `app/retrieval/opensearch_client.py` | Creates cached OpenSearch client. |
| `app/retrieval/filters.py` | Builds and relaxes OpenSearch filters. |
| `app/retrieval/hybrid_retriever.py` | BM25 plus vector search plus RRF. |
| `app/retrieval/fusion.py` | Pure RRF implementation. |
| `app/providers/watsonx_embeddings.py` | watsonx embedding wrapper. |
| `app/providers/watsonx_chat.py` | watsonx chat generation wrapper. |
| `app/providers/watsonx_rerank.py` | Disabled placeholder reranker. |
| `app/policy/evidence_policy.py` | Evidence sufficiency rules. |
| `app/policy/domain_policy.py` | Domain registry loading/checking. |
| `app/observability/logging.py` | JSON logging helpers. |
| `app/prompts/classify_extract.md` | Prompt for classification. |
| `app/prompts/grounded_answer.md` | Prompt for final grounded answer. |
| `app/ingestion/__init__.py` | Placeholder package for future ingestion. |

### Config files

| File | Purpose |
|---|---|
| `config/domains.yaml` | Domain registry. |
| `config/taxonomy/ocp_sno.yaml` | Controlled metadata vocabulary. |
| `config/corpus/ocp_sno_poc.yaml` | Approved corpus manifest, currently empty. |

### Script files

| File | Purpose |
|---|---|
| `scripts/create_index.py` | Creates OpenSearch chunk/document indices. |
| `scripts/smoke_test.py` | End-to-end retrieval smoke test with fixture chunk. |
| `scripts/validate_env.py` | Checks required environment variables. |

### Deployment/OpenAPI files

| File | Purpose |
|---|---|
| `deployment/CODE_ENGINE_DEPLOY.md` | IBM Code Engine deployment guide. |
| `openapi/it_helpdesk_v1.yaml` | OpenAPI spec for Orchestrate/tool import. |

### Test files

| File | Purpose |
|---|---|
| `tests/unit/test_schemas.py` | Tests API schemas. |
| `tests/unit/test_filters.py` | Tests filter builder. |
| `tests/unit/test_fusion.py` | Tests RRF. |
| `tests/unit/test_nodes.py` | Tests graph nodes. |
| `tests/unit/test_graph_workflow.py` | Tests full graph with mocks. |
| `tests/integration/test_opensearch.py` | Tests real OpenSearch behavior. |
| `tests/integration/test_vector_retrieval.py` | Tests real vector/hybrid retrieval. |
| `tests/fixtures/sample_chunk.json` | Sample indexed chunk. |
| `tests/fixtures/sample_request.json` | Sample assist request. |

---

## 67. Final Summary

This project is a backend for a citation-grounded OpenShift/SNO support assistant.

The strongest implemented parts are:

- FastAPI API layer.
- Pydantic schemas.
- API key auth.
- LangGraph workflow.
- OpenSearch hybrid retrieval.
- RRF fusion.
- watsonx embedding/chat provider wrappers.
- Citation validation.
- Unit test coverage.
- OpenAPI spec.
- Dockerfile and Code Engine deployment notes.

The biggest remaining parts are:

- Real ingestion pipeline.
- Real approved PDF corpus.
- Full production deployment manifests if OpenShift deployment is required.
- Stricter citation validation.
- Optional reranking.
- Evaluation dataset.

If you understand the seven-node graph and how retrieval works, you understand the heart of the system.

The heart of the system is:

```text
Validate input
  → classify question
  → resolve scope
  → retrieve evidence
  → check evidence
  → generate grounded answer
  → validate citations
```

That is the pipeline to remember.

