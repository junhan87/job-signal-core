"""JobStreet GraphQL scraper.

Endpoint: https://sg.jobstreet.com/graphql
Method: POST (GraphQL, operationName=JobSearchV6)
Auth: None required — public search API served by Cloudflare.
Rate limit: ~1 req/sec is safe. Implemented via REQUEST_DELAY_SECONDS.

Pagination: page-based integer (``page`` param inside GraphQL variables, 1-indexed).
  - Total result count is available at ``response.data.jobSearchV6.totalCount``.
  - Iteration stops when the ``data`` list is empty **or** all pages are exhausted.

Required request headers (in addition to standard Content-Type / User-Agent):
  - seek-request-brand: jobstreet
  - seek-request-country: SG
  - x-seek-site: chalice

Field mapping (GraphQL response → JobListing):
  id                         → job_id
  title                      → title
  companyName (or advertiser.description fallback) → company
  teaser                     → description
  https://sg.jobstreet.com/job/{id} → url
  salaryLabel (parsed)       → salary_min / salary_max  (monthly SGD integers)
  workTypes[0]               → employment_type
  locations[0].label         → location
  listingDate.dateTimeUtc    → posted_date (ISO 8601)
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
import uuid
from typing import Iterator

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from scraper.base_scraper import BaseScraper, JobListing

logger = logging.getLogger(__name__)

JOBSTREET_GRAPHQL_URL = "https://sg.jobstreet.com/graphql"
JOBSTREET_HOME_URL = "https://sg.jobstreet.com/"
PAGE_SIZE = 32
REQUEST_DELAY_SECONDS = 1.0

# Exact query string captured from the JobStreet browser client.
# The Apollo backend validates against pre-registered query hashes — any deviation
# causes UNSTABLE_QUERY_ERROR. Do not trim or reformat this string.
_GRAPHQL_QUERY = (
    "query JobSearchV6($params: JobSearchV6QueryInput!, $locale: Locale!, $timezone: Timezone!) {\n"
    "  jobSearchV6(params: $params) {\n"
    "    canonicalCompany {\n"
    "      description\n"
    "      __typename\n"
    "    }\n"
    "    data {\n"
    "      advertiser {\n"
    "        id\n"
    "        description\n"
    "        __typename\n"
    "      }\n"
    "      branding {\n"
    "        serpLogoUrl\n"
    "        __typename\n"
    "      }\n"
    "      bulletPoints\n"
    "      classifications {\n"
    "        classification {\n"
    "          id\n"
    "          description\n"
    "          __typename\n"
    "        }\n"
    "        subclassification {\n"
    "          id\n"
    "          description\n"
    "          __typename\n"
    "        }\n"
    "        __typename\n"
    "      }\n"
    "      companyName\n"
    "      companyProfileStructuredDataId\n"
    "      currencyLabel\n"
    "      displayType\n"
    "      employer {\n"
    "        companyUrl\n"
    "        __typename\n"
    "      }\n"
    "      externalReferences {\n"
    "        id\n"
    "        sourceSystem\n"
    "        type\n"
    "        metadata {\n"
    "          name\n"
    "          assets {\n"
    "            profilePhotoUrl\n"
    "            __typename\n"
    "          }\n"
    "          __typename\n"
    "        }\n"
    "        __typename\n"
    "      }\n"
    "      id\n"
    "      isFeatured\n"
    "      listingDate {\n"
    "        dateTimeUtc\n"
    "        label(context: JOB_POSTED, length: SHORT, timezone: $timezone, locale: $locale)\n"
    "        __typename\n"
    "      }\n"
    "      locations {\n"
    "        countryCode\n"
    "        label\n"
    "        seoHierarchy {\n"
    "          contextualName\n"
    "          __typename\n"
    "        }\n"
    "        __typename\n"
    "      }\n"
    "      roleId\n"
    "      salaryLabel\n"
    "      solMetadata\n"
    "      tags {\n"
    "        label\n"
    "        type\n"
    "        __typename\n"
    "      }\n"
    "      teaser\n"
    "      title\n"
    "      tracking\n"
    "      workArrangements {\n"
    "        displayText\n"
    "        __typename\n"
    "      }\n"
    "      workTypes\n"
    "      __typename\n"
    "    }\n"
    "    facets {\n"
    "      distinctTitle {\n"
    "        count\n"
    "        id\n"
    "        label\n"
    "        __typename\n"
    "      }\n"
    "      location {\n"
    "        count\n"
    "        id\n"
    "        label {\n"
    "          lang\n"
    "          text\n"
    "          __typename\n"
    "        }\n"
    "        __typename\n"
    "      }\n"
    "      __typename\n"
    "    }\n"
    "    gptTargeting {\n"
    "      ... on GptTargetingStringValue {\n"
    "        key\n"
    "        value\n"
    "        __typename\n"
    "      }\n"
    "      ... on GptTargetingStringArrayValue {\n"
    "        key\n"
    "        values\n"
    "        __typename\n"
    "      }\n"
    "      __typename\n"
    "    }\n"
    "    info {\n"
    "      experiment\n"
    "      newSince\n"
    "      source\n"
    "      timeTaken\n"
    "      __typename\n"
    "    }\n"
    "    intentSuggestions {\n"
    "      count\n"
    "      id\n"
    "      label {\n"
    "        defaultText\n"
    "        lang\n"
    "        __typename\n"
    "      }\n"
    "      params {\n"
    "        classification\n"
    "        companyName\n"
    "        dateRange\n"
    "        distance\n"
    "        keywords\n"
    "        maxSalary\n"
    "        minSalary\n"
    "        salaryType\n"
    "        siteKey\n"
    "        sortMode\n"
    "        subclassification\n"
    "        tags\n"
    "        where\n"
    "        workArrangement\n"
    "        workTypes\n"
    "        __typename\n"
    "      }\n"
    "      type\n"
    "      __typename\n"
    "    }\n"
    "    isQueryModified\n"
    "    location {\n"
    "      defaultDistanceKms\n"
    "      description\n"
    "      isGranular\n"
    "      localisedDescriptions {\n"
    "        contextualName\n"
    "        lang\n"
    "        __typename\n"
    "      }\n"
    "      locationDescription\n"
    "      type\n"
    "      whereId\n"
    "      __typename\n"
    "    }\n"
    "    searchExecuted {\n"
    "      classification\n"
    "      companyName\n"
    "      dateRange\n"
    "      distance\n"
    "      keywords\n"
    "      maxSalary\n"
    "      minSalary\n"
    "      salaryType\n"
    "      siteKey\n"
    "      sortMode\n"
    "      subclassification\n"
    "      tags\n"
    "      where\n"
    "      workArrangement\n"
    "      workTypes\n"
    "      __typename\n"
    "    }\n"
    "    searchParams {\n"
    "      advertisergroup\n"
    "      advertiserid\n"
    "      basekeywords\n"
    "      classification\n"
    "      companyid\n"
    "      companyname\n"
    "      companyprofilestructureddataid\n"
    "      companysearch\n"
    "      daterange\n"
    "      distance\n"
    "      duplicates\n"
    "      encodedurl\n"
    "      engineconfig\n"
    "      eventcapturesessionid\n"
    "      eventcaptureuserid\n"
    "      facets\n"
    "      include\n"
    "      jobid\n"
    "      keywords\n"
    "      locale\n"
    "      maxlistingdate\n"
    "      minlistingdate\n"
    "      newsince\n"
    "      page\n"
    "      pagesize\n"
    "      queryhints\n"
    "      relatedsearchescount\n"
    "      salaryrange\n"
    "      salarytype\n"
    "      savedsearchid\n"
    "      sitekey\n"
    "      solid\n"
    "      sortmode\n"
    "      source\n"
    "      statetoken\n"
    "      subclassification\n"
    "      tags\n"
    "      userid\n"
    "      userqueryid\n"
    "      usersessionid\n"
    "      where\n"
    "      whereid\n"
    "      whereids\n"
    "      workarrangement\n"
    "      worktype\n"
    "      __typename\n"
    "    }\n"
    "    solMetadata\n"
    "    sortModes {\n"
    "      isActive\n"
    "      name\n"
    "      value\n"
    "      __typename\n"
    "    }\n"
    "    suggestions {\n"
    "      asyncPillsToken\n"
    "      company {\n"
    "        count\n"
    "        search {\n"
    "          companyName\n"
    "          keywords\n"
    "          __typename\n"
    "        }\n"
    "        __typename\n"
    "      }\n"
    "      location {\n"
    "        description\n"
    "        whereId\n"
    "        __typename\n"
    "      }\n"
    "      pills {\n"
    "        isActive\n"
    "        keywords\n"
    "        label\n"
    "        __typename\n"
    "      }\n"
    "      relatedSearches {\n"
    "        keywords\n"
    "        totalJobs\n"
    "        __typename\n"
    "      }\n"
    "      showSABFilter\n"
    "      __typename\n"
    "    }\n"
    "    totalCount\n"
    "    userQueryId\n"
    "    __typename\n"
    "  }\n"
    "}"
)

# Matches "$12,000 – $15,000 per month", "S$ 8,000 - 9,200", "$170,000 – $200,000 per year"
_SALARY_PATTERN = re.compile(
    r"(?:S?\$)\s*([\d,]+)\s*[–\-]\s*(?:S?\$)?\s*([\d,]+)"
    r"(?:\s+per\s+(month|year))?",
    re.IGNORECASE,
)

_EMPLOYMENT_TYPE_MAP: dict[str, str] = {
    "full time": "FULL_TIME",
    "fulltime": "FULL_TIME",
    "part time": "PART_TIME",
    "parttime": "PART_TIME",
    "contract/temp": "CONTRACT",
    "contract": "CONTRACT",
    "temporary": "CONTRACT",
    "casual": "PART_TIME",
}


def _build_session() -> requests.Session:
    """Return a requests Session with retry backoff and required JobStreet headers."""
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["POST"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/148.0.0.0 Safari/537.36"
            ),
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://sg.jobstreet.com",
            "Referer": "https://sg.jobstreet.com/",
            "seek-request-brand": "jobstreet",
            "seek-request-country": "SG",
            "x-custom-features": "application/features.seek.all+json",
            "x-seek-site": "chalice",
        }
    )
    return session


class JobStreetScraper(BaseScraper):
    source = "jobstreet"

    def __init__(self) -> None:
        self._session = _build_session()
        self._session_bootstrapped = False
        self._session_id = str(uuid.uuid4())
        self._sol_id: str | None = None
        # Add per-session tracking headers that must match params values
        self._session.headers.update({
            "x-seek-ec-sessionid": self._session_id,
            "x-seek-ec-visitorid": self._session_id,
        })

    def _bootstrap_session(self) -> None:
        """GET the JobStreet home page to acquire session cookies (incl. sol_id) before GraphQL."""
        if self._session_bootstrapped:
            return
        try:
            resp = self._session.get(JOBSTREET_HOME_URL, timeout=15)
            self._sol_id = self._session.cookies.get("sol_id")
            logger.info(
                "JobStreet session bootstrap: status=%d sol_id=%s cookies=%s",
                resp.status_code,
                self._sol_id,
                [c.name for c in self._session.cookies],
            )
        except requests.RequestException as exc:
            logger.warning("JobStreet session bootstrap failed (continuing anyway): %s", exc)
        finally:
            self._session_bootstrapped = True

    def fetch(self, search_terms: list[str], max_pages: int = 10) -> Iterator[JobListing]:
        """Yield JobListing objects for each search term, handling pagination."""
        self._bootstrap_session()
        for term in search_terms:
            logger.info("JobStreet: fetching '%s'", term)
            yield from self._fetch_term(term, max_pages)

    def _fetch_term(self, term: str, max_pages: int) -> Iterator[JobListing]:
        page = 1
        while page <= max_pages:
            user_query_id = (
                hashlib.md5(term.encode()).hexdigest()  # noqa: S324
                + f"-{page * 1000000 + int(uuid.uuid4().int % 9000000)}"
            )
            params: dict = {
                "channel": "web",
                "eventCaptureSessionId": self._session_id,
                "eventCaptureUserId": self._session_id,
                "include": ["seoData", "gptTargeting", "relatedSearches"],
                "keywords": term,
                "locale": "en-SG",
                "page": page,
                "pageSize": PAGE_SIZE,
                "queryHints": ["spellingCorrection"],
                "relatedSearchesCount": 12,
                "siteKey": "SG",
                "source": "FE_HOME",
                "userQueryId": user_query_id,
                "userSessionId": self._session_id,
            }
            if self._sol_id:
                params["solId"] = self._sol_id
            payload = {
                "operationName": "JobSearchV6",
                "variables": {
                    "params": params,
                    "locale": "en-SG",
                    "timezone": "Asia/Singapore",
                },
                "query": _GRAPHQL_QUERY,
            }
            try:
                resp = self._session.post(
                    JOBSTREET_GRAPHQL_URL, json=payload, timeout=15
                )
                resp.raise_for_status()
            except requests.RequestException as exc:
                logger.error(
                    "JobStreet request failed on page %d for '%s': %s", page, term, exc
                )
                break

            body = resp.json()
            errors = body.get("errors") or []
            if errors:
                first_error = errors[0] or {}
                ext = first_error.get("extensions") or {}
                error_code = ext.get("code")
                request_id = resp.headers.get("x-request-id")
                logger.error(
                    "JobStreet GraphQL error on page %d for '%s': %s | code=%s | request_id=%s",
                    page,
                    term,
                    first_error.get("message", "Unknown GraphQL error"),
                    error_code,
                    request_id,
                )
                break

            search_result = (body.get("data") or {}).get("jobSearchV6") or {}
            items = search_result.get("data") or []

            if not items:
                break

            for item in items:
                listing = _parse_listing(item)
                if listing:
                    yield listing

            total = search_result.get("totalCount") or 0
            if page * PAGE_SIZE >= total:
                break

            page += 1
            time.sleep(REQUEST_DELAY_SECONDS)


def _parse_listing(item: dict) -> JobListing | None:
    """Map a raw JobStreet GraphQL item to a JobListing. Returns None if malformed."""
    try:
        job_id = item.get("id")
        if not job_id:
            return None

        company: str = item.get("companyName") or ""
        if not company:
            advertiser = item.get("advertiser") or {}
            company = advertiser.get("description") or ""

        locations = item.get("locations") or []
        location = locations[0].get("label") if locations else None

        listing_date = item.get("listingDate") or {}
        posted_date = listing_date.get("dateTimeUtc")

        salary_min, salary_max = _parse_salary(item.get("salaryLabel") or "")

        work_types = item.get("workTypes") or []
        employment_type = _map_employment_type(work_types[0] if work_types else None)

        return JobListing(
            job_id=str(job_id),
            title=(item.get("title") or "").strip(),
            company=company.strip(),
            description=(item.get("teaser") or "").strip(),
            url=f"https://sg.jobstreet.com/job/{job_id}",
            source="jobstreet",
            salary_min=salary_min,
            salary_max=salary_max,
            employment_type=employment_type,
            location=location,
            posted_date=posted_date,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Failed to parse JobStreet listing: %s | item=%s", exc, item.get("id")
        )
        return None


def _map_employment_type(raw: str | None) -> str | None:
    """Normalise a JobStreet workType string to FULL_TIME, PART_TIME, or CONTRACT."""
    if not raw:
        return None
    return _EMPLOYMENT_TYPE_MAP.get(raw.lower().strip(), raw.upper())


def _parse_salary(label: str) -> tuple[int | None, int | None]:
    """Extract (salary_min, salary_max) as monthly SGD integers from a salary label.

    Handles:
      "$10,000 – $15,000 per month"  → (10000, 15000)
      "$170,000 – $200,000 per year" → (14167, 16667)
      "S$ 8,000 - 9,200"             → (8000, 9200)
      ""                             → (None, None)
    """
    if not label:
        return None, None
    match = _SALARY_PATTERN.search(label)
    if not match:
        return None, None
    try:
        min_val = int(match.group(1).replace(",", ""))
        max_val = int(match.group(2).replace(",", ""))
        period = (match.group(3) or "month").lower()
        if period == "year":
            min_val = round(min_val / 12)
            max_val = round(max_val / 12)
        return min_val, max_val
    except (ValueError, AttributeError):
        return None, None
