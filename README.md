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

## Scheduling and dispatch

Celery Beat reads its schedule once at startup, so it cannot pick up endpoints a user adds later.
Beat therefore holds a single static entry that fires a dispatcher every 10 seconds; the dispatcher
queries Postgres for endpoints that are due and fans out one task per endpoint.

Claiming is a single atomic statement:

```sql
UPDATE endpoint
SET next_check_at = now() + (interval_seconds * INTERVAL '1 second')
WHERE is_active AND next_check_at <= now()
RETURNING id, url
```

Beat has no leader election, so two Beat processes would dispatch the same endpoints twice. Rather
than trying to guarantee exactly one Beat, the claim is made idempotent: whichever dispatcher run
gets there first moves `next_check_at` forward, and the second finds nothing due.

The schedule advances from `now()`, not from the previous `next_check_at`. Advancing from the old
value would make a worker outage produce a catch-up burst of checks timestamped as though they had
run on time. Advancing from `now()` leaves an honest gap instead.

Health checks get no retries. A failed HTTP request *is* the measurement — retrying until it succeeds
would mean the recorded history no longer describes what the endpoint actually did. Retries are
reserved for genuine infrastructure failure, so `perform_check` retries only on `OperationalError`
from the database. The probe timestamp is captured at dispatch and passed through, so a retry writes
the row it was originally scheduled for rather than one timestamped at retry time.

`worker_prefetch_multiplier = 1`, because checks are long I/O-bound tasks. With the default prefetch,
a worker pulls a batch into memory where other workers cannot see it — during testing, 20 tasks left
the queue instantly while 12 sat stranded inside one process.

## Design decisions

### Delivery guarantees differ by task type

Dashboard updates go over Redis pub/sub. Alerts go through Celery with `acks_late=True`. The
difference is what failure costs.

A dropped dashboard update self-corrects: the next check publishes again, and the 30-second poll
repairs anything missed in between. Pub/sub has no persistence and no delivery guarantee, and that is
acceptable here.

A missed alert does not self-correct — nobody finds out the endpoint went down. `acks_late` moves the
acknowledgement from task receipt to task completion, so a worker killed mid-send has its task
redelivered. The cost is moving from at-most-once to at-least-once: a crash after the email sends but
before the ack produces a duplicate. A duplicate alert is better than a silent one.

That same setting is deliberately absent from `perform_check`. There, redelivery would write a second
result row for the same scheduled time and corrupt the history. Late ack is right for delivery, wrong
for measurement.

Retry policies are similarly specific rather than uniform: connection-level errors only on email
(`SMTPServerDisconnected`, `SMTPConnectError`, `OSError`), and 5xx or 429 only on webhooks, because a
404 means the URL is wrong and retrying changes nothing.

### Alert configuration and alert state are separate tables

`AlertConfig` is user-edited and stable. `AlertState` is machine-written on every check. Merging them
would mean the worker writing to rows the user edits, and streak counters leaking into the settings
API.

State could not be derived from the check history instead. A query can compute the current failure
streak, but it cannot record whether a notification has already been sent — and that flag is the only
thing preventing an email every 10 seconds for the length of an outage.

State is per-config, not per-endpoint: two alert configs on one endpoint with thresholds of 3 and 10
have to fire and recover independently. A unique constraint on `alertstate.config_id` enforces it.

Recovery notifications fire on `alert_sent`, not on the endpoint's previous status. A sub-threshold
blip — down for one check, back on the next — must not produce a "recovered" message for an outage
nobody was told about.

Repointing a config at a different endpoint is not allowed; `endpoint_id` is excluded from the update
model. Carrying live streak state across could make a healthy endpoint immediately fire a spurious
recovery. Moving means delete and recreate.

![alt text](<Screenshot2.png>)

### Detecting that the monitor itself has stopped

A dead worker is visible: the queue backs up. A dead Beat is silent — nothing is published, and
nothing backfills when it restarts.

The dashboard originally showed a "last checked" age that turned red past a fixed threshold, but that
signal was broken by design. The worker only published on status change, so a healthy endpoint sent
nothing for hours and looked identical to a dead one. The age could not distinguish "nothing changed"
from "nothing is running".

Publishing on every check would fix the timestamp, but it only proves the worker is alive, and it
makes the dashboard depend on the thing it is supposed to be watching. Staleness is instead computed
at read time in SQL, when the API serves the endpoint list:

```sql
e.is_active
  AND now() > GREATEST(lr.checked_at, e.monitoring_since)
              + (e.interval_seconds + :grace) * INTERVAL '1 second'
  AS is_overdue
```

Nothing runs on a schedule, so there is no second process that can also die. It catches a dead
worker, a dead Beat, a wedged broker, or a task lost after dispatch.

Two details matter. The comparison uses `checked_at` on the check result, not `next_check_at` on the
endpoint — the dispatcher advances `next_check_at` when it *claims* an endpoint, so a claimed-then-
lost task would still look healthy. And the baseline is `GREATEST(checked_at, monitoring_since)`,
where `monitoring_since` resets when an endpoint is created, reactivated, or has its interval
changed; otherwise a new endpoint with no results at all would be instantly overdue.

The 30-second grace comes from the worst case: up to 10s for Beat's next tick, up to 10s for the HTTP
timeout, plus queue and database latency.

Because this only runs when someone is looking, the same query also backs a Prometheus gauge, so the
condition is evaluated on Prometheus's scrape schedule whether or not a dashboard is open.

![alt text](<Screenshot3.png>)

### Analytics on raw rows, not rollups

At the 10-second minimum, 30 endpoints produce roughly 7.7 million check results a month. The usual
answer is to roll raw rows up into hourly or daily buckets.

I scoped the window to 7 days and measured instead. Seeding a million rows and running
`EXPLAIN ANALYZE`:

- Summary (counts and percentiles): 54ms, using `ix_checkresult_latest` via a bitmap index scan to
  find 16,400 rows out of 990,000.
- Incidents (two window functions over the same set): 74ms, with the sort staying in memory at 1.2MB.

Roughly 80% of the time in both is the heap scan reading data pages, not the window functions. At
that cost, rollup tables would have been machinery with nothing to buy. A daily retention task
deletes rows older than 30 days in batches, which keeps the decision valid as the table ages.

Partitioning by month is the next step at real scale — purging becomes dropping a partition rather
than deleting rows — but it was not worth a table rebuild here.

The same measurement replaced a `DISTINCT ON` subquery in the endpoint list with a
`LEFT JOIN LATERAL`. The original computed the latest result for every endpoint in the table before
filtering to the requesting user, so its cost grew with total rows across all users rather than with
the user's own.

### Grouping incidents

An incident is a contiguous run of failed checks — a gaps-and-islands problem. `lag()` gives each row
the previous row's state, a running count of rows where the state *changed* assigns every contiguous
run the same id, and grouping by that id collapses each run into one incident.

The subtle part is that `status_code` is NULL for a timeout or connection refusal, and
`NULL BETWEEN 200 AND 399` evaluates to NULL rather than false. Writing the filter as `NOT is_up`
therefore silently dropped every connection failure — the majority of what a monitoring service
actually detects. The expression has to be made a real boolean before the window functions see it:

```sql
(status_code IS NOT NULL AND status_code BETWEEN 200 AND 399) AS is_up
```

There is a test named for this bug, because nothing about the wrong version looks wrong.

### WebSocket authentication

The WebSocket handshake is an HTTP request and could carry an `Authorization` header — but the
browser API, `new WebSocket(url)`, accepts only a URL and an optional subprotocol. A Python client
can set headers freely; a browser cannot. So the token travels in the query string.

The cost is that tokens appear in access logs and browser history, mitigated by short expiry. The
production upgrade is to accept the connection unauthenticated and require a token as the first
message, closing the socket if it does not arrive.

### Keying live connections by user, not endpoint

Connections were originally registered per endpoint id, looked up once when the socket opened. That
worked for a read-only dashboard and broke as soon as endpoints could be created from the UI: a new
endpoint was not in the registry, so its updates went nowhere until the user reconnected.

The registry is now keyed by user id, with the endpoint's owner fetched in the worker and included in
the published payload. Connecting no longer touches the database, and cross-user leakage is
impossible by construction rather than by remembering to filter correctly.

### Publishing after the commit

The status-change publish originally ran before `session.commit()`. If the alert-dispatch loop raised
afterwards, the transaction rolled back but the message had already gone out, and the retry published
it a second time.

Publishing after the commit means a crash between the two loses a message, which the 30-second poll
repairs. A phantom update showing a state the database never held has no such backstop.

Related: first checks originally did not publish at all, on the reasoning that the initial HTTP
snapshot covered them. That held for a read-only dashboard and broke once endpoints could be created
with the dashboard open — the new row sat blank until a refresh. First checks now publish, and the
payload carries an `is_up` flag so the frontend can distinguish a genuine transition from a first
sighting.

### Closed registration instead of full SSRF protection

The service fetches arbitrary user-supplied URLs from inside its own network: cloud instance metadata
at `169.254.169.254`, internal services, the API itself.

Hostnames are resolved at validation time and rejected if any resolved address is private, loopback,
link-local, reserved, multicast or unspecified. Redirects are explicitly not followed. The same check
covers webhook alert targets, which can reach internal addresses just as easily.

It does not cover DNS rebinding, where a hostname resolves to a public address during validation and
a private one when the check later runs. Closing that means resolving once and connecting to the
resolved IP rather than the hostname, which requires a custom HTTP transport. Rather than ship a
half-defence, public registration is disabled by default behind a config flag and accounts are
created with a seed script.

Smaller decisions in the same area: cross-user access returns 404 rather than 403, so the API does
not confirm that a resource exists; and `response_model` on every route is a structural guarantee
against leaking fields like `hashed_password`.

## Challenges

**A query that returned every row in the table.** An alert lookup was written as
`.where(endpoint_id == endpoint_id)` — comparing a local variable to itself, which evaluates to
Python `True` rather than producing SQL. The WHERE clause vanished and the query returned every alert
config for every user. Model attributes have to be on the left: `AlertConfig.endpoint_id ==
endpoint_id`. A cross-user data leak caused by a variable name shadowing a column name, with no error
raised anywhere.

**"No error" is not the same as "healthy".** A `CheckResult` with `error is None` means an HTTP
response arrived — including a 503. Treating absent error as success reported failing endpoints as
up. Health is `status_code is not None and 200 <= status_code < 400`, and that definition now lives in
one function used everywhere.

**Connection refused reported as DNS failure.** The original classification inspected only the
top-level `httpx.ConnectError`, which does not distinguish causes. Walking the `__cause__` chain for
`socket.gaierror` versus `ConnectionRefusedError` separates them.

**Alerts lost when delivery was exhausted.** If an email send failed all its retries, `alert_sent`
stayed `True`, so the endpoint never alerted again for that outage. Resetting the flag on final
failure lets the next failed check re-alert.

**A foreign key that was silently None.** Creating an `AlertState` referencing a just-created
`AlertConfig` gave a null `config_id`, because the primary key does not exist until the INSERT is
sent. `session.flush()` sends it without committing, so both rows still land in one transaction.

**Alembic autogenerate produced empty migrations.** `env.py` imported models by name, so new models
were invisible to the metadata comparison. Importing the module as a whole fixes it. Separately,
`op.drop_table` does not drop a Postgres ENUM type, so a downgrade then upgrade fails with "type
already exists" until the cleanup is added by hand.

**A type-checker suppression that hid two real bugs.** SQLModel produces Pylance false positives —
`.delay` on a Celery-decorated task, `Column.desc()` on a model attribute. A blanket `# type: ignore`
to quiet them also concealed a genuine `NameError` and a genuinely-`None` primary key.

**Worker metrics under prefork.** Celery's prefork pool gives each child process its own metrics
registry, so a plain Prometheus client exposes one child's numbers. The worker uses multiprocess mode
with a shared tmpfs directory and starts the metrics server once in the parent via `worker_ready`.

**An orphaned Beat process.** Task behaviour stopped making sense for a while; the cause was a Beat
process left running from an earlier session under a different module path, dispatching alongside the
current one. `ps aux | grep celery` before starting work became a habit.

**Migrations generated inside a container vanished.** Running Alembic autogenerate through
`docker compose run --rm` wrote the file into a container that was then deleted. The versions
directory needs a bind mount, or the migration needs writing by hand.

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
  commit, so a rollback can still produce an email describing a state change that never persisted.
  Same bug class as the publish ordering above, but an email cannot be un-sent.
- **`expires` on dispatched checks.** If the worker is down for an hour, the queued tasks all run on
  restart, replaying hour-old probe times against live endpoints. The intended fix is an expiry
  shorter than the check interval, so stale messages are discarded on receipt.
- **A dead man's switch.** The staleness check and a container restart policy cover a crashed Beat,
  but the production answer is an external service that alerts when this one stops checking in.
- **Per-user API rate limiting.** Only login and registration are currently rate-limited, by IP.
- **Test coverage for the alert routes** and the target validator, currently exercised only by hand.
- **Response-time charts** on the endpoint detail page. The data is there; only the rendering is
  missing.
