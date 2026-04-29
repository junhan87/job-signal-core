# AWS Services

> Back to [Architecture Overview](../ARCHITECTURE.md)

---

## Service Map

| Service | Role | Cost (personal use) |
|---|---|---|
| **Lambda** | Serverless compute — scraper, scorer, digest | Free tier |
| **EventBridge** | Daily cron trigger (10 am UTC) | Free |
| **S3** | Raw job JSON + resume PDF storage | ~$0.01/month |
| **DynamoDB** | Job dedup, match results, resume + JD cache | Free tier |
| **SES** | Daily HTML email digest | Free tier |
| **Bedrock** | LLM gateway — Claude Haiku + Sonnet in `ap-southeast-1` | ~$1.50/month |
| **Textract** | Resume PDF text extraction (one-time per upload) | Pay-per-page |
| **Secrets Manager** | Third-party API key storage | ~$0.80/month |
| **CloudWatch** | Structured logging, alarms, dashboards | Free tier |
| **X-Ray** | Distributed tracing — scorer Lambda, DynamoDB, S3, Bedrock | Free tier |
| **SQS** | Dead-letter queue for failed scorer jobs | Free tier |
| **SNS** | Ops alert fan-out — CloudWatch alarms → email | Free tier |
| **SSM Parameter Store** | Cross-stack resource references (core → saas at synth time) | Free tier |
| **CDK** | Infrastructure as Code — all AWS resources defined in Python | Free |
| **API Gateway** | REST API for SaaS layer (Phase 2+) | Free: 1M calls/month |
| **Cognito** | User authentication (Phase 2+) | Free: 50K MAU |

---

## Why Lambda over ECS / EC2?

The scraper and scorer run for ≤ 2 minutes daily. Lambda costs effectively $0.00 at personal-use scale and eliminates all container management overhead. ECS would add ~$15/month in idle container costs with no benefit at this workload size.

---

## Why DynamoDB over RDS?

Job listings and match records are accessed by primary key (`job_id`, `user_id`) and never require multi-table joins. DynamoDB's free tier handles 25 GB storage and 200M requests/month — RDS equivalent starts at ~$15/month and requires patch management.
