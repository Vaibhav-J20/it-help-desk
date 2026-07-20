# IBM Documentation crawler

## Status

Implemented locally as two compatible modes:

- metadata-first adaptive retrieval for the normal chatbot path; and
- the existing full/bounded batch crawler for audits, prewarming, and backfills.

The metadata layer is no longer limited to products manually listed in the
registry. `catalog-global` starts at the public IBM Docs sitemap index and
expands every listed child sitemap into a durable graph:

```text
IBM Docs root -> product -> version/model -> sitemap -> canonical topic URL
```

This global pass downloads sitemap XML only. It does not request topic page
bodies, create chunks, generate embeddings, or write OpenSearch documents.
Product identity is normalized by the union of canonical product paths and
versioned IBM content-key families. Content keys, releases, and hardware models
become version nodes. This keeps model-specific sitemaps under one product path
and also connects renamed product generations that retain one content family,
instead of incorrectly treating every sitemap as a new product.

The first complete global metadata build finished on 2026-07-16 with:

- 1,190 normalized IBM Docs products;
- 3,813 product-version/model sitemap targets;
- 7,170,623 canonical topic URL records;
- 7,178,708 graph nodes; and
- 7,179,914 graph edges.

All 1,190 products have exactly one target marked as their latest available
version. No sitemap reached the configured 500,000-URL safety ceiling. The
catalog also preserves 732 useful topic records from the earlier bounded
`version_id: latest` pilot; those legacy records are searchable but are not
counted as global product-version targets. As designed, this build downloaded
no topic page bodies, generated no embeddings, and wrote nothing to OpenSearch.

IBM robots policy excludes `/docs/api`, so the global builder does not call or
bypass that endpoint. Exact page-to-page related/parent/child edges are added
organically when a selected page is fetched during a bounded live query. Until
then, sitemap membership is the authoritative topic relationship.

The adaptive path is feature-flagged off by default. After the local validation
described below, it is enabled in this workstation's `.env`; the local serving
indices are `knowledge_chunks_v2` and `knowledge_documents_v2`, while background
live-document writes still target only the explicit IBM Docs staging indices.
Live web search remains disabled until a provider credential or approved search
gateway is configured. Shared deployments must make their own explicit rollout
decision. The v1 indices remain intact as a rollback target.

Validated on 2026-07-14 with a bounded ten-product pilot:

- 10 products crawled and indexed successfully;
- 100 current IBM Docs pages stored as documents;
- 544 chunks embedded with
  `ibm/granite-embedding-278m-multilingual` at 768 dimensions;
- zero failed products and zero missing vectors;
- 100 of 100 documents passed the structural index audit;
- product-filtered BM25 and vector retrieval returned relevant installation,
  command, and administration evidence.

The validated corpus is isolated in
`knowledge_chunks_ibm_docs_staging_v2` and
`knowledge_documents_ibm_docs_staging_v2`. It has not replaced or been merged
into the existing v1 serving corpus.

Metadata-first validation on 2026-07-15 cataloged 7,603 official page records:
1,008 for watsonx Orchestrate, 130 for IBM Bob, 2,279 for Guardium Data
Protection, 1,159 for Instana, 125 for Verify Access developer documentation,
2,700 for Cloud Pak for Data, and 202 for Cloud Pak for Integration. Catalog
discovery downloaded zero page bodies, created zero chunks, generated zero
embeddings, and made zero OpenSearch writes.

The separate `orchestrate-adk` adapter was then validated with the question
"How do I install the watsonx Orchestrate ADK CLI on Windows? Give me the
commands." The corrected metadata selector fetched only the official
`getting_started/installing.md` page. It preserved the pip command, virtual
environment commands, Windows activation paths, and Orchestrate environment
commands in 28 structure-aware chunks. The immediate repeat produced one cache
hit, zero network requests, and zero failed pages.

After review, bounded pages were embedded into the isolated staging indices.
The final staging corpus contains 721 chunks and 117 document records. The
validated v2 serving corpus contains 14,609 current searchable chunks and 316
document records. A structural audit sampled every document with current chunks:
313 passed and zero failed. The original v1 indices were not modified.

The OCP Storage 4.16 PDF was reprocessed with chunker-v6 into v2. All 277
non-empty pages produced 520 current chunks and zero failed pages; 20 oversized
provider inputs were recovered by the adaptive split-and-retry path. The prior
577-chunk revision remains non-current for audit history.

The final product acceptance run is
`tests/evaluation/results/product_questions_eval_20260715T110949Z.json`.
Orchestrate, IBM Bob, OpenShift 4.16, Guardium Data Protection 12.x, Instana,
Verify Access, Cloud Pak for Data 5.4.x, and Cloud Pak for Integration 16.1.3
all returned `ANSWERED`, six citations, the correct product, and the required
command or procedural concepts: 8 of 8 passed.

The full chatbot graph also returned `ANSWERED` for the Windows ADK installation
question. Its six evidence slots and six citations all came from the official
installation page, and the answer reproduced the Python version check, pip,
virtual-environment creation, and Windows activation commands. Cross-source
selection now returns only the chosen confident cache source, preventing a
high-scoring but unrelated IBM Docs code block from entering the answer context.

A Guardium regression run on 2026-07-15 also validates explicit platform and
version handling. A question-only Windows installation request bypassed the
Linux-only serving-index hits, retrieved Windows S-TAP documentation live, and
returned `ANSWERED` with four IBM Docs citations. A request for Guardium 11.8
returned `NEEDS_CLARIFICATION` with the registered 12.x version instead of
incorrectly returning `OUT_OF_SCOPE`. The recorded run is
`tests/evaluation/results/guardium_regression_questions_eval_20260715T114913Z.json`.

The registry supports any IBM product with an exact IBM Docs product/version
path and sitemap. Under adaptive retrieval, the full page corpus no longer has
to be downloaded and embedded before the chatbot is useful. A metadata catalog
finds likely pages, then a cold query fetches no more than five page bodies and
one related-link hop. Warm queries reuse normalized disk cache and, when enabled,
the existing OpenSearch vector index.

This substantially improves time-to-first-answer, but it is not a promise that
every possible question can be answered. The answer remains evidence-only:
missing or weak evidence must produce `INSUFFICIENT_EVIDENCE`, not a guess.

## Implemented flow

```text
Stage 1 — metadata only
public IBM Docs root sitemap or an enabled registry/official-source target
    -> expand product/version sitemap XML or an allowlisted official llms.txt index
    -> URL + canonical URL + topic + version + last-modified metadata
    -> root/product/version/sitemap/topic nodes
    -> SQLite FTS catalog + relationship-edge table
    -> zero product page bodies, chunks, embeddings, or OpenSearch writes

Stage 2 — query time
resolve product/version against registry overrides, then the global graph
    -> normalized disk cache
    -> existing OpenSearch BM25 + vector retrieval
    -> accept only evidence that covers the requested topic and intent
    -> search the selected product/version topic URLs in the metadata catalog
    -> fetch 3 pages initially, at most 5 total, at most 1 related hop
    -> heading/code/list/table extraction
    -> token-aware chunking and relevant-section ranking
    -> grounded answer immediately
    -> durable raw/normalized cache
    -> optional background embedding into the existing OpenSearch indices
    -> optional allowlisted official-web search only if evidence is still weak

Batch compatibility path
registry -> bounded/full crawl -> audit -> explicit staging index -> promotion
```

The batch crawler still never indexes while fetching. Query-time live retrieval
may schedule indexing only when `ENABLE_LIVE_DOCS_INDEXING=true`; this is separate
from answering the cold request and is disabled during initial rollout.

## Repository file architecture

```text
app/
├── ingestion/
│   ├── chunker.py                         # chunker-v6 token/structure budget
│   ├── indexer.py                         # embedding split/retry and index overrides
│   ├── ibm_docs_crawler/
│       ├── __init__.py                    # package exports
│       ├── catalog.py                     # SQLite FTS catalog + graph edges
│       ├── catalog_discovery.py           # sitemap-only metadata discovery
│       ├── global_discovery.py            # root -> all product/version sitemaps
│       ├── config.py                      # environment/runtime limits
│       ├── crawler.py                     # enabled crawl -> durable staging
│       ├── extractor.py                   # HTML -> headings/code/lists/tables/links
│       ├── fetcher.py                     # concurrent-safe rate limit + bounded HTTP
│       ├── models.py                      # typed crawl/fetch/document records
│       ├── promotion.py                   # audited run -> staging indices only
│       ├── registry.py                    # target allowlist and sitemap validation
│       ├── robots.py                      # fail-closed robots.txt enforcement
│       ├── sitemap.py                     # bounded recursive sitemap discovery
│       ├── storage.py                     # SQLite + immutable artifacts
│       └── urls.py                        # canonicalization and exact path scope
│   └── official_docs/
│       ├── discovery.py                   # llms.txt/XML sitemap -> metadata catalog
│       ├── extractor.py                   # Markdown/MDX/HTML -> structured evidence
│       ├── fetcher.py                     # exact-host robots-aware page fetching
│       ├── registry.py                    # allowlisted official source adapters
│       └── urls.py                        # HTTPS host/path boundary enforcement
├── graph/nodes/
│   ├── compose_answer.py                  # IBM product-version evidence labels
│   ├── retrieve.py                        # feature-flagged adaptive router entry
│   ├── resolve_scope.py                   # registry + global-product routing
│   └── validate_citations.py              # source URL/product-version citations
├── retrieval/
│   ├── adaptive_router.py                 # cache -> index -> live docs -> web
│   ├── catalog_selector.py                # product/version/intent page ranking
│   ├── constraints.py                     # explicit OS/platform evidence facets
│   ├── live_docs.py                       # <=5 pages, <=1 related hop, cache reuse
│   ├── live_index.py                      # optional background index write
│   ├── official_docs.py                   # bounded official Markdown retrieval
│   ├── section_ranker.py                  # relevant section/command ranking
│   └── web_search.py                      # allowlisted gateway/OpenAI web adapters
└── prompts/
    ├── classify_extract.md                # generic enabled IBM product domain
    └── grounded_answer.md                 # exact-command response rules

config/
├── ibm_docs_registry.yaml                 # exact product/version/sitemap allowlist
├── official_doc_sources.yaml              # exact official host/index adapters
├── domains.yaml                           # generic ibm_products retrieval domain
└── taxonomy/ocp_sno.yaml                  # controlled shared metadata values

scripts/
├── crawl_ibm_docs.py                      # IBM + official-source plan/catalog/retrieve
├── crawl_ibm_docs_portfolio.py            # bounded multi-product crawl + index
└── create_index.py                        # supports explicit staging index names

tests/
├── conftest.py                             # isolates tests from local live flags
└── unit/
    ├── test_adaptive_retrieval.py         # catalog/cache/live/router/web boundaries
    ├── test_chunker.py                    # dense command/token-budget coverage
    ├── test_indexer.py                    # adaptive length-error recovery
    ├── test_ibm_docs_crawler.py           # registry, URL, HTML, HTTP, sitemap, storage
    └── test_official_docs.py              # llms, Markdown, source routing, cold/warm
```

## Host data architecture

The default is `~/.local/share/it-helpdesk/ibm-docs-crawler`. Override it with
`IBM_DOCS_DATA_DIR`. It is a host directory, not container or Podman Machine
storage.

```text
ibm-docs-crawler/
├── state/
│   └── crawl.sqlite3
├── raw/
│   └── <run-id>/<document-prefix>/<document-id>.(html|md)
├── normalized/
│   ├── documents/<run-id>/<document-id>.json
│   └── chunks/<run-id>/<document-id>.jsonl
└── runs/
    └── <run-id>.json
```

`run_pages` uses `(run_id, url)` as its primary key, so a refresh does not erase
prior-run history. Artifacts are per document rather than append-only global
JSONL files, so reruns cannot silently duplicate every old record.

The same SQLite database also contains `catalog_pages`, its FTS5 index, and
`catalog_edges`. `resources` records ETag, Last-Modified, content hash, and the
current raw/normalized artifact paths. A cache hit therefore avoids both the
network request and the embedding call. A stale entry is revalidated and HTTP
304 reuses its existing artifacts.

This host directory should also be backed up to an approved durable store such
as IBM COS before a Podman Machine reset. Nothing in the Podman VM is a source
of truth.

## What preserves command and troubleshooting quality

- HTML `<pre><code>` and Markdown fenced-code blocks retain line breaks,
  capitalization, flags, paths, environment variables, and language hints.
- Inline code is retained with backticks.
- Tables become Markdown tables instead of flattened word sequences.
- Lists remain ordered/unordered procedures.
- Heading paths remain attached to every chunk.
- Chunker v6 budgets punctuation and long identifiers instead of assuming a
  fixed characters-per-token ratio.
- If the embedding provider still reports an input-length error, the indexer
  recursively splits only that chunk and retries it. Transient/provider errors
  are recorded rather than incorrectly treated as length errors.
- The answer prompt requires exact commands from evidence, separates commands
  from output/configuration, and forbids mixing product versions.
- Explicit OS/platform terms in the question are mandatory retrieval facets.
  For example, Linux/UNIX-only evidence cannot satisfy a Windows request even
  when both BM25 and vector search rank it highly.
- Absence from the retrieved pages is never treated as proof that a platform is
  unsupported. Negative support claims require an explicit cited statement.
- A recognized product with an unregistered version produces
  `NEEDS_CLARIFICATION` and lists the registered versions; it is not classified
  as an unknown or out-of-scope product.
- Every answer remains evidence-only and citation-validated.

These controls make the pipeline suitable for factual documentation, system
requirements, installation, configuration, CLI/API usage, troubleshooting,
reference material, and release notes. Coverage is measured by product/version
audits and evaluation questions, not by page count alone.

## Governance and safety controls

1. New versions default to `crawl_enabled: false` until their exact path, seed,
   and public sitemap are configured.
2. IBM Docs accepts only `https://www.ibm.com/docs/...`. Additional official
   sources require an explicit record in `config/official_doc_sources.yaml`;
   the current adapter accepts only `developer.watson-orchestrate.ibm.com`.
3. `/docs/api` is hard-blocked and robots.txt is enforced fail-closed.
   Redirects for robots.txt must canonicalize back to `/robots.txt`; another
   same-host page is not accepted as a robots policy document.
4. Credentials, custom ports, non-IBM redirects, and paths outside the exact
   product prefix are rejected.
5. Redirects are validated before every next request.
6. Responses are streamed and stopped at `IBM_DOCS_MAX_RESPONSE_BYTES`.
7. The minimum delay is one second; retries use capped backoff.
8. HTML that is suspiciously short is rejected. The crawler does not bypass
   policy by calling an undocumented/disallowed API when a page is client-rendered.
9. Sitemap entries that return 404/410, lose their topic during a redirect, or
   contain unusably short content are recorded as `SKIPPED`; the crawler keeps
   looking for the requested number of valid pages within a bounded attempt
   budget.
10. A single extracted page is capped at 250 chunks by default, preventing an
    anomalous redirect or malformed page from consuming an unbounded embedding
    budget.
11. Indexing accepts only a clean `STAGED` run and index names containing
    `staging`.
12. Metadata for every staged document is taxonomy-validated before the first
    OpenSearch write. Missing artifacts for an `UNCHANGED` page block promotion
    instead of silently omitting that document.
13. Production alias promotion remains a separate, validated operation.
14. Adaptive IBM Docs retrieval is capped at five pages, three concurrent
    workers by default, and one related-link hop. It never recursively crawls
    the product at query time.
15. Official-web fallback accepts only HTTPS results from configured domains.
    It is disabled unless an approved JSON search gateway or an OpenAI Responses
    API credential and the feature flag are configured. Third-party domains are
    not enabled by default.
16. Official-source discovery accepts only registered `llms.txt` or sitemap
    links on the exact HTTPS host. Cross-host links, credentials, ports,
    traversal paths, disallowed robots paths, and targets with the wrong content
    format are rejected before retrieval.

## Registry workflow

The IBM Docs registry remains an operational override for pre-approved,
prewarmed, or specially configured targets. It currently contains watsonx
Orchestrate plus thirteen
sitemap-backed portfolio products: IBM MQ, API Connect, Db2, WebSphere
Application Server, Storage Scale, Cloud Pak for Data, Storage Protect,
Security Verify Access, App Connect Enterprise, DataPower Gateway, Guardium
Data Protection, Instana Observability, and Cloud Pak for Integration. IBM Bob
and the Verify Access developer site are registered official-source adapters.

Inspect any target without network access:

```bash
.venv/bin/python scripts/crawl_ibm_docs.py plan \
  --product ibm-mq \
  --version latest
```

Every enabled version records an exact product sitemap:

```yaml
sitemap_url: https://www.ibm.com/docs/en/SSFKSJ_9.4.0/0/sitemap.xml
crawl_enabled: true
```

Adding a registry record is not required for a public IBM Docs product already
present in the global graph. Add one only when the product needs an explicit
operational override with:

- a stable `product_id`;
- the canonical `product_name` used by the existing corpus and retrieval filter;
- the controlled `document_type`, `classification`, and `access_scope` values;
- `domain_id: ibm_products` unless it already has a dedicated domain;
- exact `docs_path_prefix` and `seed_url` values verified in a browser;
- aliases users actually type;
- a conservative `max_pages`;
- one explicit version entry and its public product sitemap.

## Metadata-first operating sequence

Build or refresh the complete public IBM Docs link graph. This follows the
public root and child sitemaps and stores metadata only:

```bash
.venv/bin/python scripts/crawl_ibm_docs.py catalog-global --concurrency 6
```

`catalog-global` performs the normalization/finalization pass automatically at
the end. If a process was interrupted after storing sitemap records, the same
idempotent finalization can be run explicitly:

```bash
.venv/bin/python scripts/crawl_ibm_docs.py catalog-finalize
```

Optional bounded discovery for diagnostics is available with
`--max-sitemaps` and `--max-urls-per-sitemap`; the latter defaults to a bounded
500,000 URLs for unusually large product sitemaps. `--content-key` can be
repeated to refresh only exact large or previously failed targets. Completed
sitemap targets whose
root `lastmod` value has not changed are skipped on a resumed/refresh run; use
`--force-refresh` only when every sitemap must be reread. Duplicate root entries
are processed once. Large sitemap XML has its own bounded 100 MB ceiling while
topic-page responses retain the stricter normal limit. A root entry that has
become unavailable is recorded in the final report; it is never replaced with
a guessed URL.

Build a complete lightweight catalog for one product. This downloads sitemap
XML but no documentation page bodies and creates no embeddings:

```bash
export IBM_DOCS_USER_AGENT='IBM-IT-Helpdesk-DocsCrawler/1.0 contact@example.com'
export IBM_DOCS_DATA_DIR="$HOME/.local/share/it-helpdesk/ibm-docs-crawler"

.venv/bin/python scripts/crawl_ibm_docs.py catalog \
  --product ibm-mq \
  --version latest
```

Inspect catalog counts:

```bash
.venv/bin/python scripts/crawl_ibm_docs.py catalog-stats --product ibm-mq
```

Catalog every enabled product/version in the registry in one metadata-only run:

```bash
.venv/bin/python scripts/crawl_ibm_docs.py catalog-all
```

For a smaller rollout, repeat `--product`:

```bash
.venv/bin/python scripts/crawl_ibm_docs.py catalog-all \
  --product watsonx-orchestrate \
  --product ibm-mq \
  --product cloud-pak-data
```

Catalog a registered official source. Discovery reads only its registered
metadata index (`llms.txt` or XML sitemap); it does not download page bodies:

```bash
.venv/bin/python scripts/crawl_ibm_docs.py source-plan \
  --source orchestrate-adk

.venv/bin/python scripts/crawl_ibm_docs.py source-catalog \
  --source orchestrate-adk
```

Run a bounded source retrieval directly for diagnostics. The first run may
fetch the selected page; the repeat should report `network_fetches: 0` and
`cache_hits: 1`:

```bash
.venv/bin/python scripts/crawl_ibm_docs.py source-retrieve \
  --source orchestrate-adk \
  --query 'How do I install the watsonx Orchestrate ADK CLI on Windows?' \
  --max-pages 1 \
  --no-related \
  --summary
```

After reviewing the retrieved evidence, an operator can explicitly embed it
into staging. This command refuses index names that do not contain `staging`:

```bash
.venv/bin/python scripts/crawl_ibm_docs.py source-retrieve \
  --source orchestrate-adk \
  --query 'How do I install the watsonx Orchestrate ADK CLI on Windows?' \
  --max-pages 1 \
  --no-related \
  --summary \
  --index-staging \
  --chunks-index knowledge_chunks_ibm_docs_staging_v2 \
  --docs-index knowledge_documents_ibm_docs_staging_v2
```

Enable the adaptive read path only after catalog search tests pass:

```dotenv
ENABLE_ADAPTIVE_RETRIEVAL=true
ENABLE_LIVE_IBM_DOCS=true
ENABLE_LIVE_OFFICIAL_SOURCES=true
ENABLE_LIVE_DOCS_INDEXING=false
ENABLE_LIVE_WEB_SEARCH=false
```

The first matching query resolves the product/version in the global graph,
checks normalized cache, then the current OpenSearch indices. If evidence does
not cover the requested topic and intent, it selects relevant graph URLs and
fetches those official pages. The answer uses only relevant extracted sections
and every fetched artifact is cached. A subsequent query can answer from disk
cache without a network call. After validating the
target OpenSearch index names and embedding model, enable background indexing:

```dotenv
LIVE_DOCS_CHUNKS_INDEX=knowledge_chunks_ibm_docs_staging_v2
LIVE_DOCS_DOCS_INDEX=knowledge_documents_ibm_docs_staging_v2
ENABLE_LIVE_DOCS_INDEXING=true
```

Both index names are mandatory when background indexing is enabled. The router
will answer and cache normally but refuse to schedule an index write when either
name is blank, so it cannot silently fall back to the serving-index variables.

The optional internet-search module supports Tavily, an approved HTTPS JSON
gateway, or the OpenAI Responses API `web_search` tool. It never scrapes
search-result HTML.
Results are domain-allowlisted and labeled `official_live_web` in evidence and
citations. Configure exactly one provider before enabling it.

Tavily provider configuration (the recommended free-tier pilot path):

```dotenv
LIVE_WEB_SEARCH_PROVIDER=tavily
LIVE_WEB_SEARCH_ENDPOINT=https://api.tavily.com/search
LIVE_WEB_SEARCH_API_KEY=<secret>
LIVE_WEB_SEARCH_ALLOWED_DOMAINS=www.ibm.com,support.ibm.com,cloud.ibm.com,redbooks.ibm.com,docs.redhat.com,access.redhat.com,developers.redhat.com
ENABLE_LIVE_WEB_SEARCH=true
```

```dotenv
LIVE_WEB_SEARCH_ENDPOINT=https://approved-search-gateway.example/query
LIVE_WEB_SEARCH_ALLOWED_DOMAINS=www.ibm.com,support.ibm.com,cloud.ibm.com,redbooks.ibm.com,docs.redhat.com,access.redhat.com,developers.redhat.com
ENABLE_LIVE_WEB_SEARCH=true
```

OpenAI provider configuration:

```dotenv
LIVE_WEB_SEARCH_PROVIDER=openai
LIVE_WEB_SEARCH_MODEL=gpt-5.5
LIVE_WEB_SEARCH_API_KEY=<secret>
LIVE_WEB_SEARCH_ALLOWED_DOMAINS=www.ibm.com,support.ibm.com,cloud.ibm.com,redbooks.ibm.com,docs.redhat.com,access.redhat.com,developers.redhat.com
ENABLE_LIVE_WEB_SEARCH=true
```

Configure those values safely with the interactive helper. It prompts for the
API key without echoing it and updates the git-ignored `.env` atomically:

```bash
.venv/bin/python scripts/configure_live_web_search.py --provider tavily
.venv/bin/python scripts/configure_live_web_search.py --check
```

An optional paid live probe verifies the provider and allowlist after setup:

```bash
.venv/bin/python scripts/configure_live_web_search.py --probe
```

The API response exposes `retrieval_provenance`, `source_urls`, and
`suggested_next_steps`; each citation also exposes `retrieval_source`.
`answer_markdown` begins with a visible knowledge-source banner and ends with a
backend-rendered Sources section containing validated clickable URLs. Together
these fields show whether an answer cited pre-existing OpenSearch knowledge, the
IBM Docs cache, live official-page retrieval, internet search, or a combination.
Internet search returns source-linked search evidence; it is not a full-site
crawler and does not replace IBM Docs extraction or the durable cache.

The runtime order is deterministic:

1. Search the existing OpenSearch corpus.
2. Reuse relevant cached official pages and query the metadata catalog.
3. Fetch a bounded set of candidate official documentation pages live.
4. If the evidence is still insufficient, query the configured allowlisted
   internet-search provider.

An exhausted search remains non-fabricating. Instead of returning a dead-end
"I don't have information" sentence, the service reports the retrieval paths
that were attempted, provides any relevant official links it did find, and asks
for the product/version/environment detail needed for a stronger retry.

The live-source flags are independent: IBM Docs and registered official-source
retrieval can run without general web search, and web search cannot silently
activate just because adaptive retrieval is enabled.

## Pilot operating sequence

Set a user agent with a monitored contact before any network operation:

```bash
export IBM_DOCS_USER_AGENT='IBM-IT-Helpdesk-DocsCrawler/1.0 contact@example.com'
export IBM_DOCS_DATA_DIR="$HOME/.local/share/it-helpdesk/ibm-docs-crawler"
```

Run the ten-product, ten-pages-per-product portfolio pilot and index only clean
runs into isolated staging indices:

```bash
.venv/bin/python scripts/crawl_ibm_docs_portfolio.py \
  --max-pages-per-product 10 \
  --index \
  --chunks-index knowledge_chunks_ibm_docs_staging_v2 \
  --docs-index knowledge_documents_ibm_docs_staging_v2
```

Audit the returned run ID:

```bash
.venv/bin/python scripts/crawl_ibm_docs.py audit --run-id '<run-id>'
```

Inspect raw HTML, normalized JSON, chunks, failed pages, titles, section paths,
code blocks, tables, duplicate URLs, and product/version metadata. A pilot should
not advance with extraction failures or missing command blocks.

The portfolio command writes a JSON run manifest under `runs/`. Audit every run
ID before increasing `--max-pages-per-product`. A full crawl still respects each
registry `max_pages` ceiling.

## Staging-index sequence

Create separate indices. Do not use `--recreate` against the live indices.

```bash
.venv/bin/python scripts/create_index.py \
  --chunks-index knowledge_chunks_ibm_docs_staging_v2 \
  --docs-index knowledge_documents_ibm_docs_staging_v2
```

Index a clean crawl run:

```bash
.venv/bin/python scripts/crawl_ibm_docs.py index-staging \
  --product ibm-mq \
  --version latest \
  --run-id '<run-id>' \
  --chunks-index knowledge_chunks_ibm_docs_staging_v2 \
  --docs-index knowledge_documents_ibm_docs_staging_v2
```

The embedding model must be the confirmed 768-dimensional
`ibm/granite-embedding-278m-multilingual`. Missing credentials fail closed;
zero-vector embeddings require an explicit isolated-test flag in the general
ingestion CLI and are never acceptable for a searchable corpus.

Before production promotion, verify:

- zero failed documents and zero unrecovered embedding failures;
- vector dimension and embedding model are uniform;
- no URL escaped the enabled product/version path;
- commands and code fences match the raw official page;
- BM25/vector retrieval finds exact commands and product facts;
- installation, configuration, troubleshooting, version ambiguity, and
  insufficient-evidence evaluations pass;
- citations contain the official source URL and correct product version;
- a snapshot and artifact backup exist;
- the production promotion decision and rollback target are recorded.

The index-level structural audit can be run against staging with:

```bash
.venv/bin/python scripts/audit_chunks.py \
  --index knowledge_chunks_ibm_docs_staging_v2 \
  --no-report
```

Production promotion should be an OpenSearch alias switch or equivalent atomic
deployment step after those checks. It is intentionally not performed by the
crawler command.

## Refresh and deletion behavior

- ETag and Last-Modified values generate conditional requests.
- HTTP 304 records `UNCHANGED`; it does not append duplicate artifacts.
- Changed content creates new per-run artifacts and the indexer creates a new
  revision while superseding old chunks.
- Two URLs with identical content keep distinct document-registry IDs, avoiding
  alias collisions.
- Removed upstream pages are not deleted from production automatically. A
  reviewed deletion/tombstone report must identify them before index changes.

## Local v2 promotion, backup, and rollback

The validated local serving configuration is:

```dotenv
OPENSEARCH_INDEX_CHUNKS=knowledge_chunks_v2
OPENSEARCH_INDEX_DOCS=knowledge_documents_v2
```

The post-validation filesystem snapshot is
`it-helpdesk-20260715t164130`; it completed with 11 successful shards and zero
failures. Snapshot files are stored in the host-mounted OpenSearch snapshot
directory, not solely in the Podman VM. Run another snapshot after a material
corpus update:

```bash
scripts/podman_opensearch.sh snapshot
```

Rollback is configuration-only: stop the API, set the two serving index values
back to `knowledge_chunks_v1` and `knowledge_documents_v1`, and restart. Do not
delete v2 while investigating. Back up both the OpenSearch snapshot directory
and `IBM_DOCS_DATA_DIR` to an approved durable store before resetting the Podman
machine.

Refresh metadata with `catalog-all`. Page bodies are refreshed lazily with
ETag/Last-Modified/content-hash validation on relevant queries. Monitor request
status, selected retrieval stage, cache/network counts, failed pages, background
index errors, OpenSearch cluster health, and product acceptance pass rate.

## Explicit non-goals for this phase

- Crawling all of `ibm.com` without product/version scope.
- Bypassing robots.txt or using `/docs/api`.
- Running JavaScript/browser automation to evade short HTML responses.
- Automatic production index replacement.
- Recursively crawling from a user query.
- Treating search-result snippets as equivalent to a complete product corpus.
- Enabling unapproved third-party domains by default.

## Verification

Run the complete unit suite:

```bash
.venv/bin/python -m pytest tests/unit -q
```

The current unit suite has 185 passing tests. It covers allowlist enforcement,
exact URL scope, redirects, response-size limits, gzip sitemap parsing, catalog
search and graph edges, cold live retrieval, warm cache reuse, command/table
extraction, `llms.txt` parsing, exact-host Markdown retrieval, cross-source
isolation, specialized-page ranking, web-search domain rejection, dense
technical token budgets, and adaptive embedding recovery.

All 11 integration tests also passed on 2026-07-15 against the local
green OpenSearch cluster and configured watsonx embedding service. They verified
BM25 filtering, vector search, and hybrid RRF without changing the live v1 or IBM
Docs staging corpora. The real sitemap/`llms.txt` discovery and public-page
cold/warm smoke tests also passed on 2026-07-15. The eight-product local answer
evaluation passed 8 of 8; a shared deployment must rerun the same gate against
its own credentials, indices, network policy, and access controls.
