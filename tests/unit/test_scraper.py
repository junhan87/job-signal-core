"""Unit tests for the MCF scraper using moto (no real AWS calls)."""
from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import boto3
import pytest
from moto import mock_aws

# Set required env vars before importing handler
os.environ.setdefault("JOBS_BUCKET", "test-jobs-bucket")
os.environ.setdefault("JOBS_TABLE", "test-jobs-table")
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-southeast-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SECURITY_TOKEN", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")


@pytest.fixture()
def aws_credentials():
    """Mocked AWS credentials so moto intercepts all boto3 calls."""
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"


@pytest.fixture()
def s3_bucket(aws_credentials):
    with mock_aws():
        s3 = boto3.client("s3", region_name="ap-southeast-1")
        s3.create_bucket(
            Bucket="test-jobs-bucket",
            CreateBucketConfiguration={"LocationConstraint": "ap-southeast-1"},
        )
        yield s3


@pytest.fixture()
def dynamo_table(aws_credentials):
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="ap-southeast-1")
        table = ddb.create_table(
            TableName="test-jobs-table",
            KeySchema=[
                {"AttributeName": "job_id", "KeyType": "HASH"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "job_id", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        table.wait_until_exists()
        yield table


class TestJobListing:
    def test_to_dict_contains_all_fields(self):
        from scraper.base_scraper import JobListing

        listing = JobListing(
            job_id="abc123",
            title="Cloud Engineer",
            company="Acme",
            description="Build stuff on AWS",
            url="https://example.com/job/abc123",
            source="mcf",
        )
        d = listing.to_dict()
        assert d["job_id"] == "abc123"
        assert d["source"] == "mcf"
        assert d["salary_min"] is None

    def test_to_json_is_valid_json(self):
        from scraper.base_scraper import JobListing

        listing = JobListing(
            job_id="j1",
            title="SRE",
            company="Corp",
            description="...",
            url="https://example.com",
            source="mcf",
        )
        parsed = json.loads(listing.to_json())
        assert parsed["job_id"] == "j1"


class TestMCFScraper:
    def _mock_mcf_response(self, items: list[dict], total: int = None) -> dict:
        return {"results": items, "total": total or len(items)}

    def _sample_item(self, job_id: str = "uuid-1") -> dict:
        return {
            "uuid": job_id,
            "title": "Cloud Solutions Architect",
            "postedCompany": {"name": "DBS Bank"},
            "description": "We need an architect",
            "salary": {"minimum": 8000, "maximum": 12000},
            "employmentTypes": [{"employmentType": {"employmentType": "FULL_TIME"}}],
            "positionLocations": [{"location": {"district": "Central"}}],
            "metadata": {"createdAt": "2026-04-01T08:00:00Z"},
        }

    def test_fetch_yields_job_listing(self):
        from scraper.mycareersfuture import MyCareersFutureScraper

        scraper = MyCareersFutureScraper()
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = self._mock_mcf_response([self._sample_item()])

        with patch.object(scraper._session, "get", return_value=mock_resp):
            results = list(scraper.fetch(["cloud architect"], max_pages=1))

        assert len(results) == 1
        assert results[0].job_id == "uuid-1"
        assert results[0].company == "DBS Bank"
        assert results[0].salary_min == 8000
        assert results[0].source == "mcf"

    def test_fetch_stops_when_no_results(self):
        from scraper.mycareersfuture import MyCareersFutureScraper

        scraper = MyCareersFutureScraper()
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"results": [], "total": 0}

        with patch.object(scraper._session, "get", return_value=mock_resp) as mock_get:
            results = list(scraper.fetch(["no results term"], max_pages=5))

        assert results == []
        assert mock_get.call_count == 1  # stopped after first empty page

    def test_malformed_item_is_skipped(self):
        from scraper.mycareersfuture import MyCareersFutureScraper

        scraper = MyCareersFutureScraper()
        # Item with no uuid should be skipped
        bad_item = {"title": "No ID job"}
        good_item = self._sample_item("good-uuid")
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = self._mock_mcf_response([bad_item, good_item])

        with patch.object(scraper._session, "get", return_value=mock_resp):
            results = list(scraper.fetch(["test"], max_pages=1))

        assert len(results) == 1
        assert results[0].job_id == "good-uuid"

    def test_request_exception_breaks_loop(self):
        from scraper.mycareersfuture import MyCareersFutureScraper
        from requests.exceptions import ConnectionError

        scraper = MyCareersFutureScraper()
        with patch.object(scraper._session, "get", side_effect=ConnectionError("timeout")):
            results = list(scraper.fetch(["cloud"], max_pages=5))

        assert results == []
