import os
import socketserver
import sys
import threading

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "exporter"))
from queue_exporter import Exporter  # noqa: E402
from sources import FileQueue, RabbitMQQueue, RedisListQueue, SimulatedQueue, SourceError  # noqa: E402


def metric(text, name):
    for line in text.splitlines():
        if line.startswith(name + " "):
            return float(line.split()[1])
    raise AssertionError("metric %s missing" % name)


def sim_at(t0=1000.0, **kw):
    return SimulatedQueue(clock=lambda: t0, **kw)


def run(sim, seconds, t0=1000.0):
    for i in range(1, seconds + 1):
        sim.step(t0 + i)


def test_balanced_queue_stays_empty():
    s = sim_at(producer_rate=5, consumers=3, rate_per_consumer=2.5)
    run(s, 60)
    out = Exporter(s).render(now=1060.0)
    assert metric(out, "queue_backlog_messages") <= 1
    assert metric(out, "queue_enqueued_total") == 300


def test_backlog_grows_when_producers_outpace_consumers():
    s = sim_at(producer_rate=45, consumers=3, rate_per_consumer=2.5)
    run(s, 10)
    out = Exporter(s).render(now=1010.0)
    assert metric(out, "queue_backlog_messages") == 375  # 450 in, 75 out
    assert metric(out, "queue_processed_total") == 75


def test_stalled_consumers_make_age_and_stalled_seconds_grow():
    s = sim_at(producer_rate=5, consumers=0)
    e = Exporter(s)
    s.step(1001.0)
    e.render(now=1001.0)
    out = e.render(now=1031.0)
    assert metric(out, "queue_oldest_message_age_seconds") == pytest.approx(30.0)
    assert metric(out, "queue_stalled_seconds") == pytest.approx(30.0, abs=0.1)


def test_empty_queue_has_zero_age_and_not_stalled():
    s = sim_at(producer_rate=0)
    out = Exporter(s).render(now=1010.0)
    assert metric(out, "queue_oldest_message_age_seconds") == 0
    assert metric(out, "queue_stalled_seconds") == 0


def test_recovery_drains_backlog():
    s = sim_at(producer_rate=5, consumers=0)
    run(s, 10)
    s.configure(consumers=6)
    run(s, 30)
    assert metric(Exporter(s).render(now=1030.0), "queue_backlog_messages") == 0


def test_output_is_deterministic():
    def once():
        s = sim_at(producer_rate=7, consumers=2)
        run(s, 20)
        return Exporter(s).render(now=1020.0)
    assert once() == once()


def test_configure_rejects_negative():
    s = sim_at()
    with pytest.raises(ValueError):
        s.configure(producer_rate=-1)
    with pytest.raises(ValueError):
        s.configure(consumers=-1)


def test_rabbitmq_adapter_maps_management_api_fields():
    payload = {"messages_ready": 40, "messages_unacknowledged": 2, "consumers": 3,
               "message_stats": {"publish": 500, "ack": 458}}
    urls = []
    q = RabbitMQQueue("http://mq:15672/", "/", "docs.in", "u", "p",
                      fetch=lambda url: urls.append(url) or payload)
    out = Exporter(q).render(now=1.0)
    assert urls == ["http://mq:15672/api/queues/%2F/docs.in"]
    assert metric(out, "queue_backlog_messages") == 42
    assert metric(out, "queue_consumers") == 3
    assert metric(out, "queue_processed_total") == 458
    assert "queue_oldest_message_age_seconds" not in out  # backend cannot tell


def test_rabbitmq_error_reports_source_down():
    def boom(url):
        raise OSError("connection refused")
    out = Exporter(RabbitMQQueue("http://mq:15672", "/", "q", "u", "p", fetch=boom)).render()
    assert metric(out, "queue_source_up") == 0
    assert "queue_backlog_messages" not in out


def test_file_queue_counts_and_ages(tmp_path):
    for i, mtime in enumerate([900.0, 950.0, 990.0]):
        f = tmp_path / ("doc%d.xml" % i)
        f.write_text("x")
        os.utime(f, (mtime, mtime))
    (tmp_path / "ignore.tmp").write_text("x")
    q = FileQueue(str(tmp_path), ".xml", clock=lambda: 1000.0)
    out = Exporter(q).render(now=1000.0)
    assert metric(out, "queue_backlog_messages") == 3
    assert metric(out, "queue_oldest_message_age_seconds") == pytest.approx(100.0)


def test_file_queue_missing_directory():
    with pytest.raises(SourceError):
        FileQueue("/nonexistent-dir-for-test").sample()


class _FakeRedis(socketserver.StreamRequestHandler):
    def handle(self):
        while True:
            head = self.rfile.readline()
            if not head:
                return
            n = int(head[1:])
            parts = []
            for _ in range(n):
                self.rfile.readline()
                parts.append(self.rfile.readline().strip())
            if parts[0] == b"LLEN":
                self.wfile.write(b":17\r\n" if parts[1] == b"docs" else b":0\r\n")
            else:
                self.wfile.write(b"-ERR\r\n")


def test_redis_list_length_over_resp():
    srv = socketserver.TCPServer(("127.0.0.1", 0), _FakeRedis)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        q = RedisListQueue("127.0.0.1", srv.server_address[1], "docs")
        out = Exporter(q).render(now=1.0)
        assert metric(out, "queue_backlog_messages") == 17
        assert "queue_processed_total" not in out
    finally:
        srv.shutdown()
        srv.server_close()


def test_redis_unreachable_reports_source_down():
    out = Exporter(RedisListQueue("127.0.0.1", 1, "docs", timeout=0.5)).render()
    assert metric(out, "queue_source_up") == 0
