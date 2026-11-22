# queue-saturation-observability

[![ci](https://github.com/Walaskien/queue-saturation-observability/actions/workflows/ci.yml/badge.svg)](https://github.com/Walaskien/queue-saturation-observability/actions/workflows/ci.yml)

Monitoring for the case where a message queue falls behind while the servers look healthy. Consumers can be stuck on a database lock, a slow downstream call or a crashed worker, and CPU and RAM stay green. This repo measures the queue itself and tells a processing bottleneck apart from a lack of host resources.

What is in it:

- a small Prometheus exporter in Python (standard library only) with adapters for RabbitMQ (management API), Redis lists and a spool directory of files, plus a simulated queue for the demo
- Prometheus recording and alerting rules with `promtool` unit tests
- an Alertmanager config with an empty receiver, a Grafana dashboard provisioned from JSON, a [runbook](docs/runbook.md) and a note on [queue bottleneck vs host saturation](docs/bottleneck-vs-host.md)
- a Docker Compose stack (Prometheus, Alertmanager, Grafana, node-exporter, exporter) to try it

It is a reference setup, not something used by customers. Check thresholds and credentials before pointing it at your own systems.

## Metrics

`queue_backlog_messages`, `queue_oldest_message_age_seconds`, `queue_enqueued_total`, `queue_processed_total`, `queue_stalled_seconds`, `queue_consumers` and `queue_source_up`. A metric is left out when the backend cannot provide it: the file adapter gives backlog and age (from file mtime), RabbitMQ gives backlog, counters, stalled time and consumers but no age, Redis lists give backlog only. The simulator gives everything.

## Alerts

Defined in `prometheus/rules/alerts.yml`:

- `QueueBacklogGrowingHostHealthy`: backlog grows while CPU is under 80% and memory under 90%. Look at consumers, locks, downstream.
- `QueueBacklogGrowingHostBusy`: backlog grows and the host is saturated. Look at the host.
- `QueueBacklogGrowingHostUnknown`: backlog grows and there are no node series at all, so the two above cannot fire.
- `QueueOldestMessageTooOld`, `QueueProcessingStalled`, `QueueConsumersDown`, `QueueExporterDown`.

## Use it on your own queue

Run the exporter next to the broker (Python 3.9+, no dependencies):

```console
# RabbitMQ (rabbitmq_management plugin, user with the "monitoring" tag)
RABBITMQ_USER=monitor RABBITMQ_PASSWORD=... \
  python3 exporter/queue_exporter.py --source rabbitmq --queue docs.in \
  --rabbitmq-url http://rabbit.example.internal:15672 --rabbitmq-vhost /

# Redis list
REDIS_PASSWORD=... python3 exporter/queue_exporter.py --source redis --queue docs:pending --redis-host 10.0.0.5

# Directory of files waiting to be imported
python3 exporter/queue_exporter.py --source file --queue /var/spool/docs --file-suffix .xml
```

Then add a scrape job for `:9101`, copy `prometheus/rules/*.yml`, import `grafana/dashboards/queue-saturation.json` and set the thresholds in `alerts.yml` to your real latency target. The host part of the alerts needs `node_exporter` on the consumer hosts.

## Demo stack

Needs Docker with Compose.

```console
make up            # build and start everything with the simulated queue
make demo-flood    # producers 6x faster than consumers
make demo-stall    # consumers stop
make demo-recover  # more consumers
make alerts        # currently firing alerts
make down
```

Grafana is on http://localhost:3000 (anonymous viewer, admin/admin is a demo password), Prometheus on :9090, Alertmanager on :9093.

## Checked

Run locally on macOS (Colima, Docker 29), Python 3.9.6:

- `pytest -q`: 13 passed. `ruff check .`: clean.
- `promtool check config` and `check rules`: success, 13 rules (6 recording, 7 alerts). `promtool test rules prometheus/tests.yml`: success.
- `amtool check-config`: valid, 1 receiver. `docker-compose config`: valid (compose v1.29 in a venv; CI uses `docker compose`).
- Demo stack end to end: after `flood` (45 msg/s in, 7.5 out) `QueueBacklogGrowingHostHealthy` fired with host CPU around 6%. After `stall` Alertmanager held `QueueOldestMessageTooOld`, `QueueConsumersDown`, `QueueProcessingStalled` and the backlog alert. Stopping the exporter container fired `QueueExporterDown`. Grafana provisioned the dashboard.
- RabbitMQ adapter against a real `rabbitmq:3.13-management` container: backlog 5, consumers 0, enqueued 5 for 5 published messages.
- Redis adapter against a real `redis:7` container: backlog 7 after 7 `RPUSH`, 6 after one `LPOP`.
- File adapter on a real directory: 3 `.xml` files counted, age taken from the oldest mtime.

CI (see the badge) runs `ruff` and `pytest` on Python 3.9 and 3.12, the `promtool` and `amtool` checks, `docker compose config`, and builds the exporter image and scrapes `/metrics` from it.

Not checked: the Redis `AUTH` path against a real server.

## Limits

- Thresholds are starting points. `for:` durations are short so the demo reacts in seconds; raise them for noisy real queues.
- RabbitMQ: one queue per exporter, and no age of the oldest message (the API does not give it), so use `QueueProcessingStalled`.
- Redis lists: backlog only, no processing rate or age.
- The simulator's `/control` endpoint is unauthenticated and exists only with `--source sim`.
- Host thresholds use the busiest host in Prometheus (`max`). Filter by `instance` if consumers live on one host.
- With no node_exporter data the two host alerts stay silent by design. `QueueBacklogGrowingHostUnknown` covers that, but only while the queue exporter itself is up.

## Not done

- Alertmanager receivers (email or chat) with a real routing example.
- Per-queue labels so one exporter can watch several queues.
- A CI check that loads the dashboard JSON into Grafana and confirms the panels get data.
- Redis AUTH test against a real server.

Related: [ansible-linux-baseline](https://github.com/Walaskien/ansible-linux-baseline) installs node_exporter on the consumer hosts.
