# Processing bottleneck or not enough host resources?

A growing queue has two very different causes, and the fix for one makes no difference to the other.

| | Processing bottleneck | Host resource shortage |
|---|---|---|
| Backlog | grows | grows |
| Host CPU / RAM | normal, often idle | high, or swapping |
| Disk wait (`iowait`) | low | may be high |
| Consumers | idle, blocked, or too few | busy, starved of CPU |
| Typical causes | lock or DB wait, slow downstream call, consumer cap, poisoned message, crashed consumer | CPU-bound work, memory leak, noisy neighbour, slow disk |
| Fix | unblock the dependency, raise concurrency | free or add resources |

## The decision in three steps

1. **Is it falling behind?** `queue:saturation_ratio:rate1m` > 1 (enqueue rate / processed rate) or `queue:backlog_growth:deriv1m` > 0.
2. **Is the host the limit?** `instance:node_cpu_busy:ratio1m`, `instance:node_memory_used:ratio`. Check disk wait with `node_cpu_seconds_total{mode="iowait"}` if CPU is low but the consumers are slow.
3. **Pick the matching alert.** `QueueBacklogGrowingHostHealthy` and `QueueBacklogGrowingHostBusy` are the same condition split by the host check, so the page already says which branch you are on.

## Why a plain "CPU high" alert is not enough

A consumer that waits on a database lock uses almost no CPU. The queue fills, users see delayed documents, and every host dashboard is green. The saturation metrics (backlog growth, oldest message age, seconds without progress) measure the queue itself, so they fire in this case.

## Limits of this approach

- The 80% / 90% host thresholds are defaults. Tune them to your hosts.
- With several hosts, the alert uses the busiest one (`max(...)`). If your consumers run on one specific host, filter by `instance`.
- A busy host and a processing bottleneck can happen together. The alert tells you the host is busy; it does not prove the host is the only cause.
