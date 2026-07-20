# Day 8 Evaluation Results

Date: 2026-07-06

This file records the first Day 8 evaluation pass after Developer B uploaded PDFs to IBM Cloud Object Storage and began indexing real corpus data into OpenSearch.

## 1. Service Health

FastAPI local health:

```json
{"status":"ok"}
```

FastAPI readiness:

```json
{"status":"ready","opensearch":true,"watsonx":true}
```

OpenSearch:

- Running locally on port `9200`.
- Version: OpenSearch `2.15.0`.
- Cluster health for project indices: green.

## 2. Automated Tests

Sandboxed test suite:

```text
87 passed, 11 skipped
```

The skipped tests were integration tests because sandboxed commands could not see localhost.

Unsandboxed integration tests:

```text
11 passed
```

Warning from watsonx integration tests:

- Current embedding model: `ibm/slate-125m-english-rtrvr-v2`
- Deprecated from: 2026-05-05
- Scheduled withdrawal: 2026-08-08

This model should be replaced before final demo or production use.

## 3. OpenSearch Index Coverage

Current OpenSearch index counts:

| Index | Count |
|---|---:|
| `knowledge_chunks_v1` | 226 chunks |
| `knowledge_documents_v1` | 3 document records |

Searchable chunk distribution:

| Document ID | Title | Version | Searchable Chunks |
|---|---|---:|---:|
| `doc-c38a` | Installing an On-Premise Cluster with the Agent-based Installer (OCP 4.16) | 4.16 | 116 |
| `doc-0c0c` | Installing an On-Premise Cluster with the Agent-based Installer (OCP 4.14) | 4.14 | 110 |

Document registry also contains:

| Document ID | Title | Status | Note |
|---|---|---|---|
| `doc-fbc5` | Networking — Configuring and Managing Cluster Networking (OCP 4.16) | `PARSED` | Registry says parsed, but no chunks are searchable in `knowledge_chunks_v1`. |

Corpus manifest currently lists 8 PDFs, but only the two SNO installation PDFs have searchable chunks.

## 4. Important Data/Evaluation Mismatch

`tests/evaluation/gold_questions.yaml` expects document IDs such as:

- `doc-4957`
- `doc-04af`
- `doc-8e43`
- `doc-73eb`
- `doc-7a28`
- `doc-a752`

Actual indexed document IDs are currently:

- `doc-c38a`
- `doc-0c0c`
- `doc-fbc5`

This means document-ID-based scoring will fail even when retrieval finds the correct PDF topic, unless the gold file is updated to match actual generated document IDs or the ingestion system is changed to produce stable expected IDs.

## 5. Partial API Evaluation

Evaluation runner added:

```text
tests/evaluation/run_evaluation.py
```

Result files created under:

```text
tests/evaluation/results/
```

### First 5 Factual Questions

Result file:

```text
tests/evaluation/results/day8_eval_20260706T092145Z.json
```

| Question | Expected | Actual | Citation Docs | Notes |
|---|---|---|---|---|
| `q001` | `ANSWERED` | `INSUFFICIENT_EVIDENCE` | none | Likely retrieval/content mismatch. |
| `q002` | `ANSWERED` | `ANSWERED` | `doc-c38a` | Status passed, but gold expected stale doc ID `doc-4957`. |
| `q003` | `ANSWERED` | `INSUFFICIENT_EVIDENCE` | none | Likely retrieval/content mismatch. |
| `q004` | `ANSWERED` | `ANSWERED` | `doc-c38a` | Suspicious: networking question answered from installation guide because networking PDF is not indexed. |
| `q005` | `ANSWERED` | `INSUFFICIENT_EVIDENCE` | none | Likely retrieval/content mismatch. |

### Version Questions

Result file:

```text
tests/evaluation/results/day8_eval_20260706T092330Z.json
```

| Question | Expected | Actual | Citation Docs | Notes |
|---|---|---|---|---|
| `q026` | `ANSWERED` | `INSUFFICIENT_EVIDENCE` | none | Cross-version compare question failed. |
| `q027` | `ANSWERED` | `ANSWERED` | `doc-0c0c` | Correctly used OCP 4.14 indexed document. |
| `q028` | `ANSWERED` | `ANSWERED` | `doc-c38a` | Expected both 4.14 and 4.16, but actual citations only show 4.16 doc. |
| `q029` | `ANSWERED` | `ANSWERED` | `doc-c38a` | Suspicious: networking feature question answered from installation guide, not networking guide. |
| `q030` | `ANSWERED` | `INSUFFICIENT_EVIDENCE` | none | OCP 4.14 SNO agent installer question failed. |

### Ambiguous Questions

Result file:

```text
tests/evaluation/results/day8_eval_20260706T092332Z.json
```

| Question | Expected | Actual | Result |
|---|---|---|---|
| `q031` | `NEEDS_CLARIFICATION` | `NEEDS_CLARIFICATION` | Pass |
| `q032` | `NEEDS_CLARIFICATION` | `NEEDS_CLARIFICATION` | Pass |
| `q033` | `NEEDS_CLARIFICATION` | `NEEDS_CLARIFICATION` | Pass |
| `q034` | `NEEDS_CLARIFICATION` | `NEEDS_CLARIFICATION` | Pass |
| `q035` | `NEEDS_CLARIFICATION` | `NEEDS_CLARIFICATION` | Pass |

This is the strongest category so far.

### Out-of-Scope Questions Before Fix

Result file:

```text
tests/evaluation/results/day8_eval_20260706T092327Z.json
```

| Question | Expected | Actual | Notes |
|---|---|---|---|
| `q036` | `OUT_OF_SCOPE` | `ANSWERED` | Serious safety failure: ServiceNow ticket question was answered using adjacent OpenShift support evidence. |
| `q037` | `OUT_OF_SCOPE` | `OUT_OF_SCOPE` | Pass |
| `q038` | `OUT_OF_SCOPE` | `NEEDS_CLARIFICATION` | Should be deterministic out-of-scope for Db2. |
| `q039` | `OUT_OF_SCOPE` | `OUT_OF_SCOPE` | Pass |
| `q040` | `OUT_OF_SCOPE` | `NEEDS_CLARIFICATION` | Should be deterministic out-of-scope for code/script generation. |

## 6. Developer A Fix Applied

Implemented deterministic out-of-scope policy so these excluded topics do not depend only on the LLM classifier:

- ServiceNow/Jira/ticketing
- live cluster access
- latest/web-search style questions
- IBM Db2
- code/script generation and deployment automation asks

Files changed:

- `app/policy/domain_policy.py`
- `app/graph/nodes/resolve_scope.py`
- `tests/unit/test_nodes.py`

Focused test result:

```text
17 passed
```

Full sandboxed suite after fix:

```text
87 passed, 11 skipped
```

## 7. Live Server Restart Needed

After the code fix, the running FastAPI server on port `8001` still returned the old out-of-scope behavior.

That means the live Uvicorn process did not reload the changed code.

Completed action:

1. Restarted FastAPI on port `8001` using `.venv/bin/uvicorn app.main:app --port 8001`.
2. Restarted ngrok using `/opt/homebrew/bin/ngrok http --url=left-appraiser-disorder.ngrok-free.dev 8001`.
3. Verified local health/readiness:

```json
{"status":"ok"}
{"status":"ready","opensearch":true,"watsonx":true}
```

4. Verified public ngrok health/readiness at `https://left-appraiser-disorder.ngrok-free.dev`.
5. Re-ran out-of-scope evaluation locally and through public ngrok.

Post-restart local result:

```text
q036 OUT_OF_SCOPE pass=True
q037 OUT_OF_SCOPE pass=True
q038 OUT_OF_SCOPE pass=True
q039 OUT_OF_SCOPE pass=True
q040 OUT_OF_SCOPE pass=True
```

Public ngrok result file:

```text
tests/evaluation/results/day8_eval_20260706T093223Z.json
```

Public result:

```text
5/5 out-of-scope questions passed.
```

## 8. Main Day 8 Blockers

### Blocker 1: Only 2 of 8 manifest PDFs are searchable

The full 40-question evaluation cannot be fairly scored until all intended PDFs are indexed into `knowledge_chunks_v1`.

Anush/Developer B should finish indexing:

- networking
- storage
- troubleshooting/support
- authentication
- operators
- updating clusters

### Blocker 2: Networking registry status is `PARSED`, not searchable

The networking PDF has a document registry record but no searchable chunks in `knowledge_chunks_v1`.

This should be investigated in the ingestion/indexer path.

### Blocker 3: Gold document IDs are stale

The expected document IDs in `gold_questions.yaml` do not match actual IDs generated by the indexer.

Options:

1. Update `gold_questions.yaml` to use actual generated IDs.
2. Change ingestion to use deterministic IDs agreed in the gold file.
3. Score by source filename/title instead of generated document ID.

### Blocker 4: Some answer statuses pass while citations are semantically wrong

Example:

- `q004` asks about default networking plugin.
- It returns `ANSWERED`.
- It cites `doc-c38a`, the installation guide, not the networking guide.

The evaluation runner should eventually score citation document correctness, not just response status.

## 9. Recommended Next Steps

For Developer B / Anush:

1. Finish indexing all 8 manifest PDFs.
2. Confirm every document has `ingestion_status=INDEXED`.
3. Confirm every expected document has chunks in `knowledge_chunks_v1`.
4. Share final actual document IDs or switch to stable IDs.

For Developer A / Vaibhav:

1. Restart FastAPI so the out-of-scope fix is live.
2. Re-run out-of-scope evaluation.
3. Improve evaluation scoring to check citation document IDs/titles.
4. Re-run full 40-question evaluation after all PDFs are indexed.
5. Replace deprecated embedding model before final demo.
