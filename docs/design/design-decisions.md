# Design Decisions

> Back to [Architecture Overview](../ARCHITECTURE.md)

---

## CDK over Terraform

AWS CDK (Python) was chosen for this project because all infrastructure logic is already in Python — the same language as the application code. This allows shared types, constants, and test utilities between application code and infrastructure definitions. Terraform would require a context switch to HCL and a separate state management setup.

---

## EventBridge over SQS Fan-Out (Phase 1)

For a single-user daily scrape, EventBridge→Lambda is the simplest correct solution. The architecture is designed to migrate to SQS fan-out with Step Functions orchestration in Phase 2 when parallel per-user scoring becomes necessary. This is documented in ADR-011.

---

## GitHub Actions with OIDC Authentication

All CI/CD workflows use AWS OIDC federation. No long-lived AWS credentials are stored in GitHub Secrets. The deploy workflow assumes a scoped IAM role via `aws-actions/configure-aws-credentials` with a short-lived token.

---

## Phased Model Strategy

| Phase | Users | Models | Cost |
|---|---|---|---|
| Phase 1 | 0–100 | Claude Haiku 4.5 for all tasks | ~$1.50/month |
| Phase 2 | 100–1,000 | Haiku for parsing, Sonnet for writing | ~$211/month per 1K users |
| Phase 3 | 1,000+ | Llama 4 via Bedrock for parsing, Sonnet for writing | Evaluate SageMaker self-host |
