# rag_core.py — PUBLIC INTERFACE CONTRACT
# Owner: Developer A
# Status: STUB — interface locked, implementation pending (ST-3)
#
# Developer B: import and call these functions from server.py.
# Do NOT change the function signatures without coordinating with Developer A first.
# See CONTEXT.md for current implementation status.


def get_iam_token(api_key: str) -> str:
    """
    Exchange an IBM Cloud API key for a short-lived IAM Bearer token.
    Caches the token in memory and auto-refreshes when < 5 min from 60-min expiry.

    Args:
        api_key: IBM Cloud API key from .env (IBM_CLOUD_API_KEY)
    Returns:
        Bearer token string for use in Authorization headers
    """
    raise NotImplementedError("ST-3: Developer A to implement")


def retrieve(query: str, top_k: int = 5, filters: dict = None) -> list:
    """
    Query Watson Discovery v2 with a natural language query and optional metadata filters.

    Args:
        query:   The user's natural language question or issue description
        top_k:   Maximum number of passage chunks to return (default 5)
        filters: Optional dict of metadata constraints, e.g.:
                 {"version": "4.16", "component": "bootstrap"}
                 Maps to Discovery v2 filter:
                 document.metadata.version::4.16,document.metadata.component::bootstrap

    Returns:
        List of dicts: [{"text": str, "source": str, "version": str}, ...]
        Returns [] if no relevant passages found.
    """
    raise NotImplementedError("ST-3: Developer A to implement")


def generate(context_chunks: list, user_query: str, mode: str) -> str:
    """
    Build a Granite prompt from a template + retrieved context chunks,
    then call Watsonx.ai for answer generation.

    Args:
        context_chunks: Output of retrieve(). If EMPTY, returns fallback WITHOUT calling LLM.
        user_query:     The original user question or issue description
        mode:           One of 'qa' | 'summarize' | 'troubleshoot'

    Returns:
        Generated answer string with source citation appended.
        If context_chunks is empty, returns:
        "I wasn't able to find relevant information in the knowledge base for your query."
    """
    raise NotImplementedError("ST-3: Developer A to implement")


def query(user_input: str, mode: str = "qa", filters: dict = None) -> dict:
    """
    Main entry point. Orchestrates retrieve() -> generate().

    Args:
        user_input: The user's raw message from Watsonx Orchestrate
        mode:       One of 'qa' | 'summarize' | 'troubleshoot' (default 'qa')
        filters:    Optional metadata filters dict passed through to retrieve()

    Returns:
        {"answer": str, "sources": list[str]}
    """
    raise NotImplementedError("ST-3: Developer A to implement")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="RAG Core CLI tester")
    parser.add_argument("input", type=str, help="Question or issue to query")
    parser.add_argument("--mode", type=str, default="qa",
                        choices=["qa", "summarize", "troubleshoot"])
    parser.add_argument("--version", type=str, default=None)
    parser.add_argument("--component", type=str, default=None)
    args = parser.parse_args()

    f = {}
    if args.version:
        f["version"] = args.version
    if args.component:
        f["component"] = args.component

    result = query(args.input, mode=args.mode, filters=f if f else None)
    print("\n=== ANSWER ===")
    print(result["answer"])
    print("\n=== SOURCES ===")
    for s in result["sources"]:
        print(f"  - {s}")
