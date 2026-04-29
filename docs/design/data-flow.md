# Data Flow

> Back to [Architecture Overview](../ARCHITECTURE.md)

---

## S3 Object Layout

```
jobsignal-raw/
├── mcf/
│   └── 2026-04-10/
│       └── jobs_batch_01.json
└── batches/
    └── 2026-04-10/
        └── {batch_id}.json        ← scorer trigger

jobsignal-resumes/
└── {user_id}/
    └── resume.pdf
```

---

## DynamoDB Table Design

| Table | Owner | Key Fields | TTL | Purpose |
|---|---|---|---|---|
| `jobsignal-jobs` | `job-signal-core` | `job_id` | 60 days | Raw job metadata + dedup |
| `jobsignal-matches` | `job-signal-saas` | `user_id` + `job_id` | 90 days | Scored results per user |
| `jobsignal-resume-cache` | `job-signal-saas` | `user_id` | None | Structured resume profile |
| `jobsignal-jd-cache` | `job-signal-saas` | `job_id` | 60 days | Parsed JD — shared across users |

All TTL values are set at write time. DynamoDB handles expiry automatically — no maintenance Lambda required.

---

## LLM Provider Decision

AWS Bedrock was chosen over direct Anthropic / OpenAI API calls for four reasons:

1. **Data residency** — All inference runs within a single configured AWS region. Resume data never leaves that regional infrastructure.
2. **IAM authentication** — Lambda assumes a role directly; no API keys to store or rotate.
3. **Model portability** — Swapping Claude for Llama 4 requires one line change in the model map, not an architecture change.
4. **Portfolio signal** — AWS-native design is what Cloud Architect and Solutions Architect roles expect to see.

> DeepSeek was evaluated and rejected immediately — it processes data on China-based infrastructure, which is incompatible with handling personal resume data in Singapore.
