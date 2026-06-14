-- Queries I use to verify the source and destination are in sync.
-- These are the same kinds of checks I'd run when a customer says
-- "I'm missing rows" — start broad, then narrow.

-- ============================================================
-- 1. ROW COUNT RECONCILIATION (run on both source and destination)
-- ============================================================
-- Postgres:
SELECT 'customers'   AS table_name, COUNT(*) AS row_count FROM ecommerce.customers
UNION ALL
SELECT 'orders',       COUNT(*) FROM ecommerce.orders
UNION ALL
SELECT 'order_items',  COUNT(*) FROM ecommerce.order_items;

-- BigQuery (equivalent):
-- SELECT 'customers' AS table_name, COUNT(*) AS row_count FROM `project.dataset.customers`
-- UNION ALL ...

-- ============================================================
-- 2. CHECKSUM-STYLE VALIDATION (catches silent corruption)
-- ============================================================
-- A row count match doesn't prove the data is the same.
-- This sums a hash of every row and compares between systems.
-- Postgres:
SELECT
    SUM(('x' || SUBSTR(MD5(customer_id::text || email || COALESCE(first_name,'')), 1, 8))::bit(32)::int)
        AS checksum_customers
FROM ecommerce.customers;

-- BigQuery equivalent uses FARM_FINGERPRINT().

-- ============================================================
-- 3. SPOT-CHECK RECENT CHANGES (most common when CDC seems off)
-- ============================================================
-- Last 10 minutes of changes on source:
SELECT order_id, customer_id, status, updated_at
FROM ecommerce.orders
WHERE updated_at > NOW() - INTERVAL '10 minutes'
ORDER BY updated_at DESC
LIMIT 50;

-- ============================================================
-- 4. REPLICATION SLOT HEALTH (Postgres-side, for CDC)
-- ============================================================
SELECT
    slot_name,
    plugin,
    slot_type,
    active,
    active_pid,
    pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), confirmed_flush_lsn)) AS lag,
    pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn))         AS retained_wal
FROM pg_replication_slots
WHERE slot_name = 'airbyte_slot';

-- Interpretation:
--   active=false       -> consumer (Airbyte) is disconnected. WAL is still being retained!
--   lag growing        -> consumer is too slow OR stuck
--   retained_wal huge  -> you will run out of disk soon

-- ============================================================
-- 5. PERMISSIONS DIAGNOSTIC (the #1 root cause of failures)
-- ============================================================
-- Check the Airbyte user's attributes:
SELECT rolname, rolreplication, rolcanlogin, rolsuper
FROM pg_roles
WHERE rolname = 'airbyte_user';

-- Check publication membership:
SELECT * FROM pg_publication_tables WHERE pubname = 'airbyte_pub';

-- Check table-level grants:
SELECT grantee, table_schema, table_name, privilege_type
FROM information_schema.table_privileges
WHERE grantee = 'airbyte_user' AND table_schema = 'ecommerce';
