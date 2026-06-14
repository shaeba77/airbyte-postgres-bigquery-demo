"""
Seed the source Postgres database with realistic e-commerce data.

Usage:
    python scripts/seed_postgres.py                  # initial seed: 1k customers, 5k orders
    python scripts/seed_postgres.py --append 100     # add 100 more orders (for testing CDC)
    python scripts/seed_postgres.py --update         # randomly update 50 orders (for testing CDC UPDATE)

I built this so I could trigger every CDC scenario on demand:
- Initial snapshot (run once)
- Incremental INSERTs (--append)
- UPDATEs (--update)
- DELETEs (--delete)
"""

import argparse
import os
import random
import sys
from datetime import datetime, timedelta, timezone

try:
    import psycopg2
    from psycopg2.extras import execute_batch
except ImportError:
    sys.exit("Install psycopg2: pip install psycopg2-binary")

# ---- config ----------------------------------------------------------------

PG_CONFIG = {
    "host":     os.getenv("PG_HOST", "localhost"),
    "port":     os.getenv("PG_PORT", "5432"),
    "dbname":   os.getenv("PG_DB",   "source_db"),
    "user":     os.getenv("PG_USER", "airbyte_user"),
    "password": os.getenv("PG_PASSWORD", "airbyte_password"),
}

FIRST_NAMES = ["Aarav", "Diya", "Liam", "Sofia", "Wei", "Aisha", "Mateo", "Yuki",
               "Olivia", "Kwame", "Priya", "Noah", "Zara", "Lucas", "Mei"]
LAST_NAMES  = ["Patel", "Garcia", "Chen", "Smith", "Kim", "Okafor", "Rossi",
               "Nakamura", "Silva", "Müller", "Singh", "Hassan"]
COUNTRIES   = ["US", "IN", "GB", "DE", "BR", "JP", "NG", "FR", "CA", "AU"]
ORDER_STATUSES = ["pending", "paid", "shipped", "delivered", "cancelled"]
SKUS = [f"SKU-{i:04d}" for i in range(1, 201)]


# ---- helpers ---------------------------------------------------------------

def connect():
    """Open a connection, fail fast with a useful message."""
    try:
        return psycopg2.connect(**PG_CONFIG)
    except psycopg2.OperationalError as e:
        sys.exit(f"Cannot connect to Postgres: {e}\nConfig: {PG_CONFIG}")


def random_customer_row():
    fn = random.choice(FIRST_NAMES)
    ln = random.choice(LAST_NAMES)
    return (
        f"{fn.lower()}.{ln.lower()}.{random.randint(1, 99999)}@example.com",
        fn, ln, random.choice(COUNTRIES),
    )


def random_order_row(customer_ids):
    return (
        random.choice(customer_ids),
        random.choice(ORDER_STATUSES),
        random.randint(500, 50_000),  # cents
    )


# ---- operations ------------------------------------------------------------

def seed_initial(conn, n_customers=1000, n_orders=5000):
    """One-shot seed for first run."""
    with conn.cursor() as cur:
        # Schema
        with open(os.path.join(os.path.dirname(__file__), "..", "sql", "01_schema.sql")) as f:
            cur.execute(f.read())

        # Customers
        customers = [random_customer_row() for _ in range(n_customers)]
        execute_batch(
            cur,
            "INSERT INTO ecommerce.customers (email, first_name, last_name, country) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (email) DO NOTHING",
            customers,
            page_size=500,
        )
        cur.execute("SELECT customer_id FROM ecommerce.customers")
        customer_ids = [r[0] for r in cur.fetchall()]

        # Orders
        orders = [random_order_row(customer_ids) for _ in range(n_orders)]
        execute_batch(
            cur,
            "INSERT INTO ecommerce.orders (customer_id, status, total_cents) "
            "VALUES (%s, %s, %s)",
            orders,
            page_size=500,
        )

        # Order items (1-4 per order)
        cur.execute("SELECT order_id FROM ecommerce.orders")
        order_ids = [r[0] for r in cur.fetchall()]
        items = []
        for oid in order_ids:
            for line in range(1, random.randint(2, 5)):
                items.append((oid, line, random.choice(SKUS),
                              random.randint(1, 5), random.randint(100, 10_000)))
        execute_batch(
            cur,
            "INSERT INTO ecommerce.order_items "
            "(order_id, line_number, sku, quantity, unit_price_cents) "
            "VALUES (%s, %s, %s, %s, %s)",
            items, page_size=500,
        )

    conn.commit()
    print(f"Seeded {n_customers} customers, {n_orders} orders, {len(items)} order items.")


def append_orders(conn, n):
    with conn.cursor() as cur:
        cur.execute("SELECT customer_id FROM ecommerce.customers")
        customer_ids = [r[0] for r in cur.fetchall()]
        if not customer_ids:
            sys.exit("No customers found. Run without --append first.")
        rows = [random_order_row(customer_ids) for _ in range(n)]
        execute_batch(
            cur,
            "INSERT INTO ecommerce.orders (customer_id, status, total_cents) "
            "VALUES (%s, %s, %s)",
            rows,
        )
    conn.commit()
    print(f"Appended {n} orders. Check Airbyte CDC sync to verify replication.")


def update_random_orders(conn, n=50):
    with conn.cursor() as cur:
        cur.execute("SELECT order_id FROM ecommerce.orders ORDER BY RANDOM() LIMIT %s", (n,))
        ids = [r[0] for r in cur.fetchall()]
        for oid in ids:
            cur.execute(
                "UPDATE ecommerce.orders SET status = %s, updated_at = NOW() WHERE order_id = %s",
                (random.choice(ORDER_STATUSES), oid),
            )
    conn.commit()
    print(f"Updated {len(ids)} orders. CDC should propagate these to BigQuery within seconds.")


def delete_random_orders(conn, n=10):
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM ecommerce.order_items WHERE order_id IN "
            "(SELECT order_id FROM ecommerce.orders ORDER BY RANDOM() LIMIT %s)",
            (n,),
        )
        cur.execute(
            "DELETE FROM ecommerce.orders WHERE order_id IN "
            "(SELECT order_id FROM ecommerce.orders ORDER BY RANDOM() LIMIT %s)",
            (n,),
        )
    conn.commit()
    print(f"Deleted {n} orders. Verify they're soft-deleted (or hard-deleted) in BigQuery.")


# ---- entrypoint ------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--append", type=int, metavar="N", help="Append N new orders")
    parser.add_argument("--update", action="store_true", help="Update 50 random orders")
    parser.add_argument("--delete", type=int, metavar="N", help="Delete N random orders")
    args = parser.parse_args()

    conn = connect()
    try:
        if args.append:
            append_orders(conn, args.append)
        elif args.update:
            update_random_orders(conn)
        elif args.delete:
            delete_random_orders(conn, args.delete)
        else:
            seed_initial(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
