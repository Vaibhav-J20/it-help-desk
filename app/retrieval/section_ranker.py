"""Rank structure-preserving cached/live chunks against a user question."""

from __future__ import annotations

import hashlib
import re
from typing import Iterable

from app.ingestion.chunker import ChunkRecord
from app.ingestion.ibm_docs_crawler.models import ExtractedDocument
from app.ingestion.ibm_docs_crawler.registry import CrawlTarget
from app.retrieval.catalog_selector import is_product_overview_query
from app.retrieval.constraints import constrain_candidates, constraints_are_satisfied
from app.retrieval.portfolio import detect_portfolio_family, is_portfolio_target

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_.-]+", re.IGNORECASE)
_STOP_WORDS = frozenset({
    "a", "an", "and", "are", "can", "do", "does", "for", "how", "i", "in",
    "is", "it", "me", "my", "of", "on", "the", "to", "what", "when", "where",
    "which", "with", "you",
})
_COMMAND_TERMS = ("command", "cli", "powershell", "shell", "terminal", "run", "install")
_OVERVIEW_FILLER_TERMS = frozenset({
    "about", "brief", "description", "describe", "explain", "give", "introduction",
    "me", "ok", "overview", "platform", "product", "software", "summary", "tell",
})


def rank_artifact_chunks(
    query: str,
    artifacts: Iterable[tuple[ExtractedDocument, list[ChunkRecord], str]],
    target: CrawlTarget,
    *,
    limit: int,
) -> list[dict]:
    product_tokens = set(_tokens(" ".join((target.product_name, target.product_id))))
    query_tokens = [token for token in _tokens(query) if token not in product_tokens]
    command_intent = any(term in query.lower() for term in _COMMAND_TERMS)
    install_intent = "install" in query.lower()
    windows_intent = "windows" in query.lower() or "powershell" in query.lower()
    overview_intent = is_product_overview_query(query, target)
    ranked: list[tuple[float, dict]] = []
    for document, chunks, origin in artifacts:
        for chunk in chunks:
            title = document.title.lower()
            section = chunk.section_path.lower()
            text = chunk.text.lower()
            text_words = _word_tokens(text)
            title_words = _word_tokens(title)
            section_words = _word_tokens(section)
            matched_text = {
                token for token in query_tokens if _token_matches(token, text_words)
            }
            matched_context = {
                token for token in query_tokens
                if _token_matches(token, title_words) or _token_matches(token, section_words)
            }
            score = (
                len(matched_text) * 2.5
                + len(matched_context) * 4.0
                + (len(matched_text | matched_context) / max(1, len(query_tokens))) * 8.0
            )
            if command_intent and "```" in chunk.text and (matched_text or matched_context):
                score += 7.0
            if install_intent and re.search(
                r"\b(?:pip|uv|npm|dnf|yum|apt|brew)?\s*install\b",
                text,
            ):
                score += 8.0
            if windows_intent and (
                "windows" in text_words or "powershell" in text_words
            ):
                score += 4.0
            if query.strip() and query.lower() in text:
                score += 10.0
            if overview_intent and document.canonical_url == target.seed_url:
                # The curated seed is the product landing/overview page. Its
                # prose often says "About <product>" rather than repeating
                # user filler such as "brief description", so lexical overlap
                # alone otherwise ranks unrelated child topics above it.
                score += 30.0 + max(0, 10 - chunk.chunk_ordinal)
            if is_portfolio_target(target):
                score += _portfolio_section_score(target.product_id, section, text)
            candidate = _candidate(document, chunk, target, origin, score)
            ranked.append((score, candidate))
    ranked.sort(key=lambda item: (-item[0], item[1]["chunk_id"]))
    return [candidate for _score, candidate in ranked[:max(1, limit)]]


def _portfolio_section_score(product_id: str, section: str, text: str) -> float:
    """Prefer offering sections over case studies and generic resources."""
    if product_id == "ibm-watsonx-portfolio":
        priorities = (
            ("ai assistants and agents", 70.0),
            ("data and analytics", 65.0),
            ("generative ai", 60.0),
            ("governance", 55.0),
        )
        for marker, bonus in priorities:
            if marker in section:
                return bonus
        if any(marker in section for marker in ("case studies", "resources", "spotlight")):
            return -25.0
        return 45.0
    if "product categories" in f"{section} {text}":
        return 100.0
    return 45.0


def candidate_set_is_confident(query: str, candidates: list[dict]) -> bool:
    """Require topic and intent coverage; retrieval-source agreement is not enough."""
    if not candidates:
        return False
    if not constraints_are_satisfied(query, candidates):
        return False
    candidates = constrain_candidates(query, candidates)
    if not candidates:
        return False
    selected = candidates[:5]
    comparison_versions = _comparison_versions(query)
    if comparison_versions:
        evidence_versions = {
            str(candidate.get("ocp_version") or candidate.get("product_version") or "")
            for candidate in candidates
        }
        if not comparison_versions.issubset(evidence_versions):
            return False
        combined = " ".join(
            " ".join((
                str(candidate.get("title") or ""),
                str(candidate.get("section_path") or ""),
                str(candidate.get("chunk_text") or ""),
            )).lower()
            for candidate in candidates[:10]
        )
        topic_tokens = [
            token for token in _tokens(query)
            if token not in comparison_versions
            and token not in {
                "between", "compared", "compare", "difference", "changed", "ocp"
            }
        ]
        words = _word_tokens(combined)
        return any(_token_matches(token, words) for token in topic_tokens)
    if any(
        candidate.get("retrieval_origin") == "global_metadata_catalog"
        for candidate in selected
    ) and _is_version_listing_query(query):
        return True

    query_tokens = _tokens(query)
    haystacks: list[str] = []
    for candidate in selected:
        haystacks.append(" ".join((
            str(candidate.get("product") or ""),
            str(candidate.get("product_version") or ""),
            str(candidate.get("title") or ""),
            str(candidate.get("section_path") or ""),
            str(candidate.get("chunk_text") or ""),
        )).lower())
    # Procedures and event announcements must be supported by at least one
    # coherent source.  Without this guard, an overview chunk that merely says
    # "certificate rotation" and an unrelated chunk containing ``cpd-cli``
    # can be concatenated into apparently complete evidence even though no
    # source documents the requested operation.
    if _requires_coherent_candidate(query):
        haystacks = [
            evidence
            for evidence in haystacks
            if _literal_facets_are_satisfied(query, evidence)
            and _intent_evidence_satisfied(query, evidence)
        ]
        if not haystacks:
            return False

    combined = " ".join(haystacks)
    if not _literal_facets_are_satisfied(query, combined):
        return False
    portfolio_family = detect_portfolio_family(query)
    if portfolio_family:
        # A single product page must never satisfy a request for an entire
        # product family. Require independent signals for several offerings or
        # several top-level IBM catalog categories before generation begins.
        return _portfolio_evidence_satisfied(portfolio_family, combined)
    if not _intent_evidence_satisfied(query, combined):
        return False
    if (
        _rotation_requested(query.casefold())
        and any(_has_automatic_lifecycle_signal(evidence) for evidence in haystacks)
    ):
        # This is a complete, corrective answer to a request that assumes a
        # manual rotation procedure exists.  Words such as "commands" and
        # "documented steps" describe the user's requested format; an official
        # source that explicitly documents scheduled renewal need not repeat
        # those words to establish that no manual sequence should be invented.
        return True
    if (
        re.search(r"\bthink\s+20\d{2}\b", query, re.IGNORECASE)
        and _has_announcement_signal(combined)
    ):
        # Exact event year, product boundary, and announcement intent were
        # already validated above. Presentation instructions such as "provide
        # clickable URLs" must not dilute an otherwise exact event match.
        return True

    product_tokens: set[str] = set()
    for candidate in selected:
        product_tokens.update(_tokens(str(candidate.get("product") or "")))
    intent_tokens = [
        token for token in query_tokens
        if token not in product_tokens and token not in _STOP_WORDS
    ]
    words = _word_tokens(combined)
    # For a pure "What is <product>?" question, all meaningful query tokens
    # can legitimately be consumed by the resolved product identity. In that
    # case, substantial product-specific evidence is enough; requiring the
    # source to literally say "overview" creates false negatives for product
    # pages and search excerpts that lead directly with the product name.
    if not intent_tokens and len(combined) >= 120:
        return True
    if (
        set(intent_tokens).issubset(_OVERVIEW_FILLER_TERMS)
        and len(combined) >= 120
        and any(term in words for term in ("about", "overview", "introduction"))
    ):
        return True
    coverage = sum(
        1 for token in intent_tokens if _token_matches(token, words)
    ) / max(1, len(intent_tokens))
    source_agreement = any(
        {"bm25", "vector"}.issubset(set(candidate.get("_sources") or []))
        for candidate in selected
    )
    required_coverage = 0.55 if source_agreement else 0.45
    return coverage >= required_coverage


def _intent_evidence_satisfied(query: str, evidence: str) -> bool:
    lowered = query.lower()
    words = _word_tokens(evidence)
    if _is_version_listing_query(query):
        return "version" in words and bool(re.search(r"\b\d+(?:\.\d+)*(?:\.x)?\b", evidence))
    if "usecase" in lowered.replace(" ", "") or "use case" in lowered:
        if "use case" not in evidence and "use cases" not in evidence:
            return False
    command_requested = bool(re.search(
        r"\b(?:command|commands|cli|cpd-cli|powershell)\b",
        lowered,
    )) or "documented steps" in lowered
    rotation_requested = _rotation_requested(lowered)
    if command_requested:
        command_snippets = _command_snippets(evidence)
        command_signal = bool(command_snippets)
        automatic_lifecycle_signal = _has_automatic_lifecycle_signal(evidence)
        if rotation_requested and command_signal and not automatic_lifecycle_signal:
            # A status/inspection command next to generic prose about rotation
            # is not a rotation procedure.  The actual command must name the
            # lifecycle action or the TLS/certificate object it changes.
            command_signal = any(
                re.search(
                    r"\b(?:rotat(?:e|es|ed|ing|ion|ions)|renew(?:al|s|ed|ing)?|"
                    r"refresh(?:es|ed|ing)?|internal[-_ ]tls|certificat\w*)\b",
                    snippet,
                )
                for snippet in command_snippets
            )
        if not command_signal and not automatic_lifecycle_signal:
            return False
    if "install" in lowered:
        if not any(term in evidence for term in (
            "install", "installation", "prerequisite", "getting started",
        )):
            return False
    if rotation_requested:
        if not re.search(
            r"\b(?:rotat(?:e|es|ed|ing|ion|ions)|renew(?:al|s|ed|ing)?|"
            r"refresh(?:es|ed|ing)?|updat(?:e|es|ed|ing))\b",
            evidence,
        ):
            return False
    if "tls" in lowered and "tls" not in words:
        return False
    if "certificate" in lowered and not any(
        word.startswith("certificat") for word in words
    ):
        return False
    if _has_announcement_signal(lowered) and not _has_announcement_signal(evidence):
        return False
    return True


def _requires_coherent_candidate(query: str) -> bool:
    """Return whether one source must independently support the request.

    Comparisons and portfolio listings intentionally aggregate sources.  In
    contrast, command/procedure questions and dated announcements become
    unsafe when their topic and action signals come from unrelated chunks.
    """
    lowered = query.casefold()
    command_or_procedure = bool(re.search(
        r"\b(?:command|commands|cli|cpd-cli|powershell|procedure|procedures|"
        r"instruction|instructions)\b",
        lowered,
    )) or "documented steps" in lowered
    dated_announcement = bool(
        re.search(r"\bthink\s+20\d{2}\b", lowered)
        and _has_announcement_signal(lowered)
    )
    return command_or_procedure or _rotation_requested(lowered) or dated_announcement


def _rotation_requested(text: str) -> bool:
    """Recognize grammatical variants without substring false positives."""
    return bool(re.search(
        r"\brotat(?:e|es|ed|ing|ion|ions)\b|\brenew(?:al|s|ed|ing)?\b|"
        r"\brefresh(?:es|ed|ing)?\b",
        text,
    ))


def _has_automatic_lifecycle_signal(evidence: str) -> bool:
    """Recognize explicit automatic/scheduled certificate lifecycle prose."""
    return bool(re.search(
        r"\b(?:"
        r"automatically\s+(?:renew(?:s|ed)?|rotat(?:es|ed)?|refresh(?:es|ed)?|"
        r"updat(?:es|ed)?)|"
        r"(?:internal[-_ ]tls|certificat\w*)\b.{0,100}\b(?:is|are)\s+"
        r"(?:automatically\s+)?(?:renewed|rotated|refreshed|updated)|"
        r"(?:renewal|rotation|refresh)\s+(?:happens?|occurs?|is\s+performed)|"
        r"(?:renew|rotat|refresh|updat)\w*\s+every\s+\d+\s+days?|"
        r"no\s+longer\s+required|not\s+required"
        r")\b",
        evidence,
    ))


def _command_snippets(evidence: str) -> list[str]:
    """Extract command-bearing lines/blocks for action-specific validation."""
    snippets: list[str] = []
    snippets.extend(
        match.group(1).strip()
        for match in re.finditer(
            r"```(?:[a-z0-9_+.-]+\n)?(.*?)```",
            evidence,
            re.DOTALL | re.IGNORECASE,
        )
        if match.group(1).strip()
    )
    command_pattern = re.compile(
        r"(?im)^\s*(?:[-*]\s+)?(?:\$\s*)?"
        r"(?:oc|kubectl|cpd-cli|podman|docker|pip|npm|dnf|yum|apt|brew|"
        r"ibmcloud|curl)\b[^\n]*"
    )
    snippets.extend(match.group(0).strip() for match in command_pattern.finditer(evidence))
    # Search excerpts often render an inline command without preserving its
    # original line break or Markdown fence.
    inline_pattern = re.compile(
        r"\b(?:oc|kubectl|cpd-cli|podman|docker|pip|npm|dnf|yum|apt|brew|"
        r"ibmcloud|curl)\s+[a-z0-9_$'{\"-][^.;\n]{0,180}",
        re.IGNORECASE,
    )
    snippets.extend(match.group(0).strip() for match in inline_pattern.finditer(evidence))
    return list(dict.fromkeys(snippets))


def _has_announcement_signal(text: str) -> bool:
    """Recognize common wording used by IBM event/newsroom pages."""
    return bool(re.search(
        r"\b(?:announc(?:e|es|ed|ement|ements|ing)|"
        r"unveil(?:s|ed|ing)?|reveal(?:s|ed|ing)?|"
        r"introduc(?:e|es|ed|ing|tion)|launch(?:es|ed|ing)?|"
        r"debut(?:s|ed|ing)?|releas(?:e|es|ed|ing)|"
        r"present(?:s|ed|ing)?|deliver(?:s|ed|ing)?|"
        r"expand(?:s|ed|ing)?)\b",
        text,
    ))


def _literal_facets_are_satisfied(query: str, evidence: str) -> bool:
    """Require exact high-value identifiers that semantic similarity can blur."""
    normalized_query = query.casefold()
    normalized_evidence = evidence.casefold()
    years = set(re.findall(r"\b20\d{2}\b", normalized_query))
    if any(year not in normalized_evidence for year in years):
        return False
    dotted_identifiers = {
        token
        for token in re.findall(r"\b[a-z][a-z0-9-]*(?:\.[a-z0-9-]+)+\b", normalized_query)
        if not re.fullmatch(r"\d+(?:\.\d+)+(?:\.x)?", token)
    }
    return all(identifier in normalized_evidence for identifier in dotted_identifiers)


def _portfolio_evidence_satisfied(family: str, evidence: str) -> bool:
    normalized = " ".join(evidence.casefold().split())
    if family == "watsonx":
        offering_patterns = {
            "watsonx.ai": r"\bwatsonx\.ai\b",
            "watsonx.data": r"\bwatsonx\.data\b",
            "watsonx.data integration": r"\bwatsonx\.data\s+integration\b",
            "watsonx.data intelligence": r"\bwatsonx\.data\s+intelligence\b",
            "watsonx BI": r"\bwatsonx\s+bi\b",
            "watsonx Orchestrate": r"\bwatsonx\s+orchestrate\b",
            "IBM Bob": r"\bibm\s+bob\b",
            "watsonx Code Assistant": r"\bwatsonx\s+code\s+assistant\b",
            "watsonx.governance": r"\bwatsonx\.governance\b",
        }
        matched = {
            name for name, pattern in offering_patterns.items()
            if re.search(pattern, normalized)
        }
        return len(matched) >= 3

    catalog_categories = (
        "artificial intelligence",
        "business operation",
        "compute",
        "data and analytics",
        "ibm cloud",
        "ibm z",
        "security",
        "storage",
        "technology business management",
    )
    category_count = sum(category in normalized for category in catalog_categories)
    return "product categories" in normalized and category_count >= 4


def _is_version_listing_query(query: str) -> bool:
    lowered = query.lower()
    return any(phrase in lowered for phrase in (
        "versions available", "available versions", "what versions",
        "which versions", "list versions", "documentation versions",
    ))


def _comparison_versions(query: str) -> set[str]:
    lowered = query.lower()
    if not any(term in lowered for term in (
        " between ", " compared to ", " compare ", " difference ", " changed ",
    )):
        return set()
    return set(re.findall(r"\b\d+\.\d+\b", lowered))


def _candidate(
    document: ExtractedDocument,
    chunk: ChunkRecord,
    target: CrawlTarget,
    origin: str,
    score: float,
) -> dict:
    digest = hashlib.sha256(
        f"{document.canonical_url}:{document.content_hash}:{chunk.chunk_ordinal}".encode()
    ).hexdigest()[:20]
    source_id = str(document.metadata.get("source_id") or "ibm-docs")
    return {
        "chunk_id": f"{target.domain_id}:live:{digest}",
        "document_id": document.document_id,
        "title": document.title,
        "domain_id": target.domain_id,
        "product": target.product_name,
        "product_version": target.product_version,
        "ocp_version": None,
        "source_uri": document.canonical_url,
        "source_type": "ibm_docs" if source_id == "ibm-docs" else "official_product_docs",
        "source_id": source_id,
        "document_type": target.document_type,
        "classification": target.classification,
        "access_scope": list(target.access_scope),
        "section_path": chunk.section_path,
        # Pseudo-pages are extraction groups, not real web page numbers.
        "page_start": None,
        "page_end": None,
        "chunk_ordinal": chunk.chunk_ordinal,
        "chunk_text": chunk.text,
        "content_hash": chunk.content_hash,
        "chunker_version": chunk.chunker_version,
        "retrieval_origin": origin,
        "_live_score": round(score, 4),
    }


def _tokens(text: str) -> list[str]:
    output: list[str] = []
    for token in dict.fromkeys(_TOKEN_RE.findall(text.lower())):
        expanded = ("use", "case") if token in {"usecase", "usecases"} else (token,)
        for value in expanded:
            if value not in _STOP_WORDS and len(value) > 1 and value not in output:
                output.append(value)
    return output[:30]


def _word_tokens(text: str) -> set[str]:
    return {token.lower() for token in re.findall(r"[a-z0-9]+", text.lower())}


def _token_matches(token: str, words: set[str]) -> bool:
    if len(token) <= 3:
        return token in words
    return any(
        word == token or word.startswith(token) or token.startswith(word)
        for word in words
    )
