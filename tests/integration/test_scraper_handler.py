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

    # Verify S3 object was created
    objects = s3.list_objects_v2(Bucket="test-jobs-bucket")
    assert objects["KeyCount"] == 1
    body = s3.get_object(
        Bucket="test-jobs-bucket", Key=objects["Contents"][0]["Key"]
    )["Body"].read()
    data = json.loads(body)
    assert data["job_id"] == "test-uuid-001"
