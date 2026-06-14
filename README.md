# Airbyte PostgreSQL → BigQuery Sync: A Support Engineer's Playbook

> A hands-on project exploring Airbyte from the perspective of a Customer Support Developer:
> setting up a real sync, intentionally breaking it, diagnosing the failures, and writing
> the kind of documentation a support team would actually use.

**Author:** Shaeba Elizabeth John
**Project goal:** Build deep, practical familiarity with Airbyte's database connectors,
CDC replication, log diagnosis, and customer-facing troubleshooting workflows.

---

## Why this repo exists

I'm a support engineer transitioning from mainframe file-transfer systems (IBM Sterling File
Gateway) into modern data integration. Rather than just reading docs, I built a working
Airbyte pipeline, broke it in realistic ways, and wrote up everything I learned — exactly
the kind of artifact a support developer produces every week.

## What's inside

| Folder | What it covers |
|---|---|
| `docs/setup.md` | Step-by-step local setup: Docker, Airbyte OSS, Postgres source, BigQuery destination |
| `docs/troubleshooting_playbook.md` | 8 real failure scenarios with root cause and fix — the kind of doc support teams actually use |
| `docs/cdc_notes.md` | My notes on understanding log-based replication (WAL, replication slots, publications) |
| `docs/lessons_learned.md` | What surprised me, what I'd warn a new user about |
| `sql/` | Schema, seed data, validation queries comparing source vs destination |
| `scripts/` | Python utilities: seed data generator, row-count reconciler, log parser |
| `screenshots/` | Airbyte UI screenshots from successful and failed syncs |

## Quick demo

```bash
# Start Postgres source + Airbyte locally
docker compose up -d

# Seed the source database with sample e-commerce data
python scripts/seed_postgres.py

# Configure Airbyte source/destination via UI (see docs/setup.md)
# Trigger a sync, then validate:
python scripts/reconcile_counts.py
```

## What I learned (TL;DR)

1. **CDC isn't magic** — it relies on the source DB's write-ahead log. If the replication
   slot fills up because no consumer is reading it, the source disk fills up and the DBA
   gets paged. This is a real production failure mode that support teams field constantly.

2. **"Sync failed" is never the real error** — the useful information is always 3–5 layers
   deep in the connector logs. I built a habit of grepping for the actual stack trace
   rather than the user-facing message.

3. **Schema evolution is where users get hurt** — adding a column on the source doesn't
   automatically propagate; you have to refresh the schema in Airbyte. I wrote up the
   exact reproduction steps in the troubleshooting playbook.

4. **Permissions are the #1 root cause** — at least half my self-inflicted failures came
   from the Postgres user lacking `REPLICATION` or `SELECT` on a new table. Now my first
   diagnostic question is always "what does `\du` show?"

Full notes in `docs/lessons_learned.md`.

## Tech stack

- **Airbyte OSS** (self-hosted via Docker Compose)
- **PostgreSQL 15** (source)
- **Google BigQuery** (destination, free tier)
- **Python 3.11** (utilities, reconciliation)
- **SQL** (validation, debugging)

## Background

I work as an Associate Software Engineer at Kyndryl, supporting IBM Sterling File Gateway
for US financial clients (Morgan Stanley, JP Morgan, BNY Mellon, etc.). My day-to-day is
triaging file-transfer failures across complex enterprise pipelines — translating that
experience to modern data integration is the goal of this project.

LinkedIn: [shaeba-elizabeth](https://www.linkedin.com/in/shaeba-elizabeth-ba5579212)
