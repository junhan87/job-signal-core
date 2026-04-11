"""Abstract base class for all job scrapers."""
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Iterator

logger = logging.getLogger(__name__)


@dataclass
class JobListing:
    job_id: str
    title: str
    company: str
    description: str
    url: str
    source: str  # "mcf" | "jobstreet" | "indeed"
    salary_min: int | None = None
    salary_max: int | None = None
    employment_type: str | None = None  # "FULL_TIME" | "PART_TIME" | "CONTRACT"
    location: str | None = None
    posted_date: str | None = None  # ISO 8601
    scraped_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


class BaseScraper(ABC):
    """All scrapers must implement fetch() and yield JobListing objects."""

    source: str = ""

    @abstractmethod
    def fetch(self, search_terms: list[str], max_pages: int = 10) -> Iterator[JobListing]:
        """Yield JobListing objects for the given search terms."""
        ...
