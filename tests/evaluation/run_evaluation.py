"""
Day 8 evaluation runner for the OpenShift & SNO Support Copilot.

Reads a YAML question set, calls POST /v1/assist, and writes a timestamped JSON
result file. It intentionally does not print API secrets.

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


def load_questions(path: Path = GOLD_FILE) -> list[dict[str, Any]]:
    data = yaml.safe_load(path.read_text())
    return data.get("questions", [])


def infer_requested_scope(question: dict[str, Any]) -> dict[str, str]:
    scope = {}
    if question.get("expected_domain_id"):
        scope["domain_id"] = question["expected_domain_id"]
    if question.get("expected_ocp_version"):
        scope["ocp_version"] = question["expected_ocp_version"]
    if question.get("expected_deployment_type"):
        scope["deployment_type"] = question["expected_deployment_type"]
    product = question.get("requested_product")
    product_version = question.get("requested_product_version")
    if question.get("expected_domain_id") == "ibm_products":
        product = product or question.get("expected_product")
        product_version = product_version or question.get("expected_product_version")
    if product:
        scope["product"] = product
    if product_version:
        scope["product_version"] = product_version
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
    answer = str(response.get("answer_markdown") or "")
    answer_lower = answer.lower()
    keyword_groups = question.get("expected_keyword_groups") or []
    keyword_groups_pass = all(
        any(str(keyword).lower() in answer_lower for keyword in group)
        for group in keyword_groups
    )
    citation_products = sorted({
        str(c.get("product")) for c in citations if c.get("product")
    })
    expected_product = question.get("expected_product")
    product_pass = not expected_product or any(
        product.lower() == str(expected_product).lower()
        for product in citation_products
    )
    citations_pass = expected_status != "ANSWERED" or bool(citations)
    answer_pass = expected_status != "ANSWERED" or bool(answer.strip())
    status_pass = actual_status == expected_status

    return {
        "id": question.get("id"),
        "category": question.get("category"),
        "expected_status": expected_status,
        "actual_status": actual_status,
        "status_pass": status_pass,
        "answer_pass": answer_pass,
        "citations_pass": citations_pass,
        "product_pass": product_pass,
        "keyword_groups_pass": keyword_groups_pass,
        "pass": (
            status_pass
            and answer_pass
            and citations_pass
            and product_pass
            and keyword_groups_pass
        ),
        "citation_count": len(citations),
        "citation_document_ids": citation_doc_ids,
        "citation_products": citation_products,
        "expected_document_ids": question.get("expected_document_ids", []),
        "http_status": actual.get("http_status"),
        "error": actual.get("error"),
    }


def select_questions(
    questions: list[dict[str, Any]],
    category: str | None,
    question_ids: set[str] | None,
    limit: int | None,
    run_all: bool,
) -> list[dict[str, Any]]:
    selected = questions
    if category:
        selected = [q for q in selected if q.get("category") == category]
    if question_ids:
        selected = [q for q in selected if q.get("id") in question_ids]
    if not run_all and limit is not None:
        selected = selected[:limit]
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description="Run API evaluation questions")
    parser.add_argument("--base-url", default=os.getenv("EVAL_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument(
        "--questions",
        type=Path,
        default=GOLD_FILE,
        help="YAML question set (default: tests/evaluation/gold_questions.yaml)",
    )
    parser.add_argument("--category", help="Optional category filter, e.g. factual")
    parser.add_argument(
        "--id",
        action="append",
        dest="question_ids",
        help="Run one question ID; repeat the option to select multiple IDs",
    )
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--all", action="store_true", help="Run all selected questions")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    api_key = os.getenv("API_KEY_SECRET", "")
    if not api_key:
        raise SystemExit("API_KEY_SECRET is not set in environment or .env")

    question_path = args.questions.expanduser().resolve()
    questions = select_questions(
        load_questions(question_path),
        args.category,
        set(args.question_ids or []),
        args.limit,
        args.all,
    )
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
            f"citations={summary['citation_count']} pass={summary['pass']}"
        )

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = RESULTS_DIR / f"{question_path.stem}_eval_{timestamp}.json"
    output = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "base_url": args.base_url,
        "question_file": str(question_path),
        "question_count": len(results),
        "passed": sum(1 for result in results if result["summary"]["pass"]),
        "results": results,
    }
    output_path.write_text(json.dumps(output, indent=2))
    print(f"Wrote {output_path}")
    return 0 if all(result["summary"]["pass"] for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
