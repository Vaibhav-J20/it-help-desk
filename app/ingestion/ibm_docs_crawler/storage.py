"""Durable crawl state plus immutable raw and normalized artifacts."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Iterator
from uuid import uuid4

from app.ingestion.chunker import ChunkRecord

from .models import ExtractedDocument
from .registry import CrawlTarget


@dataclass(frozen=True)
class CachedArtifacts:
    document: dict
    chunks: list[dict]
    fresh: bool
    last_seen_at: str
    content_hash: str | None


class CrawlStorage:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.raw_dir = data_dir / "raw"
        self.documents_dir = data_dir / "normalized" / "documents"
        self.chunks_dir = data_dir / "normalized" / "chunks"
        self.runs_dir = data_dir / "runs"
        self.db_path = data_dir / "state" / "crawl.sqlite3"
        for directory in (
            self.raw_dir, self.documents_dir, self.chunks_dir, self.runs_dir,
            self.db_path.parent,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.connection() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    product_id TEXT NOT NULL,
                    version_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    approval_json TEXT NOT NULL,
                    report_json TEXT
                );
                CREATE TABLE IF NOT EXISTS resources (
                    url TEXT PRIMARY KEY,
                    etag TEXT,
                    last_modified TEXT,
                    content_hash TEXT,
                    raw_path TEXT,
                    document_path TEXT,
                    chunks_path TEXT,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS run_pages (
                    run_id TEXT NOT NULL,
                    url TEXT NOT NULL,
                    status TEXT NOT NULL,
                    http_status INTEGER,
                    content_hash TEXT,
                    raw_path TEXT,
                    document_path TEXT,
                    chunks_path TEXT,
                    error TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (run_id, url),
                    FOREIGN KEY (run_id) REFERENCES runs(run_id)
                );
                CREATE INDEX IF NOT EXISTS idx_run_pages_status
                    ON run_pages(run_id, status);
                """
            )

    def start_run(self, target: CrawlTarget) -> str:
        now = _now()
        run_id = now.replace(":", "").replace("-", "").replace("+00:00", "Z")
        run_id = f"{target.product_id}-{target.version_id}-{run_id}-{uuid4().hex[:8]}"
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO runs (
                    run_id, product_id, version_id, status, started_at, approval_json
                ) VALUES (?, ?, ?, 'RUNNING', ?, ?)
                """,
                (
                    run_id, target.product_id, target.version_id, now,
                    json.dumps(target.run_context, sort_keys=True),
                ),
            )
        return run_id

    def record_discovered(self, run_id: str, url: str) -> None:
        self._upsert_run_page(run_id, url, status="DISCOVERED")

    def cache_headers(self, url: str) -> dict[str, str]:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT etag, last_modified FROM resources WHERE url = ?", (url,)
            ).fetchone()
        headers: dict[str, str] = {}
        if row and row["etag"]:
            headers["If-None-Match"] = row["etag"]
        if row and row["last_modified"]:
            headers["If-Modified-Since"] = row["last_modified"]
        return headers

    def load_cached_artifacts(
        self,
        url: str,
        *,
        max_age_seconds: int | None = None,
    ) -> CachedArtifacts | None:
        """Load normalized cache data, failing closed on missing/unsafe paths."""
        with self.connection() as connection:
            row = connection.execute(
                """
                SELECT document_path, chunks_path, last_seen_at, content_hash
                FROM resources WHERE url = ?
                """,
                (url,),
            ).fetchone()
        if row is None or not row["document_path"] or not row["chunks_path"]:
            return None
        document_path = self._artifact_path(str(row["document_path"]))
        chunks_path = self._artifact_path(str(row["chunks_path"]))
        if not document_path.is_file() or not chunks_path.is_file():
            return None
        try:
            document = json.loads(document_path.read_text(encoding="utf-8"))
            chunks = [
                json.loads(line)
                for line in chunks_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except (OSError, ValueError, TypeError):
            return None
        last_seen_at = str(row["last_seen_at"])
        fresh = True
        if max_age_seconds is not None:
            try:
                seen = datetime.fromisoformat(last_seen_at)
                if seen.tzinfo is None:
                    seen = seen.replace(tzinfo=timezone.utc)
                age = (datetime.now(timezone.utc) - seen).total_seconds()
                fresh = age <= max(0, max_age_seconds)
            except ValueError:
                fresh = False
        return CachedArtifacts(
            document=document,
            chunks=chunks,
            fresh=fresh,
            last_seen_at=last_seen_at,
            content_hash=str(row["content_hash"]) if row["content_hash"] else None,
        )

    def touch_resource(self, url: str) -> None:
        with self.connection() as connection:
            connection.execute(
                "UPDATE resources SET last_seen_at = ? WHERE url = ?", (_now(), url)
            )

    def save_raw(
        self,
        run_id: str,
        document_id: str,
        content: bytes,
        *,
        extension: str = "html",
    ) -> str:
        if extension not in {"html", "md", "txt"}:
            raise ValueError(f"unsupported raw artifact extension: {extension}")
        path = self.raw_dir / run_id / document_id[:6] / f"{document_id}.{extension}"
        _atomic_write_bytes(path, content)
        return str(path.relative_to(self.data_dir))

    def mark_unchanged(self, run_id: str, url: str, http_status: int = 304) -> None:
        self.touch_resource(url)
        self._upsert_run_page(run_id, url, status="UNCHANGED", http_status=http_status)

    def mark_skipped(
        self,
        run_id: str,
        url: str,
        reason: str,
        *,
        http_status: int = 0,
        raw_path: str | None = None,
    ) -> None:
        self._upsert_run_page(
            run_id,
            url,
            status="SKIPPED",
            http_status=http_status,
            raw_path=raw_path,
            error=reason,
        )

    def mark_failed(
        self,
        run_id: str,
        url: str,
        error: str,
        *,
        http_status: int = 0,
        raw_path: str | None = None,
    ) -> None:
        self._upsert_run_page(
            run_id, url, status="FAILED", http_status=http_status,
            raw_path=raw_path, error=error,
        )

    def stage_document(
        self,
        run_id: str,
        document: ExtractedDocument,
        chunks: list[ChunkRecord],
        headers: dict[str, str],
        raw_path: str,
    ) -> None:
        document_path = self.documents_dir / run_id / f"{document.document_id}.json"
        chunks_path = self.chunks_dir / run_id / f"{document.document_id}.jsonl"
        _atomic_write_text(
            document_path,
            json.dumps(document.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
        chunk_lines = "".join(
            json.dumps(
                {
                    "chunk_ordinal": chunk.chunk_ordinal,
                    "text": chunk.text,
                    "page_start": chunk.page_start,
                    "page_end": chunk.page_end,
                    "section_path": chunk.section_path,
                    "content_hash": chunk.content_hash,
                    "chunker_version": chunk.chunker_version,
                    "token_estimate": chunk.token_estimate,
                },
                ensure_ascii=False,
                sort_keys=True,
            ) + "\n"
            for chunk in chunks
        )
        _atomic_write_text(chunks_path, chunk_lines)
        relative_document = str(document_path.relative_to(self.data_dir))
        relative_chunks = str(chunks_path.relative_to(self.data_dir))
        now = _now()
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO resources (
                    url, etag, last_modified, content_hash, raw_path,
                    document_path, chunks_path, first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    etag=excluded.etag,
                    last_modified=excluded.last_modified,
                    content_hash=excluded.content_hash,
                    raw_path=excluded.raw_path,
                    document_path=excluded.document_path,
                    chunks_path=excluded.chunks_path,
                    last_seen_at=excluded.last_seen_at
                """,
                (
                    document.canonical_url, headers.get("etag"), headers.get("last-modified"),
                    document.content_hash, raw_path, relative_document, relative_chunks, now, now,
                ),
            )
        self._upsert_run_page(
            run_id,
            document.canonical_url,
            status="STAGED",
            http_status=document.http_status,
            content_hash=document.content_hash,
            raw_path=raw_path,
            document_path=relative_document,
            chunks_path=relative_chunks,
        )

    def finish_run(self, run_id: str, status: str, report: dict) -> None:
        manifest_path = self.runs_dir / f"{run_id}.json"
        _atomic_write_text(
            manifest_path,
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
        with self.connection() as connection:
            connection.execute(
                """
                UPDATE runs SET status = ?, finished_at = ?, report_json = ? WHERE run_id = ?
                """,
                (status, _now(), json.dumps(report, sort_keys=True), run_id),
            )

    def run_summary(self, run_id: str) -> dict:
        with self.connection() as connection:
            run = connection.execute(
                "SELECT * FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            counts = connection.execute(
                """
                SELECT status, COUNT(*) AS count FROM run_pages
                WHERE run_id = ? GROUP BY status
                """,
                (run_id,),
            ).fetchall()
        if run is None:
            raise KeyError(f"unknown crawl run: {run_id}")
        return {
            "run_id": run_id,
            "product_id": run["product_id"],
            "version_id": run["version_id"],
            "status": run["status"],
            "started_at": run["started_at"],
            "finished_at": run["finished_at"],
            "page_statuses": {row["status"]: row["count"] for row in counts},
            "data_dir": str(self.data_dir),
        }

    def iter_staged_artifacts(self, run_id: str) -> Iterator[tuple[dict, list[dict]]]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT
                    run_pages.url AS url,
                    run_pages.status AS page_status,
                    COALESCE(run_pages.document_path, resources.document_path) AS document_path,
                    COALESCE(run_pages.chunks_path, resources.chunks_path) AS chunks_path
                FROM run_pages
                LEFT JOIN resources ON resources.url = run_pages.url
                WHERE run_id = ? AND run_pages.status IN ('STAGED', 'UNCHANGED')
                ORDER BY run_pages.url
                """,
                (run_id,),
            ).fetchall()
        for row in rows:
            if not row["document_path"] or not row["chunks_path"]:
                raise RuntimeError(
                    "crawl state is corrupt: no normalized artifacts for "
                    f"{row['url']} ({row['page_status']})"
                )
            document_path = self.data_dir / row["document_path"]
            chunks_path = self.data_dir / row["chunks_path"]
            if not document_path.is_file() or not chunks_path.is_file():
                raise RuntimeError(
                    "crawl state references missing normalized artifacts for "
                    f"{row['url']}: {document_path}, {chunks_path}"
                )
            document = json.loads(document_path.read_text(encoding="utf-8"))
            chunks = [
                json.loads(line)
                for line in chunks_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            yield document, chunks

    def update_run_status(self, run_id: str, status: str, report: dict) -> None:
        with self.connection() as connection:
            connection.execute(
                "UPDATE runs SET status = ?, report_json = ? WHERE run_id = ?",
                (status, json.dumps(report, sort_keys=True), run_id),
            )

    def _artifact_path(self, relative_path: str) -> Path:
        root = self.data_dir.resolve()
        path = (self.data_dir / relative_path).resolve()
        if not path.is_relative_to(root):
            raise ValueError("cached artifact path escaped the crawler data directory")
        return path

    def _upsert_run_page(
        self,
        run_id: str,
        url: str,
        *,
        status: str,
        http_status: int | None = None,
        content_hash: str | None = None,
        raw_path: str | None = None,
        document_path: str | None = None,
        chunks_path: str | None = None,
        error: str | None = None,
    ) -> None:
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO run_pages (
                    run_id, url, status, http_status, content_hash, raw_path,
                    document_path, chunks_path, error, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, url) DO UPDATE SET
                    status=excluded.status,
                    http_status=COALESCE(excluded.http_status, run_pages.http_status),
                    content_hash=COALESCE(excluded.content_hash, run_pages.content_hash),
                    raw_path=COALESCE(excluded.raw_path, run_pages.raw_path),
                    document_path=COALESCE(excluded.document_path, run_pages.document_path),
                    chunks_path=COALESCE(excluded.chunks_path, run_pages.chunks_path),
                    error=excluded.error,
                    updated_at=excluded.updated_at
                """,
                (
                    run_id, url, status, http_status, content_hash, raw_path,
                    document_path, chunks_path, error, _now(),
                ),
            )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(content)
    temporary.replace(path)


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)
