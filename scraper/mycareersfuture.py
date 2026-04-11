"""MyCareersFuture public API scraper.

API docs: https://api.mycareersfuture.gov.sg/v2/jobs
No authentication required. Rate limit: ~1 req/sec is safe.
"""
from __future__ import annotations

import logging
import time
from typing import Iterator

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from scraper.base_scraper import BaseScraper, JobListing

logger = logging.getLogger(__name__)

MCF_API_BASE = "https://api.mycareersfuture.gov.sg/v2/jobs"
PAGE_SIZE = 100
REQUEST_DELAY_SECONDS = 1.0  # be polite to the public API


def _build_session() -> requests.Session:
    """Return a requests Session with retry backoff."""
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.headers.update({"User-Agent": "JobScout/1.0 (personal research tool)"})
    return session


class MyCareersFutureScraper(BaseScraper):
    source = "mcf"

    def __init__(self) -> None:
        self._session = _build_session()

    def fetch(self, search_terms: list[str], max_pages: int = 10) -> Iterator[JobListing]:
        """Yield JobListing objects for each search term, handling pagination."""
        for term in search_terms:
            logger.info("MCF: fetching '%s'", term)
            yield from self._fetch_term(term, max_pages)

    def _fetch_term(self, term: str, max_pages: int) -> Iterator[JobListing]:
        page = 0
        while page < max_pages:
            params = {
                "search": term,
                "limit": PAGE_SIZE,
                "offset": page * PAGE_SIZE,
                "employment_types": "FULL_TIME,PART_TIME,CONTRACT",
                "sort": "new_posting_date",
            }
            try:
                resp = self._session.get(MCF_API_BASE, params=params, timeout=15)
                resp.raise_for_status()
            except requests.RequestException as exc:
                logger.error("MCF request failed on page %d for '%s': %s", page, term, exc)
                break

            data = resp.json()
            results = data.get("results", [])

            if not results:
                break  # no more pages

            for item in results:
                listing = _parse_listing(item)
                if listing:
                    yield listing

            # MCF returns total count — stop early if we have all results
            total = data.get("total", 0)
            fetched_so_far = (page + 1) * PAGE_SIZE
            if fetched_so_far >= total:
                break

            page += 1
            time.sleep(REQUEST_DELAY_SECONDS)


def _parse_listing(item: dict) -> JobListing | None:
    """Map a raw MCF API response item to a JobListing. Returns None if malformed."""
    try:
        uuid = item.get("uuid") or item.get("id")
        if not uuid:
            return None

        salary = item.get("salary", {})
        metadata = item.get("metadata", {})
        company = item.get("postedCompany", {})

        return JobListing(
            job_id=str(uuid),
            title=item.get("title", "").strip(),
            company=company.get("name", "").strip(),
            description=item.get("description", "").strip(),
            url=f"https://www.mycareersfuture.gov.sg/job/{uuid}",
            source="mcf",
            salary_min=salary.get("minimum"),
            salary_max=salary.get("maximum"),
            employment_type=_map_employment_type(item.get("employmentTypes", [])),
            location=_extract_location(item),
            posted_date=metadata.get("createdAt"),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to parse MCF listing: %s | item=%s", exc, item.get("uuid"))
        return None


def _map_employment_type(types: list[dict]) -> str | None:
    if not types:
        return None
    return types[0].get("employmentType", {}).get("employmentType")


def _extract_location(item: dict) -> str | None:
    addresses = item.get("positionLocations", [])
    if addresses:
        return addresses[0].get("location", {}).get("district")
    return None
