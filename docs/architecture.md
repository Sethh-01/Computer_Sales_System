# System architecture

## Current MVP

```text
Browser (responsive Khmer UI)
       │ same-origin HTTP, HTTP-only session cookie
       ▼
Python standard-library API (modular monolith)
  ├── Authentication and request validation
  ├── Administrator-managed staff accounts and role checks
  ├── Product and inventory operations
  ├── Checkout and order history
  └── Dashboard aggregates
       │ parameterized SQL / transaction
       ▼
SQLite database (persistent local file)
```

The frontend is served by the API process, so the MVP has no cross-origin API
surface. Order creation uses a write transaction: it checks each requested
quantity, records the sale price, and deducts stock as one operation. Products
referenced by sales are archived rather than physically deleted.

## Boundaries and next scale steps

- Keep the initial deployment as a modular monolith; extract services only
  when operational scale or independent ownership justifies the extra
  complexity.
- Replace SQLite with PostgreSQL for concurrent multi-store deployments.
- Put the application behind a TLS-terminating reverse proxy/WAF and a
  rate-limiting layer before exposing it beyond a trusted local network.
- Replace the local administrator/staff accounts with a managed identity
  provider and durable, revocable sessions before multi-instance operation.
  The local MVP session store is intentionally process-local.
- The Render Blueprint uses a single paid instance with a persistent SQLite
  disk. It is not horizontally scalable; move to managed PostgreSQL and
  shared session storage before adding instances.
- The current login throttle is process-local and source-IP based. Use an
  edge WAF or shared rate-limit service for robust public-internet protection.
- Add Redis only when measured workloads need shared caching or session state.
- For cloud operation, build an immutable container, deploy behind a load
  balancer, store secrets in the cloud secret manager, and back up the
  database. Use an orchestrator only when deployment needs warrant it.
- Add structured centralized logs, metrics, alerting, and dashboards before
  production traffic. The current health endpoint is a liveness check, not a
  monitoring stack.

## Delivery and verification

GitHub Actions runs the standard-library API tests on pushes and pull requests.
The tests cover authentication, product validation, and atomic checkout with
insufficient stock. Add browser-level and load tests before a production
rollout.
