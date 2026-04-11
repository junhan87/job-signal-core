"""CDK stack: scraper Lambda + supporting infrastructure.

Deploys:
  - S3 bucket (raw job data)
  - DynamoDB table (job index + dedup)
  - SQS dead-letter queue
  - Lambda function (scraper)
  - EventBridge rule (daily cron trigger, 00:00 UTC)
  - CloudWatch alarm (Lambda errors)
"""
from __future__ import annotations

import aws_cdk as cdk
from aws_cdk import (
    Duration,
    RemovalPolicy,
    aws_dynamodb as dynamodb,
    aws_events as events,
    aws_events_targets as targets,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_logs as logs,
    aws_s3 as s3,
    aws_sqs as sqs,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cw_actions,
    aws_sns as sns,
)
from constructs import Construct


class ScraperStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ── S3: raw job data ─────────────────────────────────────────────────
        jobs_bucket = s3.Bucket(
            self,
            "JobsRawBucket",
            bucket_name=f"jobscout-raw-{self.account}",
            versioned=False,
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="expire-raw-after-90-days",
                    expiration=Duration.days(90),
                )
            ],
            removal_policy=RemovalPolicy.RETAIN,
        )

        # ── DynamoDB: job index + dedup ──────────────────────────────────────
        jobs_table = dynamodb.Table(
            self,
            "JobsTable",
            table_name="jobscout-jobs",
            partition_key=dynamodb.Attribute(name="PK", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="SK", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="ttl",
            point_in_time_recovery=True,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # ── SQS: dead-letter queue for Lambda failures ───────────────────────
        dlq = sqs.Queue(
            self,
            "ScraperDLQ",
            queue_name="jobscout-scraper-dlq",
            retention_period=Duration.days(14),
            encryption=sqs.QueueEncryption.SQS_MANAGED,
        )

        # ── Lambda: scraper ──────────────────────────────────────────────────
        scraper_fn = lambda_.Function(
            self,
            "ScraperFunction",
            function_name="jobscout-scraper",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="infrastructure.lambda.scraper_handler.handler",
            code=lambda_.Code.from_asset(
                ".",
                exclude=[
                    "cdk.out", ".venv", ".git", "tests",
                    "__pycache__", "*.pyc", "node_modules",
                ],
            ),
            timeout=Duration.minutes(10),
            memory_size=512,
            environment={
                "JOBS_BUCKET": jobs_bucket.bucket_name,
                "JOBS_TABLE": jobs_table.table_name,
                "AWS_REGION": self.region,
            },
            log_retention=logs.RetentionDays.ONE_MONTH,
            dead_letter_queue=dlq,
        )

        # ── IAM: least-privilege grants ──────────────────────────────────────
        jobs_bucket.grant_put(scraper_fn)
        jobs_table.grant_read_write_data(scraper_fn)

        # ── EventBridge: daily cron 00:00 UTC ────────────────────────────────
        rule = events.Rule(
            self,
            "DailyScraperRule",
            rule_name="jobscout-daily-scraper",
            schedule=events.Schedule.cron(minute="0", hour="0"),
            description="Trigger JobScout scraper daily at 00:00 UTC",
        )
        rule.add_target(targets.LambdaFunction(scraper_fn))

        # ── CloudWatch: alarm on Lambda errors ───────────────────────────────
        ops_topic = sns.Topic(self, "OpsAlertsTopic", topic_name="jobscout-ops-alerts")

        error_alarm = cloudwatch.Alarm(
            self,
            "ScraperErrorAlarm",
            alarm_name="jobscout-scraper-errors",
            metric=scraper_fn.metric_errors(period=Duration.minutes(5)),
            threshold=1,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            alarm_description="JobScout scraper Lambda raised an error",
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        error_alarm.add_alarm_action(cw_actions.SnsAction(ops_topic))

        # ── Outputs ──────────────────────────────────────────────────────────
        cdk.CfnOutput(self, "JobsBucketName", value=jobs_bucket.bucket_name)
        cdk.CfnOutput(self, "JobsTableName", value=jobs_table.table_name)
        cdk.CfnOutput(self, "ScraperFunctionName", value=scraper_fn.function_name)
        cdk.CfnOutput(self, "DLQUrl", value=dlq.queue_url)
        cdk.CfnOutput(self, "OpsTopicArn", value=ops_topic.topic_arn)
