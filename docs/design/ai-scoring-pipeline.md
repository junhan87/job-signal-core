# AI Scoring Pipeline

> Back to [Architecture Overview](../ARCHITECTURE.md)

---

## Overview

The scoring pipeline deliberately separates **deterministic business logic (Python)** from **language understanding tasks (Bedrock)**. This is a conscious architectural decision, not a cost optimisation.

---

## Pipeline Diagram

```mermaid
flowchart LR
    A["📄 Raw Job Description"] --> B["JD Parser<br>Bedrock — Claude Haiku<br>Extract skills, seniority,<br>certs, requirements"]
    C["📋 Resume PDF"] --> D["Resume Parser<br>Textract → Claude Haiku<br>Structured JSON profile<br>Cached per user"]

    B & D --> E

    subgraph Python["Pure Python — No LLM"]
        E["Scoring Engine<br>7-factor weighted score<br>0.0 – 10.0"]
        F["Market Adjustment<br>Recency · FCF listing · Company tier"]
        G["Action Recommender<br>Apply Now / Consider / Skip"]
    end

    E --> F --> G

    subgraph Bedrock["AWS Bedrock — Claude Sonnet"]
        H["Gap Analyser<br>Articulates what is missing<br>and how to address it"]
        I["Summary Generator<br>Plain-English match paragraph"]
    end

    G -->|score ≥ 5.0| H & I
    H & I --> J["📥 DynamoDB<br>Match Record + TTL"]
    J --> K["📧 Email Digest<br>Top 5 matches"]
```

---

## Scoring Factors

The scoring engine evaluates seven weighted factors. Specific weights and sub-criteria are proprietary and defined in the private `job-signal-saas` repository.

| Factor |
|---|
| Technical Skills Match |
| Seniority Alignment |
| Work Arrangement |
| Citizenship Eligibility |
| + 3 additional proprietary factors |

---

## Why Python Handles Scoring (Not the LLM)

| Property | Python Engine | Claude API |
|---|---|---|
| Consistency | Same inputs → same score, always | Non-deterministic |
| Explainability | Exact factor breakdown available | Black box |
| Cost | Zero marginal cost | $0.002–0.015 per call |
| Latency | Sub-millisecond | 1–3 seconds |
| Auditability | Unit-testable, version-controlled weights | Prompt-dependent |

Claude is used only where language understanding cannot be replaced by deterministic logic: parsing unstructured text and generating human-readable prose.

---

## JD Parsing Cache Design

```
Without caching:  1,000 users × 50 JDs/day = 50,000 Bedrock calls/day
With caching:     50 new JDs/day = 50 Bedrock calls/day   (1,000× cheaper)
```

Each unique job description is parsed once. The structured result is cached in DynamoDB and reused for every user who is scored against that job.

---

## Action Recommendation Thresholds

| Score Range | Recommendation |
|---|---|
| ≥ 8.0, no blocking gaps | 🟢 **Apply Now** — Strong Match |
| ≥ 6.5, ≤ 1 blocking gap | 🟡 **Apply with Note** — Address gap in cover letter |
| ≥ 5.0 | 🟠 **Consider** — Several gaps, lower probability |
| < 5.0 or hard disqualifier | 🔴 **Skip** — Poor match |
