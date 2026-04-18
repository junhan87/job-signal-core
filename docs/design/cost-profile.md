# Cost Profile

> Back to [Architecture Overview](../ARCHITECTURE.md)

---

## Personal Use (~1 User)

| Service | Monthly Cost |
|---|---|
| Lambda (all functions) | $0.00 |
| EventBridge | $0.00 |
| DynamoDB | $0.00 |
| S3 | ~$0.01 |
| SES | $0.00 |
| Bedrock (Claude Haiku) | ~$1.50 |
| Secrets Manager | ~$0.80 |
| **Total** | **~$2.31/month** |

---

## SaaS at 1,000 Users

| Service | Monthly Cost | Notes |
|---|---|---|
| Bedrock (Haiku + Sonnet) | ~$211 | JD parsing shared via cache |
| DynamoDB | ~$5 | On-demand pricing |
| Lambda | ~$2 | Beyond free tier |
| SES | ~$3 | ~30K emails/month |
| **Total** | **~$221/month** | At SGD 15/user Pro plan = SGD 15K MRR = **1.4% of revenue** |

The JD parsing cache is the key cost lever. Without it, 1,000 users scoring against the same 50 daily jobs would generate 50,000 Bedrock calls/day instead of 50.
