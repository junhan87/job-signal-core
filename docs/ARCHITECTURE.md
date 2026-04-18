# JobSignal — System Architecture

> AI-powered job screener that scrapes job platforms daily, scores each listing against your resume with AI, and delivers the top matches to your inbox.

---

## The Problem

Platform job alerts match on job title keywords only — not on the actual job description vs your resume. You waste 30–60 minutes per day reading irrelevant listings, miss well-matched roles with non-standard titles, and have no single tool aggregating multiple platforms.

## The Solution

JobSignal scrapes job platforms daily, uses AI to screen each listing against a structured resume profile, scores every role across seven weighted factors, and delivers only the top matches — with a fit score, plain-English summary, and actionable gap analysis.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Compute | AWS Lambda (serverless) |
| Scheduling | Amazon EventBridge (daily cron) |
| Storage | Amazon S3 + DynamoDB |
| AI / LLM | AWS Bedrock — Claude Haiku 4.5 + Sonnet 4.6 |
| Notifications | Amazon SES (email digest) |
| Infrastructure as Code | AWS CDK (Python) |
| CI/CD | GitHub Actions + OIDC (no static credentials) |
| Language | Python 3.12 |

---

## Architecture

```mermaid
flowchart TD
    subgraph Trigger["⏰ Schedule Layer"]
        EB["EventBridge<br>Daily cron — 10 am UTC"]
    end

    subgraph Scraper["🔍 Scraper Layer (Public Repo)"]
        LS["Lambda: Scraper"]
        MCF["MyCareersFuture<br>Public API"]
        JS["Jobstreet<br>HTML Scraper (Phase 2)"]
        IN["Indeed<br>Scraper (Phase 2)"]
    end

    subgraph Storage["🗄️ Storage Layer"]
        S3R["S3: Raw Job Data<br>jobsignal-raw/"]
        S3P["S3: Resume PDFs<br>jobsignal-resumes/"]
        DDB["DynamoDB<br>Jobs · Matches · Resume Cache"]
    end

    subgraph Scorer["🤖 AI Scorer Layer (Private Repo)"]
        LA["Lambda: AI Scorer"]
        RP["Resume Parser<br>Textract → Bedrock → JSON"]
        JP["JD Parser<br>Bedrock Claude Haiku<br>(cached — shared across users)"]
        SE["Scoring Engine<br>Python — 7-factor weighted score"]
        MA["Market Adjustment<br>Python — recency, company tier, FCF"]
        GA["Gap Analyser<br>Python identifies · Claude articulates"]
        AR["Action Recommender<br>Python threshold logic"]
        SG["Summary Generator<br>Claude Sonnet"]
    end

    subgraph LLM["☁️ AWS Bedrock (ap-southeast-1)"]
        CH["Claude Haiku 4.5<br>Parsing tasks"]
        CS["Claude Sonnet 4.6<br>Writing tasks"]
    end

    subgraph Notify["📬 Notification Layer"]
        LB["Lambda: Digest Builder"]
        SES["Amazon SES<br>HTML email digest"]
        USER["📥 Daily Email<br>Top 5 matches"]
    end

    EB -->|triggers| LS
    LS --> MCF & JS & IN
    MCF & JS & IN -->|raw JSON| S3R
    S3R -->|triggers| LA
    LA --> RP & JP
    RP -->|Textract| S3P
    JP -->|structured JD| DDB
    RP -->|structured profile| DDB
    DDB -->|cached data| SE
    SE --> MA --> GA --> AR --> SG
    LA -->|scored results| DDB
    CH -.->|parse| JP & RP
    CS -.->|write| GA & SG
    DDB -->|top matches| LB
    LB -->|sends| SES
    SES --> USER

    style Trigger fill:#f0f4ff,stroke:#3b82f6,color:#000000
    style Scraper fill:#f0fff4,stroke:#22c55e,color:#000000
    style Storage fill:#fffbeb,stroke:#f59e0b,color:#000000
    style Scorer fill:#fdf4ff,stroke:#a855f7,color:#000000
    style LLM fill:#fff1f2,stroke:#f43f5e,color:#000000
    style Notify fill:#f0f9ff,stroke:#0ea5e9,color:#000000
```

### How It Works

1. **EventBridge** fires a cron at 10 am UTC every day
2. **Scraper Lambda** calls the MyCareersFuture public API, extracts job listings, deduplicates against DynamoDB, and stores raw JSON to S3
3. **AI Scorer Lambda** picks up new jobs from S3, parses each job description via Bedrock (result cached — called once per unique JD across all users), and runs every listing through the 7-factor Python scoring engine
4. Market adjustments (recency, company tier, FCF listing status) are applied by Python
5. For jobs scoring ≥ 5.0, Bedrock articulates gap analysis and generates a human-readable match summary
6. Results are written to DynamoDB with a TTL of 90 days
7. **Digest Lambda** queries the top 5 matches and sends a formatted HTML email via SES

---

## Repository Strategy

This project uses an **Open Core model**:

| Repository | Visibility | Contents | Licence |
|---|---|---|---|
| `job-signal-core` (this repo) | Public | Scrapers, CDK infrastructure, CLI | AGPL v3 |
| `job-signal-saas` | Private | AI scorer, SaaS API, billing, dashboard | Proprietary |

The AGPL v3 licence permits free self-hosting and forks, but requires anyone running a hosted service to open-source their modifications. This is the same strategy used by Grafana, GitLab, and MongoDB — providing open portfolio visibility while protecting commercial IP.

### What Lives Where

```
Public repo (job-signal-core)         Private repo (job-signal-saas)
─────────────────────────────         ──────────────────────────────
MyCareersFuture scraper               AI scoring engine (7 factors)
Jobstreet scraper                     Prompt templates
CDK infrastructure stacks             SaaS API (API Gateway + Lambda)
Lambda handler entry points           Multi-tenant DynamoDB design
CI/CD GitHub Actions workflows        Cognito user management
Unit + integration tests              Stripe billing integration
This architecture document            React dashboard
```

---

## Deep Dives

Detailed design documentation for each building block:

| Topic | Document |
|---|---|
| AWS service choices and justifications | [AWS Services](design/aws-services.md) |
| AI scoring pipeline, caching, and thresholds | [AI Scoring Pipeline](design/ai-scoring-pipeline.md) |
| S3 layout, DynamoDB schema, LLM provider decision | [Data Flow](design/data-flow.md) |
| Cost profile — personal use and SaaS at scale | [Cost Profile](design/cost-profile.md) |
| Key design decisions (CDK, EventBridge, OIDC, model strategy) | [Design Decisions](design/design-decisions.md) |

---
