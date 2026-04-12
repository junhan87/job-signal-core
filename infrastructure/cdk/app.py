#!/usr/bin/env python3
"""CDK app entry point."""
import aws_cdk as cdk
from infrastructure.cdk.scraper_stack import ScraperStack

app = cdk.App()

ScraperStack(
    app,
    "JobSignalScraperStack",
    env=cdk.Environment(region="ap-southeast-1"),
)

app.synth()
