"""Runtime settings for the IBM Documentation crawler."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class CrawlerSettings:
    user_agent: str
    data_dir: Path
    delay_seconds: float = 1.5
    timeout_seconds: float = 30.0
    max_retries: int = 4
    max_response_bytes: int = 20_000_000
    max_chunks_per_document: int = 250
    validate_public_dns: bool = True

    @classmethod
    def from_env(cls) -> "CrawlerSettings":
        user_agent = os.getenv("IBM_DOCS_USER_AGENT", "").strip()
        if not user_agent:
            raise ValueError(
                "IBM_DOCS_USER_AGENT is required and must include a monitored contact address"
            )
        if "@" not in user_agent and "http://" not in user_agent and "https://" not in user_agent:
            raise ValueError("IBM_DOCS_USER_AGENT must include a monitored email address or URL")
        data_dir = Path(
            os.path.expandvars(os.getenv(
                "IBM_DOCS_DATA_DIR",
                str(Path.home() / ".local" / "share" / "it-helpdesk" / "ibm-docs-crawler"),
            ))
        ).expanduser()
        return cls(
            user_agent=user_agent,
            data_dir=data_dir,
            delay_seconds=max(1.0, float(os.getenv("IBM_DOCS_DELAY_SECONDS", "1.5"))),
            timeout_seconds=max(5.0, float(os.getenv("IBM_DOCS_TIMEOUT_SECONDS", "30"))),
            max_retries=max(1, int(os.getenv("IBM_DOCS_MAX_RETRIES", "4"))),
            max_response_bytes=max(
                100_000, int(os.getenv("IBM_DOCS_MAX_RESPONSE_BYTES", "20000000"))
            ),
            max_chunks_per_document=max(
                1, int(os.getenv("IBM_DOCS_MAX_CHUNKS_PER_DOCUMENT", "250"))
            ),
            validate_public_dns=os.getenv("IBM_DOCS_VALIDATE_PUBLIC_DNS", "true").lower()
            not in {"0", "false", "no"},
        )
