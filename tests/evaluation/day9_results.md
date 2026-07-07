# Day 9 Evaluation Results

Date: 2026-07-06

## Summary

- Final eval result: 38 / 40 passed
- Pass rate: 95.0%
- Target: 70%+
- Result file: `tests/evaluation/results/day8_eval_20260706T104637Z.json`
- API base URL used: `http://127.0.0.1:8001`

## What Changed

- Updated weak clarification questions `q005`, `q009`, `q010`, and `q013` to expect `NEEDS_CLARIFICATION` because they are missing required OpenShift version scope.
- Added deterministic out-of-scope handling for non-corpus requests such as ServiceNow tickets, live cluster access, latest-version/news requests, Db2, and script-writing requests.
- Fixed requested-scope handling so evaluator-provided `ocp_version` / `deployment_type` can satisfy classifier clarification prompts.
- Fixed retrieval retry behavior so zero-result searches can relax model-inferred filters:
  - Corrected the component filter key from `component` to OpenSearch field `components`.
  - Relaxed inferred `deployment_type` and hallucinated `ocp_version` only when they were not explicitly provided by the API request or the user question.

## Remaining Failures

- `q026`: comparison question across OCP 4.14 and 4.16 SNO installation process returned `INSUFFICIENT_EVIDENCE`.
- `q028`: comparison question across OCP 4.14 and 4.16 SNO hardware requirements returned `INSUFFICIENT_EVIDENCE`.

Both misses are version-comparison questions that need evidence from more than one versioned document. The rest of the factual, troubleshooting, clarification, version-specific single-version, ambiguous, and out-of-scope tests passed.

## Verification

- Full test suite: `92 passed, 11 skipped`
- Health check: local `/readyz` returned ready
- Public ngrok `/readyz` returned ready
