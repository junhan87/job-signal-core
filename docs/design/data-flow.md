# Data Flow

> Back to [Architecture Overview](../ARCHITECTURE.md)

---

## S3 Object Layout

```
jobsignal-raw/
└── mcf/
    └── 2026-04-10/
        └── jobs_batch_01.json

jobsignal-resumes/
└── {user_id}/
    └── resume_v3.pdf
```

---

## DynamoDB Table Design

| Table | Partition Key | Sort Key | TTL | Purpose |
|---|---|---|---|---|
| `jobs` | `job_id` | — | 60 days | Raw job metadata + dedup |
| `matches` | `USER#{user_id}` | `JOB#{job_id}` | 90 days | Scored results per user |
| `resume_cache` | `USER#{user_id}` | — | None | Structured resume profile |
| `jd_cache` | `job_id` | — | 60 days | Parsed JD — shared across users |

All TTL values are set at write time. DynamoDB handles expiry automatically — no maintenance Lambda required.

---

## LLM Provider Decision

AWS Bedrock was chosen over direct Anthropic / OpenAI API calls for four reasons:

1. **Data residency** — All inference runs within a single configured AWS region. Resume data never leaves that regional infrastructure.
2. **IAM authentication** — Lambda assumes a role directly; no API keys to store or rotate.
3. **Model portability** — Swapping Claude for Llama 4 requires one line change in the model map, not an architecture change.
4. **Portfolio signal** — AWS-native design is what Cloud Architect and Solutions Architect roles expect to see.

> DeepSeek was evaluated and rejected immediately — it processes data on China-based infrastructure, which is incompatible with handling personal resume data in Singapore.
