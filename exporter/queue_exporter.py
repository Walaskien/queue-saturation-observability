"""Prometheus exporter for message-queue saturation.

Sources: rabbitmq (management API), redis (list length), file (spool directory),
sim (in-process simulator for demos). See README for flags and environment.
"""
import argparse
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from sources import FileQueue, RabbitMQQueue, RedisListQueue, SimulatedQueue, SourceError


class Exporter:
    """Turns source samples into metrics; tracks 'seconds without progress'."""

    def __init__(self, source, clock=time.time):
        self.source = source
        self._clock = clock
        self._lock = threading.Lock()
        self._last_processed = None
        self._last_progress = None

    def render(self, now=None):
        with self._lock:
            now = self._clock() if now is None else now
            try:
                s = self.source.sample(now)
            except SourceError as exc:
                return ("# source error: %s\n"
                        "# TYPE queue_source_up gauge\nqueue_source_up 0\n" % exc)
            stalled = None
            if s["processed_total"] is not None:
                if (self._last_progress is None or s["backlog"] == 0
                        or s["processed_total"] != self._last_processed):
                    self._last_progress = now
                self._last_processed = s["processed_total"]
                stalled = now - self._last_progress
            rows = [
                ("queue_source_up", "gauge", "1 if the queue backend answered.", 1),
                ("queue_backlog_messages", "gauge", "Messages waiting in the queue.", s["backlog"]),
                ("queue_oldest_message_age_seconds", "gauge",
                 "Age of the oldest waiting message (sources that can tell).", s["oldest_age"]),
                ("queue_stalled_seconds", "gauge",
                 "Seconds with a non-empty backlog and no message processed.", stalled),
                ("queue_consumers", "gauge", "Active consumers (sources that can tell).",
                 s["consumers"]),
                ("queue_enqueued_total", "counter", "Messages added.", s["enqueued_total"]),
                ("queue_processed_total", "counter", "Messages processed.", s["processed_total"]),
            ]
            lines = []
            for name, kind, helptext, value in rows:
                if value is None:
                    continue
                lines += ["# HELP %s %s" % (name, helptext), "# TYPE %s %s" % (name, kind),
                          "%s %s" % (name, ("%.3f" % value) if isinstance(value, float) else value)]
            return "\n".join(lines) + "\n"


def make_handler(exporter, sim=None):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, body, ctype="text/plain; charset=utf-8"):
            data = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/metrics":
                self._send(200, exporter.render(), "text/plain; version=0.0.4")
            elif path == "/healthz":
                self._send(200, "ok\n")
            else:
                self._send(404, "not found\n")

        def do_POST(self):
            url = urlparse(self.path)
            if url.path != "/control" or sim is None:
                self._send(404, "not found (/control exists only with --source sim)\n")
                return
            q = parse_qs(url.query)
            try:
                rate = float(q["producer_rate"][0]) if "producer_rate" in q else None
                cons = int(q["consumers"][0]) if "consumers" in q else None
                sim.step()
                sim.configure(producer_rate=rate, consumers=cons)
            except (ValueError, IndexError) as exc:
                self._send(400, "bad request: %s\n" % exc)
                return
            self._send(200, "producer_rate=%s consumers=%s\n" % (sim.producer_rate, sim.consumers))

        def log_message(self, fmt, *args):
            pass

    return Handler


def build_source(a):
    env = os.environ.get
    if a.source == "sim":
        return SimulatedQueue(a.producer_rate, a.consumers, a.rate_per_consumer)
    if a.source == "rabbitmq":
        return RabbitMQQueue(a.rabbitmq_url, a.rabbitmq_vhost, a.queue,
                             env("RABBITMQ_USER", "guest"), env("RABBITMQ_PASSWORD", ""))
    if a.source == "redis":
        return RedisListQueue(a.redis_host, a.redis_port, a.queue, env("REDIS_PASSWORD"))
    return FileQueue(a.queue, a.file_suffix)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", choices=["sim", "rabbitmq", "redis", "file"], default="sim")
    p.add_argument("--queue", help="queue name / redis key / spool directory")
    p.add_argument("--port", type=int, default=9101)
    p.add_argument("--rabbitmq-url", default="http://localhost:15672")
    p.add_argument("--rabbitmq-vhost", default="/")
    p.add_argument("--redis-host", default="localhost")
    p.add_argument("--redis-port", type=int, default=6379)
    p.add_argument("--file-suffix", default="")
    p.add_argument("--producer-rate", type=float, default=5.0)
    p.add_argument("--consumers", type=int, default=3)
    p.add_argument("--rate-per-consumer", type=float, default=2.5)
    a = p.parse_args()
    if a.source != "sim" and not a.queue:
        p.error("--queue is required for source %s" % a.source)
    source = build_source(a)
    sim = source if a.source == "sim" else None
    if sim:
        def ticker():
            while True:
                sim.step()
                time.sleep(0.2)
        threading.Thread(target=ticker, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", a.port), make_handler(Exporter(source), sim)).serve_forever()


if __name__ == "__main__":
    main()
