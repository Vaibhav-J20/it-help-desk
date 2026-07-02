"""
scripts/validate_env.py
Checks that all required environment variables are present and non-empty.

Usage:
    python scripts/validate_env.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


REQUIRED_FOR_API = [
    ("IBM_CLOUD_API_KEY",           "IAM token exchange for watsonx.ai"),
    ("OPENSEARCH_URL",              "OpenSearch cluster endpoint"),
    ("OPENSEARCH_INDEX_CHUNKS",     "Chunk index name (default: knowledge_chunks_v1)"),
    ("OPENSEARCH_INDEX_DOCS",       "Document registry index name"),
    ("WATSONX_URL",                 "watsonx.ai base URL"),
    ("WATSONX_PROJECT_ID",          "watsonx.ai project ID"),
    ("WATSONX_EMBEDDING_MODEL_ID",  "Embedding model ID — verify in your account"),
    ("WATSONX_CHAT_MODEL_ID",       "Chat/generation model ID — verify in your account"),
    ("API_KEY_SECRET",              "Secret sent by Orchestrate in X-API-Key header"),
]

OPTIONAL = [
    ("OPENSEARCH_USERNAME",         "OpenSearch username (empty = no auth for local dev)"),
    ("OPENSEARCH_PASSWORD",         "OpenSearch password"),
    ("WATSONX_RERANK_MODEL_ID",     "Rerank model — only needed if ENABLE_RERANKER=true"),
    ("COS_ENDPOINT",                "IBM COS endpoint (needed for production ingestion)"),
    ("COS_BUCKET",                  "IBM COS bucket name"),
    ("COS_API_KEY",                 "IBM COS API key"),
]


def main() -> int:
    from dotenv import load_dotenv
    load_dotenv()

    print("\n=== Environment Variable Check ===\n")

    failures = []

    print("Required:")
    for var, description in REQUIRED_FOR_API:
        value = os.getenv(var, "")
        status = "✅" if value else "❌ MISSING"
        print(f"  {status:12s}  {var:<35s}  {description}")
        if not value:
            failures.append(var)

    print("\nOptional:")
    for var, description in OPTIONAL:
        value = os.getenv(var, "")
        status = "✅" if value else "⚠️  not set"
        print(f"  {status:12s}  {var:<35s}  {description}")

    print()
    if failures:
        print(f"❌ {len(failures)} required variable(s) missing: {', '.join(failures)}")
        print("   Copy .env.example to .env and fill in the missing values.\n")
        return 1

    print("✅ All required variables are set.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
