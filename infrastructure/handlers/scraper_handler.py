"""Lambda handler for the daily MCF scraper job.

Triggered by EventBridge (daily cron, 00:00 UTC).
Reads config from environment variables (set via CDK).
Writes raw JSON to S3 and deduplicates via DynamoDB.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

from scraper.base_scraper import BaseScraper
from scraper.mycareersfuture import MyCareersFutureScraper

# --- Scraper registry (add new scrapers here) ---
SCRAPERS: dict[str, type[BaseScraper]] = {
    "mcf": MyCareersFutureScraper,
}

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# --- Config from environment (injected by CDK) ---
JOBS_BUCKET = os.environ["JOBS_BUCKET"]
JOBS_TABLE = os.environ["JOBS_TABLE"]
AWS_REGION = os.environ.get("AWS_REGION", "ap-southeast-1")

# Default search terms — can be overridden by Lambda event payload
DEFAULT_SEARCH_TERMS = [
    "cloud architect",
    "solutions architect",
    "cloud engineer",
    "devops engineer",
    "platform engineer",
]

s3 = boto3.client("s3", region_name=AWS_REGION)
dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
jobs_table = dynamodb.Table(JOBS_TABLE)


def handler(event: dict, context) -> dict:
    """Lambda entry point."""
    platform: str = event.get("platform", "mcf")
    search_terms: list[str] = event.get("search_terms", DEFAULT_SEARCH_TERMS)
    run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if platform not in SCRAPERS:
        raise ValueError(f"Unknown platform: {platform!r}. Available: {list(SCRAPERS)}")

    logger.info("Scraper started | platform=%s | date=%s | terms=%s", platform, run_date, search_terms)

    scraper = SCRAPERS[platform]()
    new_count = 0
    dup_count = 0
    error_count = 0

    for listing in scraper.fetch(search_terms):
        try:
            if _is_duplicate(listing.job_id):
                dup_count += 1
                continue

            _store_to_s3(listing, run_date)
            _record_in_dynamodb(listing)
            new_count += 1

        except ClientError as exc:
            logger.error("AWS error for job %s: %s", listing.job_id, exc)
            error_count += 1
        except Exception as exc:  # noqa: BLE001
            logger.error("Unexpected error for job %s: %s", listing.job_id, exc)
            error_count += 1

    summary = {
        "date": run_date,
        "new": new_count,
        "duplicates": dup_count,
        "errors": error_count,
    }
    logger.info("Scraper complete | %s", summary)
    return summary


def _is_duplicate(job_id: str) -> bool:
    """Return True if job_id already exists in DynamoDB."""
    response = jobs_table.get_item(
        Key={"job_id": job_id},
        ProjectionExpression="job_id",
    )
    return "Item" in response


def _store_to_s3(listing, run_date: str) -> None:
    """Write raw job JSON to S3 under a date-partitioned prefix."""
    key = f"raw/{listing.source}/{run_date}/{listing.job_id}.json"
    s3.put_object(
        Bucket=JOBS_BUCKET,
        Key=key,
        Body=listing.to_json(),
        ContentType="application/json",
    )


def _record_in_dynamodb(listing) -> None:
    """Write a lightweight index record to DynamoDB for dedup and querying."""
    jobs_table.put_item(
        Item={
            "job_id": listing.job_id,
            "title": listing.title,
            "company": listing.company,
            "url": listing.url,
            "source": listing.source,
            "salary_min": listing.salary_min,
            "salary_max": listing.salary_max,
            "employment_type": listing.employment_type,
            "location": listing.location,
            "posted_date": listing.posted_date,
            "scraped_at": listing.scraped_at,
            # TTL: expire records after 60 days
            "ttl": _ttl_epoch(days=60),
        }
    )


def _ttl_epoch(days: int) -> int:
    """Return Unix epoch seconds for `days` from now (used by DynamoDB TTL)."""
    import time
    return int(time.time()) + days * 86400
