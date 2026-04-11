# JobSignal — Copilot Instructions

> AI-powered job screener for the job market. See [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md) for the full system design.

---

## Project Overview

JobSignal scrapes job platforms daily, scores each listing against a structured resume profile via AWS Bedrock (Claude), and delivers ranked matches by email. The stack is Python 3.12, AWS Lambda, CDK (Python), DynamoDB, and S3.

---

## Strategy Pattern — Core Architecture Rule

**All job-platform logic must be encapsulated in a dedicated scraper class that extends `BaseScraper`.**

### How It Works

```
scraper/
  base_scraper.py       ← Strategy interface (BaseScraper ABC + JobListing dataclass)
  mycareersfuture.py    ← Concrete strategy: MyCareersFutureScraper
  jobstreet.py          ← Concrete strategy (future): JobStreetScraper
  indeed.py             ← Concrete strategy (future): IndeedScraper
```

### Rules for New Scrapers

1. **Subclass `BaseScraper`** from `scraper/base_scraper.py`.
2. **Set the `source` class attribute** to a short unique string (e.g., `"mcf"`, `"jobstreet"`, `"indeed"`). This value populates `JobListing.source` and is used as the S3 prefix.
3. **Implement only `fetch()`** — yield `JobListing` objects. All pagination, rate-limiting, and retry logic lives inside the scraper class.
4. **Never hard-code platform logic in the Lambda handler** (`infrastructure/lambda/scraper_handler.py`). The handler calls `scraper.fetch()` and is platform-agnostic.
5. **Return `None` from `_parse_listing()`** (or equivalent) for malformed items — never raise from a parser. Log a warning instead.
6. **Each scraper is independently instantiable** — no shared mutable state between scrapers.

### Canonical Pattern

```python
# scraper/new_platform.py
from scraper.base_scraper import BaseScraper, JobListing

class NewPlatformScraper(BaseScraper):
    source = "new_platform"   # lowercase, matches S3 prefix

    def fetch(self, search_terms: list[str], max_pages: int = 10) -> Iterator[JobListing]:
        for term in search_terms:
            yield from self._fetch_term(term, max_pages)

    def _fetch_term(self, term: str, max_pages: int) -> Iterator[JobListing]:
        # pagination + rate-limiting + HTTP errors handled here
        ...
```

### Lambda Handler — Registering a New Scraper

The handler should select scrapers from a registry, not import them directly:

```python
# Preferred pattern when multiple scrapers exist
SCRAPERS: dict[str, type[BaseScraper]] = {
    "mcf": MyCareersFutureScraper,
    "jobstreet": JobStreetScraper,
}

scraper = SCRAPERS[platform]()
for listing in scraper.fetch(search_terms):
    ...
```

---

## Data Model

`JobListing` (defined in `scraper/base_scraper.py`) is the **single canonical output** for all scrapers. Do not create platform-specific dataclasses or add platform-specific fields to `JobListing`. If a platform provides extra data, map it to the closest existing field or discard it.

Key fields:
| Field | Notes |
|-------|-------|
| `job_id` | Platform-native ID; must be unique within a `source` |
| `source` | Matches the scraper's `source` class attribute |
| `salary_min` / `salary_max` | Monthly local currency integers, `None` if not advertised |
| `employment_type` | Normalised to `"FULL_TIME"`, `"PART_TIME"`, or `"CONTRACT"` |
| `posted_date` | ISO 8601 string |

---

## Code Conventions

- **Python 3.12** — use `X | Y` unions, `match` statements where appropriate.
- **`from __future__ import annotations`** at the top of every module.
- **No bare `except Exception`** — use `except SomeError as exc` and log with context. The only exception is in Lambda entry points and `_parse_listing` guards.
- **Logging**: use `logger = logging.getLogger(__name__)` per module; no `print()`.
- **requests Sessions** — always use a shared `requests.Session` with retry backoff (see `mycareersfuture.py` for the `_build_session()` pattern).
- **HTTP rate limiting** — every scraper must respect platform rate limits. Default to `time.sleep(1.0)` between pages unless the platform documents otherwise.

---

## Infrastructure (CDK)

- All Lambda environment variables are injected by CDK in `infrastructure/cdk/scraper_stack.py`. Do not hardcode resource names in Lambda code — read from `os.environ`.
- S3 key scheme: `raw/{source}/{YYYY-MM-DD}/{job_id}.json`
- DynamoDB deduplication key: `job_id` (partition key).

---

## Testing

- Unit tests live in `tests/unit/` and must not make real HTTP calls — mock at the `requests.Session` level.
- Integration tests in `tests/integration/` may call real AWS endpoints in a sandbox account.
- When adding a new scraper, add a corresponding `tests/unit/test_<platform>.py` that covers: successful fetch, empty response, malformed item (should be skipped, not raise), and HTTP error (should stop that term, not crash the whole run).

---

## What NOT to Do

- Do not add platform-specific fields or conditional logic to `JobListing`.
- Do not instantiate a specific scraper class directly in the Lambda handler — use a registry.
- Do not bypass `BaseScraper` by writing ad-hoc fetching logic in the handler or helper modules.
- Do not store credentials in code — use Lambda environment variables or AWS Secrets Manager.
