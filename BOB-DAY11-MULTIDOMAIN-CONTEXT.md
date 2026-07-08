# Bob Context — Day 11 Multi-Domain Knowledge Expansion

**Date:** 2026-07-08  
**Author:** Vaibhav + Codex  
**Purpose:** Give IBM Bob enough context to continue development after the OpenShift/SNO copilot was expanded to also support IBM watsonx Orchestrate and IBM Bob documentation.

---

## Read This First

The project is no longer only an OpenShift/SNO support copilot.

It is now an **Enterprise IT Support Copilot** backed by approved knowledge sources for:

1. Red Hat OpenShift / OCP / SNO
2. IBM watsonx Orchestrate
3. IBM Bob

The backend still exposes the same core endpoint:

```text
POST /v1/assist
```

The watsonx Orchestrate tool may still have an older name such as `query_ocp_sno_knowledge`, `query_enterprise_it_knowledge`, or `submit_a_technical_support_question`, depending on how the UI imported the OpenAPI spec. The backend behavior is what matters: all of these should point to the same `/v1/assist` endpoint.

---

## What We Achieved Today

### 1. Added Web Documentation Ingestion

Originally, ingestion only supported PDFs from local files or IBM Cloud Object Storage. Today we added support for web documentation, so the copilot can ingest documentation directly from documentation websites.

New files:

| File | Purpose |
|---|---|
| `app/ingestion/web_source.py` | Discovers web pages from either an index file like `llms.txt` or from a bounded same-site crawl. |
| `app/ingestion/text_parser.py` | Parses HTML, Markdown, and plain text into the same page/section structure used by the existing ingestion pipeline. |

Updated files:

| File | Change |
|---|---|
| `app/ingestion/cos_source.py` | Added HTTP/HTTPS document loading in addition to local and COS files. |
| `app/ingestion/run.py` | Expands web manifests before ingestion, chooses PDF parser vs text parser, and continues past individual web fetch failures. |
| `app/ingestion/metadata.py` | Allows non-OCP domains where `ocp_version` and `deployment_type` are not required. |
| `app/ingestion/indexer.py` | Allows chunks without OCP version/deployment metadata and indexes web sources cleanly. |

### 2. Added Two New Corpus Manifests

New corpus files:

| File | Domain | Source |
|---|---|---|
| `config/corpus/watsonx_orchestrate.yaml` | `watsonx_orchestrate` | `https://developer.watson-orchestrate.ibm.com/llms.txt` |
| `config/corpus/ibm_bob.yaml` | `ibm_bob` | `https://bob.ibm.com/docs/ide` |

Current ingestion results:

| Domain | Result |
|---|---|
| watsonx Orchestrate | `INDEXED: 124  SKIPPED: 36  FAILED: 0` |
| IBM Bob | `INDEXED: 30  SKIPPED: 0  FAILED: 0` |

Important nuance:

- Orchestrate coverage is stronger because the website exposes an `llms.txt` index and we discovered about 160 sources.
- IBM Bob coverage is useful but limited because the crawl is currently capped at 30 pages under `/docs/ide`.

### 3. Expanded Taxonomy and Domain Routing

Updated files:

| File | Change |
|---|---|
| `config/domains.yaml` | Added active domains for `watsonx_orchestrate` and `ibm_bob`. |
| `config/taxonomy/ocp_sno.yaml` | Added allowed domain IDs, products, document types, and components for Orchestrate and Bob. |
| `app/prompts/classify_extract.md` | Updated classifier prompt to recognize OpenShift/SNO, watsonx Orchestrate, and IBM Bob questions. |
| `app/graph/nodes/classify_extract.py` | Carries `domain_id` through extracted scope. |
| `app/graph/nodes/resolve_scope.py` | Resolves multi-domain questions instead of assuming everything is OpenShift. |

Examples of routing:

| User question | Expected domain |
|---|---|
| "What DNS records are required for SNO 4.16?" | `ocp_sno_support` |
| "What is the Orchestrate ADK?" | `watsonx_orchestrate` |
| "What is IBM Bob Agent mode?" | `ibm_bob` |

### 4. Fixed Source Labels for Non-OCP Answers

Before the fix, Orchestrate and Bob answers showed source labels like:

```text
OCP None
```

That was because the answer formatter was originally hardcoded for OpenShift.

Updated file:

| File | Change |
|---|---|
| `app/graph/nodes/compose_answer.py` | Source labels now use the product name and version when available. |
| `app/prompts/grounded_answer.md` | Prompt now describes the assistant as an approved enterprise IT support assistant instead of only OCP/SNO. |

Correct current examples:

```text
[S1] Installing the VS Code Orchestrate ADK extension — watsonx Orchestrate, pp. 1-5
```

```text
[S1] Custom modes | Docs | IBM Bob — IBM Bob, pp. 1-26
```

```text
[S1] Installing an On-Premise Cluster with the Agent-based Installer (OCP 4.16) — OpenShift 4.16, pp. 18-18
```

### 5. Fixed Orchestrate `requested_scope.component` Misuse

The watsonx Orchestrate tool started sending payloads like this:

```json
{
  "question": "What is IBM Bob Agent mode and how do custom modes work?",
  "requested_scope": {
    "component": "IBM Bob"
  }
}
```

That is understandable from the UI, but internally `component` was meant for smaller technical components like `dns`, `storage`, `operators`, or `authentication`.

If `component: "IBM Bob"` was treated as a strict OpenSearch component filter, retrieval could miss useful documents.

Fix added in:

```text
app/services/assist_service.py
```

Now these incoming values are normalized:

| Incoming `requested_scope.component` | Internal scope |
|---|---|
| `IBM Bob` / `Bob` / `Bob IDE` | `domain_id: ibm_bob` |
| `watsonx Orchestrate` / `Orchestrate` / `Orchestrate ADK` | `domain_id: watsonx_orchestrate` |
| `OpenShift` / `OCP` / `SNO` | `domain_id: ocp_sno_support` |
| Real component like `dns` | remains `component: dns` |

Tests added:

```text
tests/unit/test_assist_service.py
```

Focused test result after the fix:

```text
58 passed
```

---

## Orchestrate Front-End Configuration

### Tool URL

Base URL:

```text
https://left-appraiser-disorder.ngrok-free.dev
```

Path:

```text
/v1/assist
```

Full endpoint:

```text
https://left-appraiser-disorder.ngrok-free.dev/v1/assist
```

Health check:

```text
https://left-appraiser-disorder.ngrok-free.dev/readyz
```

Expected readiness:

```json
{"status":"ready","opensearch":true,"watsonx":true}
```

### Authentication

Use API key authentication.

Do **not** commit the API key into any markdown file.

Configure Orchestrate like this:

```text
Authentication type: API Key
Send API key in: Header
Header name: X-API-Key
Header value: value of API_KEY_SECRET from .env
```

Do not use:

```text
Authorization: Bearer ...
```

The backend expects exactly:

```text
X-API-Key: <actual secret from .env>
```

### Agent Description

Use this description in the Orchestrate profile:

```text
Citation-grounded enterprise IT support for OpenShift/OCP/SNO, IBM watsonx Orchestrate, and IBM Bob. Use this agent for installation guidance, troubleshooting, networking, storage, authentication, operators, DNS, ingress, Orchestrate ADK/agents/tools/skills, and Bob IDE modes, subagents, tools, and configuration. Answers come from the approved knowledge base with citations.
```

### Welcome Message

```text
Hello, welcome to Enterprise IT Support Copilot
```

### Quick Start Prompts

```text
What DNS records are required before starting SNO 4.16 installation?
```

```text
In watsonx Orchestrate, what is the ADK and how do I install the extension?
```

```text
What is IBM Bob Agent mode and how do custom modes work?
```

### Behavior Prompt

Use this as the agent behavior prompt:

```text
You are an enterprise IT support copilot connected to an approved knowledge-base tool.

Always call the knowledge-base tool for any question about OpenShift, OCP, OpenShift Container Platform, SNO, Single Node OpenShift, OpenShift installation, troubleshooting, networking, storage, authentication, operators, updates, DNS, ingress, cluster support, IBM watsonx Orchestrate, watsonx Orchestrate ADK, Orchestrate agents, Orchestrate tools, Orchestrate skills, Orchestrate channels, Orchestrate connections, Orchestrate knowledge bases, Orchestrate developer documentation, IBM Bob, Bob IDE, Bob Agent mode, Bob Ask mode, Bob Plan mode, Bob custom modes, Bob subagents, Bob MCP/tools/skills, Bob Shell, Bob workspace support, or Bob configuration support.

Do not answer these questions from your own knowledge. Always use the tool response.

When the tool returns status ANSWERED:
- Show the tool's answer_markdown to the user.
- Render answer_markdown as Markdown and preserve line breaks.
- Keep the citations and Sources section.
- Do not remove or invent citations.
- Do not add unsupported facts.

When the tool returns status NEEDS_CLARIFICATION:
- Ask the user the tool's clarification_question.
- Do not guess missing information.

When the tool returns status OUT_OF_SCOPE:
- Tell the user this question is outside the currently approved knowledge base.
- Do not answer from general knowledge.

When the tool returns status INSUFFICIENT_EVIDENCE:
- Tell the user the approved knowledge base does not contain enough evidence to answer safely.
- Do not invent missing commands, steps, version details, URLs, or product behavior.

Never claim you accessed a live cluster, account, IDE, repository, or production system unless the tool response explicitly says so.
If the user asks a follow-up question in these domains, call the tool again.
If the user asks for commands or step-by-step instructions, only provide them when they are supported by the tool response.
If the tool answer includes a safety note, preserve it.
```

### Tool Description

Use this tool description:

```text
Submit a technical support question for the approved enterprise IT knowledge base, including OpenShift/OCP/SNO, IBM watsonx Orchestrate, and IBM Bob. Returns a citation-grounded answer, a clarification request, an insufficient-evidence notice, or an out-of-scope notice. Never fabricates citations or answers outside the approved sources.
```

---

## Verified Demo Questions

### OpenShift/SNO

Question:

```text
What DNS records are required before starting SNO 4.16 installation?
```

Expected:

```text
ANSWERED
Sources should show OpenShift 4.16 citations.
```

### watsonx Orchestrate

Question:

```text
In watsonx Orchestrate, what is the ADK and how do I install the extension?
```

Expected:

```text
ANSWERED
Sources should show watsonx Orchestrate citations.
```

### IBM Bob

Question:

```text
What is IBM Bob Agent mode and how do custom modes work?
```

Expected:

```text
ANSWERED
Sources should show IBM Bob citations.
```

### Exact Payloads Tested After the Scope Fix

IBM Bob:

```json
{
  "question": "What is IBM Bob Agent mode and how do custom modes work?",
  "requested_scope": {
    "component": "IBM Bob"
  },
  "conversation_context": [
    {
      "role": "user",
      "content": "What is IBM Bob Agent mode and how do custom modes work?"
    }
  ]
}
```

Result:

```text
ANSWERED
### IBM Bob Agent Mode and Custom Modes
IBM Bob
```

watsonx Orchestrate:

```json
{
  "question": "How do I create a tool or skill in watsonx Orchestrate?",
  "requested_scope": {
    "component": "watsonx Orchestrate"
  },
  "conversation_context": [
    {
      "role": "user",
      "content": "How do I create a tool or skill in watsonx Orchestrate?"
    }
  ]
}
```

Result:

```text
ANSWERED
### Creating a Tool or Skill in Watsonx Orchestrate
watsonx Orchestrate
```

---

## Important Limitations

### 1. This Is Not Perfect Coverage Yet

The copilot can answer many questions from the Orchestrate and Bob docs, but it is not guaranteed to answer every question from those websites.

It can only answer when:

1. The page was discovered and indexed.
2. The page text was readable by the parser.
3. Retrieval finds the right chunks.
4. The evidence gate decides there is enough support.
5. The answer generator cites the evidence correctly.

### 2. IBM Bob Corpus Is Currently Smaller

The Bob crawl is capped at 30 pages.

If Bob fails to answer some IBM Bob documentation questions, first expand:

```text
config/corpus/ibm_bob.yaml
```

Recommended next value:

```yaml
max_pages: 100
```

Then re-run ingestion:

```bash
.venv/bin/python -m app.ingestion.run --manifest config/corpus/ibm_bob.yaml
```

### 3. Orchestrate Tool/Skill Creation Answers Need Better Coverage

The current Orchestrate answer for:

```text
How do I create a tool or skill in watsonx Orchestrate?
```

works, but it admits that it does not have full step-by-step detail for every tool/skill workflow.

Future work:

1. Identify the exact Orchestrate docs pages for tool creation, skill creation, OpenAPI skill import, and ADK CLI commands.
2. Ensure those pages are indexed.
3. Add targeted eval questions.

### 4. Embedding Model Deprecation Warning

The running logs show this warning:

```text
Model 'ibm/slate-125m-english-rtrvr-v2' is in deprecated state from 2026-05-05.
It will be withdrawn on 2026-08-08.
```

Before 2026-08-08, switch to a supported watsonx embedding model and re-index.

### 5. Local Changes Are Not Yet Committed

Run this before committing:

```bash
git status --short
```

There are both intended Day 11 changes and older unrelated/untracked files in the working tree. Do not blindly stage everything.

---

## Files Bob Should Inspect For This Day 11 Work

Core new files:

```text
app/ingestion/web_source.py
app/ingestion/text_parser.py
config/corpus/watsonx_orchestrate.yaml
config/corpus/ibm_bob.yaml
tests/unit/test_assist_service.py
```

Core updated files:

```text
app/ingestion/cos_source.py
app/ingestion/run.py
app/ingestion/metadata.py
app/ingestion/indexer.py
app/services/assist_service.py
app/graph/nodes/classify_extract.py
app/graph/nodes/resolve_scope.py
app/graph/nodes/compose_answer.py
app/prompts/classify_extract.md
app/prompts/grounded_answer.md
config/domains.yaml
config/taxonomy/ocp_sno.yaml
app/main.py
app/api/routes.py
```

Context files updated for Bob:

```text
BOB-DAY11-MULTIDOMAIN-CONTEXT.md
SESSION-LOG-V3.md
BOB-Developer-B-work-done.md
EXPLAINER.md
README.md
```

---

## Recommended Next Tasks

1. Commit the intended Day 11 code and context changes on a clean branch.
2. Expand IBM Bob crawl coverage beyond 30 pages.
3. Create a small eval set:
   - 10 watsonx Orchestrate questions
   - 10 IBM Bob questions
   - 5 mixed out-of-scope questions
4. Update or regenerate the OpenAPI spec so the tool name and description say Enterprise IT Support instead of only OCP/SNO.
5. Rename the Orchestrate frontend agent from `OpenShift & SNO Support Copilot` to `Enterprise IT Support Copilot`.
6. Replace deprecated embedding model before 2026-08-08 and re-index all corpora.

