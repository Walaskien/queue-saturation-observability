import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "exporter"))
from queue_exporter import QueueSim


def metric(text, name):
    for line in text.splitlines():
        if line.startswith(name + " "):
            return float(line.split()[1])
    raise AssertionError("metric %s missing" % name)


def sim_at(t0=1000.0, **kw):
    return QueueSim(clock=lambda: t0, **kw)


def test_balanced_queue_stays_empty():
    s = sim_at(producer_rate=5, consumers=3, rate_per_consumer=2.5)
    for i in range(1, 61):
        s.step(1000.0 + i)
    out = s.render(now=1060.0)
    assert metric(out, "queue_backlog_messages") <= 1
    assert metric(out, "queue_enqueued_total") == 300


def test_backlog_grows_when_producers_outpace_consumers():
    s = sim_at(producer_rate=45, consumers=3, rate_per_consumer=2.5)
    for i in range(1, 11):
        s.step(1000.0 + i)
    out = s.render(now=1010.0)
    # 450 in, 75 out
    assert metric(out, "queue_backlog_messages") == 375
    assert metric(out, "queue_processed_total") == 75


def test_stalled_consumers_make_oldest_message_age_grow():
    s = sim_at(producer_rate=5, consumers=0)
    s.step(1001.0)
    out = s.render(now=1031.0)
    assert metric(out, "queue_processed_total") == 0
    assert metric(out, "queue_oldest_message_age_seconds") == pytest.approx(30.0)


def test_empty_queue_has_zero_age():
    s = sim_at(producer_rate=0)
    s.step(1010.0)
    assert metric(s.render(now=1010.0), "queue_oldest_message_age_seconds") == 0


def test_recovery_drains_backlog():
    s = sim_at(producer_rate=5, consumers=0)
    for i in range(1, 11):
        s.step(1000.0 + i)
    s.configure(consumers=6)
    for i in range(11, 31):
        s.step(1000.0 + i)
    assert metric(s.render(now=1030.0), "queue_backlog_messages") == 0


def test_output_is_deterministic():
    def run():
        s = sim_at(producer_rate=7, consumers=2)
        for i in range(1, 21):
            s.step(1000.0 + i)
        return s.render(now=1020.0)
    assert run() == run()


def test_configure_rejects_negative():
    s = sim_at()
    with pytest.raises(ValueError):
        s.configure(producer_rate=-1)
    with pytest.raises(ValueError):
        s.configure(consumers=-1)
