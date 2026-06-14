# Troubleshooting Playbook: Airbyte Postgres → BigQuery

A working support engineer's notes on real failures I reproduced. Each scenario follows
the same structure: **symptom → log signature → root cause → fix → prevention**.

This is modeled on the runbook format I use at Kyndryl for IBM Sterling File Gateway
issues, adapted for Airbyte's logging conventions.

---

## Scenario 1: "Connection check failed" when adding the Postgres source

**Symptom in UI:** *"Could not connect with provided configuration. Error: FATAL:
must be superuser or replication role to start walsender"*

**Log signature:**
```
io.airbyte.commons.exceptions.ConnectionErrorException:
  State code: 28000; Error code: 0; Message: FATAL: must be superuser
```

**Root cause:** The Postgres user lacks the `REPLICATION` attribute. CDC requires it
because Airbyte connects as a replication client, not a regular reader.

**Fix:**
```sql
ALTER USER airbyte_user REPLICATION;
```

**Prevention:** Document this in the connector's prerequisites. The UI error message
*does* say "replication role" but users often miss it because the GRANT/ALTER syntax
for replication is non-obvious.

---

## Scenario 2: First sync runs but tables are empty in BigQuery

**Symptom:** Sync shows "Succeeded" with `0 records emitted`. Source has thousands of rows.

**Log signature:**
```
INFO i.a.i.s.p.PostgresSource - Publication airbyte_pub does not include table 'orders'
```

**Root cause:** The publication was created before the table existed, and Postgres
publications don't auto-include new tables unless declared with `FOR ALL TABLES`.

**Fix:**
```sql
DROP PUBLICATION airbyte_pub;
CREATE PUBLICATION airbyte_pub FOR ALL TABLES;
-- Then refresh the schema in Airbyte and trigger a full reset + resync
```

**Prevention:** Always create the publication AFTER seeding the schema, or use
`FOR ALL TABLES`. Tell users to do a "Reset your data" before resyncing — without it,
the connector's state cursor will skip ahead.

---

## Scenario 3: Replication slot lag is growing — DBA pages support

**Symptom:** Postgres disk usage climbing. DBA reports
`pg_replication_slots.confirmed_flush_lsn` is far behind `pg_current_wal_lsn()`.

**Diagnostic query:**
```sql
SELECT
    slot_name,
    active,
    pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), confirmed_flush_lsn)) AS lag
FROM pg_replication_slots;
```

**Root cause:** Airbyte sync is paused/failing, but the slot is still reserving WAL.
Postgres will retain WAL files indefinitely waiting for the slot to advance — this
is by design and is the #1 way teams accidentally fill their Postgres disk.

**Fix (escalating):**
1. Resume the sync if it's just paused
2. If the sync is broken and you can afford to lose change data:
   ```sql
   SELECT pg_drop_replication_slot('airbyte_slot');
   ```
   Then do a full reset + resync in Airbyte (full snapshot again).
3. If you can't afford the snapshot, you need to fix the sync and let it catch up.

**Prevention:** Monitoring alert on `pg_wal_lsn_diff` > some threshold. This is
non-obvious to new users and should be in our onboarding docs.

---

## Scenario 4: BigQuery destination errors with "Quota exceeded"

**Symptom:**
```
com.google.cloud.bigquery.BigQueryException: Quota exceeded: Your project exceeded
quota for streaming inserts per project.
```

**Root cause:** Default BigQuery streaming insert quota is 1 GB/sec per project. A
large backfill of a wide table can saturate it.

**Fix:**
- Switch destination loading method from `Streaming Inserts` to `GCS Staging` —
  uploads to a Cloud Storage bucket first, then bulk-loads. Cheaper, faster, no quota.
- For ongoing CDC volume, request a quota increase from GCP if streaming is required.

**Prevention:** Default new users to GCS Staging unless they have a strict
sub-minute latency requirement. The UI should probably make this the default.

---

## Scenario 5: Schema change on source isn't reflected in destination

**Symptom:** Customer added a `phone_number` column to `customers` table. Sync still
succeeds but the column never appears in BigQuery.

**Log signature:** No error. Sync logs show only the originally-discovered columns.

**Root cause:** Airbyte caches the source schema at connection-configuration time.
Schema changes require an explicit refresh in the UI.

**Fix:** In the connection's Replication tab → **Refresh source schema** → enable the
new column → save → trigger sync. The new column will be added to the destination
table on next sync. For breaking changes (column rename, type change), you may need a
full reset.

**Prevention:** This is the #1 support ticket I'd expect. Better solution would be
auto-propagation toggles per stream. Workaround for now: a runbook entry that says
"if you changed your source schema, refresh in Airbyte before syncing."

---

## Scenario 6: Sync stuck "Running" for hours with no progress

**Symptom:** Sync has been running for 6 hours on a table that normally takes 10
minutes. Logs show no errors, no record counts updating.

**Diagnostic steps I took:**
1. Check `pg_stat_activity` for blocked queries:
   ```sql
   SELECT pid, state, wait_event_type, wait_event, query
   FROM pg_stat_activity
   WHERE state != 'idle';
   ```
2. Found Airbyte's session in `wait_event_type=Lock`, blocked by a long-running
   `VACUUM FULL` from a maintenance job.

**Root cause:** Lock contention with another database operation. Not Airbyte's fault.

**Fix:** Wait for the blocking operation, or kill it if appropriate:
```sql
SELECT pg_terminate_backend(<blocking_pid>);
```

**Prevention:** Document the diagnostic query above in the support runbook. Without
it, a user will assume Airbyte is broken when the root cause is in their own DB.

---

## Scenario 7: Records appearing in destination but with NULL values

**Symptom:** New rows are arriving in BigQuery but several columns are `NULL` despite
being populated in the source.

**Log signature:**
```
WARN i.a.i.s.p.PostgresSource - REPLICA IDENTITY for table 'orders' is set to DEFAULT,
but no primary key found. Updates and deletes may be incomplete.
```

**Root cause:** CDC sends only changed columns by default. For UPDATE events,
Postgres only includes the changed columns plus the primary key. If you don't have
a primary key OR if you set `REPLICA IDENTITY FULL` is missing, you lose old values.

**Fix:**
```sql
ALTER TABLE ecommerce.orders REPLICA IDENTITY FULL;
```
This makes Postgres log the full old row for every UPDATE. Costs more WAL volume but
makes CDC semantics correct.

**Prevention:** Airbyte's docs warn about this, but it's buried. Worth surfacing in
the Postgres source setup wizard.

---

## Scenario 8: BigQuery permissions error mid-sync

**Symptom:** Sync starts fine, transfers some data, then fails:
```
com.google.cloud.bigquery.BigQueryException: Access Denied: Table
my-project:airbyte_raw.customers: User does not have permission to update table
```

**Root cause:** Service account has `BigQuery Data Editor` on the dataset but not on
the specific table. Common when a table was created manually before Airbyte ran.

**Fix:** Grant role at dataset level, or delete the conflicting table and let
Airbyte recreate it (only if you don't need the existing data).

**Prevention:** Setup docs should explicitly say "grant at dataset level, not table
level, and let Airbyte create destination tables fresh."

---

## General diagnostic checklist

When a user opens a ticket, my standard first questions:

1. **What's the exact error message?** Not "it failed" — the actual log line.
2. **Source and destination connector versions?** Pin them; bugs are version-specific.
3. **Sync mode?** Full refresh vs incremental vs CDC have very different failure modes.
4. **Did anything change recently?** Schema, permissions, network, connector upgrade?
5. **Can you reproduce?** Or was it a one-off?
6. **What does the connector log show 50 lines before the error?** That's usually
   where the real cause is.

This pattern works for any data pipeline, including the mainframe file-transfer
incidents I handle today at Kyndryl.
