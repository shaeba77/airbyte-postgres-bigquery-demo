"""
Reconcile row counts between the Postgres source and BigQuery destination.

This is the script I'd reach for whenever a customer says "I think I'm missing rows."
It produces a clear pass/fail report instead of forcing the user to eyeball two
result sets.

Usage:
    python scripts/reconcile_counts.py

Environment variables:
    PG_HOST, PG_DB, PG_USER, PG_PASSWORD       (source)
    GCP_PROJECT, BQ_DATASET                     (destination)
    GOOGLE_APPLICATION_CREDENTIALS              (path to service-account JSON)
"""

import os
import sys
from typing import Dict

try:
    import psycopg2
except ImportError:
    sys.exit("Install psycopg2: pip install psycopg2-binary")

try:
    from google.cloud import bigquery
except ImportError:
    sys.exit("Install BigQuery client: pip install google-cloud-bigquery")


TABLES = ["customers", "orders", "order_items"]


def get_source_counts() -> Dict[str, int]:
    conn = psycopg2.connect(
        host=os.getenv("PG_HOST", "localhost"),
        port=os.getenv("PG_PORT", "5432"),
        dbname=os.getenv("PG_DB", "source_db"),
        user=os.getenv("PG_USER", "airbyte_user"),
        password=os.getenv("PG_PASSWORD", "airbyte_password"),
    )
    counts = {}
    with conn.cursor() as cur:
        for t in TABLES:
            cur.execute(f"SELECT COUNT(*) FROM ecommerce.{t}")
            counts[t] = cur.fetchone()[0]
    conn.close()
    return counts


def get_destination_counts() -> Dict[str, int]:
    project = os.getenv("GCP_PROJECT")
    dataset = os.getenv("BQ_DATASET", "airbyte_ecommerce")
    if not project:
        sys.exit("Set GCP_PROJECT environment variable.")

    client = bigquery.Client(project=project)
    counts = {}
    for t in TABLES:
        query = f"SELECT COUNT(*) AS c FROM `{project}.{dataset}.{t}`"
        try:
            result = list(client.query(query).result())
            counts[t] = result[0]["c"]
        except Exception as e:
            print(f"  ! Failed to query {t}: {e}", file=sys.stderr)
            counts[t] = None
    return counts


def render_report(source: Dict[str, int], dest: Dict[str, int]) -> bool:
    print()
    print(f"  {'TABLE':<15} {'SOURCE':>10} {'DEST':>10}   STATUS")
    print(f"  {'-'*15} {'-'*10} {'-'*10}   {'-'*10}")
    all_ok = True
    for t in TABLES:
        s, d = source.get(t), dest.get(t)
        if d is None:
            status = "ERROR"
            all_ok = False
        elif s == d:
            status = "OK"
        else:
            diff = abs(s - d)
            status = f"DRIFT (Δ={diff})"
            all_ok = False
        print(f"  {t:<15} {s:>10} {str(d):>10}   {status}")
    print()
    return all_ok


def main():
    print("Fetching source counts (Postgres)...")
    source = get_source_counts()
    print("Fetching destination counts (BigQuery)...")
    dest = get_destination_counts()

    ok = render_report(source, dest)

    if ok:
        print("All tables in sync.")
        sys.exit(0)
    else:
        print("Drift detected. Investigate using docs/troubleshooting_playbook.md.")
        print("First diagnostic to run:")
        print("    SELECT * FROM pg_replication_slots WHERE slot_name = 'airbyte_slot';")
        sys.exit(1)


if __name__ == "__main__":
    main()
