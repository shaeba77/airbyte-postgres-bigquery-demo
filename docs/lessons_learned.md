# Lessons Learned

Honest reflection on what surprised me, what I struggled with, and what I'd tell
the next person picking this up.

## What surprised me

**1. How much of "data integration" is really database internals.**

I expected this to be mostly about ETL tooling. It's not. To actually support
Airbyte, you have to understand Postgres replication, MySQL binlog format, SQL Server
permissions, BigQuery loading semantics, and so on. The integration tool is the thin
layer; the depth is in the source and destination systems.

This is a strength for someone with a support background — we're used to learning
new systems quickly. But I underestimated how much DB knowledge I needed.

**2. The UI hides the interesting failures.**

The Airbyte web UI gives clean status messages: "Sync failed." The actual cause is
always in the connector logs, often dozens of lines deep, often as a stack trace
from a library the user has never heard of (jOOQ, Debezium, Jackson). Getting
comfortable reading these logs was the highest-leverage skill I built.

This mirrors my Sterling File Gateway work, where the alert says "file failed" but
the real cause is in the gateway logs and the IBM Tivoli trace — three layers down.

**3. Permissions are 50% of all issues.**

Postgres user missing `REPLICATION`, BigQuery service account missing dataset access,
S3 bucket policy missing `s3:ListBucket` — I broke things this way constantly. I
now default to checking permissions first on any new ticket.

**4. CDC is fragile in a specific, predictable way.**

The replication slot mechanism is brilliant but unforgiving. If your consumer goes
down and stays down, your source disk fills. If you reset the wrong stream, you lose
state. If you don't have a primary key, your UPDATEs are wrong. These aren't bugs —
they're the consequences of CDC's design — but they're traps for new users.

## What I struggled with

**Java stack traces.** Airbyte connectors are mostly Java. I haven't written Java
professionally, so the first few stack traces felt opaque. I got better fast — most
support work is about pattern-matching, not writing the code — but I want to do a
focused refresher on Java fundamentals.

**BigQuery cost mental model.** I'm used to fixed-cost on-prem systems. BigQuery's
"you pay per byte scanned" model means a poorly-written validation query can cost
real money. I had to retrain my instinct to "just SELECT * and look at it."

**Knowing when to stop investigating.** As a support engineer, you have to triage
fast. I caught myself going down rabbit holes on minor issues. Need to keep
sharpening the "is this blocking the customer right now?" instinct.

## What I'd tell the next person

1. **Set up Airbyte locally first, before you read any docs.** The hands-on
   experience makes every doc 10× more useful.

2. **Break things on purpose.** Run a sync with a missing permission. Kill the
   destination mid-load. Drop a column. Each failure teaches you a log signature
   you'll see in real tickets.

3. **Learn one SQL diagnostic query per system.** For Postgres CDC, it's the
   `pg_replication_slots` query in `cdc_notes.md`. For BigQuery, it's
   `INFORMATION_SCHEMA.JOBS_BY_PROJECT` to find recent failed loads. These are
   the queries you'll paste into Slack 50 times a week.

4. **Read the connector source on GitHub.** Airbyte connectors are open source.
   When a log message confuses you, you can search the codebase for the exact
   string and see what triggered it. This is a superpower most users don't realize
   they have.

5. **Write down what you learn.** This repo exists because I forced myself to
   document every failure. Future-me thanks past-me constantly.

## What I'd build next

- A small Python script that parses Airbyte connector logs and surfaces the
  "real" error from a stack trace — useful for first-line triage
- A MySQL → Snowflake version of this same project, to compare CDC mechanics
- A reproduction of a real Airbyte GitHub issue, with a fix — to demonstrate
  contribution-readiness

If I were joining the Airbyte team, week 1 would be exactly the workflow in this
repo, scaled across the connectors I'd be on call for.
