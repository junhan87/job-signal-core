"""Integration tests for the scraper Lambda handler (moto — no real AWS)."""
from __future__ import annotations

import json
import os

import boto3
import pytest
from moto import mock_aws
from unittest.mock import MagicMock, patch

os.environ.setdefault("JOBS_BUCKET", "test-jobs-bucket")
os.environ.setdefault("JOBS_TABLE", "test-jobs-table")
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-southeast-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SECURITY_TOKEN", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")


@pytest.fixture(autouse=True)
def aws_env():
    """Ensure fake credentials are always set for moto."""
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"


@mock_aws
def test_handler_stores_new_job_and_deduplicates():
    """First call stores the job; second call with same job is deduped."""
    # --- Arrange AWS resources via moto ---
    s3 = boto3.client("s3", region_name="ap-southeast-1")
    s3.create_bucket(
        Bucket="test-jobs-bucket",
        CreateBucketConfiguration={"LocationConstraint": "ap-southeast-1"},
    )

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

    # --- Mock the scraper to return a predictable listing ---
    from scraper.base_scraper import JobListing

    fake_listing = JobListing(
        job_id="test-uuid-001",
        title="Cloud Architect",
        company="Test Corp",
        description="Build on AWS",
        url="https://mcf.gov.sg/job/test-uuid-001",
        source="mcf",
        salary_min=8000,
        salary_max=12000,
    )

    MockScraper = MagicMock()
    mock_instance = MagicMock()
    mock_instance.source = "mcf"
    mock_instance.fetch.return_value = iter([fake_listing])
    MockScraper.return_value = mock_instance

    # Patch the SCRAPERS dict so handler uses our mock
    with patch.dict("infrastructure.handlers.scraper_handler.SCRAPERS", {"mcf": MockScraper}):
        from infrastructure.handlers import scraper_handler

        # First run — should store
        result1 = scraper_handler.handler({}, None)
        assert result1["new"] == 1
        assert result1["duplicates"] == 0

        # Second run — same listing, should be deduped
        mock_instance.fetch.return_value = iter([fake_listing])
        result2 = scraper_handler.handler({}, None)
        assert result2["new"] == 0
        assert result2["duplicates"] == 1

    # Verify S3 objects: 1 raw job + 1 batch manifest
    objects = s3.list_objects_v2(Bucket="test-jobs-bucket")
    assert objects["KeyCount"] == 2
    keys = sorted(obj["Key"] for obj in objects["Contents"])

    raw_key = [k for k in keys if k.startswith("raw/")][0]
    body = s3.get_object(Bucket="test-jobs-bucket", Key=raw_key)["Body"].read()
    data = json.loads(body)
    assert data["job_id"] == "test-uuid-001"

    # Verify batch manifest structure
    manifest_key = [k for k in keys if k.startswith("batches/")][0]
    manifest = json.loads(
        s3.get_object(Bucket="test-jobs-bucket", Key=manifest_key)["Body"].read()
    )
    assert manifest["source"] == "mcf"
    assert manifest["job_ids"] == ["test-uuid-001"]
    assert manifest["job_count"] == 1
    assert "batch_id" in manifest
    assert manifest["batch_id"].startswith("mcf-")
    assert "scraped_at" in manifest

    # Verify batch_id is returned in handler response
    assert result1["batch_id"] is not None
    assert result1["batch_id"] == manifest["batch_id"]


@mock_aws
def test_handler_routes_jobstreet_platform():
    """EventBridge passes {"platform": "jobstreet"} — handler must route to JobStreetScraper."""
    s3 = boto3.client("s3", region_name="ap-southeast-1")
    s3.create_bucket(
        Bucket="test-jobs-bucket",
        CreateBucketConfiguration={"LocationConstraint": "ap-southeast-1"},
    )
    ddb = boto3.resource("dynamodb", region_name="ap-southeast-1")
    table = ddb.create_table(
        TableName="test-jobs-table",
        KeySchema=[{"AttributeName": "job_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "job_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    table.wait_until_exists()

    from scraper.base_scraper import JobListing

    fake_listing = JobListing(
        job_id="js-job-001",
        title="Solutions Architect",
        company="Tech Corp",
        description="Design systems",
        url="https://sg.jobstreet.com/job/js-job-001",
        source="jobstreet",
    )

    MockScraper = MagicMock()
    mock_instance = MagicMock()
    mock_instance.source = "jobstreet"
    mock_instance.fetch.return_value = iter([fake_listing])
    MockScraper.return_value = mock_instance

    with patch.dict(
        "infrastructure.handlers.scraper_handler.SCRAPERS",
        {"jobstreet": MockScraper},
    ):
        from infrastructure.handlers import scraper_handler

        result = scraper_handler.handler({"platform": "jobstreet"}, None)

    assert result["new"] == 1
    assert result["errors"] == 0
    assert result["batch_id"].startswith("jobstreet-")
    mock_instance.fetch.assert_called_once()


def test_handler_raises_for_unknown_platform():
    """An unrecognised platform key must raise ValueError — not silently default."""
    with patch.dict(
        "infrastructure.handlers.scraper_handler.SCRAPERS",
        {"mcf": MagicMock(), "jobstreet": MagicMock()},
    ):
        from infrastructure.handlers import scraper_handler

        with pytest.raises(ValueError, match="Unknown platform"):
            scraper_handler.handler({"platform": "indeed"}, None)

