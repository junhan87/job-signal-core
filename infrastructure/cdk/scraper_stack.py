"""CDK stack: scraper Lambda + supporting infrastructure.

Deploys:
  - S3 bucket (raw job data)
  - DynamoDB table (job index + dedup)
  - SQS dead-letter queue
  - Lambda function (scraper)
  - EventBridge rule (daily cron trigger, 10:00 UTC)
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
            bucket_name=f"jobsignal-raw-{self.account}",
            versioned=False,
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            # Raw objects expire after 90 days. DynamoDB TTL is 60 days.
            # The 30-day gap is intentional: raw JSON stays available for
            # reprocessing or audit after the DynamoDB index entry expires.
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="expire-raw-after-90-days",
                    expiration=Duration.days(90),
                )
            ],
            removal_policy=RemovalPolicy.RETAIN,
        )

        # ── DynamoDB: job index + dedup ──────────────────────────────────────
        # Future tables (add when their features are built):
        #   - jobsignal-matches:      PK=USER#{user_id}, SK=JOB#{job_id}
        #   - jobsignal-resume-cache: PK=USER#{user_id}
        #   - jobsignal-jd-cache:     PK=job_id
        jobs_table = dynamodb.Table(
            self,
            "JobsTable",
            table_name="jobsignal-jobs",
            partition_key=dynamodb.Attribute(name="job_id", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="ttl",
            point_in_time_recovery=True,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # ── SQS: dead-letter queue for Lambda failures ───────────────────────
        dlq = sqs.Queue(
            self,
            "ScraperDLQ",
            queue_name="jobsignal-scraper-dlq",
            retention_period=Duration.days(14),
            encryption=sqs.QueueEncryption.SQS_MANAGED,
        )

        # ── Lambda Layer: runtime dependencies ───────────────────────────────
        deps_layer = lambda_.LayerVersion(
            self,
            "ScraperDepsLayer",
            code=lambda_.Code.from_asset("layer"),
            compatible_runtimes=[lambda_.Runtime.PYTHON_3_12],
            description="Runtime dependencies (requests)",
        )

        # ── Lambda: scraper ──────────────────────────────────────────────────
        scraper_fn = lambda_.Function(
            self,
            "ScraperFunction",
            function_name="jobsignal-scraper",
            runtime=lambda_.Runtime.PYTHON_3_12,
            layers=[deps_layer], 
            handler="infrastructure.handlers.scraper_handler.handler",
            code=lambda_.Code.from_asset(
                ".",
                exclude=[
                    "cdk.out", ".venv", ".git", "tests",
                    "__pycache__", "*.pyc", "node_modules",
                    "layer",
                ],
            ),
            timeout=Duration.minutes(10),
            memory_size=512,
            environment={
                "JOBS_BUCKET": jobs_bucket.bucket_name,
                "JOBS_TABLE": jobs_table.table_name,
            },
            log_retention=logs.RetentionDays.ONE_MONTH,
            dead_letter_queue=dlq,
        )

        # ── IAM: least-privilege grants ──────────────────────────────────────
        jobs_bucket.grant_put(scraper_fn)
        jobs_table.grant_read_write_data(scraper_fn)

        # ── EventBridge: daily cron 10:00 UTC ────────────────────────────────
        rule = events.Rule(
            self,
            "DailyScraperRule",
            rule_name="jobsignal-daily-scraper",
            schedule=events.Schedule.cron(minute="0", hour="10"),
            description="Trigger JobSignal scraper daily at 10:00 UTC",
        )
        rule.add_target(targets.LambdaFunction(scraper_fn))

        # ── CloudWatch: alarm on Lambda errors ───────────────────────────────
        ops_topic = sns.Topic(self, "OpsAlertsTopic", topic_name="jobsignal-ops-alerts")

        error_alarm = cloudwatch.Alarm(
            self,
            "ScraperErrorAlarm",
            alarm_name="jobsignal-scraper-errors",
            metric=scraper_fn.metric_errors(period=Duration.minutes(5)),
            threshold=1,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            alarm_description="JobSignal scraper Lambda raised an error",
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        error_alarm.add_alarm_action(cw_actions.SnsAction(ops_topic))

        # ── Outputs ──────────────────────────────────────────────────────────
        cdk.CfnOutput(self, "JobsBucketName", value=jobs_bucket.bucket_name)
        cdk.CfnOutput(self, "JobsTableName", value=jobs_table.table_name)
        cdk.CfnOutput(self, "ScraperFunctionName", value=scraper_fn.function_name)
        cdk.CfnOutput(self, "DLQUrl", value=dlq.queue_url)
        cdk.CfnOutput(self, "OpsTopicArn", value=ops_topic.topic_arn)
