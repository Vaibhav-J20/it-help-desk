"""
Day 8 evaluation runner for the OpenShift & SNO Support Copilot.

Reads tests/evaluation/gold_questions.yaml, calls POST /v1/assist, and writes
a timestamped JSON result file. It intentionally does not print API secrets.

Usage:
    python tests/evaluation/run_evaluation.py --limit 5
    python tests/evaluation/run_evaluation.py --category factual --limit 10
    python tests/evaluation/run_evaluation.py --all
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[2]
GOLD_FILE = ROOT / "tests" / "evaluation" / "gold_questions.yaml"
RESULTS_DIR = ROOT / "tests" / "evaluation" / "results"
DEFAULT_BASE_URL = "http://127.0.0.1:8001"


def load_questions() -> list[dict[str, Any]]:
    data = yaml.safe_load(GOLD_FILE.read_text())
    return data.get("questions", [])


def infer_requested_scope(question: dict[str, Any]) -> dict[str, str]:
    scope = {}
    if question.get("expected_ocp_version"):
        scope["ocp_version"] = question["expected_ocp_version"]
    if question.get("expected_deployment_type"):
        scope["deployment_type"] = question["expected_deployment_type"]
    return scope


def call_assist(base_url: str, api_key: str, question: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {"question": question["question"]}
    scope = infer_requested_scope(question)
    if scope:
        payload["requested_scope"] = scope

    try:
        with httpx.Client(timeout=120.0) as client:
            response = client.post(
                f"{base_url.rstrip('/')}/v1/assist",
                headers={"X-API-Key": api_key},
                json=payload,
            )
        response_data = response.json()
        return {
            "http_status": response.status_code,
            "response": response_data,
            "error": None,
        }
    except Exception as exc:
        return {
            "http_status": None,
            "response": None,
            "error": str(exc),
        }


def evaluate_result(question: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    response = actual.get("response") or {}
    actual_status = response.get("status")
    expected_status = question.get("expected_status")
    citations = response.get("citations") or []
    citation_doc_ids = sorted({c.get("document_id") for c in citations if c.get("document_id")})

    return {
        "id": question.get("id"),
        "category": question.get("category"),
        "expected_status": expected_status,
        "actual_status": actual_status,
        "status_pass": actual_status == expected_status,
        "citation_count": len(citations),
        "citation_document_ids": citation_doc_ids,
        "expected_document_ids": question.get("expected_document_ids", []),
        "http_status": actual.get("http_status"),
        "error": actual.get("error"),
    }


def select_questions(
    questions: list[dict[str, Any]],
    category: str | None,
    limit: int | None,
    run_all: bool,
) -> list[dict[str, Any]]:
    selected = questions
    if category:
        selected = [q for q in selected if q.get("category") == category]
    if not run_all and limit is not None:
        selected = selected[:limit]
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Day 8 API evaluation questions")
    parser.add_argument("--base-url", default=os.getenv("EVAL_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--category", help="Optional category filter, e.g. factual")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--all", action="store_true", help="Run all selected questions")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    api_key = os.getenv("API_KEY_SECRET", "")
    if not api_key:
        raise SystemExit("API_KEY_SECRET is not set in environment or .env")

    questions = select_questions(load_questions(), args.category, args.limit, args.all)
    if not questions:
        raise SystemExit("No questions selected")

    results = []
    for question in questions:
        actual = call_assist(args.base_url, api_key, question)
        summary = evaluate_result(question, actual)
        results.append({
            "question": question,
            "summary": summary,
            "actual": actual,
        })
        print(
            f"{summary['id']} {summary['category']}: "
            f"expected={summary['expected_status']} actual={summary['actual_status']} "
            f"citations={summary['citation_count']} pass={summary['status_pass']}"
        )

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = RESULTS_DIR / f"day8_eval_{timestamp}.json"
    output = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "base_url": args.base_url,
        "question_count": len(results),
        "results": results,
    }
    output_path.write_text(json.dumps(output, indent=2))
    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
