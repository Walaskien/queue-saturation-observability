# Runbook

Every alert links here. Format: symptom, what to check, what to do.
Queries run in Prometheus (`:9090`) or the Grafana dashboard "Queue saturation vs host resources".

First question for any backlog alert: **is the host busy?**
See [bottleneck-vs-host.md](bottleneck-vs-host.md).

## QueueBacklogGrowingHostHealthy

**Symptom:** backlog grows (> 1 msg/s, > 100 messages) while CPU < 80% and memory < 90%.

**Check**
1. `queue:saturation_ratio:rate1m` > 1: producers outpace consumers. If it is about 1 but the backlog still grows, look at step 3.
2. `queue_consumers`: did the number of consumers drop?
3. Consumer logs: errors, retries, timeouts to the database or to a downstream service, lock waits.
4. Is the consumer count capped by a setting (thread pool, prefetch, `max_connections`) while the host is idle?

**Do:** fix the blocked dependency first, then raise consumer concurrency. Adding hosts or CPU will not help: the host is not the limit.

## QueueBacklogGrowingHostBusy

**Symptom:** same growth, but CPU >= 80% or memory >= 90%.

**Check:** `instance:node_cpu_busy:ratio1m`, `instance:node_memory_used:ratio`; `top`/`vmstat 1` on the host (is it `us`, `sy`, `wa` (disk) or swap?); which process uses it (consumers, or something else on the same host).

**Do:** remove or move the unrelated load, or scale the consumers out. If the consumers themselves are the load, the queue is under-provisioned.

## QueueOldestMessageTooOld

**Symptom:** the oldest waiting message is older than 60 s (threshold in `prometheus/rules/alerts.yml`; set it to your real latency target).

**Check:** is the backlog large (slow drain) or small (consumers not taking messages: one poisoned message at the head, consumers stuck)? Compare `queue_backlog_messages` and `queue_processed_total` rate.

**Do:** large backlog: see the two alerts above. Small backlog and no progress: restart or unblock the consumers, move the poisoned message to a dead-letter queue.

## QueueProcessingStalled

**Symptom:** backlog is not empty and `queue_processed_total` has not changed for more than 2 minutes. This is the main stall signal for backends without message age (RabbitMQ API).

**Check:** consumers connected? (`queue_consumers`), unacked messages stuck (RabbitMQ: `messages_unacknowledged`), downstream service down.

**Do:** restart stuck consumers; fix the downstream; verify `queue_processed_total` moves again.

## QueueConsumersDown

**Symptom:** `queue_consumers == 0` with messages waiting (sources that report consumers).

**Check:** consumer service status and logs; broker connection credentials; network between consumers and broker.

**Do:** restart the service, then watch `queue:backlog_growth:deriv1m` turn negative.

## QueueExporterDown

**Symptom:** the exporter is not scraped, or it cannot reach the queue backend (`queue_source_up == 0`).

**Check:** exporter process/container; the credentials and URL passed to it; the backend itself. Other queue alerts are blind until this is fixed.
