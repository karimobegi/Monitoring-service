# Uptime Monitor

A self-hosted endpoint monitoring service. It checks HTTP endpoints on a schedule, records the results,
pushes status changes to a live dashboard over WebSockets, and sends email or webhook alerts when
something goes down and again when it recovers.

Built with FastAPI, PostgreSQL, Celery and Redis, running as a Docker Compose stack.

![alt text](<Screenshot1.png>)


## What it does

- Checks endpoints at a configurable interval (10 seconds to 24 hours), recording status code,
  response time, and the failure class when there is no response at all.
- Distinguishes DNS failures, connection refusals and timeouts rather than lumping them together as
  "error".
- Alerts by email or webhook after a configurable number of consecutive failures, and sends a
  recovery notice when the endpoint comes back.
- Reports uptime percentage, response-time percentiles and a list of incidents over a 7-day window.
- Detects when the monitoring system itself has stopped checking, and marks affected endpoints as
  stale in the UI and as a Prometheus metric.

## Architecture

Seven containers:

| Service | Role |
| --- | --- |
| `api` | FastAPI app: REST API, WebSocket endpoint, static frontend, Prometheus metrics |
| `worker` | Celery worker running the HTTP checks and sending alerts |
| `beat` | Celery Beat, dispatching due checks every 10s and running daily retention |
| `db` | PostgreSQL 17 |
| `redis` | Celery broker, pub/sub for live updates, rate-limit counters |
| `migrate` | One-off Alembic `upgrade head` on startup |
| `prometheus` | Scrapes the API and worker, evaluates alert rules |
| `mailpit` | Catches outbound mail in development |

The check loop works in two stages. Beat triggers `dispatch_due_checks` every 10 seconds, which
claims all due endpoints in a single `UPDATE ... RETURNING` and advances their `next_check_at` in the
same statement. Each claimed endpoint becomes a `perform_check` task. Claiming atomically in one
statement is what stops two dispatcher runs racing to check the same endpoint.

When a check changes an endpoint's up/down state, the worker publishes to Redis. The API holds a
subscriber that forwards the message to any WebSocket connected for that user.

![alt text](<Screenshot2.png>)

## Design decisions

### Detecting that the monitor itself has stopped

The dashboard originally showed a "last checked" age that turned red past a fixed threshold. That
signal was broken by design: the worker only published on status change, so a healthy endpoint sent
nothing for hours and looked identical to a dead worker. The age could not distinguish "nothing
changed" from "nothing is running".

The obvious fix is to publish on every check so the timestamp always refreshes. That works, but it
only proves the worker is alive, and it makes the dashboard depend on the thing it is supposed to be
watching.

Instead, staleness is computed at read time in SQL. When the API serves the endpoint list, Postgres
compares each endpoint's newest check result against its own interval:

```sql
e.is_active
  AND now() > GREATEST(lr.checked_at, e.monitoring_since)
              + (e.interval_seconds + :grace) * INTERVAL '1 second'
  AS is_overdue
```

Nothing runs on a schedule, so there is no second process that can also die. It catches a dead
worker, a dead Beat, a wedged broker, or a task lost after dispatch — every way checks can stop
without anything visibly crashing.

Two details matter here. The comparison is against `checked_at` on the check result, not
`next_check_at` on the endpoint: the dispatcher advances `next_check_at` when it *claims* an
endpoint, so a claimed-then-lost task would still look healthy. And the baseline is
`GREATEST(checked_at, monitoring_since)`, where `monitoring_since` is reset when an endpoint is
created, reactivated, or has its interval changed — otherwise a newly created endpoint with no
results at all would be instantly overdue.

The grace period is 30 seconds, derived from the worst case: up to 10s waiting for Beat's next tick,
up to 10s for the HTTP timeout, plus queue and database latency.

The same query backs a Prometheus gauge, so the condition is also evaluated on Prometheus's scrape
schedule rather than only when someone has the dashboard open.

### Analytics on raw rows, not rollups

At the 10-second minimum interval, 30 endpoints produce roughly 7.7 million check results a month.
The usual answer is to roll raw rows up into hourly or daily buckets.

I scoped the history window to 7 days and measured instead. Seeding a million rows and running
`EXPLAIN ANALYZE` against both analytics queries:

- Summary (counts and percentiles): 54ms, using `ix_checkresult_latest` via a bitmap index scan to
  find 16,400 rows out of 990,000.
- Incidents (two window functions over the same set): 74ms, with the sort staying in memory at 1.2MB.

Roughly 80% of the time in both is the heap scan reading data pages, not the window functions. At
that cost, rollup tables would have been machinery with nothing to buy. A daily retention task
deletes rows older than 30 days in batches, which keeps the decision valid as the table ages.

Partitioning by month would be the next step at real scale — purging becomes dropping a partition
rather than deleting rows — but it was not worth a table rebuild here.

### Grouping incidents

An incident is a contiguous run of failed checks, which is a gaps-and-islands problem. `lag()` gives
each row the previous row's state, a running count of the rows where state *changed* assigns every
contiguous run the same id, and grouping by that id collapses each run into one incident.

The subtle part is that `status_code` is NULL for a timeout or connection refusal, and
`NULL BETWEEN 200 AND 399` evaluates to NULL rather than false. Writing the filter as `NOT is_up`
therefore silently dropped every connection failure — the majority of what a monitoring service
actually detects. The fix is to make the expression a real boolean before the window functions see
it:

```sql
(status_code IS NOT NULL AND status_code BETWEEN 200 AND 399) AS is_up
```

This is covered by a test named for the bug, because nothing about the wrong version looks wrong.

### Keying live connections by user, not endpoint

WebSocket connections were originally registered per endpoint id, looked up once when the socket
opened. That worked for a read-only dashboard and broke as soon as endpoints could be created from
the UI: a new endpoint was not in the registry, so its updates went nowhere until the user
reconnected.

The registry is now keyed by user id, and the endpoint's owner is fetched in the worker and included
in the published payload. Connecting no longer touches the database at all, and cross-user leakage is
impossible by construction rather than by remembering to filter correctly.

### Publishing after the commit

The status-change publish originally ran before `session.commit()`. If the alert-dispatch loop raised
afterwards, the transaction rolled back but the message had already gone out, and the task retry
published it a second time. Publishing after the commit means a crash between the two loses a
message, which the dashboard's 30-second poll repairs. A phantom update showing a state the database
never held has no such backstop.

### Closed registration instead of full SSRF protection

The service fetches arbitrary user-supplied URLs from inside its own network, which is a textbook
SSRF surface: cloud instance metadata at `169.254.169.254`, internal services, the API itself.

Hostnames are resolved at validation time and rejected if any resolved address is private, loopback,
link-local, reserved, multicast or unspecified. Redirects are explicitly not followed. That blocks
the direct attacks, and the same check covers webhook alert targets, which are equally capable of
reaching internal addresses.

It does not cover DNS rebinding, where a hostname resolves to a public address during validation and
a private one when the worker later performs the check. Closing that properly means resolving once
and connecting to the resolved IP rather than the hostname, which requires a custom HTTP transport.
Rather than ship a half-defence, public registration is disabled by default behind a config flag and
accounts are created with a seed script.

## Challenges

**Connection refused was reported as a DNS failure.** The original error classification inspected
only the top-level `httpx.ConnectError`, which does not distinguish causes. Walking the exception
chain for `socket.gaierror` versus `ConnectionRefusedError` separates them.

**Alerts were lost when delivery was exhausted.** If an email send failed all its retries, the alert
state still recorded `alert_sent = True`, so the endpoint never alerted again for that outage.
Resetting the flag on final failure lets the next failed check re-alert.

**The endpoint list joined nothing.** The list route returned endpoints without their latest status,
and the single-endpoint route continued to do so after the list was fixed — the fields simply fell
back to their `None` defaults, which looks like real data. Both routes now share one query, so they
cannot drift apart again.

**Migrations generated inside a container disappeared.** Running Alembic autogenerate through
`docker compose run --rm` wrote the file into a container that was then deleted. The versions
directory needs a bind mount, or the migration needs writing by hand.

**Worker metrics under prefork.** Celery's prefork pool means each child process has its own
metrics registry, so a plain Prometheus client exposes only one child's numbers. The worker uses
multiprocess mode with a shared tmpfs directory, and starts the metrics HTTP server once in the
parent via the `worker_ready` signal.

![alt text](<Screenshot3.png>)

## Running it

```bash
cp .env.example .env     # then fill in SECRET_KEY, POSTGRES_PASSWORD, DATABASE_URL
docker compose up --build -d
```

The `migrate` service applies migrations before the API starts. The dashboard is at
`http://localhost:8000/static/login.html`.

Registration is disabled by default. Create an account with the seed script, which also adds a few
endpoints to monitor:

```bash
docker compose exec api python -m scripts.seed_demo "<password>"
```

Mailpit catches all outbound alerts at `http://localhost:8025`. Prometheus is at
`http://localhost:9090`. Both, along with the worker's metrics port, are bound to loopback only.

### Tests

```bash
createdb monitor_test
pytest
```

Tests run against a local PostgreSQL rather than the container, because the dispatcher uses
Postgres-specific SQL that SQLite cannot stand in for. The schema is built by running the real
migration chain, so a broken migration fails the suite.

## What I would do next

- **Alert dispatch happens inside the transaction.** `queue_alert` sends a Celery task before the
  commit, so a rollback can still result in an email that describes a state change that never
  persisted. Same bug class as the publish ordering above, but an email cannot be un-sent.
- **`expires` on dispatched checks.** If the worker is down for an hour, the queued tasks all execute
  on restart, replaying hour-old probe times against live endpoints.
- **Per-user API rate limiting.** Currently only login and registration are rate-limited by IP.
- **Test coverage for the alert routes** and the target validator, which are currently only exercised
  by hand.
- **Response-time charts** on the endpoint detail page. The data is there; only the rendering is
  missing.
