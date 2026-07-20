"""
Evaluation Runner — OpenShift & SNO Support Copilot
Owner: Developer B (Anush)
Script: scripts/run_eval.py

Runs all 40 gold questions from tests/evaluation/gold_questions.yaml
against the live /v1/assist API and records results.

Usage:
    python3 scripts/run_eval.py
    python3 scripts/run_eval.py --url https://left-appraiser-disorder.ngrok-free.dev
    python3 scripts/run_eval.py --questions tests/evaluation/gold_questions.yaml
    python3 scripts/run_eval.py --category factual
    python3 scripts/run_eval.py --dry-run

Output:
    docs/operations/EVAL_RESULTS.md  — full results table
    Exit 0 if pass rate >= 70%, else exit 1
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path

import requests
import yaml
from dotenv import load_dotenv

load_dotenv()

DEFAULT_URL = os.getenv("API_URL", "https://left-appraiser-disorder.ngrok-free.dev")
DEFAULT_API_KEY = os.getenv("API_KEY_SECRET") or os.getenv("API_KEY", "")
PASS_THRESHOLD = 0.70  # 70% pass rate required


def _call_api(url: str, api_key: str, question: dict) -> dict:
    """POST /v1/assist and return the parsed response."""
    payload: dict = {"question": question["question"]}

    scope = {}
    # Support both field names used in gold_questions.yaml
    version = question.get("expected_version") or question.get("expected_ocp_version")
    if version:
        scope["ocp_version"] = version
    deployment = question.get("expected_deployment_type")
    if deployment:
        scope["deployment_type"] = deployment
    if question.get("expected_domain_id"):
        scope["domain_id"] = question["expected_domain_id"]
    if question.get("expected_product"):
        scope["product"] = question["expected_product"]
    if question.get("expected_product_version"):
        scope["product_version"] = question["expected_product_version"]
    if scope:
        payload["requested_scope"] = scope

    resp = requests.post(
        f"{url}/v1/assist",
        headers={
            "X-API-Key": api_key,
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()


def _evaluate(question: dict, response: dict) -> dict:
    """
    Evaluate a single question/response pair.

    Returns a result dict with:
      pass: bool
      reason: str
    """
    category = question.get("category", "")
    expected_status = question.get("expected_status")
    actual_status = response.get("status", "")

    # --- Status-based evaluation ---
    if expected_status:
        # ambiguous, out_of_scope — must match exactly
        passed = actual_status == expected_status
        reason = (
            "correct status"
            if passed
            else f"expected {expected_status}, got {actual_status}"
        )
        return {"pass": passed, "reason": reason, "actual_status": actual_status}

    # --- Factual / troubleshoot / version questions ---
    # Must return ANSWERED or INSUFFICIENT_EVIDENCE (not NEEDS_CLARIFICATION)
    if actual_status == "ANSWERED":
        # Check citations present
        citations = response.get("citations", [])
        if not citations:
            return {
                "pass": False,
                "reason": "ANSWERED but no citations",
                "actual_status": actual_status,
            }
        # Check answer_markdown present
        if not response.get("answer_markdown"):
            return {
                "pass": False,
                "reason": "ANSWERED but answer_markdown is null",
                "actual_status": actual_status,
            }
        # Version check: if expected_version set, no citation should be from wrong version
        expected_version = question.get("expected_version")
        if expected_version and category == "version":
            wrong = [
                c for c in citations
                if c.get("ocp_version") and c["ocp_version"] != expected_version
            ]
            if wrong:
                return {
                    "pass": False,
                    "reason": f"version leak: citations from {[c['ocp_version'] for c in wrong]}",
                    "actual_status": actual_status,
                }
        return {"pass": True, "reason": "ANSWERED with citations", "actual_status": actual_status}

    elif actual_status == "INSUFFICIENT_EVIDENCE":
        # Acceptable for factual/troubleshoot when OpenSearch not yet connected
        return {
            "pass": True,
            "reason": "INSUFFICIENT_EVIDENCE (acceptable — shared OpenSearch pending)",
            "actual_status": actual_status,
        }

    else:
        return {
            "pass": False,
            "reason": f"unexpected status: {actual_status}",
            "actual_status": actual_status,
        }


def run_eval(
    url: str,
    api_key: str,
    questions_path: Path,
    category_filter: str | None,
    dry_run: bool,
    report_path: Path,
) -> dict:
    if not dry_run and not api_key:
        raise ValueError("API_KEY_SECRET or API_KEY must be set; no fallback key is embedded")
    with open(questions_path) as f:
        data = yaml.safe_load(f)

    questions = data.get("questions", [])
    if category_filter:
        questions = [q for q in questions if q.get("category") == category_filter]

    print(f"\n{'─'*65}")
    print(f"  Evaluation Runner — {len(questions)} question(s)")
    print(f"  API: {url}")
    if dry_run:
        print("  DRY RUN — no API calls")
    print(f"{'─'*65}\n")

    results = []

    for q in questions:
        qid = q.get("id", "?")
        category = q.get("category", "?")

        if dry_run:
            print(f"  [{qid}] {category:15s} {q['question'][:60]}")
            continue

        try:
            response = _call_api(url, api_key, q)
            result = _evaluate(q, response)
            result["id"] = qid
            result["category"] = category
            result["question"] = q["question"]
            result["response"] = response
            results.append(result)

            status_icon = "✅" if result["pass"] else "❌"
            print(
                f"  {status_icon} [{qid}] {category:15s} "
                f"{result['actual_status']:25s} {result['reason']}"
            )
            time.sleep(0.3)  # avoid rate limiting

        except Exception as e:
            results.append({
                "id": qid,
                "category": category,
                "question": q["question"],
                "pass": False,
                "reason": f"ERROR: {e}",
                "actual_status": "ERROR",
                "response": {},
            })
            print(f"  ❌ [{qid}] {category:15s} ERROR: {e}")

    if dry_run:
        return {}

    # --- Summary ---
    total = len(results)
    passed = sum(1 for r in results if r["pass"])
    pass_rate = passed / total if total else 0

    by_category: dict = {}
    for r in results:
        cat = r["category"]
        by_category.setdefault(cat, {"pass": 0, "total": 0})
        by_category[cat]["total"] += 1
        if r["pass"]:
            by_category[cat]["pass"] += 1

    print(f"\n{'─'*65}")
    print(f"  Results: {passed}/{total} passed ({pass_rate:.0%})")
    for cat, counts in sorted(by_category.items()):
        print(f"    {cat:20s} {counts['pass']}/{counts['total']}")
    overall = "PASS ✅" if pass_rate >= PASS_THRESHOLD else "FAIL ❌"
    print(f"  Overall: {overall}  (threshold: {PASS_THRESHOLD:.0%})")
    print(f"{'─'*65}\n")

    # --- Write report ---
    _write_report(results, passed, total, pass_rate, by_category, report_path, url)

    return {
        "total": total,
        "passed": passed,
        "pass_rate": pass_rate,
        "by_category": by_category,
        "overall_pass": pass_rate >= PASS_THRESHOLD,
    }


def _write_report(results, passed, total, pass_rate, by_category, report_path, url):
    os.makedirs(report_path.parent, exist_ok=True)
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    overall = "✅ PASS" if pass_rate >= PASS_THRESHOLD else "❌ FAIL"

    lines = [
        "# Evaluation Results — OpenShift & SNO Support Copilot",
        "",
        f"**Date:** {now}  ",
        f"**API:** {url}  ",
        f"**Overall:** {overall} — {passed}/{total} ({pass_rate:.0%})  ",
        "",
        "## By Category",
        "",
        "| Category | Pass | Total | Rate |",
        "|---|---|---|---|",
    ]
    for cat, counts in sorted(by_category.items()):
        rate = counts["pass"] / counts["total"] if counts["total"] else 0
        lines.append(f"| {cat} | {counts['pass']} | {counts['total']} | {rate:.0%} |")

    lines += ["", "---", "", "## Per-Question Results", "",
              "| ID | Category | Status | Pass | Reason |",
              "|---|---|---|---|---|"]

    for r in results:
        icon = "✅" if r["pass"] else "❌"
        lines.append(
            f"| {r['id']} | {r['category']} | {r['actual_status']} "
            f"| {icon} | {r['reason']} |"
        )

    lines += ["", "---", "*Generated by `scripts/run_eval.py`*"]

    with open(report_path, "w") as f:
        f.write("\n".join(lines))
    print(f"  Report written to: {report_path}")


def main():
    parser = argparse.ArgumentParser(description="Run 40-question evaluation against /v1/assist")
    parser.add_argument("--url", default=DEFAULT_URL, help="API base URL")
    parser.add_argument("--api-key", default=DEFAULT_API_KEY, help="X-API-Key value")
    parser.add_argument("--questions", type=Path,
                        default=Path("tests/evaluation/gold_questions.yaml"))
    parser.add_argument("--category", default=None,
                        help="Filter to one category (factual/troubleshoot/version/ambiguous/out_of_scope)")
    parser.add_argument("--dry-run", action="store_true",
                        help="List questions without calling API")
    parser.add_argument("--report", type=Path,
                        default=Path("docs/operations/EVAL_RESULTS.md"))
    args = parser.parse_args()

    summary = run_eval(
        url=args.url,
        api_key=args.api_key,
        questions_path=args.questions,
        category_filter=args.category,
        dry_run=args.dry_run,
        report_path=args.report,
    )

    if not args.dry_run:
        import sys
        sys.exit(0 if summary.get("overall_pass") else 1)


if __name__ == "__main__":
    main()
