-- Sample e-commerce schema for the source Postgres database.
-- Designed to exercise CDC: includes primary keys, foreign keys, and a table
-- where REPLICA IDENTITY FULL is needed for correct UPDATE semantics.

CREATE SCHEMA IF NOT EXISTS ecommerce;

-- Customers: simple table with a surrogate PK
CREATE TABLE ecommerce.customers (
    customer_id     BIGSERIAL PRIMARY KEY,
    email           VARCHAR(255) NOT NULL UNIQUE,
    first_name      VARCHAR(100),
    last_name       VARCHAR(100),
    country         VARCHAR(2),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Orders: has FK + a status column we'll UPDATE frequently to test CDC
CREATE TABLE ecommerce.orders (
    order_id        BIGSERIAL PRIMARY KEY,
    customer_id     BIGINT NOT NULL REFERENCES ecommerce.customers(customer_id),
    status          VARCHAR(20) NOT NULL DEFAULT 'pending',
    total_cents     INTEGER NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Order items: composite-ish key, no surrogate. Tests CDC with multi-column identity.
CREATE TABLE ecommerce.order_items (
    order_id        BIGINT NOT NULL REFERENCES ecommerce.orders(order_id),
    line_number     INTEGER NOT NULL,
    sku             VARCHAR(50) NOT NULL,
    quantity        INTEGER NOT NULL,
    unit_price_cents INTEGER NOT NULL,
    PRIMARY KEY (order_id, line_number)
);

-- Index used by reconciliation queries
CREATE INDEX idx_orders_customer ON ecommerce.orders(customer_id);
CREATE INDEX idx_orders_status   ON ecommerce.orders(status);

-- Required for CDC UPDATE/DELETE to send full old row
ALTER TABLE ecommerce.orders REPLICA IDENTITY FULL;
