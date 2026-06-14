# Notes on Postgres Logical Replication (and why CDC support is hard)

Personal notes from building this project. Written for myself, but useful for anyone
new to CDC.

## The mental model that finally made it click

Postgres writes every change (INSERT, UPDATE, DELETE) to the **Write-Ahead Log (WAL)**
*before* applying it to data files. The WAL is the source of truth for crash recovery —
it's an append-only stream of "here's what I'm about to do."

CDC piggybacks on this. Instead of polling tables for changes (slow, expensive, can miss
deletes), a CDC consumer subscribes to the WAL stream and gets every change in order.

Three Postgres concepts make this work:

### 1. `wal_level = logical`

By default, Postgres writes only enough WAL info to recover after a crash. Setting
`wal_level=logical` makes it write enough to *reconstruct the logical change* — e.g.,
"row X in table Y was updated, here are the new values."

This requires a server restart. Forgetting this is a common first-time failure.

### 2. Publications

A **publication** is a named set of tables you want to publish changes for:

```sql
CREATE PUBLICATION my_pub FOR ALL TABLES;
-- or
CREATE PUBLICATION my_pub FOR TABLE customers, orders;
```

This is metadata only — it tells Postgres "when these tables change, include the change
in the logical decode output."

**Gotcha:** `FOR TABLE` does NOT auto-include tables added later. `FOR ALL TABLES`
does. Most Airbyte users want `FOR ALL TABLES`.

### 3. Replication slots

A **replication slot** is Postgres's bookmark for a consumer. It tracks the last LSN
(Log Sequence Number) that the consumer confirmed receiving.

```sql
SELECT pg_create_logical_replication_slot('airbyte_slot', 'pgoutput');
```

The slot guarantees Postgres won't recycle WAL files past the slot's position — which
is great for reliability and **catastrophic if the consumer disappears**. Postgres will
fill the disk before discarding WAL data the slot still needs.

This is the single most important operational concept for CDC support. When a user
opens a ticket about Postgres disk filling up, the answer is almost always:
- a stuck replication slot, OR
- a slot for a deleted consumer that never got cleaned up

Diagnostic:
```sql
SELECT
    slot_name,
    active,
    pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), confirmed_flush_lsn)) AS lag
FROM pg_replication_slots;
```

## Why CDC support is hard

A support engineer needs to know:

1. **The source's replication model** — Postgres uses logical replication; MySQL uses
   binlog; SQL Server uses CDC tables or Change Tracking; Oracle has LogMiner. Each has
   different setup, failure modes, and permissions.

2. **The consumer's state machine** — Airbyte tracks per-table cursors plus the global
   LSN. If state gets out of sync (e.g., user resets one stream but not others),
   weird things happen.

3. **The destination's idempotency model** — does the destination support upserts?
   Append-only? Merge-on-key? Each affects what "incremental" actually means.

4. **The data semantics** — `REPLICA IDENTITY DEFAULT` vs `FULL`, primary keys, NULLs
   in keys, schema evolution. Each is a footgun.

## Open questions I still have

- How does Airbyte handle DDL events (e.g., `ALTER TABLE`)? My understanding is they're
  ignored and require manual schema refresh, but I want to verify.
- What's the right monitoring stack for production Airbyte? Built-in alerts seem
  limited; users probably layer Datadog/Grafana on top.
- For destinations like BigQuery that don't natively upsert, how does Airbyte avoid
  duplicates? (I think it's the `airbyte_raw` + dbt-style normalization pattern, but
  I want to read the source.)

These are the kinds of questions I'd want to answer in my first week on the team.

## References I found useful

- Postgres docs: [Logical Replication](https://www.postgresql.org/docs/current/logical-replication.html)
- Debezium architecture docs (similar concepts, very well written)
- Airbyte's own [Postgres source docs](https://docs.airbyte.com/integrations/sources/postgres)
- The Confluent CDC blog series
