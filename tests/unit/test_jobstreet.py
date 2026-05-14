"""Unit tests for the JobStreet scraper — no real HTTP calls."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from scraper.jobstreet import JobStreetScraper, _map_employment_type, _parse_salary


class TestJobStreetScraper:
    def _mock_response(self, items: list[dict], total: int | None = None) -> MagicMock:
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "data": {
                "jobSearchV6": {
                    "data": items,
                    "totalCount": total if total is not None else len(items),
                }
            }
        }
        return mock_resp

    def _sample_item(self, job_id: str = "92096366") -> dict:
        return {
            "id": job_id,
            "title": "Solution Architect",
            "companyName": "Acme Corp",
            "advertiser": {"description": "Acme Corp Advertiser"},
            "teaser": "Design and deliver cloud-native solutions.",
            "locations": [{"label": "Central Region"}],
            "listingDate": {"dateTimeUtc": "2026-05-13T07:00:00.000Z"},
            "salaryLabel": "$10,000 – $15,000 per month",
            "workTypes": ["Full time"],
        }

    def test_fetch_yields_job_listing(self):
        scraper = JobStreetScraper()
        mock_resp = self._mock_response([self._sample_item()])

        with patch.object(scraper._session, "get", return_value=MagicMock(status_code=200)):
            with patch.object(scraper._session, "post", return_value=mock_resp):
                results = list(scraper.fetch(["solution architect"], max_pages=1))

        assert len(results) == 1
        listing = results[0]
        assert listing.job_id == "92096366"
        assert listing.title == "Solution Architect"
        assert listing.company == "Acme Corp"
        assert listing.source == "jobstreet"
        assert listing.salary_min == 10000
        assert listing.salary_max == 15000
        assert listing.employment_type == "FULL_TIME"
        assert listing.location == "Central Region"
        assert listing.url == "https://sg.jobstreet.com/job/92096366"
        assert listing.posted_date == "2026-05-13T07:00:00.000Z"

    def test_fetch_stops_when_no_results(self):
        scraper = JobStreetScraper()
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "data": {"jobSearchV6": {"data": [], "totalCount": 0}}
        }

        with patch.object(scraper._session, "get", return_value=MagicMock(status_code=200)):
            with patch.object(scraper._session, "post", return_value=mock_resp) as mock_post:
                results = list(scraper.fetch(["no results term"], max_pages=5))

        assert results == []
        assert mock_post.call_count == 1  # stopped after first empty page

    def test_malformed_item_is_skipped(self):
        scraper = JobStreetScraper()
        bad_item = {"title": "No ID job"}  # missing id → should be skipped
        good_item = self._sample_item("good-id-123")
        mock_resp = self._mock_response([bad_item, good_item])

        with patch.object(scraper._session, "get", return_value=MagicMock(status_code=200)):
            with patch.object(scraper._session, "post", return_value=mock_resp):
                results = list(scraper.fetch(["test"], max_pages=1))

        assert len(results) == 1
        assert results[0].job_id == "good-id-123"

    def test_request_exception_breaks_loop(self):
        scraper = JobStreetScraper()

        with patch.object(scraper._session, "get", return_value=MagicMock(status_code=200)):
            with patch.object(
                scraper._session,
                "post",
                side_effect=requests.exceptions.ConnectionError("timeout"),
            ):
                results = list(scraper.fetch(["cloud"], max_pages=5))

        assert results == []

    def test_http_error_breaks_loop(self):
        scraper = JobStreetScraper()
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
            "403 Forbidden"
        )

        with patch.object(scraper._session, "get", return_value=MagicMock(status_code=200)):
            with patch.object(
                scraper._session, "post", return_value=mock_resp
            ) as mock_post:
                results = list(scraper.fetch(["cloud"], max_pages=5))

        assert results == []
        assert mock_post.call_count == 1

    def test_employment_type_mapping(self):
        assert _map_employment_type("Full time") == "FULL_TIME"
        assert _map_employment_type("full time") == "FULL_TIME"
        assert _map_employment_type("Part time") == "PART_TIME"
        assert _map_employment_type("Contract/Temp") == "CONTRACT"
        assert _map_employment_type("contract") == "CONTRACT"
        assert _map_employment_type(None) is None

    def test_company_falls_back_to_advertiser_description(self):
        """When companyName is null, advertiser.description is used."""
        scraper = JobStreetScraper()
        item = self._sample_item()
        item["companyName"] = None
        mock_resp = self._mock_response([item])

        with patch.object(scraper._session, "get", return_value=MagicMock(status_code=200)):
            with patch.object(scraper._session, "post", return_value=mock_resp):
                results = list(scraper.fetch(["test"], max_pages=1))

        assert results[0].company == "Acme Corp Advertiser"

    def test_contract_temp_work_type(self):
        """Contract/Temp workType should normalise to CONTRACT."""
        scraper = JobStreetScraper()
        item = self._sample_item("contract-job-1")
        item["workTypes"] = ["Contract/Temp"]
        item["salaryLabel"] = ""
        mock_resp = self._mock_response([item])

        with patch.object(scraper._session, "get", return_value=MagicMock(status_code=200)):
            with patch.object(scraper._session, "post", return_value=mock_resp):
                results = list(scraper.fetch(["contract"], max_pages=1))

        assert results[0].employment_type == "CONTRACT"
        assert results[0].salary_min is None
        assert results[0].salary_max is None


class TestParseSalary:
    def test_monthly_salary(self):
        assert _parse_salary("$10,000 – $15,000 per month") == (10000, 15000)

    def test_monthly_salary_en_dash(self):
        assert _parse_salary("$8,500 – $12,500 per month") == (8500, 12500)

    def test_annual_salary_converted_to_monthly(self):
        min_val, max_val = _parse_salary("$170,000 – $200,000 per year")
        assert min_val == round(170000 / 12)
        assert max_val == round(200000 / 12)

    def test_singapore_dollar_prefix(self):
        assert _parse_salary("S$ 8,000 - 9,200") == (8000, 9200)

    def test_empty_label_returns_none(self):
        assert _parse_salary("") == (None, None)

    def test_unparseable_label_returns_none(self):
        assert _parse_salary("Competitive") == (None, None)


class TestHandlerRegistry:
    def test_jobstreet_key_resolves_in_scrapers(self):
        import os

        os.environ.setdefault("JOBS_BUCKET", "test-bucket")
        os.environ.setdefault("JOBS_TABLE", "test-table")

        from infrastructure.handlers.scraper_handler import SCRAPERS

        assert "jobstreet" in SCRAPERS
        assert SCRAPERS["jobstreet"] is JobStreetScraper
