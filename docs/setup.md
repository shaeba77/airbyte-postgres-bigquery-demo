# Local Setup Guide

## Prerequisites

- Docker Desktop (4.x or later), 4 GB RAM allocated minimum
- Python 3.10+
- A Google Cloud account with billing enabled (BigQuery has a free tier — this should cost $0)
- ~10 GB free disk

## Step 1: Start the source database

Spin up Postgres with replication enabled (required for CDC):

```bash
docker compose up -d postgres
```

The `docker-compose.yml` in this repo sets these critical Postgres parameters:

```yaml
command:
  - "postgres"
  - "-c"
  - "wal_level=logical"          # Required for logical replication
  - "-c"
  - "max_wal_senders=10"
  - "-c"
  - "max_replication_slots=10"
```

**Why this matters:** without `wal_level=logical`, Airbyte's CDC mode will fail at the
"creating replication slot" step. This was my first self-inflicted failure — see
`troubleshooting_playbook.md` scenario 1.

## Step 2: Seed the source

```bash
python scripts/seed_postgres.py
```

This creates an `ecommerce` schema with three tables (`customers`, `orders`,
`order_items`) and ~10,000 rows of realistic-looking sample data. Run it again
later to insert/update rows for testing incremental syncs.

Verify with:
```bash
psql -h localhost -U airbyte_user -d source_db -c "SELECT count(*) FROM ecommerce.orders;"
```

## Step 3: Start Airbyte

Airbyte OSS via abctl (their official launcher):

```bash
# Install abctl
curl -LsfS https://get.airbyte.com | bash -

# Launch
abctl local install
```

Open http://localhost:8000. Default credentials are printed in the terminal.

## Step 4: Configure the Postgres source

In the Airbyte UI:

1. **Sources** → **+ New source** → **Postgres**
2. Host: `host.docker.internal` (so Airbyte's containers can reach your Postgres)
3. Port: `5432`, DB: `source_db`, User: `airbyte_user`
4. **Replication method:** `Read Changes using Write-Ahead Log (CDC)`
5. Replication slot: `airbyte_slot`
6. Publication: `airbyte_pub`

Before saving, run this in Postgres (the Airbyte UI tests connection but doesn't create these):

```sql
CREATE PUBLICATION airbyte_pub FOR ALL TABLES;
SELECT pg_create_logical_replication_slot('airbyte_slot', 'pgoutput');
ALTER USER airbyte_user REPLICATION;
```

## Step 5: Configure the BigQuery destination

1. Create a GCP project, enable BigQuery API
2. Create a service account with `BigQuery Data Editor` + `BigQuery User` roles
3. Download the JSON key
4. In Airbyte: **Destinations** → **+ New** → **BigQuery**
5. Paste the service account JSON, set dataset location to `US`

## Step 6: Create the connection

1. **Connections** → **+ New connection**
2. Source = your Postgres, Destination = your BigQuery
3. Sync frequency: **Manual** (for testing — avoids burning warehouse quota)
4. Select streams: all three tables
5. Sync mode: **Incremental | Append + Deduped** (this is what real users want)

## Step 7: Trigger and verify

Click **Sync now**. First sync does a full snapshot, then switches to CDC.

Verify row counts match:
```bash
python scripts/reconcile_counts.py
```

Expected output:
```
customers     source=1000     destination=1000     ✓
orders        source=5000     destination=5000     ✓
order_items   source=12473    destination=12473    ✓
```

## What to try next

To actually learn from this, intentionally break things and watch the logs:

- Drop a column on the source and re-sync
- Insert 1M rows and watch the replication slot lag
- Stop the BigQuery destination mid-sync
- Revoke `SELECT` on one table and re-sync

Each of these is covered in `troubleshooting_playbook.md`.
